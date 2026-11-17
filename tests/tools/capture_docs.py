"""Скриншоты для docs/FRAMEWORK.md: отчёты прогона и сам сайт, нужное место обведено красной рамкой.

Перед запуском нужен прогон с нарочно падающим сценарием и собранный Allure-отчёт:
    docker compose run --rm -e INCLUDE_DEMO=1 tests sh run.sh
    docker compose run --rm allure
    docker compose run --rm -v ./docs:/docs tests python tools/capture_docs.py

Скриншоты пересоздаются целиком, поэтому после правок интерфейса или отчётов достаточно запустить заново.
"""
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framework.api import AuthApi, BookingApi  # noqa: E402
from framework.config import load_config  # noqa: E402
from framework.http import ApiClient  # noqa: E402

REPORTS = Path(os.getenv("REPORTS_DIR", "/reports"))
OUT = Path(os.getenv("DOCS_IMG_DIR", "/docs/img"))
MARK = "outline: 4px solid #e53935; outline-offset: 3px; border-radius: 4px;"
TRACE_PORT = 9323


def mark(target: Locator) -> None:
    target.first.scroll_into_view_if_needed()
    target.first.evaluate("(el, style) => { el.dataset.docMark = '1'; el.style.cssText += style; }", MARK)


def unmark(page: Page) -> None:
    page.evaluate("""() => document.querySelectorAll('[data-doc-mark]').forEach(el => {
        el.style.outline = ''; el.style.outlineOffset = ''; delete el.dataset.docMark; })""")


def shot(page: Page, name: str, full_page: bool = False) -> None:
    page.wait_for_timeout(400)  # анимации раскрытия в Allure
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page, animations="disabled")
    print(f"  {path}")
    unmark(page)


def allure(page: Page) -> None:
    report = REPORTS / "allure-report" / "index.html"
    page.set_viewport_size({"width": 1440, "height": 1180})
    page.goto(report.as_uri())
    page.get_by_text("Environment", exact=True).wait_for()
    mark(page.locator(".widget", has=page.get_by_text("Environment", exact=True)))
    shot(page, "allure-overview")

    # во вкладке Categories только упавшие, сгруппированные по тексту ошибки
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(report.as_uri() + "#categories")
    leaf = page.locator(".node__leaf", has_text="Бронь показывает не тот статус").first
    page.goto(report.as_uri() + leaf.get_attribute("href"))
    page.locator(".status-details").first.wait_for()
    mark(page.locator(".status-details").first)
    shot(page, "allure-failed")

    page.set_viewport_size({"width": 1440, "height": 1560})
    page.locator(".attachment-row__name", has_text="page.log").first.click()
    page.locator(".attachment-row__name", has_text="screenshot.png").first.click()
    page.locator(".attachment-row__content img").first.wait_for()
    page.locator(".test-result-execution").first.evaluate("el => el.scrollIntoView()")
    for name in ("page.log", "screenshot.png", "trace.zip"):
        mark(page.locator(".attachment-row__name", has_text=name))
    shot(page, "allure-attachments")

    # у любого сценария, и зелёного тоже, во вложениях лог всех HTTP-запросов и SQL
    page.set_viewport_size({"width": 1440, "height": 1300})
    page.goto(report.as_uri() + "#suites")
    leaf = page.locator(".node__leaf", has_text="Новая бронь создаётся в статусе pending").first
    page.goto(report.as_uri() + leaf.get_attribute("href"))
    page.locator(".attachment-row__name", has_text="scenario.log").first.click()
    page.locator(".attachment-row__content pre, .attachment-row__content code").first.wait_for()
    mark(page.locator(".attachment-row__name", has_text="scenario.log"))
    shot(page, "allure-http-log")
    page.set_viewport_size({"width": 1440, "height": 900})


