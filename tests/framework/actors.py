"""Действующие лица сценариев. Ярлык в .feature («сотрудник 2», «АХО») → свой пользователь с нужной ролью."""
import time
from dataclasses import dataclass

from framework import data
from framework.api import AuthApi
from framework.config import Credentials
from framework.db import Database
from framework.prepare import Preparation, user_row

ROLE_BY_WORD = {
    "сотрудник": "employee",
    "руководитель": "manager",
    "АХО": "facility",
    "админ": "admin",
    # в примерах таблиц удобно писать роль как в API
    "employee": "employee", "manager": "manager", "facility": "facility", "admin": "admin",
}


def role_of(label: str) -> str:
    word = label.split()[0]
    if word not in ROLE_BY_WORD:
        raise ValueError(f"По ярлыку {label!r} не понять роль; первое слово должно быть из {list(ROLE_BY_WORD)}")
    return ROLE_BY_WORD[word]


@dataclass
class Actor:
    label: str
    id: int
    email: str
    password: str
    role: str
    access_token: str | None = None
    refresh_token: str | None = None
    first_refresh_token: str | None = None


class AdminSession:
    """Встроенный администратор: готовит данные. Токен перевыпускается заранее, до истечения."""

    def __init__(self, auth: AuthApi, creds: Credentials, ttl_margin: int = 120):
        self._auth, self._creds, self._margin = auth, creds, ttl_margin
        self._token, self._expires_at = None, 0.0

    @property
    def token(self) -> str:
        if self._token is None or time.time() > self._expires_at:
            resp = self._auth.login(self._creds.email, self._creds.password)
            assert resp.status_code == 200, f"Админ не вошёл: {resp.status_code} {resp.text}"
            body = resp.json()
            self._token = body["access_token"]
            self._expires_at = time.time() + body["expires_in"] - self._margin
        return self._token


class ActorFactory:
    def __init__(self, auth: AuthApi, admin: AdminSession, db: Database):
        self._auth, self._admin, self._db = auth, admin, db
        self._password_hash: str | None = None

    def register(self, label: str, prep: Preparation | None = None) -> Actor:
        """С prep — строкой в БД (сразу с нужной ролью), без — через API, как настоящий пользователь."""
        if prep is None:
            return self.register_via_api(label)
        role = role_of(label)
        row = user_row(prep, email=data.unique_email(role), full_name=f"Тест {label}", role=role,
                       password_hash=self._hash())
        prep.flush()
        return Actor(label=label, id=row["id"], email=row["email"], password=data.PASSWORD, role=role)

    def _hash(self) -> str:
        """Хеш общего тестового пароля берётся у пользователя, зарегистрированного через API, один раз
        на процесс: формат хеша и число итераций остаются заботой сервиса, тесты их не повторяют."""
        if self._password_hash is None:
            template = self.register_via_api("сотрудник")
            row = self._db.one("SELECT password_hash FROM auth.users WHERE id = %s", (template.id,))
            self._password_hash = row["password_hash"]
        return self._password_hash

    def register_via_api(self, label: str) -> Actor:
        role = role_of(label)
        email = data.unique_email(role)
        resp = self._auth.register(email, data.PASSWORD, f"Тест {label}")
        assert resp.status_code == 201, f"Регистрация {label}: {resp.status_code} {resp.text}"
        user = resp.json()
        if role != "employee":
            resp = self._auth.patch_user(self._admin.token, user["id"], role=role)
            assert resp.status_code == 200, f"Назначение роли {role}: {resp.status_code} {resp.text}"
        return Actor(label=label, id=user["id"], email=email, password=data.PASSWORD, role=role)

    def login(self, actor: Actor) -> Actor:
        resp = self._auth.login(actor.email, actor.password)
        assert resp.status_code == 200, f"Вход {actor.label}: {resp.status_code} {resp.text}"
        tokens = resp.json()
        actor.access_token, actor.refresh_token = tokens["access_token"], tokens["refresh_token"]
        actor.first_refresh_token = actor.first_refresh_token or actor.refresh_token
        return actor
