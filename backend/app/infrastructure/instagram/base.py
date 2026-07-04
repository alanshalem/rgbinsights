"""InstagramSource port (Strategy).

Isolates the fragile IG/ToS-bound access behind a stable interface so the
use cases depend only on this, and tests can swap in a Fake. The real
implementation is InstagrapiInstagramSource; tests use FakeInstagramSource.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.entities import (
    Comment,
    DmThread,
    Friendship,
    IgUser,
    Post,
    ProfileInfo,
)

ProgressFn = Callable[..., None]


@runtime_checkable
class InstagramSource(Protocol):
    def current_user_pk(self) -> str:
        """Our own account pk. Used to classify DM message direction."""
        ...

    def get_post(self, url: str) -> Post:
        """Raise PostNotFoundError if the url resolves to nothing."""
        ...

    def get_recent_posts(self, limit: int) -> list[Post]: ...

    def get_likers(self, media_pk: str) -> list[IgUser]: ...

    def get_comments(self, media_pk: str) -> list[Comment]: ...

    def get_dm_threads(
        self, progress: ProgressFn | None = None, since: datetime | None = None
    ) -> list[DmThread]:
        """DM threads. If `since` is given, stop paging once threads are older
        than it (incremental sync: only what changed since the last run)."""
        ...

    def send_dm(self, user_pk: str, text: str) -> None:
        """Send a DM. Raises SendBlockedError if Instagram refuses (spam /
        feedback_required), SendNotSupportedError if the source can't send."""
        ...

    def get_friendships(self, user_pks: list[str]) -> dict[str, Friendship]:
        """Follow status for many users at once (empty if unavailable)."""
        ...

    def get_profile(self, username: str) -> ProfileInfo:
        """Richer profile fields (follower count, verified, bio)."""
        ...

    def reset_budget(self) -> None:
        """Reset the per-run request counter. Called at the start of each
        top-level operation so the cap is per-operation, not per-process."""
        ...
