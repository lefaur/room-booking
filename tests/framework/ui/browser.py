"""Браузер для UI-сценариев.

Chromium запускается один раз на процесс behavex и только когда до него дошёл первый @ui-сценарий:
API-сценарии браузер не поднимают. Каждому сценарию — свой контекст (чистые cookies и localStorage),
поэтому сценарии не видят сессии друг друга и спокойно идут параллельно.

Трасса Playwright пишется у каждого UI-сценария, а сохраняется только у упавшего, вместе со скриншотом
и журналом страницы (см. UiSession.save_failure).
"""
import atexit
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, expect, sync_playwright

from framework.config import Config

DESKTOP = {"width": 1366, "height": 860}
MOBILE = {"width": 375, "height": 812}

# Уведомление живёт несколько секунд и к моменту падения уже исчезло со скриншота.
# Страница с первой загрузки складывает каждое показанное уведомление в журнал, его кладём в отчёт.
TOASTS_JOURNAL_SCRIPT = """
window.__toasts = [];
new MutationObserver(mutations => {
  for (const m of mutations) for (const node of m.addedNodes) {
    if (node.nodeType === 1 && node.dataset && node.dataset.testid === "toast") {
      window.__toasts.push({ time: new Date().toISOString(), kind: node.dataset.kind, text: node.textContent.trim() });
    }
  }
}).observe(document, { childList: true, subtree: true });
"""


@dataclass
class UiSession:
    """Контекст и вкладка одного сценария плюс журнал того, что происходило в браузере."""

    context: BrowserContext
    page: Page
    journal: list[str] = field(default_factory=list)
    _started: float = field(default_factory=time.monotonic)
    _last_url: str = ""

    def __post_init__(self):
        self.page.on("console", lambda msg: self._note(f"console.{msg.type}: {msg.text}")
                     if msg.type in ("error", "warning") else None)
        self.page.on("pageerror", lambda error: self._note(f"pageerror: {error}"))
        self.page.on("requestfailed", lambda req: self._note(
            f"request failed: {req.method} {req.url} ({req.failure})"))
        self.page.on("response", lambda resp: self._note(
            f"HTTP {resp.status}: {resp.request.method} {resp.url}") if resp.status >= 400 else None)
        self.page.on("framenavigated", self._on_navigated)
        # созданное через интерфейс (регистрация, редактор этажа) тоже надо убрать за сценарием
        self.created: list = []
        self.page.on("response", lambda resp: self.created.append(resp)
                     if resp.status == 201 and resp.request.method == "POST" else None)

    def track_created(self, cleanup) -> None:
        """Передать уборке всё, что сценарий создал в браузере. Вызывать до close(): тело ответа
        читается из ещё открытого контекста."""
        for resp in self.created:
            try:
                cleanup.track("POST", resp.url, resp.status, resp.json)
            except Exception:
                pass  # ответ без JSON-тела — не сущность

    def _on_navigated(self, frame) -> None:
        # SPA шлёт событие на каждый pushState и перезагрузку данных: пишем только смену адреса
        if frame == self.page.main_frame and frame.url != self._last_url:
            self._last_url = frame.url
            self._note(f"navigated: {frame.url}")

    def _note(self, text: str) -> None:
        self.journal.append(f"[{time.monotonic() - self._started:7.2f}s] {text}")

    def close(self, failed: bool, folders: list[Path]) -> list[Path]:
        """Закрыть контекст. У упавшего сценария перед этим сохранить артефакты в каждую из папок."""
        saved: list[Path] = []
        try:
            if failed:
                saved = self.save_failure(folders)
            else:
                self.context.tracing.stop()
        finally:
            self.context.close()
        return saved

    def save_failure(self, folders: list[Path]) -> list[Path]:
        """Скриншот, трасса и журнал. Каждый шаг в своём try: сломанная страница не должна
        лишить нас остальных артефактов и тем более замаскировать настоящую причину падения."""
        first = folders[0]
        first.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        steps = [
            ("screenshot.png", lambda p: self.page.screenshot(path=str(p), full_page=True)),
            ("trace.zip", lambda p: self.context.tracing.stop(path=str(p))),
            ("page.log", lambda p: p.write_text(self._page_log(), encoding="utf-8")),
            ("page.html", lambda p: p.write_text(self.page.content(), encoding="utf-8")),
        ]
        for suffix, save in steps:
            path = first / suffix
            try:
                save(path)
                files.append(path)
            except Exception as error:
                self._note(f"не удалось сохранить {suffix}: {error}")
        for folder in folders[1:]:
            folder.mkdir(parents=True, exist_ok=True)
            for path in files:
                (folder / path.name).write_bytes(path.read_bytes())
        return files

    def _page_log(self) -> str:
        try:
            toasts = self.page.evaluate("() => window.__toasts || []")
        except Exception as error:
            toasts = [f"журнал недоступен: {error}"]
        try:
            storage = self.page.evaluate("() => Object.keys(localStorage)")
        except Exception:
            storage = []
        return "\n".join([
            f"URL: {self.page.url}",
            f"Viewport: {self.page.viewport_size}",
            f"localStorage keys: {storage}",
            "",
            "Уведомления за сценарий:",
            *([f"  {json.dumps(t, ensure_ascii=False)}" for t in toasts] or ["  —"]),
            "",
            "События страницы (консоль, ошибки JS, HTTP >= 400, переходы):",
            *([f"  {line}" for line in self.journal] or ["  —"]),
        ]) + "\n"


class BrowserHolder:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        expect.set_options(timeout=cfg.ui.timeout_ms)

    def _launch(self) -> Browser:
        if self._browser is None:
            self._playwright = sync_playwright().start()
            # /dev/shm в контейнере всего 64 МБ: без этого флага вкладки Chromium падают на тяжёлых страницах.
            # --lang: формат поля даты берётся из языка процесса браузера, а не из locale контекста
            self._browser = self._playwright.chromium.launch(headless=self._cfg.ui.headless,
                                                             args=["--disable-dev-shm-usage", "--lang=ru-RU"],
                                                             env={**os.environ, "LANG": "ru_RU.UTF-8", "LANGUAGE": "ru"})
        return self._browser

    def new_session(self, mobile: bool = False, title: str = "") -> UiSession:
        options = dict(
            base_url=self._cfg.base_url,
            locale="ru-RU",
            timezone_id=self._cfg.ui.timezone,
            viewport=MOBILE if mobile else DESKTOP,
        )
        if mobile:
            options.update(is_mobile=True, has_touch=True, device_scale_factor=2)
        context = self._launch().new_context(**options)
        context.set_default_timeout(self._cfg.ui.timeout_ms)
        context.add_init_script(TOASTS_JOURNAL_SCRIPT)
        # снимки DOM и экрана на каждое действие: в trace viewer видно, что было на странице перед падением
        context.tracing.start(title=title, screenshots=True, snapshots=True, sources=False)
        return UiSession(context=context, page=context.new_page())

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._playwright.stop()
            self._browser = self._playwright = None


_holder: BrowserHolder | None = None


def browser_for_process(cfg: Config) -> BrowserHolder:
    """behavex в одном рабочем процессе вызывает before_all много раз (на каждую порцию сценариев).
    Держатель браузера один на процесс, иначе каждый вызов оставлял бы за собой живой Chromium."""
    global _holder
    if _holder is None:
        _holder = BrowserHolder(cfg)
        atexit.register(_holder.close)
    return _holder


def artifact_name(feature: str, scenario: str) -> str:
    return re.sub(r"[^\w-]+", "_", f"{feature}-{scenario}")[:100]
