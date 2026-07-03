"""Domain entities — plain dataclasses, no external deps.

These are the shapes the InstagramSource port returns and the use cases
consume. They are intentionally decoupled from both the instagrapi models
and the SQLModel persistence rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EngagementType(StrEnum):
    COMMENT = "comment"
    LIKE = "like"


@dataclass(frozen=True, slots=True)
class IgUser:
    """An Instagram user. Identity is `pk` (stable numeric id); username can change."""

    pk: str
    username: str
    full_name: str = ""
    profile_pic_url: str | None = None
    is_private: bool = False


@dataclass(frozen=True, slots=True)
class Post:
    media_pk: str
    shortcode: str
    url: str
    caption: str = ""
    taken_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Comment:
    user: IgUser
    text: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DmMessage:
    """A single DM. `user_pk` is the author of the message."""

    user_pk: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DmThread:
    """A DM thread with the *other* participant and its messages.

    `user` is the other participant (not us). Direction flags are computed
    by the use case by comparing each message's author against our own pk.
    """

    thread_id: str
    user: IgUser
    messages: list[DmMessage] = field(default_factory=list)
    last_message_at: datetime | None = None
