from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import Settings


def create_db_engine(settings: Settings):
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set.")
    return create_engine(settings.database_url, pool_pre_ping=True)


def create_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db_session(session_factory):
    return session_factory()


def check_db_connection(engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
