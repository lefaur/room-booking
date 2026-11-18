"""Шаги UI-сценариев (Playwright). Все начинаются с «в браузере …» или описывают видимое на экране,
чтобы не пересекаться с API-шагами вида «пользователь "X" …».

Проверки в UI идут через expect из Playwright: он сам ждёт, пока элемент появится или текст сменится,
поэтому sleep в шагах не нужен. Итог действия в браузере проверяется ещё и по API — экран может врать."""
import re
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlparse

from behave import step
from playwright.sync_api import expect

from framework import data, models
from framework.infra import wait_until
from framework.prepare import floor_row, resource_row
from framework.support import actor, as_model, day_of, expect as expect_resp, parse, preparation
from framework.ui.pages import (BasePage, BookingsPage, EditorPage, ForgotPasswordPage, JobsPage, LoginPage,
                                MapPage, ProfilePage, RegisterPage, ResetPasswordPage, SettingsPage, UsersPage,
                                sign_in)

RESET_LINK = re.compile(r"reset-password\?token=[\w-]+")

STATES = {"свободен": "free", "свободна": "free", "занят": "busy", "занята": "busy",
          "недоступен": "off", "недоступна": "off"}
STATUS_TEXT = {"Ждёт подтверждения", "Подтверждена", "Вы на месте", "Отменена", "Не подтверждена вовремя", "Неявка"}


def _page(context):
    assert context.page is not None, "Сценарий без тега @ui: браузер не запущен"
    return context.page


def _name(context, label: str) -> str:
    """Ресурсы сценария называются уникально, в .feature — коротким ярлыком."""
    return context.resources[label].name


# --- данные ---

@step("есть этаж для UI с ресурсами")
def step_ui_floor(context):
    """Небольшой отдельный этаж на сценарий: на общем тестовом этаже тысячи ресурсов, на карте их не разглядеть.
    Этаж и все ресурсы — одной SQL-транзакцией (ресурс ссылается на этаж из той же пачки)."""
    rows = []
    for row in context.table:
        kind = "room" if row["тип"] == "переговорка" else "desk"
        x, y, w, h = (int(v) for v in row["x,y,w,h"].split(","))
        rows.append((row["ярлык"], dict(kind=kind, name=data.unique_name(row["ярлык"]),
                                        capacity=6 if kind == "room" else 1, x=x, y=y, w=w, h=h)))
    floor_fields = dict(name=data.unique_name("ui-floor"), level=3, width=600, height=400)
    prep = preparation(context)
    if prep:
        with prep:
            floor = floor_row(prep, **floor_fields)
            created = [(label, resource_row(prep, floor_id=lambda: floor["id"], **fields)) for label, fields in rows]
        context.floor = as_model(models.Floor, floor)
        for label, res in created:
            context.resources[label] = as_model(models.Resource, res)
        return
    context.floor = parse(models.Floor, expect_resp(context.booking.create_floor(context.admin.token,
                                                                                  **floor_fields), 201))
    for label, fields in rows:
        resp = context.booking.create_resource(context.admin.token, floor_id=context.floor.id, **fields)
        context.resources[label] = parse(models.Resource, expect_resp(resp, 201))


# --- вход ---

@step('в браузере "{label}" вошёл в систему')
def step_ui_signed_in(context, label):
    person = actor(context, label)
    sign_in(_page(context), person.access_token, person.refresh_token)
    _page(context).goto("/")
    context.ui_actor = label


@step('в браузере гость открывает "{path}"')
def step_ui_guest_opens(context, path):
    _page(context).goto(path)


@step('в браузере открывают "{path}"')
def step_ui_opens(context, path):
    _page(context).goto(path)


@step('в браузере "{label}" входит через форму')
def step_ui_login(context, label):
    person = actor(context, label, logged_in=False)
    page = LoginPage(_page(context))
    if urlparse(page.page.url).path != "/login":
        page.open()
    page.login(person.email, person.password)


@step('в браузере "{label}" входит через форму с паролем "{password}"')
def step_ui_login_password(context, label, password):
    person = actor(context, label, logged_in=False)
    LoginPage(_page(context)).open().login(person.email, password)


@step("в браузере гость регистрируется через форму")
def step_ui_register(context):
    step_ui_register_password(context, data.PASSWORD)


@step('в браузере гость регистрируется через форму с паролем "{password}"')
def step_ui_register_password(context, password):
    context.new_user = SimpleNamespace(email=data.unique_email("ui"), full_name=f"UI {data.uid()}")
    RegisterPage(_page(context)).open().register(context.new_user.full_name, context.new_user.email, password)


