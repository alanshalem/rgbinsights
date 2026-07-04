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
    _migrate()


# New nullable columns added to already-existing tables. create_all() creates
# brand-new tables (e.g. events) but never ALTERs existing ones, so add these by
# hand to preserve data already scanned/synced. Keyed by table -> {column: ddl}.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "posts": {"event_id": "INTEGER"},
    "dm_threads": {
        "last_outgoing_at": "DATETIME",
        "last_incoming_at": "DATETIME",
    },
    "users": {
        "follows_us": "BOOLEAN",
        "we_follow": "BOOLEAN",
        "follower_count": "INTEGER",
        "is_verified": "BOOLEAN DEFAULT 0",
        "is_business": "BOOLEAN DEFAULT 0",
        "biography": "TEXT",
        "profile_synced_at": "DATETIME",
    },
}


def _migrate() -> None:
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for column, ddl in columns.items():
                if column not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
