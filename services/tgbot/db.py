import os
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, MetaData, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from common.messaging import Outbox, make_processed_model, utcnow

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://officespace:officespace@localhost:5433/officespace")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    metadata = MetaData(schema="tgbot")


class Link(Base):
    """Привязка аккаунта к чату: один пользователь — один чат, один чат — один пользователь."""
    __tablename__ = "links"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_email: Mapped[str] = mapped_column(String(120))
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LinkCode(Base):
    """Одноразовый код: пользователь получает его в приложении и отправляет боту /start <код>."""
    __tablename__ = "link_codes"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    user_email: Mapped[str] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


ProcessedEvent = make_processed_model(Base)
outbox = Outbox(Base, SessionLocal, source="tgbot")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
