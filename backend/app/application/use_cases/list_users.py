"""Read-side use case: assemble user views with the derived traffic light."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.application.dto import StatusCounts, UserEngagement, UserView
from app.application.use_cases._shared import _naive
from app.domain.entities import EngagementType
from app.domain.traffic_light import TrafficLight, classify
from app.infrastructure.persistence import models
from app.infrastructure.persistence.repositories import DmThreadRepository


def event_counts(session: Session, event: int | None) -> StatusCounts:
    """Traffic-light snapshot for an event (or global if None) — for toast deltas."""
    return ListUsersUseCase(session).counts(event=event)


class ListUsersUseCase:
    """Read-side: assemble user views with derived traffic light + action link.

    When an `event` is given, the semáforo uses that fiesta's `promo_start` as a
    cutoff (DMs before the campaign don't count). Without it, the global state is
    used (the boolean flags, so it works even before DMs are re-synced).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def execute(
        self,
        event: int | None = None,
        post: str | None = None,
        status: TrafficLight | None = None,
        search: str | None = None,
        order: str = "status",
        follows: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserView]:
        views = self._sort(self._build(event, post, status, search, follows), order)
        views = views[offset:]
        if limit is not None:
            views = views[:limit]
        return views

    def counts(
        self,
        event: int | None = None,
        post: str | None = None,
        search: str | None = None,
        follows: bool | None = None,
    ) -> StatusCounts:
        views = self._build(event, post, None, search, follows)
        by = {"red": 0, "yellow": 0, "green": 0}
        for v in views:
            by[v.traffic_light.value] += 1
        return StatusCounts(red=by["red"], yellow=by["yellow"], green=by["green"], total=len(views))

    # -- internals -------------------------------------------------------

    def _build(
        self,
        event: int | None,
        post: str | None,
        status: TrafficLight | None,
        search: str | None,
        follows: bool | None = None,
    ) -> list[UserView]:
        cutoff = self._cutoff(event)
        post_filter = self._post_filter(event, post)
        event_posts_total = len(post_filter) if event is not None and post_filter is not None else 0
        engagements = self._load_engagements(post_filter)
        if not engagements:
            return []

        fan = self._fan_scores()
        threads = DmThreadRepository(self._session).by_user_pk()
        users_by_pk = self._users_by_pk(list(engagements))
        post_urls = self._post_urls()
        needle = search.lower() if search else None

        views: list[UserView] = []
        for user_pk, rows in engagements.items():
            user = users_by_pk.get(user_pk)
            if user is None:
                continue
            if (
                needle
                and needle not in user.username.lower()
                and needle not in (user.full_name or "").lower()
            ):
                continue

            if follows is True and user.follows_us is not True:
                continue

            thread = threads.get(user_pk)
            light = _thread_light(thread, cutoff)
            if status is not None and light != status:
                continue

            action_url = (
                f"https://instagram.com/direct/t/{thread.thread_id}/"
                if thread is not None
                else f"https://instagram.com/{user.username}/"
            )
            engaged_times = [e.created_at for e in rows if e.created_at is not None]
            views.append(
                UserView(
                    pk=user.pk,
                    username=user.username,
                    full_name=user.full_name,
                    profile_pic_url=user.profile_pic_url,
                    is_private=user.is_private,
                    traffic_light=light,
                    thread_id=thread.thread_id if thread is not None else None,
                    action_url=action_url,
                    last_message_at=thread.last_message_at if thread is not None else None,
                    engagement_count=fan.get(user_pk, 0),
                    follows_us=user.follows_us,
                    we_follow=user.we_follow,
                    follower_count=user.follower_count,
                    is_verified=user.is_verified,
                    is_business=user.is_business,
                    biography=user.biography,
                    event_engaged=len({e.post_media_pk for e in rows}),
                    event_posts_total=event_posts_total,
                    last_engaged_at=max(engaged_times) if engaged_times else None,
                    engagements=[
                        UserEngagement(
                            post_media_pk=e.post_media_pk,
                            type=EngagementType(e.type),
                            comment_text=e.comment_text,
                            post_url=post_urls.get(e.post_media_pk),
                        )
                        for e in rows
                    ],
                )
            )
        return views

    def _cutoff(self, event: int | None) -> datetime | None:
        if event is None:
            return None
        row = self._session.get(models.Event, event)
        return _naive(row.promo_start) if row is not None else None

    def _post_filter(self, event: int | None, post: str | None) -> set[str] | None:
        if post is not None:
            return {post}
        if event is not None:
            pks = self._session.exec(
                select(models.Post.media_pk).where(models.Post.event_id == event)
            )
            return set(pks)
        return None

    def _load_engagements(self, post_filter: set[str] | None) -> dict[str, list[models.Engagement]]:
        stmt = select(models.Engagement)
        if post_filter is not None:
            stmt = stmt.where(col(models.Engagement.post_media_pk).in_(post_filter))
        grouped: dict[str, list[models.Engagement]] = {}
        for row in self._session.exec(stmt):
            grouped.setdefault(row.user_pk, []).append(row)
        return grouped

    def _users_by_pk(self, pks: list[str]) -> dict[str, models.User]:
        """Batch-load users by pk (one IN query, chunked under SQLite's limit)."""
        out: dict[str, models.User] = {}
        for i in range(0, len(pks), 900):
            chunk = pks[i : i + 900]
            for user in self._session.exec(
                select(models.User).where(col(models.User.pk).in_(chunk))
            ):
                out[user.pk] = user
        return out

    def _post_urls(self) -> dict[str, str]:
        """media_pk -> post URL, so each engagement can link to its post."""
        return {
            media_pk: url
            for media_pk, url in self._session.exec(
                select(models.Post.media_pk, models.Post.url)
            )
        }

    def _fan_scores(self) -> dict[str, int]:
        """user_pk -> distinct posts engaged (global loyalty signal).

        Counted in SQL (GROUP BY) so we don't pull the whole Engagement table
        into memory on every request.
        """
        stmt = select(
            models.Engagement.user_pk,
            func.count(func.distinct(models.Engagement.post_media_pk)),
        ).group_by(col(models.Engagement.user_pk))
        return {user_pk: count for user_pk, count in self._session.exec(stmt)}

    @staticmethod
    def _sort(views: list[UserView], order: str) -> list[UserView]:
        rank = {TrafficLight.RED: 0, TrafficLight.YELLOW: 1, TrafficLight.GREEN: 2}
        if order == "fans":
            return sorted(views, key=lambda v: (-v.engagement_count, v.username.lower()))
        if order == "followers":
            return sorted(views, key=lambda v: (-(v.follower_count or 0), v.username.lower()))
        if order == "username":
            return sorted(views, key=lambda v: v.username.lower())
        return sorted(views, key=lambda v: (rank[v.traffic_light], v.username.lower()))


def _thread_light(thread: models.DmThread | None, cutoff: datetime | None) -> TrafficLight:
    if thread is None:
        return TrafficLight.RED
    if cutoff is None:
        # Global: booleans work even before timestamps are back-filled by a sync.
        return classify(thread.has_outgoing, thread.has_incoming)
    incoming = thread.last_incoming_at is not None and _after(thread.last_incoming_at, cutoff)
    outgoing = thread.last_outgoing_at is not None and _after(thread.last_outgoing_at, cutoff)
    return classify(outgoing, incoming)


def _after(dt: datetime, cutoff: datetime) -> bool:
    naive = _naive(dt)
    return naive is not None and naive >= cutoff
