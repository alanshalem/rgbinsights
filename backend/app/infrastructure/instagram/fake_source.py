"""FakeInstagramSource — in-memory sample data.

Lets the whole app (and the frontend) run without touching Instagram, and
backs the use-case tests. Data is crafted to exercise all three semáforo
states:
  - lucia  -> commented, thread with incoming  -> GREEN
  - tomas  -> liked, thread outgoing only      -> YELLOW
  - sofia  -> commented + liked, no thread      -> RED
  - martin -> liked, no thread                  -> RED
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.entities import (
    Comment,
    DmMessage,
    DmThread,
    Friendship,
    IgUser,
    Post,
    ProfileInfo,
)
from app.infrastructure.instagram.errors import PostNotFoundError

_OUR_PK = "0"


def _dt(day: int) -> datetime:
    return datetime(2026, 6, day, 12, 0, tzinfo=UTC)


_LUCIA = IgUser(pk="101", username="lucia.dj", full_name="Lucía", is_private=False)
_TOMAS = IgUser(pk="102", username="tomas_beats", full_name="Tomás", is_private=False)
_SOFIA = IgUser(pk="103", username="sofi.raver", full_name="Sofía", is_private=True)
_MARTIN = IgUser(pk="104", username="martin.k", full_name="Martín", is_private=False)

_POST_A = Post(
    media_pk="900001",
    shortcode="Cabc123",
    url="https://instagram.com/p/Cabc123/",
    caption="RGB — closing set 🔴🟢🔵",
    taken_at=_dt(10),
)
_POST_B = Post(
    media_pk="900002",
    shortcode="Cdef456",
    url="https://instagram.com/p/Cdef456/",
    caption="next party lineup",
    taken_at=_dt(20),
)


class FakeInstagramSource:
    """Deterministic in-memory source implementing the InstagramSource port."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []  # (user_pk, text) for tests

    def reset_budget(self) -> None:
        pass

    def send_dm(self, user_pk: str, text: str) -> None:
        self.sent.append((user_pk, text))

    def get_friendships(self, user_pks: list[str]) -> dict[str, Friendship]:
        # lucia follows us; tomas is mutual; others neither.
        rel = {
            "101": Friendship(following=False, followed_by=True),
            "102": Friendship(following=True, followed_by=True),
        }
        return {pk: rel.get(pk, Friendship(following=False, followed_by=False)) for pk in user_pks}

    def get_profile(self, username: str) -> ProfileInfo:
        return ProfileInfo(
            pk="0",
            username=username,
            full_name=username.title(),
            follower_count=1234,
            is_verified=False,
            is_business=False,
            biography="dj / productor",
            is_private=False,
            profile_pic_url=None,
        )

    def current_user_pk(self) -> str:
        return _OUR_PK

    def get_post(self, url: str) -> Post:
        for post in (_POST_A, _POST_B):
            if url.rstrip("/") == post.url.rstrip("/") or post.shortcode in url:
                return post
        raise PostNotFoundError(url)

    def get_recent_posts(self, limit: int) -> list[Post]:
        return [_POST_B, _POST_A][:limit]

    def get_likers(self, media_pk: str) -> list[IgUser]:
        if media_pk == _POST_A.media_pk:
            return [_TOMAS, _SOFIA, _MARTIN]
        if media_pk == _POST_B.media_pk:
            return [_LUCIA, _TOMAS]
        return []

    def get_comments(self, media_pk: str) -> list[Comment]:
        if media_pk == _POST_A.media_pk:
            return [
                Comment(user=_LUCIA, text="temazo 🔥", created_at=_dt(11)),
                Comment(user=_SOFIA, text="cuándo la próxima?", created_at=_dt(11)),
            ]
        if media_pk == _POST_B.media_pk:
            return [Comment(user=_LUCIA, text="ahí estaré", created_at=_dt(21))]
        return []

    def get_dm_threads(
        self, progress: object | None = None, since: datetime | None = None
    ) -> list[DmThread]:
        return [
            # lucia answered us -> GREEN
            DmThread(
                thread_id="t-lucia",
                user=_LUCIA,
                messages=[
                    DmMessage(user_pk=_OUR_PK, created_at=_dt(12)),
                    DmMessage(user_pk=_LUCIA.pk, created_at=_dt(13)),
                ],
                last_message_at=_dt(13),
            ),
            # we wrote tomas, no reply -> YELLOW
            DmThread(
                thread_id="t-tomas",
                user=_TOMAS,
                messages=[DmMessage(user_pk=_OUR_PK, created_at=_dt(14))],
                last_message_at=_dt(14),
            ),
        ]
