"""DM sync use case: pull direct threads and derive outgoing/incoming state."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session

from app.application.dto import SyncResult
from app.application.use_cases._shared import (
    KEY_DMS_SYNCED,
    ProgressFn,
    _now,
    map_instagram_error,
)
from app.domain.entities import DmThread
from app.domain.result import Ok, Result
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import InstagramError
from app.infrastructure.persistence.repositories import (
    AppStateRepository,
    DmThreadRepository,
    ThreadIn,
    UserRepository,
)

logger = logging.getLogger(__name__)

# Said (log + task progress + the refresh summary) when DM_THREADS_LIMIT cut an
# incremental sync short: the watermark still moves to this sync's start.
CAPPED_NOTE = (
    "se llegó al tope de chats por sync (DM_THREADS_LIMIT): los chats más viejos "
    "con mensajes nuevos no se sincronizaron"
)


@dataclass(frozen=True, slots=True)
class DmSyncResult(SyncResult):
    """SyncResult plus whether the thread cap cut an incremental sync short."""

    capped: bool = False


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
    ) -> Result[DmSyncResult]:
        self._source.reset_budget()
        state = AppStateRepository(self._session)
        since = None if (force or not incremental) else state.get_dt(KEY_DMS_SYNCED)
        # The next sync pages back to when THIS one started: a thread that gets a
        # message while we page is re-read next time instead of being missed.
        started = _now()
        try:
            our_pk = self._source.current_user_pk()
            inbox = self._source.get_dm_threads(progress, since)
        except InstagramError as exc:
            logger.warning("dm sync failed: %s", exc)
            return map_instagram_error(exc)

        threads = inbox.threads
        self._users.upsert_many((t.user for t in threads), started)
        self._threads.upsert_many((_thread_in(t, our_pk) for t in threads), synced_at=started)

        state.set_dt(KEY_DMS_SYNCED, started)
        self._session.commit()
        logger.info("synced %d DM threads (incremental=%s)", len(threads), since is not None)
        capped = since is not None and not inbox.complete
        if capped:
            logger.warning("dm sync: %s", CAPPED_NOTE)
            if progress is not None:
                progress(len(threads), len(threads), CAPPED_NOTE)
        return Ok(
            DmSyncResult(
                threads_synced=len(threads),
                users_touched=len(threads),
                incremental=since is not None,
                capped=capped,
            )
        )


def _thread_in(thread: DmThread, our_pk: str) -> ThreadIn:
    """Derive the per-direction flags/timestamps the semáforo needs."""
    out_times = [
        m.created_at for m in thread.messages if m.user_pk == our_pk and m.created_at is not None
    ]
    in_times = [
        m.created_at for m in thread.messages if m.user_pk != our_pk and m.created_at is not None
    ]
    return ThreadIn(
        thread_id=thread.thread_id,
        user_pk=thread.user.pk,
        has_outgoing=any(m.user_pk == our_pk for m in thread.messages),
        has_incoming=any(m.user_pk != our_pk for m in thread.messages),
        last_outgoing_at=max(out_times) if out_times else None,
        last_incoming_at=max(in_times) if in_times else None,
        last_message_at=thread.last_message_at,
    )
