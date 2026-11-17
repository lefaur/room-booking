"""Воркер notifier: события из RabbitMQ → письма по SMTP (в стенде это Mailpit)."""
import logging
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage

from sqlalchemy import DateTime, MetaData, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from common.messaging import consume_forever, make_processed_model, utcnow
from notifier.templates import ROUTING_KEYS, recipient, render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("notifier")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://officespace:officespace@localhost:5433/officespace")
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
MAIL_FROM = os.getenv("MAIL_FROM", "OfficeSpace <no-reply@officespace.test>")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    metadata = MetaData(schema="notifier")


ProcessedEvent = make_processed_model(Base)


class SentEmail(Base):
    __tablename__ = "sent_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    recipient: Mapped[str] = mapped_column(String(120), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def send_mail(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = MAIL_FROM, to, subject
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(message)


def handle(event: dict) -> None:
    with SessionLocal() as db:
        if db.get(ProcessedEvent, event["event_id"]):
            log.info("событие %s уже обработано, пропускаю", event["event_id"])
            return
        to = recipient(event)
        subject, body = render(event)
        # письмо уходит до коммита: упадём между отправкой и коммитом — при повторе письмо придёт дважды.
        # Это осознанный выбор «лучше дубль, чем потеря» для at-least-once доставки.
        send_mail(to, subject, body)
        db.add(ProcessedEvent(event_id=event["event_id"], event_type=event["type"]))
        db.add(SentEmail(event_id=event["event_id"], event_type=event["type"], recipient=to,
                         subject=subject, body=body))
        db.commit()
        log.info("письмо «%s» → %s", subject, to)


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS notifier"))
    Base.metadata.create_all(engine)
    consume_forever("notifier", ROUTING_KEYS, handle)


if __name__ == "__main__":
    main()