@step("в браузере нажимают «Выйти»")
def step_ui_logout(context):
    BasePage(_page(context)).header.logout()


@step('в браузере "{label}" запрашивает сброс пароля через форму')
def step_ui_forgot(context, label):
    person = actor(context, label, logged_in=False)
    context.mails_before = context.mail.count(person.email, "Сброс пароля")
    page = LoginPage(_page(context)).open()
    page.by_id("to-forgot").click()
    ForgotPasswordPage(page.page).request(person.email)


@step('в браузере "{label}" открывает ссылку из письма и задаёт пароль "{password}"')
def step_ui_reset(context, label, password):
    person = actor(context, label, logged_in=False)
    message = context.mail.wait_for(person.email, "Сброс пароля", count=context.mails_before + 1)
    link = RESET_LINK.search(message["Text"])
    assert link, f"В письме нет ссылки на сброс:\n{message['Text']}"
    # в письме адрес для людей (localhost:8080); браузер тестов ходит на тот же путь своего стенда
    page = _page(context)
    page.goto(f"/{link.group(0)}")
    ResetPasswordPage(page).set_password(password)
    person.password = password


# --- что видно на экране ---

@step('открыта страница "{path}"')
def step_ui_path(context, path):
    # не wait_until: в sync API Playwright page.url обновляется, только пока идёт вызов Playwright
    _page(context).wait_for_url(lambda url: urlparse(url).path == path)


@step("открыта страница входа")
def step_ui_login_page(context):
    step_ui_path(context, "/login")
    expect(_page(context).get_by_test_id("login-form")).to_be_visible()


@step("открыта карта офиса")
def step_ui_map_page(context):
    step_ui_path(context, "/")
    expect(_page(context).get_by_role("heading", name="Карта офиса")).to_be_visible()


@step("открыта страница «Нет доступа»")
def step_ui_forbidden(context):
    step_ui_path(context, "/forbidden")
    expect(_page(context).get_by_test_id("forbidden")).to_be_visible()


@step('в шапке имя пользователя "{label}"')
def step_ui_header_user(context, label):
    expect(BasePage(_page(context)).header.current_user).to_have_text(f"Тест {label}")


@step("в шапке имя нового пользователя")
def step_ui_header_new_user(context):
    expect(BasePage(_page(context)).header.current_user).to_have_text(context.new_user.full_name)


@step("форма показывает ошибку «{text}»")
def step_ui_form_error(context, text):
    expect(BasePage(_page(context)).form_error).to_contain_text(text)


@step("всплывает уведомление «{text}»")
def step_ui_toast(context, text):
    expect(BasePage(_page(context)).toast(text)).to_be_visible()


@step("форма сообщает, что письмо отправлено")
def step_ui_forgot_sent(context):
    expect(ForgotPasswordPage(_page(context)).sent).to_contain_text("Если такой email зарегистрирован")


@step("на странице входа сообщение о смене пароля")
def step_ui_reset_done(context):
    step_ui_login_page(context)
    expect(LoginPage(_page(context)).reset_done).to_be_visible()


@step('новый пользователь зарегистрирован с ролью "{role}"')
def step_new_user_role(context, role):
    resp = expect_resp(context.auth.list_users(context.admin.token, email=context.new_user.email), 200)
    users = resp.json()
    assert len(users) == 1 and users[0]["role"] == role, users


@step("в меню есть разделы {names}")
def step_ui_menu_has(context, names):
    header = BasePage(_page(context)).header
    for name in _quoted(names):
        expect(header.link(name)).to_be_attached()


@step("в меню нет разделов {names}")
def step_ui_menu_lacks(context, names):
    header = BasePage(_page(context)).header
    expect(header.link("Брони")).to_be_attached()  # меню отрисовалось — значит, отсутствие не случайно
    for name in _quoted(names):
        expect(header.link(name)).to_have_count(0)


def _quoted(text: str) -> list[str]:
    return [part.strip(" «»") for part in text.split(",")]


# --- карта и бронирование ---

@step('в браузере открывают карту этажа на {day}, {hhmm}')
def step_ui_open_map(context, day, hhmm):
    page = MapPage(_page(context))
    page.open(floor=context.floor.id, date=day_of(context, day).isoformat(), time=hhmm)
    page.wait_loaded()


