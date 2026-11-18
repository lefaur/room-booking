"""Сервис booking: этажи, переговорки и рабочие места, брони, правила бронирования, карта этажа,
производственный календарь. Публикует события броней в RabbitMQ через outbox."""
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import AwareDatetime
from sqlalchemy import exists, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from booking import calendar_sync, config, logic, schemas
from booking.db import Base, SessionLocal, engine, get_db
from booking.events import confirm_deadline, emit, outbox
from booking.logic import settings_map
from booking.models import ACTIVE_STATUSES, Booking, Floor, JobRun, Resource, Setting, utcnow
from common.security import Principal, current_principal, require, require_service

# Страховка от двойной брони на уровне БД: даже если проверка в коде пропустит гонку,
# PostgreSQL не даст двум активным броням одного ресурса пересечься по времени.
NO_OVERLAP_DDL = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bookings_no_overlap') THEN
    ALTER TABLE booking.bookings ADD CONSTRAINT bookings_no_overlap
      EXCLUDE USING gist (resource_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)
      WHERE (status IN ('pending', 'confirmed', 'checked_in'));
  END IF;
END $$;
"""


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS booking"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(NO_OVERLAP_DDL))
    with SessionLocal() as db:
        for key, value in config.DEFAULT_SETTINGS.items():
            if not db.get(Setting, key):
                db.add(Setting(key=key, value=value))
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    outbox.start_relay()
    yield


app = FastAPI(title="OfficeSpace · booking", root_path=config.ROOT_PATH, lifespan=lifespan)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok"}


# --- этажи ---

def _floor_or_404(db: Session, floor_id: int) -> Floor:
    floor = db.get(Floor, floor_id)
    if not floor:
        raise HTTPException(404, "Нет такого этажа")
    return floor


@app.get("/floors", response_model=list[schemas.FloorOut])
def list_floors(db: Session = Depends(get_db), _: Principal = Depends(current_principal)):
    return db.scalars(select(Floor).order_by(Floor.level, Floor.id)).all()


@app.post("/floors", response_model=schemas.FloorOut, status_code=201)
def create_floor(body: schemas.FloorIn, db: Session = Depends(get_db), _: Principal = Depends(require("floors.write"))):
    floor = Floor(**body.model_dump())
    db.add(floor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Этаж с таким названием уже есть")
    return floor


@app.get("/floors/{floor_id}", response_model=schemas.FloorOut)
def get_floor(floor_id: int, db: Session = Depends(get_db), _: Principal = Depends(current_principal)):
    return _floor_or_404(db, floor_id)


@app.patch("/floors/{floor_id}", response_model=schemas.FloorOut)
def patch_floor(floor_id: int, body: schemas.FloorPatch, db: Session = Depends(get_db),
                _: Principal = Depends(require("floors.write"))):
    floor = _floor_or_404(db, floor_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(floor, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Этаж с таким названием уже есть")
    return floor


@app.delete("/floors/{floor_id}", status_code=204)
def delete_floor(floor_id: int, db: Session = Depends(get_db), _: Principal = Depends(require("floors.write"))):
    floor = _floor_or_404(db, floor_id)
    if db.scalar(select(exists().where(Resource.floor_id == floor.id))):
        raise HTTPException(409, "На этаже есть ресурсы, сначала удалите их")
    db.delete(floor)
    db.commit()
    return Response(status_code=204)


@app.get("/floors/{floor_id}/map", response_model=schemas.FloorMap)
def floor_map(floor_id: int, at: AwareDatetime | None = None, db: Session = Depends(get_db),
              principal: Principal = Depends(current_principal)):
    """Ресурсы этажа с признаком занятости на момент at (по умолчанию сейчас) и тем, своя ли это бронь."""
    floor = _floor_or_404(db, floor_id)
    moment = at or utcnow()
    holders = dict(db.execute(select(Booking.resource_id, Booking.user_id).join(Resource).where(
        Resource.floor_id == floor.id, Booking.status.in_(ACTIVE_STATUSES),
        Booking.start_at <= moment, Booking.end_at > moment)).all())
    resources = db.scalars(select(Resource).where(Resource.floor_id == floor.id).order_by(Resource.id)).all()
    return schemas.FloorMap(
        floor=schemas.FloorOut.model_validate(floor), at=moment,
        resources=[schemas.MapResource(**schemas.ResourceOut.model_validate(r).model_dump(), busy=r.id in holders,
                                       mine=holders.get(r.id) == principal.user_id)
                   for r in resources])


# --- ресурсы (переговорки и рабочие места) ---

def _check_geometry(db: Session, floor: Floor, x: int, y: int, w: int, h: int, skip_id: int | None = None) -> None:
    if x + w > floor.width or y + h > floor.height:
        raise HTTPException(422, "Ресурс выходит за границы плана этажа")
    overlap = select(Resource.name).where(
        Resource.floor_id == floor.id, Resource.x < x + w, Resource.x + Resource.w > x,
        Resource.y < y + h, Resource.y + Resource.h > y)
    if skip_id is not None:
        overlap = overlap.where(Resource.id != skip_id)
    other = db.scalar(overlap.limit(1))
    if other:
        raise HTTPException(409, f"Ресурс пересекается с «{other}»")


def _resource_or_404(db: Session, resource_id: int, lock: bool = False) -> Resource:
    stmt = select(Resource).where(Resource.id == resource_id)
    if lock:
        stmt = stmt.with_for_update()
    resource = db.scalar(stmt)
    if not resource:
        raise HTTPException(404, "Нет такого ресурса")
    return resource


@app.get("/resources", response_model=list[schemas.ResourceOut])
def list_resources(floor_id: int | None = None, kind: Literal["room", "desk"] | None = None,
                   active: bool | None = None, min_capacity: int | None = None,
                   db: Session = Depends(get_db), _: Principal = Depends(current_principal)):
    query = select(Resource).order_by(Resource.id)
    if floor_id is not None:
        query = query.where(Resource.floor_id == floor_id)
    if kind:
        query = query.where(Resource.kind == kind)
    if active is not None:
        query = query.where(Resource.active.is_(active))
    if min_capacity is not None:
        query = query.where(Resource.capacity >= min_capacity)
    return db.scalars(query).all()


@app.post("/resources", response_model=schemas.ResourceOut, status_code=201)
def create_resource(body: schemas.ResourceIn, db: Session = Depends(get_db),
                    _: Principal = Depends(require("resources.write"))):
    floor = db.scalar(select(Floor).where(Floor.id == body.floor_id).with_for_update())
    if not floor:
        raise HTTPException(404, "Нет такого этажа")
    _check_geometry(db, floor, body.x, body.y, body.w, body.h)
    resource = Resource(**body.model_dump())
    db.add(resource)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "На этаже уже есть ресурс с таким названием")
    return resource


@app.get("/resources/{resource_id}", response_model=schemas.ResourceOut)
def get_resource(resource_id: int, db: Session = Depends(get_db), _: Principal = Depends(current_principal)):
    return _resource_or_404(db, resource_id)


@app.patch("/resources/{resource_id}", response_model=schemas.ResourceOut)
def patch_resource(resource_id: int, body: schemas.ResourcePatch, db: Session = Depends(get_db),
                   _: Principal = Depends(require("resources.write"))):
    resource = _resource_or_404(db, resource_id, lock=True)
    if body.version != resource.version:
        raise HTTPException(409, f"Ресурс уже изменён: текущая версия {resource.version}")
    changes = body.model_dump(exclude_none=True, exclude={"version"})
    if resource.kind == "desk" and changes.get("capacity", 1) != 1:
        raise HTTPException(422, "У рабочего места вместимость 1")
    geometry = {k: changes.get(k, getattr(resource, k)) for k in ("x", "y", "w", "h")}
    if any(k in changes for k in geometry):
        _check_geometry(db, db.get(Floor, resource.floor_id), skip_id=resource.id, **geometry)
    for field, value in changes.items():
        setattr(resource, field, value)
    resource.version += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "На этаже уже есть ресурс с таким названием")
    return resource


@app.delete("/resources/{resource_id}", status_code=204)
def delete_resource(resource_id: int, db: Session = Depends(get_db),
                    _: Principal = Depends(require("resources.write"))):
    resource = _resource_or_404(db, resource_id)
    if db.scalar(select(exists().where(Booking.resource_id == resource.id))):
        raise HTTPException(409, "У ресурса есть брони: отключите его (active=false) вместо удаления")
    db.delete(resource)
    db.commit()
    return Response(status_code=204)


# --- брони ---

def _room_interval(body: schemas.BookingIn, rules: dict[str, int], now: datetime) -> tuple[datetime, datetime]:
    if body.start is None or body.end is None or body.date_from or body.date_to:
        raise HTTPException(422, "Для переговорки укажите start и end (без date_from/date_to)")
    start, end = body.start.astimezone(timezone.utc), body.end.astimezone(timezone.utc)
    for moment in (start, end):
        if moment.minute % 30 or moment.second or moment.microsecond:
            raise HTTPException(422, "Время брони должно быть кратно 30 минутам")
    if end <= start:
        raise HTTPException(422, "Окончание должно быть позже начала")
    if start < now:
        raise HTTPException(422, "Нельзя бронировать в прошлом")
    if end - start > timedelta(hours=rules["max_booking_hours"]):
        raise HTTPException(422, f"Бронь длиннее допустимой ({rules['max_booking_hours']} ч)")
    return start, end


def _desk_interval(db: Session, body: schemas.BookingIn, rules: dict[str, int],
                   now: datetime) -> tuple[datetime, datetime]:
    if body.date_from is None or body.date_to is None or body.start or body.end:
        raise HTTPException(422, "Для рабочего места укажите date_from и date_to (без start/end)")
    if body.date_to < body.date_from:
        raise HTTPException(422, "date_to раньше date_from")
    if body.date_from < now.astimezone(config.OFFICE_TZ).date():
        raise HTTPException(422, "Нельзя бронировать в прошлом")
    days = (body.date_to - body.date_from).days + 1
    if days > rules["max_desk_days"]:
        raise HTTPException(422, f"Рабочее место можно занять не больше чем на {rules['max_desk_days']} дн.")
    day_off = calendar_sync.first_non_working(db, body.date_from, body.date_to)
    if day_off:
        raise HTTPException(422, f"{day_off['date'].isoformat()} — нерабочий день {day_off['title']}".strip())
    start = datetime.combine(body.date_from, time(0), config.OFFICE_TZ).astimezone(timezone.utc)
    end = datetime.combine(body.date_to + timedelta(days=1), time(0), config.OFFICE_TZ).astimezone(timezone.utc)
    return start, end


@app.post("/bookings", response_model=schemas.BookingOut, status_code=201)
def create_booking(body: schemas.BookingIn, db: Session = Depends(get_db),
                   principal: Principal = Depends(require("bookings.create"))):
    rules = settings_map(db)
    now = utcnow()
    # блокировка строки ресурса сериализует параллельные брони одного ресурса
    resource = _resource_or_404(db, body.resource_id, lock=True)
    if not resource.active:
        raise HTTPException(409, "Ресурс отключён")
    if resource.kind == "room":
        start, end = _room_interval(body, rules, now)
    else:
        start, end = _desk_interval(db, body, rules, now)
    if start > now + timedelta(days=rules["booking_horizon_days"]):
        raise HTTPException(422, f"Бронировать можно не дальше чем на {rules['booking_horizon_days']} дн. вперёд")

    active_count = db.scalar(select(func.count()).select_from(Booking).where(
        Booking.user_id == principal.user_id, Booking.status.in_(ACTIVE_STATUSES), Booking.end_at > now))
    if active_count >= rules["max_active_bookings_per_user"]:
        raise HTTPException(409, f"Превышен лимит активных броней ({rules['max_active_bookings_per_user']})")

    logic.expire_pending(db, resource.id)  # просроченные pending не должны держать время
    clash = db.scalar(select(exists().where(
        Booking.resource_id == resource.id, Booking.status.in_(ACTIVE_STATUSES),
        Booking.start_at < end, Booking.end_at > start)))
    if clash:
        db.commit()  # сохраняем просрочку, если она случилась
        raise HTTPException(409, _busy_message(resource))

    booking = Booking(resource_id=resource.id, user_id=principal.user_id, user_email=principal.email,
                      start_at=start, end_at=end, created_at=now)
    db.add(booking)
    try:
        db.flush()
        emit(db, "booking.created", booking,
             confirm_until=confirm_deadline(booking, rules["confirm_timeout_minutes"]))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, _busy_message(resource))
    return booking


def _busy_message(resource: Resource) -> str:
    return "Переговорка занята на это время" if resource.kind == "room" else "Рабочее место занято в эти дни"


def _visible_booking(db: Session, booking_id: int, principal: Principal, lock: bool = False) -> Booking:
    stmt = select(Booking).where(Booking.id == booking_id)
    if lock:
        stmt = stmt.with_for_update()
    booking = db.scalar(stmt)
    # чужую бронь без права видеть все не раскрываем: 404, а не 403
    if not booking or (booking.user_id != principal.user_id and "bookings.read_all" not in principal.perms):
        raise HTTPException(404, "Нет такой брони")
    return booking


@app.get("/bookings", response_model=list[schemas.BookingOut])
def list_bookings(scope: Literal["own", "all"] = "own", status: str | None = None, resource_id: int | None = None,
                  limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    query = select(Booking).order_by(Booking.id).limit(limit).offset(offset)
    if scope == "all":
        if "bookings.read_all" not in principal.perms:
            raise HTTPException(403, "Нет прав: bookings.read_all")
    else:
        query = query.where(Booking.user_id == principal.user_id)
    if status:
        query = query.where(Booking.status == status)
    if resource_id is not None:
        query = query.where(Booking.resource_id == resource_id)
    return db.scalars(query).all()


@app.get("/bookings/{booking_id}", response_model=schemas.BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    return _visible_booking(db, booking_id, principal)


@app.post("/bookings/{booking_id}/confirm", response_model=schemas.BookingOut)
def confirm_booking(booking_id: int, db: Session = Depends(get_db),
                    principal: Principal = Depends(current_principal)):
    return logic.confirm(db, _visible_booking(db, booking_id, principal, lock=True), principal.user_id)


@app.post("/bookings/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel_booking(booking_id: int, db: Session = Depends(get_db),
                   principal: Principal = Depends(current_principal)):
    booking = _visible_booking(db, booking_id, principal, lock=True)
    return logic.cancel(db, booking, principal.user_id, "bookings.cancel_any" in principal.perms)


@app.post("/bookings/{booking_id}/check-in", response_model=schemas.BookingOut)
def check_in_booking(booking_id: int, db: Session = Depends(get_db),
                     principal: Principal = Depends(current_principal)):
    return logic.check_in(db, _visible_booking(db, booking_id, principal, lock=True), principal.user_id)


# --- календарь ---

@app.get("/calendar", response_model=list[schemas.CalendarDayOut])
def get_calendar(date_from: date, date_to: date, db: Session = Depends(get_db),
                 _: Principal = Depends(current_principal)):
    if date_to < date_from or (date_to - date_from).days > 366:
        raise HTTPException(422, "Период от 1 до 367 дней, date_to не раньше date_from")
    return calendar_sync.days_between(db, date_from, date_to)


# --- правила и служебное ---

@app.get("/settings")
def get_settings(db: Session = Depends(get_db), _: Principal = Depends(current_principal)):
    return settings_map(db)


@app.put("/settings")
def put_settings(body: schemas.SettingsPatch, db: Session = Depends(get_db),
                 _: Principal = Depends(require("settings.write"))):
    for key, value in body.model_dump(exclude_none=True).items():
        db.get(Setting, key).value = value
    db.commit()
    return settings_map(db)


@app.post("/jobs/expire-pending")
def run_expire_job(db: Session = Depends(get_db), _: Principal = Depends(require("jobs.run"))):
    expired = logic.expire_pending(db)
    db.commit()
    return {"expired": expired}


# --- внутренний API: только внутри сети, gateway его не пропускает ---

JOBS = {
    "expire-pending": lambda db: {"expired": logic.expire_pending(db)},
    "send-reminders": lambda db: {"reminded": logic.send_reminders(db)},
    "release-no-shows": lambda db: {"released": logic.release_no_shows(db)},
    "sync-calendar": calendar_sync.sync,
}


@app.post("/internal/jobs/{job}", dependencies=[Depends(require_service)])
def run_internal_job(job: str):
    """Запуск джобы планировщиком. Каждый запуск пишется в job_runs; ошибка → 502 и статус failed."""
    if job not in JOBS:
        raise HTTPException(404, f"Нет джобы {job}")
    with SessionLocal() as db:
        run = JobRun(job=job, started_at=utcnow())
        db.add(run)
        db.commit()
        try:
            result = JOBS[job](db)
            db.commit()
            run.status, run.details = "ok", result
        except Exception as error:  # noqa: BLE001 — любая ошибка джобы фиксируется в журнале
            db.rollback()
            run.status, run.details = "failed", {"error": f"{type(error).__name__}: {error}"[:500]}
        run.finished_at = utcnow()
        db.commit()
        if run.status == "failed":
            raise HTTPException(502, {"job": job, "status": "failed", "run_id": run.id, **run.details})
        return {"job": job, "status": "ok", "run_id": run.id, **run.details}


@app.get("/internal/bookings", dependencies=[Depends(require_service)])
def internal_upcoming(user_id: int, db: Session = Depends(get_db)):
    """Ближайшие активные брони пользователя (для команды бота /my)."""
    rows = db.execute(select(Booking, Resource.name).join(Resource).where(
        Booking.user_id == user_id, Booking.status.in_(ACTIVE_STATUSES), Booking.end_at > utcnow(),
    ).order_by(Booking.start_at).limit(10)).all()
    return [{"booking_id": b.id, "resource_name": name, "start": b.start_at, "end": b.end_at, "status": b.status}
            for b, name in rows]


@app.post("/internal/bookings/{booking_id}/{action}", response_model=schemas.BookingOut,
          dependencies=[Depends(require_service)])
def internal_action(booking_id: int, action: Literal["confirm", "cancel", "check-in"], user_id: int,
                    db: Session = Depends(get_db)):
    """Действие от имени пользователя (кнопки в Telegram). Те же правила, что и в публичном API."""
    booking = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not booking or booking.user_id != user_id:
        raise HTTPException(404, "Нет такой брони")
    if action == "confirm":
        return logic.confirm(db, booking, user_id)
    if action == "cancel":
        return logic.cancel(db, booking, user_id, can_cancel_any=False)
    return logic.check_in(db, booking, user_id)
