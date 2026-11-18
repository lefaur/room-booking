"""Уборка за сценарием: всё, что он создал, удаляется после него из БД одной транзакцией.

Шаги ничего не регистрируют руками: созданное узнаётся по успешным ответам API (из тестов и из браузера)
и по SQL-подготовке. Удаляется только своё, поэтому уборка безопасна в параллельном прогоне.
KEEP_DATA=1 оставляет данные на стенде — посмотреть руками, что сценарий после себя оставил.
"""
import logging
import os
import re
import time

from framework.db import Database

log = logging.getLogger("cleanup")

KEEP_DATA = os.getenv("KEEP_DATA", "").lower() in ("1", "true", "yes")

# Успешный ответ на создание → вид сущности. Путь без query-строки.
CREATED_BY = [
    ("POST", re.compile(r"/api/auth/register$"), "user"),
    ("POST", re.compile(r"/api/booking/floors$"), "floor"),
    ("POST", re.compile(r"/api/booking/resources$"), "resource"),
]
TABLE_KIND = {"auth.users": "user", "booking.floors": "floor", "booking.resources": "resource"}

# От зависимых строк к главным. Брони удаляются по пользователю и по ресурсу: на ресурс сценария
# может бронировать и встроенный админ, а пользователь сценария — на чужом этаже.
STATEMENTS = [
    """DELETE FROM booking.bookings WHERE user_id = ANY(%(user)s) OR resource_id = ANY(%(resource)s)
          OR resource_id IN (SELECT id FROM booking.resources WHERE floor_id = ANY(%(floor)s))""",
    "DELETE FROM booking.resources WHERE id = ANY(%(resource)s) OR floor_id = ANY(%(floor)s)",
    "DELETE FROM booking.floors WHERE id = ANY(%(floor)s)",
    "DELETE FROM tgbot.link_codes WHERE user_id = ANY(%(user)s)",
    "DELETE FROM tgbot.links WHERE user_id = ANY(%(user)s)",
    # refresh-токены и сбросы пароля уходят каскадом, в журнале входов user_id обнуляется
    "DELETE FROM auth.users WHERE id = ANY(%(user)s)",
]


class Cleanup:
    def __init__(self):
        self.ids: dict[str, set[int]] = {"user": set(), "floor": set(), "resource": set()}

    def track(self, method: str, url: str, status: int, body) -> None:
        """body — разобранный JSON ответа или функция, которая его вернёт (браузерный ответ читается лениво)."""
        if status != 201:
            return
        path = url.split("?", 1)[0]
        for m, pattern, kind in CREATED_BY:
            if method == m and pattern.search(path):
                payload = body() if callable(body) else body
                self.ids[kind].add(payload["id"])
                return

    def track_row(self, table: str, row: dict) -> None:
        kind = TABLE_KIND.get(table)
        if kind:
            self.ids[kind].add(row["id"])

    def forget(self, kind: str, entity_id: int) -> None:
        """Сущность живёт дольше сценария (общий этаж процесса) — её убирает after_all."""
        self.ids[kind].discard(entity_id)

    def run(self, db: Database) -> str:
        """Возвращает строку для журнала хуков."""
        if KEEP_DATA:
            return f"уборка пропущена (KEEP_DATA): {self._summary()}"
        if not any(self.ids.values()):
            return "уборка: сценарий ничего не создал"
        started = time.perf_counter()
        params = {kind: sorted(ids) for kind, ids in self.ids.items()}
        deleted = []
        with db.transaction() as cur:
            for sql in STATEMENTS:
                cur.execute(sql, params)
                deleted.append(cur.rowcount)
        note = (f"уборка: {self._summary()}; удалено строк {sum(deleted)} "
                f"за {(time.perf_counter() - started) * 1000:.0f} мс")
        log.info(note)
        for ids in self.ids.values():
            ids.clear()
        return note

    def _summary(self) -> str:
        return ", ".join(f"{kind} {sorted(ids)}" for kind, ids in self.ids.items() if ids)
