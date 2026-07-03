from __future__ import annotations

from collections.abc import Iterator

import pytest

# Ensure models are registered on SQLModel.metadata.
from app.infrastructure.persistence import models  # noqa: F401
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture
def session() -> Iterator[Session]:
    # In-memory DB shared across the connection for the test's lifetime.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