def trace_viewer(page: Page) -> None:
    traces = sorted((REPORTS / "ui-failures").glob("*/trace.zip"))
    if not traces:
        print("  нет reports/ui-failures/*/trace.zip — пропускаю trace viewer")
        return
    server = subprocess.Popen(["playwright", "show-trace", "--host", "127.0.0.1", "--port", str(TRACE_PORT),
                               str(traces[0])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                page.goto(f"http://127.0.0.1:{TRACE_PORT}", timeout=2000)
                break
            except Exception:
                time.sleep(0.5)
        # упавшее действие в списке слева: по нему видно снимок страницы и ожидаемое/полученное значение
        failed_action = page.get_by_text("LocatorAssertions.to_have_text").first
        failed_action.wait_for(timeout=20000)
        failed_action.click()
        page.wait_for_timeout(1500)
        mark(failed_action)
        shot(page, "trace-viewer")
    finally:
        server.terminate()


DEMO_FLOOR = "Офис, 3 этаж"
DEMO_ROOMS = [("Москва", 20, 20, 240, 150, 10), ("Питер", 280, 20, 180, 150, 6), ("Казань", 480, 20, 150, 150, 4),
              ("Переговорная 4", 650, 20, 130, 150, 4)]
DEMO_DESKS = [(f"Место {i + 1}", 40 + (i % 6) * 120, 240 + (i // 6) * 110, 90, 60) for i in range(12)]


def demo_floor(http: ApiClient, token: str) -> tuple[int, date]:
    """Этаж с переговорками, местами и парой броней: на чистом стенде карта пустая, на тестовом — мелкие этажи."""
    booking = BookingApi(http)
    day = date.today() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    floors = http.request("GET", "/api/booking/floors", token=token).json()
    existing = next((f for f in floors if f["name"] == DEMO_FLOOR), None)
    if existing:
        return existing["id"], day
    floor = booking.create_floor(token, name=DEMO_FLOOR, level=3, width=800, height=480).json()
    ids = {}
    for name, x, y, w, h, capacity in DEMO_ROOMS:
        ids[name] = booking.create_resource(token, floor_id=floor["id"], kind="room", name=name, capacity=capacity,
                                            x=x, y=y, w=w, h=h, equipment=["projector"] if capacity > 5 else []).json()
    for name, x, y, w, h in DEMO_DESKS:
        ids[name] = booking.create_resource(token, floor_id=floor["id"], kind="desk", name=name, capacity=1,
                                            x=x, y=y, w=w, h=h).json()
    off = ids["Переговорная 4"]
    booking.patch_resource(token, off["id"], version=off["version"], active=False)
    tz = load_config().office_tz
    for room in ("Москва", "Казань"):
        booking.create_booking(token, resource_id=ids[room]["id"],
                               start=datetime.combine(day, dtime(10), tz).isoformat(),
                               end=datetime.combine(day, dtime(11, 30), tz).isoformat())
    for desk in ("Место 2", "Место 5", "Место 9"):
        booking.create_booking(token, resource_id=ids[desk]["id"], date_from=day.isoformat(), date_to=day.isoformat())
    return floor["id"], day


def app(page: Page) -> None:
    cfg = load_config()
    http = ApiClient(cfg.base_url, cfg.http_timeout)
    tokens = AuthApi(http).login(cfg.admin.email, cfg.admin.password).json()
    floor_id, day = demo_floor(http, tokens["access_token"])
    page.goto(cfg.base_url + "/login")
    page.evaluate("""([a, r]) => { localStorage.setItem('officespace.access', a);
                                   localStorage.setItem('officespace.refresh', r); }""",
                  [tokens["access_token"], tokens["refresh_token"]])
    page.goto(f"{cfg.base_url}/?floor={floor_id}&date={day.isoformat()}&time=10:30")
    page.locator('[data-testid="map-resource"][data-name="Питер"]').click()
    page.get_by_test_id("booking-panel").wait_for()
    shot(page, "app-map")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="ru-RU",
                                timezone_id="Europe/Moscow")
        page.set_default_timeout(15000)
        for capture in (app, allure, trace_viewer):
            print(capture.__name__)
            capture(page)
        browser.close()


if __name__ == "__main__":
    main()
