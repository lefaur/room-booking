import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timezone

import psycopg2
from behave import step

from framework import data, models
from framework.prepare import resource_row
from framework.support import (actor, as_model, day_of, expect, next_cell, office_datetime, parse, preparation,
                               test_floor)


def _last_booking(context) -> models.Booking:
    assert context.bookings, "В сценарии ещё нет брони"
    return context.bookings[-1]


def _remember_booking(context, resp) -> None:
    if resp.status_code == 201:
        context.bookings.append(parse(models.Booking, resp))


# --- ресурсы для сценария ---

def _create_resource(context, label: str, kind: str, capacity: int) -> None:
    floor = test_floor(context)
    x, y = next_cell(context)
    fields = dict(floor_id=floor["id"], kind=kind, name=data.unique_name(label), capacity=capacity,
                  x=x, y=y, w=10, h=10)
    prep = preparation(context)
    if prep:
        with prep:
            row = resource_row(prep, **fields)
        context.resources[label] = as_model(models.Resource, row)
    else:
        resp = context.booking.create_resource(context.admin.token, **fields)
        context.resources[label] = parse(models.Resource, expect(resp, 201))


@step('есть переговорка "{label}" на {capacity:d} мест')
def step_room(context, label, capacity):
    _create_resource(context, label, "room", capacity)


@step('есть рабочее место "{label}"')
def step_desk(context, label):
    _create_resource(context, label, "desk", 1)


@step('переговорка "{label}" отключена')
def step_room_disabled(context, label):
    res = context.resources[label]
    resp = context.booking.patch_resource(context.admin.token, res.id, version=res.version, active=False)
    context.resources[label] = parse(models.Resource, expect(resp, 200))


# --- бронирование ---

def _book_room(context, label, res_label, day, start, end):
    return context.booking.create_booking(
        actor(context, label).access_token, resource_id=context.resources[res_label].id,
        start=office_datetime(context, day, start).isoformat(), end=office_datetime(context, day, end).isoformat())


@step('пользователь "{label}" бронирует "{res}" на {day} с {start} до {end}')
def step_book_room(context, label, res, day, start, end):
    context.resp = _book_room(context, label, res, day, start, end)
    _remember_booking(context, context.resp)


@step('пользователь "{label}" забронировал "{res}" на {day} с {start} до {end}')
def step_booked_room(context, label, res, day, start, end):
    step_book_room(context, label, res, day, start, end)
    expect(context.resp, 201)


@step('пользователь "{label}" бронирует "{res}" на время без часового пояса')
def step_book_naive(context, label, res):
    day = day_of(context, "завтра")
    context.resp = context.booking.create_booking(
        actor(context, label).access_token, resource_id=context.resources[res].id,
        start=datetime.combine(day, time(10)).isoformat(), end=datetime.combine(day, time(11)).isoformat())


@step('пользователь "{label}" бронирует место "{res}" с {day_from} по {day_to}')
def step_book_desk(context, label, res, day_from, day_to):
    context.resp = context.booking.create_booking(
        actor(context, label).access_token, resource_id=context.resources[res].id,
        date_from=day_of(context, day_from).isoformat(), date_to=day_of(context, day_to).isoformat())
    _remember_booking(context, context.resp)


@step('пользователь "{label}" забронировал место "{res}" с {day_from} по {day_to}')
def step_booked_desk(context, label, res, day_from, day_to):
    step_book_desk(context, label, res, day_from, day_to)
    expect(context.resp, 201)


@step("бронь идёт с 00:00 {day_from} до 00:00 {day_to} по времени офиса")
def step_desk_interval(context, day_from, day_to):
    booking = parse(models.Booking, context.resp)
    expected_start = office_datetime(context, day_from, "00:00")
    expected_end = office_datetime(context, day_to, "00:00")
    assert (booking.start, booking.end) == (expected_start, expected_end), (
        f"Бронь {booking.start} – {booking.end}, ожидали {expected_start} – {expected_end}")


# --- действия с бронью ---

@step('пользователь "{label}" подтверждает бронь')
def step_confirm(context, label):
    context.resp = context.booking.confirm(actor(context, label).access_token, _last_booking(context).id)


@step('пользователь "{label}" подтвердил бронь')
def step_confirmed(context, label):
    step_confirm(context, label)
    expect(context.resp, 200)


