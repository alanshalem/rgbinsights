"""InstagramSource port (Strategy).

Isolates the fragile IG/ToS-bound access behind a stable interface so the
use cases depend only on this, and tests can swap in a Fake. The real
implementation is InstagrapiInstagramSource; tests use FakeInstagramSource.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.entities import Comment, DmThread, IgUser, Post


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

    def get_dm_threads(self) -> list[DmThread]: ...

    def send_dm(self, user_pk: str, text: str) -> None:
        """Send a DM. Raises SendBlockedError if Instagram refuses (spam /
        feedback_required), SendNotSupportedError if the source can't send."""
        ...
