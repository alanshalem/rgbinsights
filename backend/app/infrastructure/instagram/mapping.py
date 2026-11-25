"""instagrapi models -> domain entities (pure, no requests)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.entities import DmMessage, DmThread, IgUser, Post


def as_dt(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def utc(when: datetime) -> datetime:
    """Aware UTC. instagrapi builds DM times with datetime.fromtimestamp, i.e.
    naive local time — astimezone() reads a naive value exactly that way."""
    return when.astimezone(UTC)


def raw_user_pk(raw: Any) -> str | None:
    """A user's pk in a raw API list (instagrapi reads `id`, then `pk`)."""
    pk = raw.get("id", raw.get("pk")) if isinstance(raw, dict) else None
    return str(pk) if pk else None


def to_user(u: Any) -> IgUser:
    return IgUser(
        pk=str(u.pk),
        username=u.username,
        full_name=getattr(u, "full_name", "") or "",
        profile_pic_url=str(u.profile_pic_url) if getattr(u, "profile_pic_url", None) else None,
        is_private=bool(getattr(u, "is_private", False)),
    )


def to_post(m: Any) -> Post:
    return Post(
        media_pk=str(m.pk),
        shortcode=m.code,
        url=f"https://instagram.com/p/{m.code}/",
        caption=getattr(m, "caption_text", "") or "",
        taken_at=as_dt(getattr(m, "taken_at", None)),
    )


def to_thread(thread: Any, our_pk: str) -> DmThread | None:
    """A 1:1 thread with its counterpart, or None for a group/self thread."""
    other = _pick_other_user(thread, our_pk)
    if other is None:
        return None
    messages = [
        DmMessage(user_pk=str(m.user_id), created_at=as_dt(m.timestamp)) for m in thread.messages
    ]
    return DmThread(
        thread_id=str(thread.id),
        user=other,
        messages=messages,
        last_message_at=messages[0].created_at if messages else None,
    )


def _pick_other_user(thread: Any, our_pk: str) -> IgUser | None:
    """A thread lists all participants; pick the single one that isn't us.

    We key everything by pk (usernames change), and only 1:1 threads map to a
    user in this tool — group threads are skipped.
    """
    others = [u for u in thread.users if str(u.pk) != our_pk]
    if len(others) != 1:
        return None
    return to_user(others[0])