@step('пользователь "{label}" отменяет бронь')
def step_cancel(context, label):
    context.resp = context.booking.cancel(actor(context, label).access_token, _last_booking(context).id)


@step('пользователь "{label}" отменил бронь')
def step_cancelled(context, label):
    step_cancel(context, label)
    expect(context.resp, 200)


@step('пользователь "{label}" запрашивает бронь')
def step_get_booking(context, label):
    context.resp = context.booking.get_booking(actor(context, label).access_token, _last_booking(context).id)


@step('бронь в статусе "{status}"')
def step_status_in_response(context, status):
    booking = parse(models.Booking, context.resp)
    assert booking.status == status, f"Статус {booking.status}, ожидали {status}"


@step('в БД бронь в статусе "{status}"')
def step_status_in_db(context, status):
    row = context.db.one("SELECT status FROM booking.bookings WHERE id = %s", (_last_booking(context).id,))
    assert row and row["status"] == status, f"В БД {row}, ожидали {status}"


@step('в БД бронь отменена пользователем "{label}"')
def step_cancelled_by(context, label):
    row = context.db.one("SELECT status, cancelled_by FROM booking.bookings WHERE id = %s",
                         (_last_booking(context).id,))
    assert row == {"status": "cancelled", "cancelled_by": context.users[label].id}, row


@step("бронь создана {minutes:d} минут назад")
def step_age_booking(context, minutes):
    updated = context.db.execute(
        "UPDATE booking.bookings SET created_at = now() - make_interval(mins => %s) WHERE id = %s",
        (minutes, _last_booking(context).id))
    assert updated == 1


# --- правила и джобы ---

@step('в правилах "{key}" = {value:d}')
def step_set_rule(context, key, value):
    assert "settings" in context.scenario.effective_tags, (
        "Правила глобальные: сценарий, который их меняет, должен иметь тег @settings")
    expect(context.booking.put_settings(context.admin.token, **{key: value}), 200)


@step('администратор задаёт правило "{key}" = {value:d}')
def step_admin_sets_rule(context, key, value):
    context.resp = context.booking.put_settings(context.admin.token, **{key: value})


@step("администратор запускает джобу просрочки")
def step_run_expire(context):
    context.resp = context.booking.run_expire_job(context.admin.token)


# --- гонки ---

@step('{count:d} сотрудников одновременно бронируют "{res}" на {day} с {start} до {end}')
def step_race(context, count, res, day, start, end):
    labels = [f"сотрудник {i}" for i in range(1, count + 1)]
    for label in labels:
        actor(context, label)  # готовим всех заранее, чтобы в гонке были только брони
    barrier = threading.Barrier(count)

    def attempt(label):
        barrier.wait()
        return _book_room(context, label, res, day, start, end)

    with ThreadPoolExecutor(max_workers=count) as pool:
        context.race = list(pool.map(attempt, labels))


@step("ровно один запрос получил 201, остальные 409")
def step_race_result(context):
    codes = sorted(r.status_code for r in context.race)
    assert codes == [201] + [409] * (len(codes) - 1), f"Коды ответов: {codes}"


@step('в БД ровно одна активная бронь на "{res}"')
def step_one_active(context, res):
    row = context.db.one("SELECT count(*) AS n FROM booking.bookings "
                         "WHERE resource_id = %s AND status IN ('pending', 'confirmed', 'checked_in')",
                         (context.resources[res].id,))
    assert row["n"] == 1, f"Активных броней: {row['n']}"


@step('в БД напрямую вставляется бронь на "{res}" на {day} с {start} до {end}')
def step_insert_directly(context, res, day, start, end):
    context.db_error = None
    try:
        context.db.execute(
            "INSERT INTO booking.bookings (resource_id, user_id, user_email, start_at, end_at, status, "
            "created_at, updated_at) VALUES (%s, 0, 'direct@db.test', %s, %s, 'pending', now(), now())",
            (context.resources[res].id, office_datetime(context, day, start).astimezone(timezone.utc),
             office_datetime(context, day, end).astimezone(timezone.utc)))
    except psycopg2.Error as error:
        context.db_error = error


@step('БД отклоняет вставку по ограничению "{constraint}"')
def step_db_rejected(context, constraint):
    error = context.db_error
    assert error is not None, "Вставка прошла, двойная бронь в БД"
    assert isinstance(error, psycopg2.errors.ExclusionViolation), type(error)
    assert error.diag.constraint_name == constraint, error.diag.constraint_name
