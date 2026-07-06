"""Use cases — orchestrate the source, repos, and domain rules.

Expected failures (post not found, challenge) are returned as Result.Err,
never raised, so the API can map them to clean HTTP responses.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.application.dto import (
    EnrichResult,
    ScanBatchResult,
    ScannedPost,
    ScanResult,
    StatusCounts,
    SyncResult,
    UserEngagement,
    UserView,
)
from app.domain.entities import EngagementType, Post
from app.domain.result import Err, ErrorCode, Ok, Result
from app.domain.traffic_light import TrafficLight, classify
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    InstagramError,
    LoginRequiredError,
    PostNotFoundError,
    RateLimitedError,
)
from app.infrastructure.persistence import models
from app.infrastructure.persistence.repositories import (
    AppStateRepository,
    DmThreadRepository,
    EngagementRepository,
    PostRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)

ProgressFn = Callable[..., None]

# app_state keys for cache/TTL timestamps.
KEY_DMS_SYNCED = "dms_synced_at"
KEY_RELATIONS_SYNCED = "relationships_synced_at"


def _now() -> datetime:
    return datetime.now(UTC)


def map_instagram_error(exc: InstagramError) -> Err:
    if isinstance(exc, PostNotFoundError):
        return Err(ErrorCode.POST_NOT_FOUND, "post not found")
    if isinstance(exc, ChallengeRequiredError):
        return Err(ErrorCode.CHALLENGE_REQUIRED, str(exc))
    if isinstance(exc, LoginRequiredError):
        return Err(ErrorCode.LOGIN_REQUIRED, str(exc))
    if isinstance(exc, RateLimitedError):
        return Err(ErrorCode.RATE_LIMITED, str(exc))
    return Err(ErrorCode.UNKNOWN, str(exc))


def event_counts(session: Session, event: int | None) -> StatusCounts:
    """Traffic-light snapshot for an event (or global if None) — for toast deltas."""
    return ListUsersUseCase(session).counts(event=event)


def state_delta(before: StatusCounts, after: StatusCounts) -> dict[str, int]:
    """Positive state transitions between two snapshots, for the 'qué cambió' toast.

    respondieron  = new greens (someone replied → green)
    amarillos     = net new yellows (contacted, no reply yet)
    Only positive moves are reported; a quiet sync yields an empty dict.
    """
    out: dict[str, int] = {}
    if (respondieron := after.green - before.green) > 0:
        out["respondieron"] = respondieron
    if (amarillos := after.yellow - before.yellow) > 0:
        out["amarillos"] = amarillos
    return out


def _to_scanned(post: Post) -> ScannedPost:
    return ScannedPost(
        media_pk=post.media_pk,
        shortcode=post.shortcode,
        url=post.url,
        caption=post.caption,
        taken_at=post.taken_at,
    )


class ScanPostUseCase:
    def __init__(self, source: InstagramSource, session: Session) -> None:
        self._source = source
        self._session = session
        self._users = UserRepository(session)
        self._posts = PostRepository(session)
        self._engagements = EngagementRepository(session)

    def execute(self, url: str, event_id: int | None = None) -> Result[ScanResult]:
        self._source.reset_budget()
        try:
            post = self._source.get_post(url)
            comments = self._source.get_comments(post.media_pk)
            likers = self._source.get_likers(post.media_pk)
        except InstagramError as exc:
            logger.warning("scan failed for %s: %s", url, exc)
            return map_instagram_error(exc)

        now = _now()
        self._posts.upsert(post, scanned_at=now, event_id=event_id)

        seen: set[str] = set()
        new_users = 0

        for comment in comments:
            new_users += self._record(comment.user, now, seen)
            self._engagements.upsert(
                comment.user.pk,
                post.media_pk,
                EngagementType.COMMENT,
                comment.text,
                comment.created_at,
            )
        for liker in likers:
            new_users += self._record(liker, now, seen)
            self._engagements.upsert(liker.pk, post.media_pk, EngagementType.LIKE, None, None)

        self._session.commit()
        logger.info("scanned %s: %d users, %d new", url, len(seen), new_users)
        return Ok(ScanResult(_to_scanned(post), users_found=len(seen), new_users=new_users))

    def _record(self, user: object, now: datetime, seen: set[str]) -> int:
        from app.domain.entities import IgUser

        assert isinstance(user, IgUser)
        is_new = self._users.upsert(user, now)
        first_time_this_scan = user.pk not in seen
        seen.add(user.pk)
        return 1 if (is_new and first_time_this_scan) else 0


class ScanPostsUseCase:
    """Scan several posts by URL list, or by date range over recent posts."""

    def __init__(self, source: InstagramSource, session: Session, recent_limit: int) -> None:
        self._source = source
        self._session = session
        self._recent_limit = recent_limit
        self._single = ScanPostUseCase(source, session)

    def by_urls(
        self, urls: list[str], event_id: int | None = None, progress: ProgressFn | None = None
    ) -> Result[ScanBatchResult]:
        results = []
        for i, url in enumerate(urls, 1):
            if progress is not None:
                progress(i - 1, len(urls), f"post {i}/{len(urls)}")
            results.append(self._single.execute(url, event_id))
        return self._run(results)

    def by_date_range(
        self, date_from: datetime, date_to: datetime, event_id: int | None = None
    ) -> Result[ScanBatchResult]:
        try:
            recent = self._source.get_recent_posts(self._recent_limit)
        except InstagramError as exc:
            return map_instagram_error(exc)
        in_range = [
            p for p in recent if p.taken_at is not None and date_from <= p.taken_at <= date_to
        ]
        return self._run([self._single.execute(p.url, event_id) for p in in_range])

    @staticmethod
    def _run(results: list[Result[ScanResult]]) -> Result[ScanBatchResult]:
        oks: list[ScanResult] = []
        errs: list[Err] = []
        for r in results:
            if isinstance(r, Ok):
                oks.append(r.value)
            else:
                # A challenge blocks everything — surface it immediately.
                if r.code is ErrorCode.CHALLENGE_REQUIRED:
                    return r
                errs.append(r)
        # If nothing succeeded, surface the failure instead of a misleading
        # empty-but-OK batch (e.g. login blocked / post not found).
        if not oks and errs:
            return errs[0]
        return Ok(
            ScanBatchResult(
                results=oks,
                total_users_found=sum(r.users_found for r in oks),
                total_new_users=sum(r.new_users for r in oks),
            )
        )


class RescanEventUseCase:
    """Re-scan every post already assigned to a fiesta (no URLs to paste)."""

    def __init__(self, source: InstagramSource, session: Session, recent_limit: int) -> None:
        self._session = session
        self._batch = ScanPostsUseCase(source, session, recent_limit)

    def execute(
        self,
        event_id: int,
        progress: ProgressFn | None = None,
        force: bool = False,
        skip_hours: float = 6.0,
    ) -> Result[ScanBatchResult]:
        posts = PostRepository(self._session).list_all(event_id=event_id)
        if force:
            stale = posts
        else:
            cutoff = _naive(_now() - timedelta(hours=skip_hours))
            stale = [
                p
                for p in posts
                if p.last_scanned_at is None or _naive(p.last_scanned_at) < cutoff  # type: ignore[operator]
            ]
        skipped = len(posts) - len(stale)
        urls = [p.url for p in stale]
        if not urls:
            return Ok(
                ScanBatchResult(results=[], total_users_found=0, total_new_users=0, skipped=skipped)
            )
        result = self._batch.by_urls(urls, event_id=event_id, progress=progress)
        if isinstance(result, Ok):
            return Ok(replace(result.value, skipped=skipped))
        return result


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
    ) -> Result[SyncResult]:
        self._source.reset_budget()
        state = AppStateRepository(self._session)
        since = None if (force or not incremental) else state.get_dt(KEY_DMS_SYNCED)
        try:
            our_pk = self._source.current_user_pk()
            threads = self._source.get_dm_threads(progress, since)
        except InstagramError as exc:
            logger.warning("dm sync failed: %s", exc)
            return map_instagram_error(exc)

        now = _now()
        for thread in threads:
            out_times = [
                m.created_at
                for m in thread.messages
                if m.user_pk == our_pk and m.created_at is not None
            ]
            in_times = [
                m.created_at
                for m in thread.messages
                if m.user_pk != our_pk and m.created_at is not None
            ]
            self._users.upsert(thread.user, now)
            self._threads.upsert(
                thread_id=thread.thread_id,
                user_pk=thread.user.pk,
                has_outgoing=any(m.user_pk == our_pk for m in thread.messages),
                has_incoming=any(m.user_pk != our_pk for m in thread.messages),
                last_outgoing_at=max(out_times) if out_times else None,
                last_incoming_at=max(in_times) if in_times else None,
                last_message_at=thread.last_message_at,
                synced_at=now,
            )

        state.set_dt(KEY_DMS_SYNCED, now)
        self._session.commit()
        logger.info("synced %d DM threads (incremental=%s)", len(threads), since is not None)
        return Ok(
            SyncResult(
                threads_synced=len(threads),
                users_touched=len(threads),
                incremental=since is not None,
            )
        )


class EnrichProfilesUseCase:
    """The slow, opt-in "extra data" step, for a fiesta's users:

    1. Follow relationship (te sigue / mutuo) — read from our followers/following
       lists (the only accurate way; show_many omits "followed_by").
    2. Richer profile per user (follower count, verified, bio) — one call each,
       so only users not yet enriched are fetched.
    """

    def __init__(self, source: InstagramSource, session: Session) -> None:
        self._source = source
        self._session = session
        self._users = UserRepository(session)

    def execute(
        self,
        pks: list[str],
        limit: int = 1000,
        progress: ProgressFn | None = None,
        force: bool = False,
        cache_hours: float = 12.0,
    ) -> Result[EnrichResult]:
        self._source.reset_budget()
        now = _now()
        state = AppStateRepository(self._session)

        relations = 0
        last = state.get_dt(KEY_RELATIONS_SYNCED)
        fresh = last is not None and (now - last) < timedelta(hours=cache_hours)
        relations_cached = bool(fresh) and not force
        if relations_cached:
            # Followers/following read < cache_hours ago — reuse stored flags
            # (hundreds of paginated, ban-prone requests skipped).
            logger.info("relationships fresh (%s) — skipping fetch", last)
        else:
            try:
                if progress is not None:
                    progress(0, 0, "trayendo relaciones (te sigue)…")
                rels = self._source.get_friendships(pks)
                self._users.set_friendships(rels)
                relations = len(rels)
                state.set_dt(KEY_RELATIONS_SYNCED, now)
            except InstagramError as exc:
                logger.warning("relationship fetch skipped: %s", exc)

        pending = self._users.unenriched(pks)[:limit]
        total = len(pending)
        enriched = 0
        for user in pending:
            if progress is not None:
                progress(enriched, total, f"@{user.username}")
            try:
                profile = self._source.get_profile(user.username)
            except InstagramError as exc:
                logger.warning("enrich failed for @%s: %s", user.username, exc)
                return map_instagram_error(exc)
            self._users.set_profile(user.pk, profile, now)
            enriched += 1

        self._session.commit()
        return Ok(
            EnrichResult(enriched=enriched, relations=relations, relations_cached=relations_cached)
        )


def _naive(dt: datetime | None) -> datetime | None:
    """Drop tzinfo so DB-read (naive) and API (maybe aware) datetimes compare."""
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo is not None else dt


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
