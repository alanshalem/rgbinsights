"""Scan use cases: pull likers + commenters of posts into the DB."""

from __future__ import annotations

import logging
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
from app.domain.entities import EngagementType
from app.domain.result import Err, ErrorCode, Ok, Result
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import InstagramError
from app.infrastructure.persistence.repositories import (
    EngagementRepository,
    PostRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)


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
