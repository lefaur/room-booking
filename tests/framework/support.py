"""Общие помощники шагов: участники, площадка для ресурсов, даты, проверка ответа."""
import re
from datetime import date, datetime, time, timedelta

from pydantic import BaseModel
from requests import Response

from framework import data, prepare
from framework.actors import Actor
from framework.http import ApiClient
from framework.prepare import Preparation

GRID = 11          # шаг сетки, на которой раскладываются ресурсы тестового этажа
GRID_COLUMNS = 900
FLOOR_SIZE = GRID * GRID_COLUMNS


def preparation(context) -> Preparation | None:
    """Пачка SQL-подготовки сценария (None при PREPARE_VIA=api); созданное сразу попадает в уборку."""
    return Preparation(context.db, on_created=context.cleanup.track_row) if prepare.VIA_SQL else None


def actor(context, label: str, logged_in: bool = True, via_api: bool = False) -> Actor:
    """Участник сценария по ярлыку: создаётся при первом упоминании, дальше переиспользуется.
    via_api — когда важны побочные эффекты настоящей регистрации (приветственное письмо)."""
    if label not in context.users:
        context.users[label] = context.actors.register(label, None if via_api else preparation(context))
    person = context.users[label]
    if logged_in and person.access_token is None:
        context.actors.login(person)
    return person


def test_floor(context) -> dict:
    """Один этаж на процесс: ресурсы разных сценариев раскладываются по сетке и не пересекаются.
    Живёт дольше сценария, поэтому из уборки сценария исключается и удаляется в after_all."""
    shared = context.shared
    if shared.floor is None:
        name = data.unique_name("autotest-floor")
        prep = preparation(context)
        if prep:
            with prep:
                floor = prepare.floor_row(prep, name=name, level=1, width=FLOOR_SIZE, height=FLOOR_SIZE)
        else:
            floor = expect(context.booking.create_floor(context.admin.token, name=name, level=1,
                                                        width=FLOOR_SIZE, height=FLOOR_SIZE), 201).json()
        context.cleanup.forget("floor", floor["id"])
        shared.floor = floor
    return shared.floor


def as_model(model: type[BaseModel], row: dict):
    """Строка БД в контракт API: лишние столбцы (created_at) отбрасываются."""
    return model.model_validate({name: row[name] for name in model.model_fields})


def next_cell(context) -> tuple[int, int]:
    index = next(context.shared.cells)
    return (index % GRID_COLUMNS) * GRID, (index // GRID_COLUMNS) * GRID


def expect(resp: Response, status: int, contains: str | None = None) -> Response:
    assert resp.status_code == status, (
        f"Ожидали {status}, пришло {resp.status_code}\n\n{ApiClient.describe(resp)}")
    if contains is not None:
        assert contains.lower() in resp.text.lower(), (
            f"В ответе нет «{contains}»\n\n{ApiClient.describe(resp)}")
    return resp


def parse(model: type[BaseModel], resp: Response):
    """Ответ по контракту: лишнее или пропавшее поле ломает тест сразу."""
    body = resp.json()
    if isinstance(body, list):
        return [model.model_validate(item) for item in body]
    return model.model_validate(body)


WEEKDAYS = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}


def next_week_monday(context) -> date:
    today = datetime.now(context.cfg.office_tz).date()
    return today + timedelta(days=7 - today.weekday())


def work_week_monday(context) -> date:
    """Понедельник ближайшей (начиная со следующей) недели, где пн–пт рабочие по календарю сервиса.
    Так сценарии с рабочими местами не зависят от того, в какой день и месяц их запускают."""
    shared = context.shared
    if shared.work_monday is None:
        monday = next_week_monday(context)
        for _ in range(3):
            resp = context.booking.calendar(context.admin.token, monday.isoformat(),
                                            (monday + timedelta(days=4)).isoformat())
            expect(resp, 200)
            if all(day["working"] for day in resp.json()):
                shared.work_monday = monday
                break
            monday += timedelta(days=7)
        else:
            raise AssertionError("В ближайшие три недели нет полностью рабочей недели")
    return shared.work_monday


def day_of(context, text: str) -> date:
    """Кроме «завтра» / «через N дн.» понимает «ср рабочей недели» и «сб следующей недели»."""
    match = re.fullmatch(r"(пн|вт|ср|чт|пт|сб|вс) (рабочей|следующей) недели", text.strip())
    if not match:
        return data.parse_day(text, context.cfg.office_tz)
    monday = work_week_monday(context) if match.group(2) == "рабочей" else next_week_monday(context)
    return monday + timedelta(days=WEEKDAYS[match.group(1)])


def office_datetime(context, day: str, hhmm: str) -> datetime:
    hours, minutes = map(int, hhmm.split(":"))
    return datetime.combine(day_of(context, day), time(hours, minutes), context.cfg.office_tz)
