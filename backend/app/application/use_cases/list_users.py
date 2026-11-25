"""Read-side use case: assemble user views with the derived traffic light."""

from __future__ import annotations

from app.application.dto import StatusCounts, UserEngagement, UserView
from app.application.ports import EngagementRow, UnitOfWork, UserFilter, UserRow
from app.domain.traffic_light import TrafficLight

# Every order the board offers (key -> how the export names it). The single
# source of truth for the API's `order` parameter and the export's filters.
ORDER_LABELS: dict[str, str] = {
    "username": "usuario",
    "status": "estado",
    "fans": "fans",
    "followers": "seguidores",
}
DEFAULT_ORDER = "status"
ORDER_PATTERN = "^(" + "|".join(ORDER_LABELS) + ")$"


def event_counts(uow: UnitOfWork, event: int | None) -> StatusCounts:
    """Traffic-light snapshot for an event (or global if None) — for toast deltas."""
    return ListUsersUseCase(uow).counts(event=event)


class ListUsersUseCase:
    """Read-side: assemble user views with derived traffic light + action link.

    When an `event` is given, the semáforo uses that fiesta's `promo_start` as a
    cutoff (DMs before the campaign don't count). Without it, the global state is
    used (the boolean flags, so it works even before DMs are re-synced).
    Filtering, sorting, counting and pagination run in SQL; only the requested
    page is materialized.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._query = uow.user_list

    def execute(
        self,
        event: int | None = None,
        post: str | None = None,
        status: TrafficLight | None = None,
        search: str | None = None,
        order: str = DEFAULT_ORDER,
        follows: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserView]:
        f = UserFilter(event=event, post=post, search=search, follows=follows)
        rows = self._query.page(f, status=status, order=order, limit=limit, offset=offset)
        if not rows:
            return []
        engagements = self._query.engagements(f, [r.pk for r in rows])
        total = self._query.event_posts_total(f)
        return [_to_view(r, engagements.get(r.pk, []), total) for r in rows]

    def counts(
        self,
        event: int | None = None,
        post: str | None = None,
        search: str | None = None,
        follows: bool | None = None,
    ) -> StatusCounts:
        by = self._query.counts(UserFilter(event=event, post=post, search=search, follows=follows))
        return StatusCounts(
            red=by[TrafficLight.RED],
            yellow=by[TrafficLight.YELLOW],
            green=by[TrafficLight.GREEN],
            total=sum(by.values()),
        )


def _to_view(row: UserRow, engagements: list[EngagementRow], event_posts_total: int) -> UserView:
    action_url = (
        f"https://instagram.com/direct/t/{row.thread_id}/"
        if row.thread_id is not None
        else f"https://instagram.com/{row.username}/"
    )
    return UserView(
        pk=row.pk,
        username=row.username,
        full_name=row.full_name,
        profile_pic_url=row.profile_pic_url,
        is_private=row.is_private,
        traffic_light=row.traffic_light,
        thread_id=row.thread_id,
        action_url=action_url,
        last_message_at=row.last_message_at,
        engagement_count=row.fans,
        follows_us=row.follows_us,
        we_follow=row.we_follow,
        follower_count=row.follower_count,
        is_verified=row.is_verified,
        is_business=row.is_business,
        biography=row.biography,
        event_engaged=row.event_engaged,
        event_posts_total=event_posts_total,
        last_engaged_at=row.last_engaged_at,
        engagements=[
            UserEngagement(
                post_media_pk=e.post_media_pk,
                type=e.type,
                comment_text=e.comment_text,
                post_url=e.post_url,
            )
            for e in engagements
        ],
    )
