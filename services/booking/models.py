from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from booking.db import Base

# брони в этих статусах держат время ресурса
ACTIVE_STATUSES = ("pending", "confirmed", "checked_in")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Floor(Base):
    __tablename__ = "floors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    level: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)   # размеры плана в условных единицах
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Resource(Base):
    """Переговорка (room, бронь по времени) или рабочее место (desk, бронь на дни)."""
    __tablename__ = "resources"
    __table_args__ = (UniqueConstraint("floor_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    floor_id: Mapped[int] = mapped_column(ForeignKey("floors.id", ondelete="RESTRICT"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(80))
    capacity: Mapped[int] = mapped_column(Integer)
    x: Mapped[int] = mapped_column(Integer)
    y: Mapped[int] = mapped_column(Integer)
    w: Mapped[int] = mapped_column(Integer)
    h: Mapped[int] = mapped_column(Integer)
    equipment: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # оптимистическая блокировка: правка с устаревшей версией получает 409
    version: Mapped[int] = mapped_column(Integer, default=1)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (CheckConstraint("end_at > start_at", name="bookings_end_after_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="RESTRICT"), index=True)
    # пользователи живут в сервисе auth, поэтому без внешнего ключа: id и email берутся из токена
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    user_email: Mapped[str] = mapped_column(String(120))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # pending → confirmed → checked_in; pending → expired; confirmed → no_show; pending/confirmed → cancelled
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    cancelled_by: Mapped[int | None] = mapped_column(Integer)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[int] = mapped_column(Integer)


class CalendarDay(Base):
    """Исключения производственного календаря. Нет строки — будни рабочие, суббота и воскресенье нет."""
    __tablename__ = "calendar_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))   # holiday | working | short
    title: Mapped[str] = mapped_column(String(120), default="")


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="running")   # running | ok | failed
    details: Mapped[dict] = mapped_column(JSON, default=dict)
