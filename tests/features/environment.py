import itertools
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framework import pause  # noqa: E402
from framework.actors import ActorFactory, AdminSession  # noqa: E402
from framework.api import AuthApi, BookingApi, SchedulerApi, TelegramLinkApi  # noqa: E402
from framework.cleanup import Cleanup  # noqa: E402
from framework.config import load_config  # noqa: E402
from framework.db import Database  # noqa: E402
from framework.http import ApiClient  # noqa: E402
from framework.infra import Mailpit, RabbitAdmin, Stubs  # noqa: E402
from framework.locks import ScenarioLocks  # noqa: E402
from framework.ui.browser import artifact_name, browser_for_process  # noqa: E402

SETTINGS_TAG = "settings"
CALENDAR_TAG = "calendar"
UI_TAG = "ui"
MOBILE_TAG = "mobile"


def before_all(context):
    context.cfg = load_config(context.config.userdata.get("env"))
    context.http = ApiClient(context.cfg.base_url, context.cfg.http_timeout)
    context.auth = AuthApi(context.http)
    context.booking = BookingApi(context.http)
    context.tg = TelegramLinkApi(context.http)
    context.scheduler = SchedulerApi(context.http)
    context.mail = Mailpit(context.cfg.mailpit_url, context.cfg.http_timeout)
    context.rabbit = RabbitAdmin(context.cfg.rabbitmq, context.cfg.http_timeout)
    context.stubs = Stubs(context.cfg.stubs_url, context.cfg.http_timeout)
    context.db = Database(context.cfg.db)
    context.admin = AdminSession(context.auth, context.cfg.admin)
    context.actors = ActorFactory(context.auth, context.admin, context.db)
    # живёт весь прогон процесса (присваивания внутри сценария behave откатывает)
    context.shared = SimpleNamespace(floor=None, cells=itertools.count(), work_monday=None)
    context.browser = browser_for_process(context.cfg)
    # всё, что создано через API, попадает в уборку текущего сценария
    context.http.on_response = lambda resp: _track(context, resp)


def _track(context, resp) -> None:
    cleanup = getattr(context, "cleanup", None)
    if cleanup is not None:
        cleanup.track(resp.request.method, resp.url, resp.status_code, resp.json)


def before_scenario(context, scenario):
    # Блокировки общего состояния (правила, календарь) — до первого шага: см. framework/locks.py
    context.locks = ScenarioLocks()
    try:
        context.hook_notes = context.locks.acquire(set(scenario.effective_tags))
    except BaseException:
        context.locks.release()  # часть уже взятых не должна пережить упавший хук
        raise
    context.cleanup = Cleanup()
    context.users = {}
    context.resources = {}
    context.bookings = []
    context.chats = {}
    context.reset_tokens = []
    context.resp = None
    context.settings_snapshot = None
    context.http.history.clear()
    context.ui = None
    context.page = None
    if UI_TAG in scenario.effective_tags:
        context.ui = context.browser.new_session(mobile=MOBILE_TAG in scenario.effective_tags,
                                                 title=f"{scenario.feature.name}: {scenario.name}")
        context.page = context.ui.page
    # @settings меняет глобальные правила: снимаем их до и возвращаем после (под монопольной блокировкой)
    if SETTINGS_TAG in scenario.effective_tags:
        resp = context.booking.get_settings(context.admin.token)
        assert resp.status_code == 200, resp.text
        context.settings_snapshot = resp.json()


def after_scenario(context, scenario):
    failed = scenario.status.name in ("failed", "error")
    try:
        if pause.wanted(failed):
            pause.wait(f"{scenario.feature.name}: {scenario.name}", failed, context.users, context.resources)
        if context.ui is not None:
            context.ui.track_created(context.cleanup)
            folders = [Path(context.cfg.ui.artifacts_dir) / artifact_name(scenario.feature.name, scenario.name)]
            evidence = _evidence_path(context)
            if evidence:
                folders.append(evidence)  # behavex прикладывает эту папку к HTML-отчёту и к Allure
            saved = context.ui.close(failed, folders)
            if saved:
                print(f"Артефакты UI-падения: {folders[0]}")
        snapshot = getattr(context, "settings_snapshot", None)
        if snapshot:
            resp = context.booking.put_settings(context.admin.token, **snapshot)
            assert resp.status_code == 200, f"Не удалось вернуть настройки: {resp.text}"
        # @calendar меняет производственный календарь: возвращаем стандартный источник и пересинхронизируемся
        if CALENDAR_TAG in scenario.effective_tags:
            context.stubs.reset_calendar()
            resp = context.scheduler.run(context.admin.token, "sync-calendar")
            assert resp.status_code == 200, f"Не удалось вернуть календарь: {resp.text}"
            context.shared.work_monday = None
        context.hook_notes.append(context.cleanup.run(context.db))
    finally:
        # снимаются последними: соседи не должны увидеть правила или календарь до отката
        if getattr(context, "locks", None) is not None:
            context.locks.release()
        _write_hook_notes(context)


def _write_hook_notes(context) -> None:
    """Хуки идут мимо лога сценария (behavex пишет его только на шагах): их журнал — отдельным
    вложением hooks.log в Allure. По нему видно, сколько сценарий ждал блокировок и что за ним убрано."""
    evidence = _evidence_path(context)
    notes = getattr(context, "hook_notes", None)
    if evidence and notes:
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "hooks.log").write_text("\n".join(notes) + "\n", encoding="utf-8")


def _evidence_path(context) -> Path | None:
    """Папка вложений сценария у behavex; при запуске голым behave её нет."""
    try:
        return Path(context.evidence_path)
    except Exception:
        return None


def after_all(context):
    if context.shared.floor is not None:  # общий этаж процесса со всеми ресурсами, что на нём остались
        floor_cleanup = Cleanup()
        floor_cleanup.ids["floor"].add(context.shared.floor["id"])
        floor_cleanup.run(context.db)
    context.browser.close()
    context.db.close()
