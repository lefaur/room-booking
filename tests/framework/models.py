"""Контракты ответов. extra="forbid": новое или пропавшее поле в ответе сразу роняет проверку."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TokenPair(Contract):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"]
    expires_in: int


class User(Contract):
    id: int
    email: str
    full_name: str
    role: Literal["employee", "manager", "facility", "admin"]
    is_active: bool
    created_at: datetime


class Floor(Contract):
    id: int
    name: str
    level: int
    width: int
    height: int


class Resource(Contract):
    id: int
    floor_id: int
    kind: Literal["room", "desk"]
    name: str
    capacity: int
    x: int
    y: int
    w: int
    h: int
    equipment: list[str]
    active: bool
    version: int


class MapResource(Resource):
    busy: bool


class FloorMap(Contract):
    floor: Floor
    at: datetime
    resources: list[MapResource]


class Booking(Contract):
    id: int
    resource_id: int
    user_id: int
    user_email: str
    start: datetime
    end: datetime
    status: Literal["pending", "confirmed", "checked_in", "cancelled", "expired", "no_show"]
    created_at: datetime
    updated_at: datetime
    cancelled_by: int | None
    checked_in_at: datetime | None


class CalendarDay(Contract):
    date: date
    working: bool
    kind: Literal["workday", "weekend", "holiday", "working_weekend", "short"]
    title: str


class JobRun(Contract):
    job: str
    status: Literal["ok", "failed"]
    trigger: Literal["manual", "schedule"]
    started_at: datetime
    finished_at: datetime
    result: dict


class LinkCode(Contract):
    code: str
    expires_at: datetime
    command: str
