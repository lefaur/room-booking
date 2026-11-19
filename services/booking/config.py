import os
from zoneinfo import ZoneInfo

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://officespace:officespace@localhost:5433/officespace")
ROOT_PATH = os.getenv("ROOT_PATH", "")

# демо-этаж при старте (booking/demo.py) — чтобы стенд, открытый руками, не был пустым
DEMO_DATA = os.getenv("DEMO_DATA", "").lower() in ("1", "true", "yes")

# часовой пояс офиса: в нём считаются «сегодня» и границы дней для рабочих мест
OFFICE_TZ = ZoneInfo(os.getenv("OFFICE_TZ", "Europe/Moscow"))

# внешний источник производственного календаря: GET {CALENDAR_URL}/{year}
CALENDAR_URL = os.getenv("CALENDAR_URL", "http://localhost:8090/calendar")
CALENDAR_TIMEOUT_SECONDS = float(os.getenv("CALENDAR_TIMEOUT_SECONDS", "3"))

# правила бронирования по умолчанию; меняются через PUT /settings
DEFAULT_SETTINGS = {
    "max_active_bookings_per_user": 3,
    "confirm_timeout_minutes": 15,
    "max_booking_hours": 4,
    "max_desk_days": 5,
    "booking_horizon_days": 30,
    "reminder_minutes_before": 30,
    "checkin_open_minutes_before": 10,
    "no_show_grace_minutes": 15,
}

# рабочее место считается брошенным, если до полудня первого дня никто не отметился
DESK_CHECKIN_DEADLINE_HOURS = 12
