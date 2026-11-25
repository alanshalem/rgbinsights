"""Direct messages for the instagrapi adapter: reading the inbox and sending a DM.

Sending is the highest-risk Instagram action, so its failures are classified
precisely: a dead session/IP stops (pause), an Instagram push-back blocks, a
recipient who closed DMs is skipped, and only a network hiccup is retryable.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.domain.entities import DmInbox, DmThread
from app.domain.errors import (
    InstagramError,
    RecipientUnavailableError,
    SendBlockedError,
    SendRetryableError,
)
from app.infrastructure.instagram.error_mapping import (
    classify_login_error,
    is_session_error,
    send_block_message,
)
from app.infrastructure.instagram.mapping import as_dt, to_thread, utc

if TYPE_CHECKING:
    from collections.abc import Callable

    from instagrapi import Client


def read_inbox(client: Client, limit: int, since: datetime | None) -> DmInbox:
    """Inbox pages, newest activity first, each one instagrapi's own
    direct_threads_chunk request (its defaults: 20 threads, 10 messages).

    Every sync reads at most `limit` (dm_threads_limit) threads. With `since`,
    paging stops at the first thread last active before `since` (pinned threads
    sit on top out of order and never stop it); only threads active since then
    are returned. instagrapi floors activity to whole seconds, so `since` is
    floored too and a thread in that same second is re-read (harmless) rather
    than missed. If the cap is hit first, the inbox is marked incomplete.
    """
    our_pk = str(client.user_id)
    floor = since.astimezone(UTC).replace(microsecond=0) if since is not None else None
    threads: list[DmThread] = []
    seen = 0
    cursor: str | None = None
    while True:
        chunk, cursor = client.direct_threads_chunk(cursor=cursor)
        for t in chunk:
            seen += 1
            if seen > limit:
                return DmInbox(threads=threads, complete=floor is None)
            activity = as_dt(getattr(t, "last_activity_at", None))
            if floor is not None and activity is not None and utc(activity) < floor:
                if getattr(t, "is_pin", False):
                    continue  # pinned: on top regardless of activity
                return DmInbox(threads=threads)  # back to the previous sync
            if (thread := to_thread(t, our_pk)) is not None:
                threads.append(thread)  # 1:1 only; group/self threads skipped
        if not cursor or not chunk:
            return DmInbox(threads=threads)
        if seen >= limit:
            return DmInbox(threads=threads, complete=floor is None)


def parse_recipient(user_pk: str) -> int:
    """The numeric id direct_send needs; checked before any login or request."""
    try:
        return int(user_pk)
    except (TypeError, ValueError) as exc:
        raise SendRetryableError(f"user_pk inválido: {user_pk!r}") from exc


def send_text(
    client: Client,
    user_pk: str,
    recipient: int,
    text: str,
    on_session_error: Callable[[InstagramError], None],
) -> None:
    """Send one DM to `recipient` (`user_pk`, parsed); every failure leaves as a
    classified InstagramError.

    `on_session_error` hears about a session-level failure before it is raised
    (the facade drops a dead session there).
    """
    from instagrapi.exceptions import (
        ClientForbiddenError,
        ClientThrottledError,
        DirectMessageRequestsDisabled,
        FeedbackRequired,
        PleaseWaitFewMinutes,
        RateLimitError,
        SentryBlock,
    )

    # instagrapi routes any text containing "http" through the link-preview
    # endpoint (broadcast/link/), which Instagram blocks far harder (403) than
    # plain text. Drop the URL scheme so it goes via broadcast/text/ — IG still
    # auto-links the bare domain, so the recipient gets a clickable link.
    safe_text = re.sub(r"https?://", "", text)
    try:
        client.direct_send(safe_text, user_ids=[recipient])
    except DirectMessageRequestsDisabled as exc:
        # The recipient closed message requests — their setting, not a block
        # on us. Skip this one and keep the campaign going.
        raise RecipientUnavailableError(
            f"@{user_pk} no acepta mensajes nuevos — se saltea"
        ) from exc
    except InstagramError as exc:
        # Already classified: a failed relogin (hook) or a guard rail.
        on_session_error(exc)
        raise
    except Exception as exc:  # noqa: BLE001 — every raw failure is classified below
        if is_session_error(exc):
            # The session/account/IP is the problem (expired, challenge or
            # checkpoint, IP block) — never a per-target failure. Classify it so
            # the campaign pauses/blocks and the UI guides the right fix.
            err = classify_login_error(exc)
            on_session_error(err)
            raise err from exc
        if isinstance(
            exc,
            (
                FeedbackRequired,
                SentryBlock,
                PleaseWaitFewMinutes,
                ClientThrottledError,
                RateLimitError,
                ClientForbiddenError,  # a 403 on the send endpoint = action-block
            ),
        ):
            # A genuine Instagram push-back on sending — stop and wait.
            raise SendBlockedError(send_block_message(exc)) from exc
        # Network/timeout: transient, not a block.
        raise SendRetryableError(f"envío falló (reintentable): {exc}") from exc