@step('на карте ресурс "{label}" {state}')
def step_ui_map_state(context, label, state):
    expect(MapPage(_page(context)).resource(_name(context, label))).to_have_attribute("data-state", STATES[state])


@step('в браузере выбирают на карте "{label}"')
def step_ui_select(context, label):
    MapPage(_page(context)).select(_name(context, label))


@step('клик по "{label}" на карте не открывает бронирование')
def step_ui_select_disabled(context, label):
    page = MapPage(_page(context))
    page.resource(_name(context, label)).click()
    expect(page.panel).to_have_count(0)
    expect(page.by_id("map-hint")).to_be_visible()


@step("в браузере бронируют выбранную переговорку с {start} до {end}")
def step_ui_book_room(context, start, end):
    MapPage(_page(context)).book_room(start, end)


@step("в браузере бронируют выбранное место с {day_from} по {day_to}")
def step_ui_book_desk(context, day_from, day_to):
    MapPage(_page(context)).book_desk(day_of(context, day_from).isoformat(), day_of(context, day_to).isoformat())


@step("панель сообщает, что бронь создана")
def step_ui_created(context):
    context.ui_booking_id = MapPage(_page(context)).created_booking_id()


@step('по API у "{label}" бронь на "{res}" {day} с {start} до {end} по времени офиса в статусе "{status}"')
def step_api_room_booking(context, label, res, day, start, end, status):
    booking = _api_booking(context, label, res)
    tz = context.cfg.office_tz
    got = (booking.start.astimezone(tz).date(), booking.start.astimezone(tz).strftime("%H:%M"),
           booking.end.astimezone(tz).strftime("%H:%M"), booking.status)
    assert got == (day_of(context, day), start, end, status), f"Бронь по API: {booking}"


@step('по API у "{label}" бронь на "{res}" с {day_from} по {day_to} в статусе "{status}"')
def step_api_desk_booking(context, label, res, day_from, day_to, status):
    booking = _api_booking(context, label, res)
    tz = context.cfg.office_tz
    last_day = booking.end.astimezone(tz).date() - timedelta(days=1)  # бронь места идёт до 00:00 следующего дня
    got = (booking.start.astimezone(tz).date(), last_day, booking.status)
    assert got == (day_of(context, day_from), day_of(context, day_to), status), f"Бронь по API: {booking}"


def _api_booking(context, label: str, res: str) -> models.Booking:
    resp = expect_resp(context.booking.list_bookings(actor(context, label).access_token), 200)
    found = [b for b in parse(models.Booking, resp) if b.resource_id == context.resources[res].id]
    assert len(found) == 1, f"Броней на {res}: {len(found)}"
    return found[0]


# --- брони ---

@step("в браузере открывают раздел «{section}»")
def step_ui_go(context, section):
    BasePage(_page(context)).header.go(section)


@step("в браузере открывают вкладку «{tab}»")
def step_ui_tab(context, tab):
    ids = {"Активные": "active", "История": "history", "Все сотрудники": "everyone"}
    BookingsPage(_page(context)).tab(ids[tab])


@step('в браузере {action} бронь на "{label}"')
def step_ui_booking_action(context, action, label):
    actions = {"подтверждают": "confirm", "отменяют": "cancel", "отмечаются в": "checkin"}
    BookingsPage(_page(context)).act(_name(context, label), actions[action])


@step('карточка брони на "{label}" в статусе «{status}»')
def step_ui_card_status(context, label, status):
    assert status in STATUS_TEXT, f"Нет такого статуса в интерфейсе: {status}"
    card = BookingsPage(_page(context)).card(_name(context, label))
    expect(card.get_by_test_id("booking-status")).to_have_text(status)


@step('в списке нет брони на "{label}"')
def step_ui_no_card(context, label):
    expect(BookingsPage(_page(context)).card(_name(context, label))).to_have_count(0)


@step('у карточки брони на "{label}" нет кнопки «{button}»')
def step_ui_card_no_button(context, label, button):
    card = BookingsPage(_page(context)).card(_name(context, label))
    expect(card).to_be_visible()
    expect(card.get_by_role("button", name=button)).to_have_count(0)


# --- редактор ---

@step("в браузере открывают редактор этажа")
def step_ui_editor(context):
    page = EditorPage(_page(context))
    page.open(floor=context.floor.id)
    expect(page.plan).to_be_visible()


