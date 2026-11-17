"""Конфиг окружения: tests/config/<TEST_ENV>.yaml, отдельные поля можно переопределить переменными окружения."""
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str


@dataclass(frozen=True)
class RabbitConfig:
    url: str
    user: str
    password: str


@dataclass(frozen=True)
class UiConfig:
    headless: bool
    timeout_ms: int
    # браузер нарочно в другом часовом поясе: UI обязан считать брони по времени офиса, а не по часам ноутбука
    timezone: str
    artifacts_dir: str  # скриншот, трасса и журнал упавших UI-сценариев, папка на сценарий


@dataclass(frozen=True)
class Config:
    env: str
    base_url: str
    db: DbConfig
    admin: Credentials
    jwt_secret: str
    office_tz: ZoneInfo
    http_timeout: float
    mailpit_url: str
    stubs_url: str
    rabbitmq: RabbitConfig
    ui: "UiConfig"


def load_config(env: str | None = None) -> Config:
    env = env or os.getenv("TEST_ENV", "docker")
    raw = yaml.safe_load((CONFIG_DIR / f"{env}.yaml").read_text(encoding="utf-8"))
    return Config(
        env=env,
        base_url=os.getenv("BASE_URL", raw["base_url"]).rstrip("/"),
        db=DbConfig(**{**raw["db"], "host": os.getenv("DB_HOST", raw["db"]["host"])}),
        admin=Credentials(**raw["admin"]),
        jwt_secret=os.getenv("JWT_SECRET", raw["jwt_secret"]),
        office_tz=ZoneInfo(raw["office_tz"]),
        http_timeout=float(raw["http_timeout"]),
        mailpit_url=os.getenv("MAILPIT_URL", raw["mailpit_url"]).rstrip("/"),
        stubs_url=os.getenv("STUBS_URL", raw["stubs_url"]).rstrip("/"),
        rabbitmq=RabbitConfig(**raw["rabbitmq"]),
        ui=UiConfig(
            headless=os.getenv("HEADED", "") == "",
            timeout_ms=int(raw["ui"]["timeout_ms"]),
            timezone=raw["ui"]["timezone"],
            artifacts_dir=os.getenv("UI_ARTIFACTS_DIR", raw["ui"]["artifacts_dir"]),
        ),
    )
