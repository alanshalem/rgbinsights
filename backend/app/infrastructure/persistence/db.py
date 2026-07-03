"""DB engine, table creation, and session factory."""

from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.infrastructure.config.settings import get_settings

# Import models so SQLModel.metadata is populated before create_all.
from app.infrastructure.persistence import models  # noqa: F401

_settings = get_settings()

# check_same_thread=False: FastAPI may touch the session across threads.
engine = create_engine(
    _settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
