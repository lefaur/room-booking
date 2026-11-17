from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from booking import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    metadata = MetaData(schema="booking")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
