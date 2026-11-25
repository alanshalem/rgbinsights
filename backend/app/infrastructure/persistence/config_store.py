"""SqlConfigStore: the ConfigStore port over the `app_config` table (S25)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping

from sqlmodel import Session, col, delete, select

from app.infrastructure.persistence import models

logger = logging.getLogger(__name__)


class SqlConfigStore:
    """Each call opens (and closes) its own session and transaction."""

    def __init__(self, new_session: Callable[[], Session]) -> None:
        self._new_session = new_session

    def load(self) -> dict[str, object]:
        with self._new_session() as session:
            rows = session.exec(select(models.ConfigOverride)).all()
        out: dict[str, object] = {}
        for row in rows:
            try:
                out[row.key] = json.loads(row.value)
            except ValueError:
                # Unreadable: that setting just uses its default.
                logger.warning("ignoring unreadable app_config value for %s", row.key)
        return out

    def save(self, values: Mapping[str, object]) -> None:
        with self._new_session() as session:
            for key, value in values.items():
                row = session.get(models.ConfigOverride, key)
                if row is None:
                    row = models.ConfigOverride(key=key, value=json.dumps(value))
                else:
                    row.value = json.dumps(value)
                session.add(row)
            session.commit()

    def delete(self, keys: Iterable[str] | None = None) -> None:
        with self._new_session() as session:
            stmt = delete(models.ConfigOverride)
            if keys is not None:
                stmt = stmt.where(col(models.ConfigOverride.key).in_(list(keys)))
            session.exec(stmt)
            session.commit()
