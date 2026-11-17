"""Производственный календарь: синхронизация с внешним источником и проверка рабочих дней."""
from datetime import date, timedelta
from typing import Literal

import httpx
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from booking import config
from booking.models import CalendarDay, utcnow


class SourceDay(BaseModel):
    date: date
    type: Literal["holiday", "working", "short"]
    title: str = ""


class SourceYear(BaseModel):
    year: int
    days: list[SourceDay]


def fetch_year(year: int) -> SourceYear:
    response = httpx.get(f"{config.CALENDAR_URL}/{year}", timeout=config.CALENDAR_TIMEOUT_SECONDS)
    response.raise_for_status()
    data = SourceYear.model_validate(response.json())
    if data.year != year or any(d.date.year != year for d in data.days):
        raise ValueError(f"Источник вернул данные не за {year} год")
    return data


def sync(db: Session) -> dict:
    """Скачивает текущий и следующий год. Если хоть один год не скачался или битый,
    в БД ничего не меняется: лучше старый календарь, чем наполовину пустой."""
    this_year = utcnow().astimezone(config.OFFICE_TZ).year
    years = [fetch_year(y) for y in (this_year, this_year + 1)]
    for year in years:
        db.execute(delete(CalendarDay).where(CalendarDay.day >= date(year.year, 1, 1),
                                             CalendarDay.day <= date(year.year, 12, 31)))
        db.add_all(CalendarDay(day=d.date, kind=d.type, title=d.title) for d in year.days)
    return {"years": [y.year for y in years], "days": sum(len(y.days) for y in years)}


def overrides(db: Session, start: date, end: date) -> dict[date, CalendarDay]:
    rows = db.scalars(select(CalendarDay).where(CalendarDay.day >= start, CalendarDay.day <= end))
    return {row.day: row for row in rows}


def describe_day(day: date, override: CalendarDay | None) -> dict:
    weekend = day.weekday() >= 5
    if override is None:
        kind, working = ("weekend", False) if weekend else ("workday", True)
    elif override.kind == "holiday":
        kind, working = "holiday", False
    elif override.kind == "working":
        kind, working = "working_weekend", True
    else:
        kind, working = "short", True
    return {"date": day, "working": working, "kind": kind, "title": override.title if override else ""}


def days_between(db: Session, start: date, end: date) -> list[dict]:
    known = overrides(db, start, end)
    return [describe_day(start + timedelta(days=i), known.get(start + timedelta(days=i)))
            for i in range((end - start).days + 1)]


def first_non_working(db: Session, start: date, end: date) -> dict | None:
    return next((d for d in days_between(db, start, end) if not d["working"]), None)
