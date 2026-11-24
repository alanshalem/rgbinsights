"""Enrich use case: follow relationship + richer profile for a fiesta's users."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, tzinfo

from sqlmodel import Session

from app.application.dto import EnrichResult
from app.application.use_cases._shared import (
    KEY_FOLLOW_GRAPH_FULL,
    KEY_RELATIONS_SYNCED,
    ProgressFn,
    _now,
    map_instagram_error,
)
from app.domain.entities import Friendship, ProfileInfo
from app.domain.result import Err, Ok, Result
from app.infrastructure.instagram.base import FollowGraph, InstagramSource
from app.infrastructure.instagram.errors import InstagramError
from app.infrastructure.persistence.repositories import (
    AppStateRepository,
    FollowGraphRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)

# Profiles saved (and committed) together: a failure loses at most this many
# reads, and no SQLite write transaction stays open across Instagram calls.
PROFILE_BATCH = 10


class EnrichProfilesUseCase:
    """The slow, opt-in "extra data" step, for a fiesta's users:

    1. Follow relationship (te sigue / mutuo) — read from our followers/following
       lists (the only accurate way; show_many omits "followed_by"); followers
       incrementally between periodic full reads, following always whole; saved
       as soon as it is read.
    2. Richer profile per user (follower count, verified, bio) — one call each,
       only for users not yet enriched, capped per run and per local day, saved
       in batches so a failed run keeps its progress and the next one continues.
    """

    def __init__(self, source: InstagramSource, session: Session) -> None:
        self._source = source
        self._session = session
        self._users = UserRepository(session)
        self._graph = FollowGraphRepository(session)
        self._state = AppStateRepository(session)

    def execute(
        self,
        pks: list[str],
        limit: int = 1000,
        progress: ProgressFn | None = None,
        force: bool = False,
        cache_hours: float = 12.0,
        *,
        daily_cap: int | None = None,
        tz: tzinfo = UTC,
        full_refresh_days: float = 7.0,
    ) -> Result[EnrichResult]:
        self._source.reset_budget()
        relations, relations_cached = self._sync_relations(
            pks, progress, force, cache_hours, full_refresh_days
        )

        pending = [(u.pk, u.username) for u in self._users.unenriched(pks)]
        allowed = limit
        if daily_cap is not None:
            local_midnight = (
                _now().astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            )
            allowed = min(
                allowed, max(0, daily_cap - self._users.profiles_synced_since(local_midnight))
            )
        todo = pending[: max(0, allowed)]
        total = len(todo)
        batch: list[tuple[str, ProfileInfo]] = []
        enriched = 0
        for pk, username in todo:
            if progress is not None:
                progress(enriched, total, f"@{username}")
            try:
                profile = self._source.get_profile(username)
            except InstagramError as exc:
                logger.warning("enrich failed for @%s: %s", username, exc)
                self._save_profiles(batch)
                err = map_instagram_error(exc)
                remaining = len(pending) - enriched
                return Err(
                    err.code,
                    f"{err.message} — Se guardaron {enriched} perfiles; faltan {remaining} "
                    "(la próxima corrida sigue desde ahí).",
                )
            batch.append((pk, profile))
            enriched += 1
            if len(batch) >= PROFILE_BATCH:
                self._save_profiles(batch)
                batch = []
        self._save_profiles(batch)
        return Ok(
            EnrichResult(enriched=enriched, relations=relations, relations_cached=relations_cached)
        )

    def _sync_relations(
        self,
        pks: list[str],
        progress: ProgressFn | None,
        force: bool,
        cache_hours: float,
        full_refresh_days: float,
    ) -> tuple[int, bool]:
        """Set "te sigue"/"lo seguís" for `pks`; returns (users set, cached)."""
        now = _now()
        last = self._state.get_dt(KEY_RELATIONS_SYNCED)
        if not force and last is not None and (now - last) < timedelta(hours=cache_hours):
            # Followers/following read < cache_hours ago — reuse stored flags.
            logger.info("relationships fresh (%s) — skipping fetch", last)
            return 0, True

        last_full = self._state.get_dt(KEY_FOLLOW_GRAPH_FULL)
        full = force or last_full is None or (now - last_full) >= timedelta(days=full_refresh_days)
        known = None if full else FollowGraph(*self._graph.load())
        try:
            if progress is not None:
                progress(0, 0, "trayendo relaciones (te sigue)…")
            read = self._source.get_follow_graph(known)
        except InstagramError as exc:
            logger.warning("relationship fetch skipped: %s", exc)
            return 0, False

        if known is None:
            self._graph.replace(read.followers, read.following)
            self._state.set_dt(KEY_FOLLOW_GRAPH_FULL, now)
            graph = read
        else:
            # New followers are added; following always comes back whole.
            self._graph.add_followers(read.followers)
            self._graph.replace_following(read.following)
            graph = FollowGraph(
                followers=known.followers | read.followers, following=read.following
            )
        rels = {
            pk: Friendship(following=pk in graph.following, followed_by=pk in graph.followers)
            for pk in set(pks)
        }
        self._users.set_friendships(rels)
        self._state.set_dt(KEY_RELATIONS_SYNCED, now)
        self._session.commit()  # keep the graph even if a profile read fails later
        return len(rels), False

    def _save_profiles(self, batch: list[tuple[str, ProfileInfo]]) -> None:
        """Write and commit fetched profiles — only between Instagram calls."""
        if not batch:
            return
        now: datetime = _now()
        for pk, profile in batch:
            self._users.set_profile(pk, profile, now)
        self._session.commit()
