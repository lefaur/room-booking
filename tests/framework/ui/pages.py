"""Page objects веб-интерфейса. Элементы ищутся по data-testid: тесты не ломаются от смены текста или вёрстки.

Шаги работают со страницами, а не с локаторами: если экран переделают, правится один класс, а не сценарии.
"""
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, expect

ACCESS_KEY = "officespace.access"
REFRESH_KEY = "officespace.refresh"


class BasePage:
    path = "/"

    def __init__(self, page: Page):
        self.page = page

    def open(self, **params) -> "BasePage":
        query = urlencode({k: v for k, v in params.items() if v is not None})
        self.page.goto(self.path + (f"?{query}" if query else ""))
        return self

    def by_id(self, test_id: str) -> Locator:
        return self.page.get_by_test_id(test_id)

    @property
    def header(self) -> "Header":
        return Header(self.page)

    def toast(self, text: str) -> Locator:
        return self.by_id("toast").filter(has_text=text)

    @property
    def form_error(self) -> Locator:
        return self.by_id("form-error")


class Header(BasePage):
    @property
    def current_user(self) -> Locator:
        return self.by_id("current-user")

    @property
    def nav(self) -> Locator:
        return self.by_id("main-nav")

    @property
    def menu_toggle(self) -> Locator:
        return self.by_id("menu-toggle")

    def link(self, text: str) -> Locator:
        return self.nav.get_by_role("link", name=text, exact=True)

    def go(self, text: str) -> None:
        if self.menu_toggle.is_visible():  # на телефоне меню спрятано под «гамбургер»
            self.menu_toggle.click()
        self.link(text).click()

    def logout(self) -> None:
        if self.menu_toggle.is_visible():
            self.menu_toggle.click()
        self.by_id("logout").click()


def sign_in(page: Page, access_token: str, refresh_token: str) -> None:
    """Вход без формы: кладём токены туда же, куда их кладёт приложение. Форму входа проверяют свои сценарии,
    остальным незачем тратить на неё время."""
    page.goto("/login")
    page.evaluate("([key, value]) => localStorage.setItem(key, value)", [ACCESS_KEY, access_token])
    page.evaluate("([key, value]) => localStorage.setItem(key, value)", [REFRESH_KEY, refresh_token])


class LoginPage(BasePage):
    path = "/login"

    def login(self, email: str, password: str) -> None:
        self.by_id("login-email").fill(email)
        self.by_id("login-password").fill(password)
        self.by_id("login-submit").click()

    @property
    def reset_done(self) -> Locator:
        return self.by_id("reset-done")


class RegisterPage(BasePage):
    path = "/register"

    def register(self, full_name: str, email: str, password: str) -> None:
        self.by_id("register-name").fill(full_name)
        self.by_id("register-email").fill(email)
        self.by_id("register-password").fill(password)
        self.by_id("register-submit").click()


class ForgotPasswordPage(BasePage):
    path = "/forgot-password"

    def request(self, email: str) -> None:
        self.by_id("forgot-email").fill(email)
        self.by_id("forgot-submit").click()

    @property
    def sent(self) -> Locator:
        return self.by_id("forgot-sent")


class ResetPasswordPage(BasePage):
    path = "/reset-password"

    def set_password(self, password: str, repeat: str | None = None) -> None:
        self.by_id("reset-password").fill(password)
        self.by_id("reset-repeat").fill(repeat if repeat is not None else password)
        self.by_id("reset-submit").click()


class MapPage(BasePage):
    path = "/"

    def resource(self, name: str) -> Locator:
        return self.page.locator(f'[data-testid="map-resource"][data-name="{name}"]')

    def wait_loaded(self) -> None:
        expect(self.by_id("floor-plan")).to_be_visible()

    def select(self, name: str) -> None:
        self.resource(name).click()
        expect(self.by_id("panel-title")).to_have_text(name)

    @property
    def panel(self) -> Locator:
        return self.by_id("booking-panel")

    def book_room(self, start: str, end: str) -> None:
        self.by_id("booking-start").select_option(start)
        self.by_id("booking-end").select_option(end)
        self.by_id("booking-submit").click()

    def book_desk(self, date_from: str, date_to: str) -> None:
        self.by_id("booking-date-from").fill(date_from)
        self.by_id("booking-date-to").fill(date_to)
        self.by_id("booking-submit").click()

    def created_booking_id(self) -> int:
        link = self.by_id("booking-created-link")
        expect(link).to_be_visible()
        return int(link.get_attribute("href").rstrip("/").split("/")[-1])


class BookingsPage(BasePage):
    path = "/bookings"

    def tab(self, test_id: str) -> None:
        self.by_id(f"tab-{test_id}").click()

    def card(self, resource_name: str) -> Locator:
        return self.by_id("booking-card").filter(
            has=self.page.get_by_test_id("booking-resource").get_by_text(resource_name, exact=True))

    def act(self, resource_name: str, action: str) -> None:
        self.card(resource_name).get_by_test_id(f"booking-{action}").click()


class ProfilePage(BasePage):
    path = "/profile"

    def request_code(self) -> str:
        self.by_id("telegram-get-code").click()
        command = self.by_id("telegram-command")
        expect(command).to_be_visible()
        return command.inner_text()

    def check_link(self) -> None:
        self.by_id("telegram-check").click()

    @property
    def linked(self) -> Locator:
        return self.by_id("telegram-linked")


class EditorPage(BasePage):
    path = "/admin/editor"

    @property
    def plan(self) -> Locator:
        return self.by_id("editor-plan")

    def resource(self, name: str) -> Locator:
        return self.page.locator(f'[data-testid="editor-resource"][data-name="{name}"]')

    def _scale(self) -> float:
        """Сколько экранных пикселей в единице плана (SVG вписан в блок с сохранением пропорций)."""
        box = self.plan.bounding_box()
        _, _, width, height = map(float, self.plan.get_attribute("viewBox").split())
        return min(box["width"] / width, box["height"] / height)

    def drag(self, name: str, dx: float, dy: float) -> None:
        """Перетаскивает ресурс мышью на dx, dy в единицах плана."""
        scale = self._scale()
        box = self.resource(name).locator("rect.res").bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        mouse = self.page.mouse
        mouse.move(x, y)
        mouse.down()
        mouse.move(x + dx * scale, y + dy * scale, steps=10)
        mouse.up()

    def save(self) -> None:
        self.by_id("editor-save").click()

    def add_resource(self, kind: str, name: str) -> None:
        self.by_id("new-kind").select_option(kind)
        self.by_id("new-name").fill(name)
        self.by_id("new-submit").click()


class JobsPage(BasePage):
    path = "/admin/jobs"

    def row(self, job: str) -> Locator:
        return self.page.locator(f'[data-testid="job-row"][data-job="{job}"]')

    def run(self, job: str) -> None:
        self.row(job).get_by_test_id("job-run").click()


class SettingsPage(BasePage):
    path = "/admin/settings"

    def set(self, key: str, value: int) -> None:
        self.by_id(f"setting-{key}").fill(str(value))

    def save(self) -> None:
        self.by_id("settings-save").click()


class UsersPage(BasePage):
    path = "/admin/users"

    def search(self, email: str) -> None:
        self.by_id("users-search").fill(email)
        self.by_id("users-search-submit").click()

    def row(self, email: str) -> Locator:
        return self.page.locator(f'[data-testid="user-row"][data-email="{email}"]')

    def set_role(self, email: str, role: str) -> None:
        self.row(email).get_by_test_id("user-role").select_option(role)
