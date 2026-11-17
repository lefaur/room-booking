"""Переходы статусов брони и джобы. Общие для публичного API, бота (через /internal) и планировщика."""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from booking import config
from booking.events import emit
from booking.models import Booking, Resource, Setting, utcnow


def settings_map(db: Session) -> dict[str, int]:
    return {row.key: row.value for row in db.scalars(select(Setting))}


def _hhmm(moment) -> str:
    return moment.astimezone(config.OFFICE_TZ).strftime("%H:%M")


def checkin_window(booking: Booking, kind: str, rules: dict[str, int]):
    opens = booking.start_at - timedelta(minutes=rules["checkin_open_minutes_before"])
    if kind == "room":
        closes = booking.start_at + timedelta(minutes=rules["no_show_grace_minutes"])
    else:
        closes = booking.start_at + timedelta(hours=config.DESK_CHECKIN_DEADLINE_HOURS)
    return opens, closes


# --- действия с бронью ---

def confirm(db: Session, booking: Booking, actor_id: int) -> Booking:
    if booking.user_id != actor_id:
        raise HTTPException(403, "Подтвердить бронь может только её автор")
    timeout = timedelta(minutes=settings_map(db)["confirm_timeout_minutes"])
    if booking.status == "pending" and booking.created_at < utcnow() - timeout:
        booking.status = "expired"  # джоба ещё не успела, но срок подтверждения уже вышел
        emit(db, "booking.expired", booking)
        db.commit()
    if booking.status != "pending":
        raise HTTPException(409, f"Нельзя подтвердить бронь в статусе {booking.status}")
    booking.status = "confirmed"
    emit(db, "booking.confirmed", booking)
    db.commit()
    return booking


def cancel(db: Session, booking: Booking, actor_id: int, can_cancel_any: bool) -> Booking:
    if booking.user_id != actor_id and not can_cancel_any:
        raise HTTPException(403, "Нет прав: bookings.cancel_any")
    if booking.status not in ("pending", "confirmed"):
        raise HTTPException(409, f"Нельзя отменить бронь в статусе {booking.status}")
    if booking.end_at <= utcnow():
        raise HTTPException(409, "Бронь уже закончилась")
    booking.status = "cancelled"
    booking.cancelled_by = actor_id
    emit(db, "booking.cancelled", booking, cancelled_by=actor_id, by_owner=actor_id == booking.user_id)
    db.commit()
    return booking


def check_in(db: Session, booking: Booking, actor_id: int) -> Booking:
    if booking.user_id != actor_id:
        raise HTTPException(403, "Отметиться может только автор брони")
    if booking.status != "confirmed":
        raise HTTPException(409, f"Отметиться можно только в подтверждённой брони, сейчас {booking.status}")
    resource = db.get(Resource, booking.resource_id)
    opens, closes = checkin_window(booking, resource.kind, settings_map(db))
    now = utcnow()
    if not opens <= now < closes:
        raise HTTPException(409, f"Отметиться можно с {_hhmm(opens)} до {_hhmm(closes)}")
    booking.status = "checked_in"
    booking.checked_in_at = now
    db.commit()
    return booking


# --- джобы (коммитит вызывающий) ---

def expire_pending(db: Session, resource_id: int | None = None) -> int:
    """Неподтверждённые за confirm_timeout_minutes брони → expired."""
    border = utcnow() - timedelta(minutes=settings_map(db)["confirm_timeout_minutes"])
    query = select(Booking).where(Booking.status == "pending", Booking.created_at < border)
    if resource_id is not None:
        query = query.where(Booking.resource_id == resource_id)
    rows = db.scalars(query.with_for_update(skip_locked=True)).all()
    for booking in rows:
        booking.status = "expired"
        emit(db, "booking.expired", booking)
    db.flush()  # следующие запросы в этой транзакции должны видеть новые статусы
    return len(rows)


def send_reminders(db: Session) -> int:
    """Подтверждённые брони переговорок, которые начнутся в ближайшие reminder_minutes_before минут.
    reminder_sent_at не даёт напомнить дважды."""
    now = utcnow()
    border = now + timedelta(minutes=settings_map(db)["reminder_minutes_before"])
    rows = db.scalars(select(Booking).join(Resource).where(
        Resource.kind == "room", Booking.status == "confirmed", Booking.reminder_sent_at.is_(None),
        Booking.start_at > now, Booking.start_at <= border).with_for_update(of=Booking, skip_locked=True)).all()
    for booking in rows:
        booking.reminder_sent_at = now
        emit(db, "booking.reminder", booking)
    db.flush()  # следующие запросы в этой транзакции должны видеть новые статусы
    return len(rows)


def release_no_shows(db: Session) -> int:
    """Подтверждённые брони без отметки после окна чек-ина → no_show, ресурс освобождается."""
    now = utcnow()
    grace = timedelta(minutes=settings_map(db)["no_show_grace_minutes"])
    desk_deadline = timedelta(hours=config.DESK_CHECKIN_DEADLINE_HOURS)
    rows = db.scalars(select(Booking).join(Resource).where(
        Booking.status == "confirmed",
        or_(and_(Resource.kind == "room", Booking.start_at + grace <= now),
            and_(Resource.kind == "desk", Booking.start_at + desk_deadline <= now)),
    ).with_for_update(of=Booking, skip_locked=True)).all()
    for booking in rows:
        booking.status = "no_show"
        emit(db, "booking.no_show", booking)
    db.flush()  # следующие запросы в этой транзакции должны видеть новые статусы
    return len(rows)
