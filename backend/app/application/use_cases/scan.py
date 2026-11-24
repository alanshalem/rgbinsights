"""Scan use cases: pull likers + commenters of posts into the DB."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import datetime, timedelta

from sqlmodel import Session

from app.application.dto import ScanBatchResult, ScanResult
from app.application.use_cases._shared import (
    ProgressFn,
    _naive,
    _now,
    _to_scanned,
    map_instagram_error,
)
from app.domain.entities import EngagementType, Post
from app.domain.result import Err, ErrorCode, Ok, Result
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import InstagramError
from app.infrastructure.persistence.repositories import (
    EngagementIn,
    EngagementRepository,
    PostRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)

# The shortcode in a post/reel URL (instagram.com/p/<code>/, /reel/<code>/ ...).
_SHORTCODE = re.compile(r"/(?:p|reels?|tv)/([A-Za-z0-9_-]+)")


def _shortcode(url: str) -> str | None:
    match = _SHORTCODE.search(url)
    return match.group(1) if match else None


class ScanPostUseCase:
    def __init__(self, source: InstagramSource, session: Session) -> None:
        self._source = source
        self._session = session
        self._users = UserRepository(session)
        self._posts = PostRepository(session)
        self._engagements = EngagementRepository(session)

    def execute(self, url: str, event_id: int | None = None) -> Result[ScanResult]:
        """Scan a post by URL. A post already stored is not fetched again: its
        media_pk is all the likers/comments reads need."""
        code = _shortcode(url)
        post = self._posts.find_by_shortcode(code) if code else None
        if post is None:
            try:
                post = self._source.get_post(url)
            except InstagramError as exc:
                logger.warning("scan failed for %s: %s", url, exc)
                return map_instagram_error(exc)
        return self.scan(post, event_id)

    def scan(self, post: Post, event_id: int | None = None) -> Result[ScanResult]:
        """Likers + comments of a post we already have (no post lookup). Only
        comments newer than the newest one stored are paged."""
        self._source.reset_budget()
        since = self._posts.last_comment_at(post.media_pk)
        try:
            comments = self._source.get_comments(post.media_pk, since)
            likers = self._source.get_likers(post.media_pk)
        except InstagramError as exc:
            logger.warning("scan failed for %s: %s", post.url, exc)
            return map_instagram_error(exc)

        now = _now()
        newest = max((c.created_at for c in comments if c.created_at is not None), default=None)
        self._posts.upsert(post, scanned_at=now, event_id=event_id, last_comment_at=newest)
        # Comments first, then likers: a user in both keeps the liker's data.
        people = [c.user for c in comments] + likers
        new_pks = self._users.upsert_many(people, now)
        self._engagements.upsert_many(
            post.media_pk,
            [
                EngagementIn(c.user.pk, EngagementType.COMMENT, c.text, c.created_at)
                for c in comments
            ]
            + [EngagementIn(liker.pk, EngagementType.LIKE) for liker in likers],
        )
        self._session.commit()

        found = len({u.pk for u in people})
        logger.info("scanned %s: %d users, %d new", post.url, found, len(new_pks))
        return Ok(ScanResult(_to_scanned(post), users_found=found, new_users=len(new_pks)))


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
        # user_medias already returned each post: no media_info per post.
        return self._run([self._single.scan(p, event_id) for p in in_range])

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
