"""Board read-model: filter, sort, count and paginate users in SQL.

Replaces loading every engagement/thread/post into Python per request. The
result must match the previous in-Python version exactly, so a few details are
deliberate:

- Case folding uses Python's `str.lower` (registered as `py_lower`): SQLite's
  lower()/LIKE only fold ASCII, which would break searches like "ángeles".
- A user's thread is the most recently inserted one (highest rowid), as the
  old `{user_pk: thread}` map built from a table scan kept the last row.
- Ties (same lowercased username) keep the engagement first-seen order:
  insertion (id) order, or (post, id) when filtered by posts — the order in
  which SQLite returned the post-filtered rows through its post index.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Select,
    Table,
    and_,
    case,
    distinct,
    func,
    literal_column,
    or_,
    select,
)
from sqlmodel import Session

from app.domain.entities import EngagementType
from app.domain.traffic_light import TrafficLight
from app.infrastructure.persistence import models
from app.infrastructure.persistence.repositories import chunked

_USERS: Table = models.User.__table__  # type: ignore[attr-defined]
_ENGAGEMENTS: Table = models.Engagement.__table__  # type: ignore[attr-defined]
_THREADS: Table = models.DmThread.__table__  # type: ignore[attr-defined]
_POSTS: Table = models.Post.__table__  # type: ignore[attr-defined]
_EVENTS: Table = models.Event.__table__  # type: ignore[attr-defined]

# Sort rank of each light (board order: red first). Mirrors domain `classify`:
# any incoming -> green, else any outgoing -> yellow, else red.
_RANK = {TrafficLight.RED: 0, TrafficLight.YELLOW: 1, TrafficLight.GREEN: 2}
_LIGHT = {rank: light for light, rank in _RANK.items()}


@dataclass(frozen=True, slots=True)
class UserFilter:
    event: int | None = None
    post: str | None = None
    search: str | None = None
    follows: bool | None = None


@dataclass(frozen=True, slots=True)
class UserRow:
    pk: str
    username: str
    full_name: str
    profile_pic_url: str | None
    is_private: bool
    follows_us: bool | None
    we_follow: bool | None
    follower_count: int | None
    is_verified: bool
    is_business: bool
    biography: str | None
    thread_id: str | None
    last_message_at: datetime | None
    traffic_light: TrafficLight
    fans: int  # distinct posts engaged, global
    event_engaged: int  # distinct posts engaged within the filter
    last_engaged_at: datetime | None


@dataclass(frozen=True, slots=True)
class EngagementRow:
    post_media_pk: str
    type: EngagementType
    comment_text: str | None
    post_url: str | None


def _py_lower(value: str | None) -> str | None:
    return value.lower() if value is not None else None


class UserListQuery:
    def __init__(self, session: Session) -> None:
        self._session = session

    def page(
        self,
        f: UserFilter,
        status: TrafficLight | None,
        order: str,
        limit: int | None,
        offset: int,
    ) -> list[UserRow]:
        stmt, rank, username = self._base(f)
        stmt = stmt.add_columns(rank.label("rank"))
        if status is not None:
            stmt = stmt.where(rank == _RANK[status])
        stmt = stmt.order_by(*self._order(order, rank, username), literal_column("first_seq"))
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return [_to_row(r._mapping) for r in self._session.execute(stmt)]

    def counts(self, f: UserFilter) -> dict[TrafficLight, int]:
        stmt, rank, _ = self._base(f)
        sub = stmt.add_columns(rank.label("rank")).subquery()
        grouped = select(sub.c.rank, func.count()).group_by(sub.c.rank)
        out = dict.fromkeys(TrafficLight, 0)
        for r, n in self._session.execute(grouped):
            out[_LIGHT[r]] = n
        return out

    def engagements(self, f: UserFilter, user_pks: Sequence[str]) -> dict[str, list[EngagementRow]]:
        """Each user's engagements within the filter, in the board's order."""
        e = _ENGAGEMENTS.alias("e")
        p = _POSTS.alias("p")
        out: dict[str, list[EngagementRow]] = {}
        for chunk in chunked(list(user_pks)):
            stmt = (
                select(e.c.user_pk, e.c.post_media_pk, e.c.type, e.c.comment_text, p.c.url)
                .select_from(e.outerjoin(p, p.c.media_pk == e.c.post_media_pk))
                .where(e.c.user_pk.in_(chunk), *self._post_condition(f, e))
                .order_by(*self._engagement_order(f, e))
            )
            for user_pk, post_pk, type_, text, url in self._session.execute(stmt):
                out.setdefault(user_pk, []).append(
                    EngagementRow(post_pk, EngagementType(type_), text, url)
                )
        return out

    def event_posts_total(self, f: UserFilter) -> int:
        if f.event is None:
            return 0
        if f.post is not None:
            return 1
        stmt = select(func.count()).select_from(_POSTS).where(_POSTS.c.event_id == f.event)
        return int(self._session.execute(stmt).scalar_one())

    # -- internals -------------------------------------------------------

    def _base(self, f: UserFilter) -> tuple[Select[Any], ColumnElement[Any], ColumnElement[Any]]:
        """Filtered users joined with their latest thread; plus rank/username keys."""
        self._ensure_py_lower()
        u = _USERS
        e = _ENGAGEMENTS.alias("e")
        e2 = _ENGAGEMENTS.alias("e2")
        t = _THREADS.alias("t")
        t2 = _THREADS.alias("t2")

        seq = func.row_number().over(order_by=self._engagement_order(f, e))
        filtered = (
            select(e.c.user_pk, e.c.post_media_pk, e.c.created_at, seq.label("seq"))
            .where(*self._post_condition(f, e))
            .subquery("filtered")
        )
        agg = (
            select(
                filtered.c.user_pk,
                func.count(distinct(filtered.c.post_media_pk)).label("event_engaged"),
                func.max(filtered.c.created_at).label("last_engaged_at"),
                func.min(filtered.c.seq).label("first_seq"),
            )
            .group_by(filtered.c.user_pk)
            .subquery("agg")
        )
        latest_thread = (
            select(func.max(literal_column("t2.rowid")))
            .where(t2.c.user_pk == u.c.pk)
            .scalar_subquery()
        )
        fans = (
            select(func.count(distinct(e2.c.post_media_pk)))
            .where(e2.c.user_pk == u.c.pk)
            .scalar_subquery()
        )
        username = func.py_lower(u.c.username)

        stmt = select(
            u.c.pk,
            u.c.username,
            u.c.full_name,
            u.c.profile_pic_url,
            u.c.is_private,
            u.c.follows_us,
            u.c.we_follow,
            u.c.follower_count,
            u.c.is_verified,
            u.c.is_business,
            u.c.biography,
            t.c.thread_id,
            t.c.last_message_at,
            fans.label("fans"),
            agg.c.event_engaged,
            agg.c.last_engaged_at,
            agg.c.first_seq,
        ).select_from(
            agg.join(u, u.c.pk == agg.c.user_pk).outerjoin(
                t, literal_column("t.rowid") == latest_thread
            )
        )
        if f.search:
            needle = f.search.lower()
            stmt = stmt.where(
                or_(
                    func.instr(username, needle) > 0,
                    func.instr(func.py_lower(func.coalesce(u.c.full_name, "")), needle) > 0,
                )
            )
        if f.follows is True:
            stmt = stmt.where(u.c.follows_us.is_(True))
        return stmt, self._rank(f, t), username

    def _rank(self, f: UserFilter, t: Any) -> ColumnElement[Any]:
        incoming: ColumnElement[Any] = t.c.has_incoming
        outgoing: ColumnElement[Any] = t.c.has_outgoing
        if f.event is not None and self._session.get(models.Event, f.event) is not None:
            # Per-fiesta: only DMs at/after promo_start count. Compared against the
            # stored value directly, as the old naive-datetime comparison did.
            cutoff = select(_EVENTS.c.promo_start).where(_EVENTS.c.id == f.event).scalar_subquery()
            incoming = and_(t.c.last_incoming_at.is_not(None), t.c.last_incoming_at >= cutoff)
            outgoing = and_(t.c.last_outgoing_at.is_not(None), t.c.last_outgoing_at >= cutoff)
        return case(
            (incoming, _RANK[TrafficLight.GREEN]),
            (outgoing, _RANK[TrafficLight.YELLOW]),
            else_=_RANK[TrafficLight.RED],
        )

    @staticmethod
    def _order(order: str, rank: ColumnElement[Any], username: ColumnElement[Any]) -> list[Any]:
        u = _USERS
        if order == "fans":
            return [literal_column("fans").desc(), username]
        if order == "followers":
            return [func.coalesce(u.c.follower_count, 0).desc(), username]
        if order == "username":
            return [username]
        return [rank, username]

    @staticmethod
    def _post_condition(f: UserFilter, e: Any) -> list[ColumnElement[bool]]:
        if f.post is not None:
            return [e.c.post_media_pk == f.post]
        if f.event is not None:
            event_posts = select(_POSTS.c.media_pk).where(_POSTS.c.event_id == f.event)
            return [e.c.post_media_pk.in_(event_posts)]
        return []

    @staticmethod
    def _engagement_order(f: UserFilter, e: Any) -> list[Any]:
        if f.post is None and f.event is None:
            return [e.c.id]
        return [e.c.post_media_pk, e.c.id]

    def _ensure_py_lower(self) -> None:
        conn = self._session.connection().connection
        if not conn.info.get("py_lower"):
            conn.driver_connection.create_function(  # type: ignore[union-attr]
                "py_lower", 1, _py_lower, deterministic=True
            )
            conn.info["py_lower"] = True


def _to_row(m: Any) -> UserRow:
    return UserRow(
        pk=m["pk"],
        username=m["username"],
        full_name=m["full_name"],
        profile_pic_url=m["profile_pic_url"],
        is_private=m["is_private"],
        follows_us=m["follows_us"],
        we_follow=m["we_follow"],
        follower_count=m["follower_count"],
        is_verified=m["is_verified"],
        is_business=m["is_business"],
        biography=m["biography"],
        thread_id=m["thread_id"],
        last_message_at=m["last_message_at"],
        traffic_light=_LIGHT[m["rank"]],
        fans=m["fans"] or 0,
        event_engaged=m["event_engaged"],
        last_engaged_at=m["last_engaged_at"],
    )
