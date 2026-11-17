import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://officespace:officespace@localhost:5433/officespace")
ROOT_PATH = os.getenv("ROOT_PATH", "")

ACCESS_TTL_SECONDS = int(os.getenv("ACCESS_TTL_SECONDS", "900"))
REFRESH_TTL_SECONDS = int(os.getenv("REFRESH_TTL_SECONDS", str(7 * 24 * 3600)))

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@officespace.test")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin12345")

# вход блокируется, если с последнего успешного входа (но не дольше окна) накопилось столько неудач
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))

PASSWORD_RESET_TTL_SECONDS = int(os.getenv("PASSWORD_RESET_TTL_SECONDS", "1800"))
