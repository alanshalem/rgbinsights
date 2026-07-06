"""Enrich use case: follow relationship + richer profile for a fiesta's users."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlmodel import Session

from app.application.dto import EnrichResult
from app.application.use_cases._shared import (
    KEY_RELATIONS_SYNCED,
    ProgressFn,
    _now,
    map_instagram_error,
)
from app.domain.result import Ok, Result
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import InstagramError
from app.infrastructure.persistence.repositories import AppStateRepository, UserRepository

logger = logging.getLogger(__name__)


class EnrichProfilesUseCase:
    """The slow, opt-in "extra data" step, for a fiesta's users:

    1. Follow relationship (te sigue / mutuo) — read from our followers/following
       lists (the only accurate way; show_many omits "followed_by").
    2. Richer profile per user (follower count, verified, bio) — one call each,
       so only users not yet enriched are fetched.
    """

    def __init__(self, source: InstagramSource, session: Session) -> None:
        self._source = source
        self._session = session
        self._users = UserRepository(session)

    def execute(
        self,
        pks: list[str],
        limit: int = 1000,
        progress: ProgressFn | None = None,
        force: bool = False,
        cache_hours: float = 12.0,
    ) -> Result[EnrichResult]:
        self._source.reset_budget()
        now = _now()
        state = AppStateRepository(self._session)

        relations = 0
        last = state.get_dt(KEY_RELATIONS_SYNCED)
        fresh = last is not None and (now - last) < timedelta(hours=cache_hours)
        relations_cached = bool(fresh) and not force
        if relations_cached:
            # Followers/following read < cache_hours ago — reuse stored flags
            # (hundreds of paginated, ban-prone requests skipped).
            logger.info("relationships fresh (%s) — skipping fetch", last)
        else:
            try:
                if progress is not None:
                    progress(0, 0, "trayendo relaciones (te sigue)…")
                rels = self._source.get_friendships(pks)
                self._users.set_friendships(rels)
                relations = len(rels)
                state.set_dt(KEY_RELATIONS_SYNCED, now)
            except InstagramError as exc:
                logger.warning("relationship fetch skipped: %s", exc)

        pending = self._users.unenriched(pks)[:limit]
        total = len(pending)
        enriched = 0
        for user in pending:
            if progress is not None:
                progress(enriched, total, f"@{user.username}")
            try:
                profile = self._source.get_profile(user.username)
            except InstagramError as exc:
                logger.warning("enrich failed for @%s: %s", user.username, exc)
                return map_instagram_error(exc)
            self._users.set_profile(user.pk, profile, now)
            enriched += 1

        self._session.commit()
        return Ok(
            EnrichResult(enriched=enriched, relations=relations, relations_cached=relations_cached)
        )
