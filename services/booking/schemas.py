from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Equipment = Literal["projector", "whiteboard", "tv", "videoconf"]


class FloorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    level: int = Field(ge=-5, le=200)
    width: int = Field(ge=10, le=100_000)
    height: int = Field(ge=10, le=100_000)


class FloorPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    level: int | None = Field(default=None, ge=-5, le=200)


class FloorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    level: int
    width: int
    height: int


class ResourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    floor_id: int
    kind: Literal["room", "desk"]
    name: str = Field(min_length=1, max_length=80)
    capacity: int = Field(ge=1, le=500)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)
    equipment: list[Equipment] = []

    @model_validator(mode="after")
    def desk_is_single_seat(self):
        if self.kind == "desk" and self.capacity != 1:
            raise ValueError("У рабочего места вместимость 1")
        return self


class ResourcePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    name: str | None = Field(default=None, min_length=1, max_length=80)
    capacity: int | None = Field(default=None, ge=1, le=500)
    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)
    w: int | None = Field(default=None, ge=1)
    h: int | None = Field(default=None, ge=1)
    equipment: list[Equipment] | None = None
    active: bool | None = None


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    floor_id: int
    kind: str
    name: str
    capacity: int
    x: int
    y: int
    w: int
    h: int
    equipment: list[str]
    active: bool
    version: int


class MapResource(ResourceOut):
    busy: bool


class FloorMap(BaseModel):
    floor: FloorOut
    at: datetime
    resources: list[MapResource]


class BookingIn(BaseModel):
    """Переговорка: start и end (с часовым поясом). Рабочее место: date_from и date_to включительно."""
    model_config = ConfigDict(extra="forbid")

    resource_id: int
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    date_from: date | None = None
    date_to: date | None = None


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_id: int
    user_id: int
    user_email: str
    start: datetime = Field(validation_alias="start_at")
    end: datetime = Field(validation_alias="end_at")
    status: str
    created_at: datetime
    updated_at: datetime
    cancelled_by: int | None
    checked_in_at: datetime | None


class CalendarDayOut(BaseModel):
    date: date
    working: bool
    kind: Literal["workday", "weekend", "holiday", "working_weekend", "short"]
    title: str


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_active_bookings_per_user: int | None = Field(default=None, ge=1, le=50)
    confirm_timeout_minutes: int | None = Field(default=None, ge=1, le=1440)
    max_booking_hours: int | None = Field(default=None, ge=1, le=24)
    max_desk_days: int | None = Field(default=None, ge=1, le=60)
    booking_horizon_days: int | None = Field(default=None, ge=1, le=365)
    reminder_minutes_before: int | None = Field(default=None, ge=5, le=1440)
    checkin_open_minutes_before: int | None = Field(default=None, ge=0, le=120)
    no_show_grace_minutes: int | None = Field(default=None, ge=5, le=240)
