"""Генерация тестовых данных. Всё уникально, поэтому сценарии не мешают друг другу при параллельном запуске."""
import re
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

PASSWORD = "Passw0rd123"


def uid() -> str:
    return uuid.uuid4().hex[:10]


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}.{uid()}@officespace.test"


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uid()}"


_DAYS = {"сегодня": 0, "завтра": 1, "послезавтра": 2, "вчера": -1}


def parse_day(text: str, tz: ZoneInfo) -> date:
    """«сегодня», «завтра», «послезавтра», «вчера», «через N дн.» → дата в часовом поясе офиса."""
    today = datetime.now(tz).date()
    text = text.strip()
    if text in _DAYS:
        return today + timedelta(days=_DAYS[text])
    match = re.fullmatch(r"через (\d+) дн\.?", text)
    if match:
        return today + timedelta(days=int(match.group(1)))
    raise ValueError(f"Не понимаю день: {text!r}")


def office_datetime(day: str, hhmm: str, tz: ZoneInfo) -> datetime:
    hours, minutes = map(int, hhmm.split(":"))
    return datetime.combine(parse_day(day, tz), time(hours, minutes), tz)
