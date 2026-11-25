"""DB engine and table creation (the composition root builds the one engine)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, event, make_url
from sqlalchemy.schema import CreateIndex
from sqlmodel import SQLModel, create_engine

# Import models so SQLModel.metadata is populated before create_all.
from app.infrastructure.persistence import models  # noqa: F401

# File-based SQLite only: WAL lets the board read while a scan/campaign writes,
# busy_timeout waits for a lock instead of failing with "database is locked",
# and synchronous=NORMAL is the safe, faster pairing for WAL.
_FILE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
)


def _is_file_sqlite(url: str) -> bool:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return False
    database = parsed.database or ""
    return database not in ("", ":memory:") and "mode=memory" not in str(parsed)


def _apply_file_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        for pragma in _FILE_PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def build_engine(url: str) -> Engine:
    # check_same_thread=False: FastAPI may touch the session across threads.
    engine = create_engine(url, echo=False, connect_args={"check_same_thread": False})
    if _is_file_sqlite(url):
        event.listen(engine, "connect", _apply_file_pragmas)
    return engine


def create_db_and_tables(bind: Engine) -> None:
    SQLModel.metadata.create_all(bind)
    _migrate(bind)


# New nullable columns added to already-existing tables. create_all() creates
# brand-new tables (e.g. events, follow_edges) but never ALTERs existing ones, so
# add these by hand to preserve data already scanned/synced. Keyed by table ->
# {column: ddl}.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "posts": {"event_id": "INTEGER", "last_comment_at": "DATETIME"},
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


def _migrate(bind: Engine) -> None:
    with bind.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for column, ddl in columns.items():
                if column not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        # create_all() skips existing tables, indexes included: add any declared
        # index an older DB lacks (after the ALTERs, since some index new
        # columns). Non-unique only, so existing data can never make this fail.
        for declared in SQLModel.metadata.sorted_tables:
            for index in declared.indexes:
                if not index.unique:
                    conn.execute(CreateIndex(index, if_not_exists=True))
