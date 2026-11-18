"""Коннектор к PostgreSQL: проверки состояния и подготовка данных, которую нельзя сделать через API
(например, «состарить» бронь, чтобы проверить джобу просрочки). Запросы пишутся в лог сценария."""
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from framework.config import DbConfig

log = logging.getLogger("db")


class Database:
    def __init__(self, cfg: DbConfig):
        self._cfg = cfg
        self._conn = None

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(host=self._cfg.host, port=self._cfg.port, dbname=self._cfg.dbname,
                                          user=self._cfg.user, password=self._cfg.password)
            self._conn.autocommit = True
        return self._conn

    def all(self, sql: str, params: dict | tuple | None = None) -> list[dict]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            log.info("SQL: %s\n-> %s", cur.query.decode(), rows)
        return rows

    def one(self, sql: str, params: dict | tuple | None = None) -> dict | None:
        rows = self.all(sql, params)
        assert len(rows) <= 1, f"Ожидалась одна строка, пришло {len(rows)}"
        return rows[0] if rows else None

    def execute(self, sql: str, params: dict | tuple | None = None) -> int:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            log.info("SQL: %s\n-> %s rows", cur.query.decode(), cur.rowcount)
            return cur.rowcount

    @contextmanager
    def transaction(self):
        """Курсор в одной транзакции: либо записалось всё, либо ничего."""
        conn = self.conn
        conn.autocommit = False
        try:
            with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                yield cur
        finally:
            conn.autocommit = True

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
