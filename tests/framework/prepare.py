"""Подготовка предусловий прямо в БД.

Предусловие («Дано пользователь вошёл», «Дано есть переговорка…», этаж для UI) через API стоит HTTP-запроса
и всей бизнес-логики сервиса: регистрация считает хеш пароля, пишет событие в outbox и шлёт приветственное
письмо, а назначение роли — ещё один запрос. Сценарий же проверяет совсем другое. Поэтому строки
предусловий копятся и пишутся пачкой INSERT … RETURNING в одной транзакции.

То, что сценарий проверяет, по-прежнему идёт через API. Предусловие, у которого важны побочные эффекты
(письмо после регистрации), явно создаётся через API отдельным шагом.

PREPARE_VIA=api возвращает старый путь целиком: для сравнения скорости и на случай, если схема БД
разъехалась с кодом подготовки.
"""
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone

from psycopg2.extras import Json, execute_values

from framework.db import Database

log = logging.getLogger("prepare")

VIA_SQL = os.getenv("PREPARE_VIA", "sql").lower() != "api"


class Preparation:
    """Строки копятся через add() и пишутся в flush() одной транзакцией, таблица за таблицей.

    add() сразу возвращает словарь строки, после flush() в нём появляются id и значения по умолчанию.
    Значение-функция вычисляется в момент записи: так ресурс ссылается на этаж, добавленный в ту же пачку.
    """

    def __init__(self, db: Database, on_created: Callable[[str, dict], None] | None = None):
        self._db = db
        self._on_created = on_created
        self._pending: dict[str, list[dict]] = {}  # порядок таблиц = порядок первого add()

    def add(self, table: str, **values) -> dict:
        row = dict(values)
        self._pending.setdefault(table, []).append(row)
        return row

    def flush(self) -> None:
        if not self._pending:
            return
        started = time.perf_counter()
        counts = []
        with self._db.transaction() as cur:
            for table, rows in self._pending.items():
                resolved = [{k: _resolve(v) for k, v in row.items()} for row in rows]
                columns = list(resolved[0])
                inserted = execute_values(
                    cur, f"INSERT INTO {table} ({', '.join(columns)}) VALUES %s RETURNING *",
                    [tuple(r[c] for c in columns) for r in resolved], fetch=True)
                for row, returned in zip(rows, inserted):  # RETURNING сохраняет порядок VALUES
                    row.clear()
                    row.update(returned)
                counts.append(f"{table} ×{len(rows)}")
        created = list(self._pending.items())
        self._pending.clear()
        log.info("SQL-подготовка одной транзакцией: %s, %.0f мс", ", ".join(counts),
                 (time.perf_counter() - started) * 1000)
        if self._on_created:
            for table, rows in created:
                for row in rows:
                    self._on_created(table, row)

    def __enter__(self) -> "Preparation":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:  # сценарий уже упал на подготовке — дописывать половину незачем
            self.flush()


def _resolve(value):
    value = value() if callable(value) else value
    return Json(value) if isinstance(value, (list, dict)) else value


def now() -> datetime:
    return datetime.now(timezone.utc)


def user_row(prep: Preparation, *, email: str, full_name: str, role: str, password_hash: str) -> dict:
    return prep.add("auth.users", email=email, full_name=full_name, password_hash=password_hash,
                    role=role, is_active=True, created_at=now())


def floor_row(prep: Preparation, *, name: str, level: int, width: int, height: int) -> dict:
    return prep.add("booking.floors", name=name, level=level, width=width, height=height, created_at=now())


def resource_row(prep: Preparation, *, floor_id, kind: str, name: str, capacity: int,
                 x: int, y: int, w: int, h: int, equipment: list | None = None) -> dict:
    return prep.add("booking.resources", floor_id=floor_id, kind=kind, name=name, capacity=capacity,
                    x=x, y=y, w=w, h=h, equipment=equipment or [], active=True, version=1)
