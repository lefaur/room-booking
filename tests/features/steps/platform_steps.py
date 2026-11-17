"""Шаги для планировщика, календаря, check-in, напоминаний и неявок."""
from datetime import datetime

from behave import step

from framework import models
from framework.support import actor, day_of, expect, parse


def _last_booking(context) -> models.Booking:
    assert context.bookings, "В сценарии ещё нет брони"
    return context.bookings[-1]


# --- планировщик ---

@step('администратор запускает джобу "{job}"')
def step_run_job(context, job):
    context.resp = context.scheduler.run(context.admin.token, job)


@step('администратор запустил джобу "{job}"')
def step_ran_job(context, job):
    step_run_job(context, job)
    expect(context.resp, 200)


@step('пользователь "{label}" запускает джобу "{job}"')
def step_user_runs_job(context, label, job):
    context.resp = context.scheduler.run(actor(context, label).access_token, job)


@step('джоба отработала со статусом "{status}"')
def step_job_status(context, status):
    run = parse(models.JobRun, context.resp)
    assert run.status == status and run.trigger == "manual", run


@step('в журнале джоб booking последний запуск "{job}" со статусом "{status}"')
def step_job_journal(context, job, status):
    row = context.db.one("SELECT status, details FROM booking.job_runs WHERE job = %s ORDER BY id DESC LIMIT 1",
                         (job,))
    assert row and row["status"] == status, f"Последний запуск {job}: {row}"


@step("в списке джоб планировщика есть")
def step_jobs_listed(context):
    resp = expect(context.scheduler.jobs(context.admin.token), 200)
    jobs = {job["name"]: job for job in resp.json()}
    for row in context.table:
        assert row["джоба"] in jobs, f"Нет джобы {row['джоба']}, есть {sorted(jobs)}"
        assert jobs[row["джоба"]]["schedule"] == row["расписание"], jobs[row["джоба"]]


# --- календарь ---

@step('внешний календарь отдаёт праздник "{title}" в {holiday} и рабочую {working}')
def step_calendar_source(context, title, holiday, working):
    """Источник отдаёт за текущий и следующий год только эти два дня (остальные годы — стандартно)."""
    holiday_day, working_day = day_of(context, holiday), day_of(context, working)
    this_year = datetime.now(context.cfg.office_tz).year
    days = {year: [] for year in (this_year, this_year + 1)}
    days[holiday_day.year].append({"date": holiday_day.isoformat(), "type": "holiday", "title": title})
    days[working_day.year].append({"date": working_day.isoformat(), "type": "working", "title": "Перенос"})
    context.stubs.set_calendar("ok", days)


@step('внешний календарь в режиме "{mode}"')
def step_calendar_mode(context, mode):
    context.stubs.set_calendar(mode)


@step('в календаре сервиса {day} — "{kind}" "{title}"')
def step_calendar_day_titled(context, day, kind, title):
    found = _calendar_day(context, day)
    assert (found.kind, found.title) == (kind, title), found


@step('в календаре сервиса {day} — "{kind}"')
def step_calendar_day(context, day, kind):
    found = _calendar_day(context, day)
    assert found.kind == kind, found


def _calendar_day(context, day) -> models.CalendarDay:
    target = day_of(context, day).isoformat()
    resp = expect(context.booking.calendar(actor(context, "сотрудник").access_token, target, target), 200)
    (found,) = parse(models.CalendarDay, resp)
    return found


# --- время брони относительно «сейчас» ---

@step("бронь начинается через {minutes:d} минут")
def step_starts_in(context, minutes):
    _shift(context, minutes)


@step("бронь началась {minutes:d} минут назад")
def step_started_ago(context, minutes):
    _shift(context, -minutes)


def _shift(context, minutes: int) -> None:
    """Сдвигаем бронь к текущему моменту прямо в БД: через API бронь в прошлом не создать,
    а ждать реальные 15 минут в тесте нельзя."""
    booking = _last_booking(context)
    duration = booking.end - booking.start
    updated = context.db.execute(
        "UPDATE booking.bookings SET start_at = now() + make_interval(mins => %s), "
        "end_at = now() + make_interval(mins => %s) + %s WHERE id = %s",
        (minutes, minutes, duration, booking.id))
    assert updated == 1


# --- check-in ---

@step('пользователь "{label}" отмечается в брони')
def step_check_in(context, label):
    context.resp = context.booking.check_in(actor(context, label).access_token, _last_booking(context).id)


@step("в БД время отметки заполнено")
def step_checked_in_at(context):
    row = context.db.one("SELECT checked_in_at FROM booking.bookings WHERE id = %s", (_last_booking(context).id,))
    assert row["checked_in_at"] is not None, row


@step("в БД напоминание по брони {state}")
def step_reminder_state(context, state):
    row = context.db.one("SELECT reminder_sent_at FROM booking.bookings WHERE id = %s",
                         (_last_booking(context).id,))
    sent = row["reminder_sent_at"] is not None
    assert sent == (state == "отправлено"), f"reminder_sent_at = {row['reminder_sent_at']}, ожидали «{state}»"


@step("у ресурса не осталось активных броней")
def step_time_released(context):
    booking = _last_booking(context)
    row = context.db.one("SELECT count(*) AS n FROM booking.bookings WHERE resource_id = %s "
                         "AND status IN ('pending', 'confirmed', 'checked_in')", (booking.resource_id,))
    assert row["n"] == 0, f"У ресурса остались активные брони: {row['n']}"



# --- чистка токенов и внутренний API ---

@step('refresh-токен пользователя "{label}" просрочен')
def step_expire_refresh(context, label):
    updated = context.db.execute("UPDATE auth.refresh_tokens SET expires_at = now() - interval '1 day' "
                                 "WHERE user_id = %s", (context.users[label].id,))
    assert updated >= 1


@step('в БД нет refresh-токенов пользователя "{label}"')
def step_no_refresh(context, label):
    row = context.db.one("SELECT count(*) AS n FROM auth.refresh_tokens WHERE user_id = %s",
                         (context.users[label].id,))
    assert row["n"] == 0, f"Осталось токенов: {row['n']}"


@step('гость обращается к "{path}"')
def step_guest_get(context, path):
    context.resp = context.http.request("POST" if "/jobs/" in path else "GET", path)
