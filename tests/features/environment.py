import itertools
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from framework.actors import ActorFactory, AdminSession  # noqa: E402
from framework.api import AuthApi, BookingApi, SchedulerApi, TelegramLinkApi  # noqa: E402
from framework.config import load_config  # noqa: E402
from framework.db import Database  # noqa: E402
from framework.http import ApiClient  # noqa: E402
from framework.infra import Mailpit, RabbitAdmin, Stubs  # noqa: E402
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
    context.actors = ActorFactory(context.auth, context.admin)
    # живёт весь прогон процесса (присваивания внутри сценария behave откатывает)
    context.shared = SimpleNamespace(floor=None, cells=itertools.count(), work_monday=None)
    context.browser = browser_for_process(context.cfg)


def before_scenario(context, scenario):
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
    # Сценарии с тегом @settings меняют глобальные правила: снимаем их до и возвращаем после.
    # В параллельном прогоне такие сценарии исключены и идут отдельным последовательным проходом.
    if SETTINGS_TAG in scenario.effective_tags:
        resp = context.booking.get_settings(context.admin.token)
        assert resp.status_code == 200, resp.text
        context.settings_snapshot = resp.json()


def after_scenario(context, scenario):
    if context.ui is not None:
        failed = scenario.status.name in ("failed", "error")
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


def _evidence_path(context) -> Path | None:
    """Папка вложений сценария у behavex; при запуске голым behave её нет."""
    try:
        return Path(context.evidence_path)
    except Exception:
        return None


def after_all(context):
    context.browser.close()
    context.db.close()
