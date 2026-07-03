"""InstagrapiInstagramSource — the real adapter.

instagrapi is imported lazily so the app (and FakeInstagramSource) boots even
when the package isn't installed. This is the only module that knows about
instagrapi's models and exceptions; everything else sees domain entities.

Good-behaviour rules live here: session reuse (login once), randomized delays
between requests, and a hard cap on requests per run.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.domain.entities import Comment, DmMessage, DmThread, IgUser, Post
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    InstagramError,
    LoginRequiredError,
    PostNotFoundError,
    RateLimitedError,
)

if TYPE_CHECKING:
    from instagrapi import Client

logger = logging.getLogger(__name__)


class _RequestBudget:
    """Randomized throttle + a hard per-run request cap."""

    def __init__(self, min_delay: float, max_delay: float, max_requests: int) -> None:
        self._min = min_delay
        self._max = max_delay
        self._max_requests = max_requests
        self._count = 0

    def spend(self) -> None:
        self._count += 1
        if self._count > self._max_requests:
            raise RateLimitedError(
                f"request cap reached ({self._max_requests}); stopping to stay safe"
            )
        # Jitter avoids a robotic fixed cadence.
        time.sleep(random.uniform(self._min, self._max))


class InstagrapiInstagramSource:
    """Adapter over instagrapi.Client implementing the InstagramSource port."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._budget = _RequestBudget(
            settings.scan_min_delay_seconds,
            settings.scan_max_delay_seconds,
            settings.scan_max_requests,
        )
        self._client: Client | None = None

    # -- login / session -------------------------------------------------

    def _login(self) -> Client:
        if self._client is not None:
            return self._client

        # Lazy import: keeps instagrapi optional at import time.
        from instagrapi import Client
        from instagrapi.exceptions import (
            ChallengeRequired,
            LoginRequired,
            TwoFactorRequired,
        )

        client = Client()
        client.delay_range = [
            self._settings.scan_min_delay_seconds,
            self._settings.scan_max_delay_seconds,
        ]
        client.challenge_code_handler = self._challenge_code_handler

        session_path = Path(self._settings.ig_session_file)
        if session_path.exists():
            # Reuse a saved session: log in once, not every run.
            client.load_settings(session_path)
            logger.info("loaded IG session from %s", session_path)

        verification_code = self._totp_code(client)
        try:
            client.login(
                self._settings.ig_username,
                self._settings.ig_password,
                verification_code=verification_code,
            )
        except TwoFactorRequired as exc:
            raise ChallengeRequiredError(
                "2FA required. Set IG_2FA_SECRET in .env to resolve it automatically."
            ) from exc
        except ChallengeRequired as exc:
            raise ChallengeRequiredError("Instagram requested verification (challenge).") from exc
        except LoginRequired as exc:
            raise LoginRequiredError(str(exc)) from exc
        except InstagramError:
            raise  # already a handled type (e.g. from the TOTP guard)
        except Exception as exc:
            # Any other instagrapi/network error is surfaced as handled, so the
            # UI shows a message instead of the API returning a raw 500.
            raise LoginRequiredError(f"login failed: {exc}") from exc

        client.dump_settings(session_path)
        logger.info("saved IG session to %s", session_path)
        self._client = client
        return client

    def _totp_code(self, client: Client) -> str:
        """Generate a 2FA code from the seed, or "" if none is configured.

        The seed is stripped first (a stray inline comment or whitespace in
        .env must not be treated as a real seed), and a malformed seed becomes
        a clear handled error rather than an unhandled base32 crash.
        """
        secret = self._settings.ig_2fa_secret.strip()
        if not secret:
            return ""
        try:
            return str(client.totp_generate_code(secret))
        except Exception as exc:
            raise LoginRequiredError(
                "IG_2FA_SECRET is not a valid base32 TOTP seed; "
                "leave it empty if the account has no 2FA."
            ) from exc

    def _challenge_code_handler(self, username: str, choice: Any) -> str:
        # We can't prompt interactively from the API. Surface it as a handled
        # error so the app informs the user instead of crashing.
        raise ChallengeRequiredError(
            f"challenge code required for {username}; resolve it and retry"
        )

    # -- port methods ----------------------------------------------------

    def current_user_pk(self) -> str:
        client = self._login()
        return str(client.user_id)

    def get_post(self, url: str) -> Post:
        from instagrapi.exceptions import ClientError, MediaNotFound

        client = self._login()
        self._budget.spend()
        try:
            media_pk = client.media_pk_from_url(url)
            media = client.media_info(media_pk)
        except MediaNotFound as exc:
            raise PostNotFoundError(url) from exc
        except ClientError as exc:
            raise PostNotFoundError(url) from exc
        return _to_post(media)

    def get_recent_posts(self, limit: int) -> list[Post]:
        client = self._login()
        self._budget.spend()
        medias = client.user_medias(client.user_id, amount=limit)
        return [_to_post(m) for m in medias]

    def get_likers(self, media_pk: str) -> list[IgUser]:
        client = self._login()
        self._budget.spend()
        return [_to_user(u) for u in client.media_likers(media_pk)]

    def get_comments(self, media_pk: str) -> list[Comment]:
        client = self._login()
        self._budget.spend()
        comments: list[Comment] = []
        for c in client.media_comments(media_pk):
            comments.append(
                Comment(
                    user=_to_user(c.user),
                    text=c.text,
                    created_at=_as_dt(getattr(c, "created_at_utc", None)),
                )
            )
        return comments

    def get_dm_threads(self) -> list[DmThread]:
        client = self._login()
        self._budget.spend()
        threads: list[DmThread] = []
        for t in client.direct_threads(amount=self._settings.recent_posts_limit):
            other = _pick_other_user(t, str(client.user_id))
            if other is None:
                continue  # group / self thread — no single counterpart
            messages = [
                DmMessage(user_pk=str(m.user_id), created_at=_as_dt(m.timestamp))
                for m in t.messages
            ]
            threads.append(
                DmThread(
                    thread_id=str(t.id),
                    user=other,
                    messages=messages,
                    last_message_at=messages[0].created_at if messages else None,
                )
            )
        return threads


# -- mapping helpers -----------------------------------------------------


def _as_dt(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _to_user(u: Any) -> IgUser:
    return IgUser(
        pk=str(u.pk),
        username=u.username,
        full_name=getattr(u, "full_name", "") or "",
        profile_pic_url=str(u.profile_pic_url) if getattr(u, "profile_pic_url", None) else None,
        is_private=bool(getattr(u, "is_private", False)),
    )


def _to_post(m: Any) -> Post:
    return Post(
        media_pk=str(m.pk),
        shortcode=m.code,
        url=f"https://instagram.com/p/{m.code}/",
        caption=getattr(m, "caption_text", "") or "",
        taken_at=_as_dt(getattr(m, "taken_at", None)),
    )


def _pick_other_user(thread: Any, our_pk: str) -> IgUser | None:
    """A thread lists all participants; pick the single one that isn't us.

    We key everything by pk (usernames change), and only 1:1 threads map to a
    user in this tool — group threads are skipped.
    """
    others = [u for u in thread.users if str(u.pk) != our_pk]
    if len(others) != 1:
        return None
    return _to_user(others[0])
