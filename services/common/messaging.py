"""RabbitMQ: топология, transactional outbox и потребитель с повторами и очередью недоставленных (DLQ).

Публикация: сервис пишет событие в свою таблицу outbox в той же транзакции, что и данные.
Отдельный поток (relay) отправляет неотправленные строки в брокер с подтверждением доставки.
Брокер лежит — данные всё равно сохраняются, события уйдут, когда он поднимется.
Доставка «как минимум один раз», поэтому потребители обязаны быть идемпотентными (processed_events).
"""
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pika
from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column

log = logging.getLogger("messaging")

AMQP_URL = os.getenv("AMQP_URL", "amqp://officespace:officespace@localhost:5672/")
EXCHANGE = "officespace.events"
DEAD_LETTER_EXCHANGE = "officespace.dlx"
MAX_RETRIES = int(os.getenv("CONSUMER_MAX_RETRIES", "3"))
HEARTBEAT_FILE = Path("/tmp/heartbeat")  # healthcheck воркера: файл обновляется каждую секунду


class PermanentError(Exception):
    """Сообщение не обработать никогда (битые данные): сразу в очередь недоставленных."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def connect() -> tuple[pika.BlockingConnection, pika.adapters.blocking_connection.BlockingChannel]:
    params = pika.URLParameters(AMQP_URL)
    params.heartbeat = 30
    params.blocked_connection_timeout = 30
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.exchange_declare(EXCHANGE, "topic", durable=True)
    channel.exchange_declare(DEAD_LETTER_EXCHANGE, "direct", durable=True)
    return connection, channel


def declare_queue(channel, queue: str, routing_keys: list[str]) -> None:
    """Очередь потребителя и её DLQ: отклонённые сообщения уходят в <queue>.dlq."""
    channel.queue_declare(f"{queue}.dlq", durable=True)
    channel.queue_bind(f"{queue}.dlq", DEAD_LETTER_EXCHANGE, routing_key=queue)
    channel.queue_declare(queue, durable=True, arguments={
        "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE, "x-dead-letter-routing-key": queue})
    for key in routing_keys:
        channel.queue_bind(queue, EXCHANGE, routing_key=key)


def _close(connection) -> None:
    try:
        if connection and connection.is_open:
            connection.close()
    except Exception:  # noqa: BLE001 — закрываем то, что уже сломалось
        pass


# --- outbox ---

def make_outbox_model(base):
    class OutboxEvent(base):
        __tablename__ = "outbox"

        id: Mapped[int] = mapped_column(primary_key=True)
        event_id: Mapped[str] = mapped_column(String(36), unique=True)
        event_type: Mapped[str] = mapped_column(String(60))
        payload: Mapped[dict] = mapped_column(JSON)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
        sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    return OutboxEvent


def make_processed_model(base):
    """Обработанные события: повторная доставка того же event_id ничего не делает."""
    class ProcessedEvent(base):
        __tablename__ = "processed_events"

        event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
        event_type: Mapped[str] = mapped_column(String(60))
        processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    return ProcessedEvent


class Outbox:
    def __init__(self, base, session_factory, source: str):
        self.model = make_outbox_model(base)
        self._session_factory = session_factory
        self._source = source

    def add(self, db, event_type: str, payload: dict) -> str:
        """Добавляет событие в текущую транзакцию. Коммитит вызывающий."""
        event_id = str(uuid.uuid4())
        db.add(self.model(event_id=event_id, event_type=event_type, payload=payload, created_at=utcnow()))
        return event_id

    def start_relay(self) -> None:
        threading.Thread(target=self._relay_forever, name="outbox-relay", daemon=True).start()

    def _relay_forever(self) -> None:
        while True:
            connection = None
            try:
                connection, channel = connect()
                channel.confirm_delivery()
                while True:
                    if not self._publish_batch(channel):
                        connection.process_data_events(time_limit=0.2)
            except Exception:  # noqa: BLE001 — переподключаемся при любой ошибке
                log.exception("outbox relay: ошибка, переподключение через 1 с")
                _close(connection)
                time.sleep(1)

    def _publish_batch(self, channel) -> int:
        model = self.model
        with self._session_factory() as db:
            rows = db.scalars(select(model).where(model.sent_at.is_(None)).order_by(model.id)
                              .limit(100).with_for_update(skip_locked=True)).all()
            for row in rows:
                envelope = {"event_id": row.event_id, "type": row.event_type, "source": self._source,
                            "occurred_at": row.created_at.isoformat(), "payload": row.payload}
                channel.basic_publish(
                    EXCHANGE, row.event_type, json.dumps(envelope, ensure_ascii=False).encode(),
                    pika.BasicProperties(content_type="application/json", delivery_mode=2,
                                         message_id=row.event_id, type=row.event_type))
                row.sent_at = utcnow()
            db.commit()
            return len(rows)


# --- потребитель ---

def consume_forever(queue: str, routing_keys: list[str], handler) -> None:
    """handler(event). Битый конверт или PermanentError → сразу DLQ.
    Любая другая ошибка (SMTP, сеть) → повтор с паузой, после MAX_RETRIES попыток → DLQ."""
    while True:
        connection = None
        try:
            connection, channel = connect()
            declare_queue(channel, queue, routing_keys)
            channel.basic_qos(prefetch_count=1)
            for method, props, body in channel.consume(queue, inactivity_timeout=1):
                HEARTBEAT_FILE.touch()
                if method is not None:
                    _handle_one(channel, queue, method, props, body, handler)
        except Exception:  # noqa: BLE001
            log.exception("consumer %s: ошибка, переподключение через 1 с", queue)
            _close(connection)
            time.sleep(1)


def _handle_one(channel, queue, method, props, body, handler) -> None:
    try:
        event = json.loads(body)
        if not isinstance(event, dict) or not {"event_id", "type", "payload"} <= event.keys():
            raise PermanentError("В конверте нет event_id, type или payload")
        handler(event)
    except (PermanentError, ValueError, KeyError, TypeError) as error:
        log.warning("%s: сообщение %s → DLQ: %r", queue, props.message_id, error)
        channel.basic_nack(method.delivery_tag, requeue=False)
        return
    except Exception as error:  # noqa: BLE001 — временная ошибка, пробуем ещё
        retries = int((props.headers or {}).get("x-retries", 0))
        if retries >= MAX_RETRIES:
            log.error("%s: сообщение %s → DLQ после %s повторов: %r", queue, props.message_id, retries, error)
            channel.basic_nack(method.delivery_tag, requeue=False)
            return
        log.warning("%s: повтор %s сообщения %s: %r", queue, retries + 1, props.message_id, error)
        time.sleep(0.5 * (retries + 1))
        channel.basic_publish("", queue, body, pika.BasicProperties(
            content_type="application/json", delivery_mode=2, message_id=props.message_id, type=props.type,
            headers={**(props.headers or {}), "x-retries": retries + 1}))
    channel.basic_ack(method.delivery_tag)