@step('в браузере перетаскивают "{label}" на {dx:d} вправо и {dy:d} вниз')
def step_ui_drag(context, label, dx, dy):
    EditorPage(_page(context)).drag(_name(context, label), dx, dy)


@step("в браузере сохраняют изменения редактора")
def step_ui_editor_save(context):
    EditorPage(_page(context)).save()


@step('в браузере добавляют на план {kind} "{label}"')
def step_ui_editor_add(context, kind, label):
    name = data.unique_name(label)
    context.new_resource_name = name
    EditorPage(_page(context)).add_resource("room" if kind == "переговорку" else "desk", name)
    context.new_resource_label = label


@step("новый ресурс появился на плане редактора")
def step_ui_new_on_plan(context):
    expect(EditorPage(_page(context)).resource(context.new_resource_name)).to_be_visible()


@step('по API на этаже есть {kind} с этим названием')
def step_api_new_resource(context, kind):
    resp = expect_resp(context.booking.list_resources(context.admin.token, floor_id=context.floor.id), 200)
    found = [r for r in parse(models.Resource, resp) if r.name == context.new_resource_name]
    assert len(found) == 1, f"Ресурса {context.new_resource_name} нет на этаже"
    expected = "room" if kind == "переговорка" else "desk"
    assert found[0].kind == expected, found[0]


@step('по API "{label}" стоит в точке {x:d},{y:d}')
def step_api_position(context, label, x, y):
    resp = expect_resp(context.booking.get_resource(context.admin.token, context.resources[label].id), 200)
    resource = parse(models.Resource, resp)
    assert (resource.x, resource.y) == (x, y), f"{label} стоит в {resource.x},{resource.y}, ожидали {x},{y}"


# --- профиль и Telegram ---

@step("в браузере получают код привязки Telegram в профиле")
def step_ui_tg_code(context):
    page = ProfilePage(_page(context)).open()
    command = page.request_code()
    context.link_code = SimpleNamespace(command=command)


@step("после ответа бота в профиле Telegram привязан")
def step_ui_tg_linked(context):
    page = ProfilePage(_page(context))
    # привязку делает поллер бота асинхронно; ждём её по API, затем жмём кнопку, как сделал бы человек
    token = actor(context, context.ui_actor).access_token
    wait_until(lambda: context.tg.get_link(token).status_code == 200, message="Бот не привязал чат")
    page.check_link()
    expect(page.linked).to_be_visible()


# --- администрирование ---

@step('в браузере запускают джобу "{job}"')
def step_ui_run_job(context, job):
    page = JobsPage(_page(context)).open()
    page.run(job)


@step('у джобы "{job}" последний запуск «{status}»')
def step_ui_job_status(context, job, status):
    expect(JobsPage(_page(context)).row(job).get_by_test_id("job-status")).to_have_text(status)


@step('в браузере меняют правило "{key}" на {value:d}')
def step_ui_setting(context, key, value):
    assert "settings" in context.scenario.effective_tags, "Сценарий меняет глобальные правила: нужен тег @settings"
    page = SettingsPage(_page(context)).open()
    page.set(key, value)
    page.save()


@step('по API правило "{key}" = {value:d}')
def step_api_setting(context, key, value):
    settings = expect_resp(context.booking.get_settings(context.admin.token), 200).json()
    assert settings[key] == value, f"{key} = {settings[key]}, ожидали {value}"


@step('в браузере назначают пользователю "{label}" роль "{role}"')
def step_ui_set_role(context, label, role):
    person = actor(context, label, logged_in=False)
    page = UsersPage(_page(context)).open()
    page.search(person.email)
    page.set_role(person.email, role)


@step('по API у пользователя "{label}" роль "{role}"')
def step_api_role(context, label, role):
    person = actor(context, label, logged_in=False)
    resp = expect_resp(context.auth.list_users(context.admin.token, email=person.email), 200)
    assert resp.json()[0]["role"] == role, resp.json()


# --- телефон ---

@step("меню свёрнуто под кнопку")
def step_ui_menu_collapsed(context):
    header = BasePage(_page(context)).header
    expect(header.menu_toggle).to_be_visible()
    expect(header.nav).to_be_hidden()


@step("страница помещается по ширине экрана")
def step_ui_no_horizontal_scroll(context):
    page = _page(context)
    width = page.evaluate("document.documentElement.scrollWidth")
    viewport = page.viewport_size["width"]
    assert width <= viewport, f"Горизонтальная прокрутка: ширина страницы {width}px при экране {viewport}px"
