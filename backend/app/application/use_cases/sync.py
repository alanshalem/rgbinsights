"""DM sync use case: pull direct threads and derive outgoing/incoming state."""

from __future__ import annotations

import logging

from sqlmodel import Session

from app.application.dto import SyncResult
from app.application.use_cases._shared import (
    KEY_DMS_SYNCED,
    ProgressFn,
    _now,
    map_instagram_error,
)
from app.domain.result import Ok, Result
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import InstagramError
from app.infrastructure.persistence.repositories import (
    AppStateRepository,
    DmThreadRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)


class SyncDmsUseCase:
    def __init__(self, source: InstagramSource, session: Session) -> None:
        self._source = source
        self._session = session
        self._users = UserRepository(session)
        self._threads = DmThreadRepository(session)

    def execute(
        self,
        progress: ProgressFn | None = None,
        force: bool = False,
        incremental: bool = True,
    ) -> Result[SyncResult]:
        self._source.reset_budget()
        state = AppStateRepository(self._session)
        since = None if (force or not incremental) else state.get_dt(KEY_DMS_SYNCED)
        try:
            our_pk = self._source.current_user_pk()
            threads = self._source.get_dm_threads(progress, since)
        except InstagramError as exc:
            logger.warning("dm sync failed: %s", exc)
            return map_instagram_error(exc)

        now = _now()
        for thread in threads:
            out_times = [
                m.created_at
                for m in thread.messages
                if m.user_pk == our_pk and m.created_at is not None
            ]
            in_times = [
                m.created_at
                for m in thread.messages
                if m.user_pk != our_pk and m.created_at is not None
            ]
            self._users.upsert(thread.user, now)
            self._threads.upsert(
                thread_id=thread.thread_id,
                user_pk=thread.user.pk,
                has_outgoing=any(m.user_pk == our_pk for m in thread.messages),
                has_incoming=any(m.user_pk != our_pk for m in thread.messages),
                last_outgoing_at=max(out_times) if out_times else None,
                last_incoming_at=max(in_times) if in_times else None,
                last_message_at=thread.last_message_at,
                synced_at=now,
            )

        state.set_dt(KEY_DMS_SYNCED, now)
        self._session.commit()
        logger.info("synced %d DM threads (incremental=%s)", len(threads), since is not None)
        return Ok(
            SyncResult(
                threads_synced=len(threads),
                users_touched=len(threads),
                incremental=since is not None,
            )
        )
