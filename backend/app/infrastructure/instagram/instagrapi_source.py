"""InstagrapiInstagramSource — the real adapter.

instagrapi is imported lazily so the app (and FakeInstagramSource) boots even
when the package isn't installed. This is the only module that knows about
instagrapi's models and exceptions; everything else sees domain entities.

Good-behaviour rules live here: session reuse (login once), randomized delays
between requests, and a hard cap on requests per run.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.domain.entities import (
    Comment,
    DmMessage,
    DmThread,
    Friendship,
    IgUser,
    Post,
    ProfileInfo,
)
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    InstagramError,
    LoginRequiredError,
    PostNotFoundError,
    SendBlockedError,
)
from app.infrastructure.instagram.session import build_client
from app.infrastructure.instagram.throttle import RequestBudget

if TYPE_CHECKING:
    from instagrapi import Client

logger = logging.getLogger(__name__)


class InstagrapiInstagramSource:
    """Adapter over instagrapi.Client implementing the InstagramSource port."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._budget = RequestBudget(
            settings.scan_min_delay_seconds,
            settings.scan_max_delay_seconds,
            settings.scan_max_requests,
        )
        self._client: Client | None = None

    # -- login / session -------------------------------------------------

    def _login(self) -> Client:
        """Authenticate, trying the cheapest/lowest-risk path first.

        1. A saved session.json (reuses the device; no network login) — validated.
        2. IG_SESSIONID from a real browser (low ban risk; recommended bootstrap).
        3. username/password (+ TOTP) — auto-renews when the session finally dies.

        Every success is persisted to session.json so the next start reuses it and
        the account keeps a stable device. This is what makes the login survive
        restarts and self-heal on expiry.
        """
        if self._client is not None:
            return self._client

        # Lazy import: keeps instagrapi optional at import time.
        from instagrapi.exceptions import (
            ChallengeRequired,
            LoginRequired,
            TwoFactorRequired,
        )

        client = build_client(self._settings, self._challenge_code_handler)
        session_path = Path(self._settings.ig_session_file)
        errors: list[str] = []

        # 1. Reuse a saved session (build_client already loaded it).
        if session_path.exists() and self._session_valid(client):
            logger.info("reusing saved IG session")
            self._client = client
            return client

        # 2. Bootstrap from a browser sessionid.
        sessionid = self._settings.ig_sessionid.strip()
        if sessionid:
            try:
                client.login_by_sessionid(sessionid)
                self._persist(client, session_path)
                self._client = client
                return client
            except (ChallengeRequired, LoginRequired) as exc:
                errors.append(f"sessionid vencido/rechazado: {exc}")
            except Exception as exc:  # noqa: BLE001 — surfaced below as handled
                errors.append(f"sessionid: {exc}")

        # 3. username/password (auto-renews when the session dies).
        if self._settings.ig_username and self._settings.ig_password:
            try:
                verification_code = self._totp_code(client)
                client.login(
                    self._settings.ig_username,
                    self._settings.ig_password,
                    verification_code=verification_code,
                )
                self._persist(client, session_path)
                self._client = client
                return client
            except TwoFactorRequired as exc:
                raise ChallengeRequiredError(
                    "IG pide 2FA. Cargá IG_2FA_SECRET en .env para resolverlo solo."
                ) from exc
            except ChallengeRequired as exc:
                raise ChallengeRequiredError(
                    "Instagram pidió verificación (challenge). Reconectá con el sessionid."
                ) from exc
            except InstagramError:
                raise  # already a handled type (e.g. from the TOTP guard)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"user/pass: {exc}")

        detail = "; ".join(errors) if errors else "no hay sessionid ni user/pass en .env"
        raise LoginRequiredError(f"no se pudo iniciar sesión de Instagram ({detail})")

    def _session_valid(self, client: Client) -> bool:
        """Cheap authed probe: True if the loaded session still works."""
        try:
            client.account_info()
            return True
        except Exception:  # noqa: BLE001 — any failure means fall through to re-login
            return False

    def _persist(self, client: Client, session_path: Path) -> None:
        try:
            client.dump_settings(session_path)
            logger.info("saved IG session to %s", session_path)
        except Exception:  # noqa: BLE001 — persistence is best-effort
            logger.warning("could not save IG session", exc_info=True)

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

    def reset_budget(self) -> None:
        self._budget.reset()

    def send_dm(self, user_pk: str, text: str) -> None:
        client = self._login()
        self._budget.spend()
        try:
            client.direct_send(text, user_ids=[int(user_pk)])
        except Exception as exc:
            raise SendBlockedError(f"envío rechazado: {exc}") from exc

    def get_friendships(self, user_pks: list[str]) -> dict[str, Friendship]:
        client = self._login()
        self._budget.spend()
        raw = client.friendships_show_many([int(pk) for pk in user_pks])
        return {
            str(pk): Friendship(following=bool(st.following), followed_by=bool(st.followed_by))
            for pk, st in raw.items()
        }

    def get_profile(self, username: str) -> ProfileInfo:
        client = self._login()
        self._budget.spend()
        u = client.user_info_by_username(username)
        return ProfileInfo(
            pk=str(u.pk),
            username=u.username,
            full_name=u.full_name or "",
            follower_count=u.follower_count,
            is_verified=bool(u.is_verified),
            is_business=bool(getattr(u, "is_business", False)),
            biography=u.biography or "",
            is_private=bool(u.is_private),
            profile_pic_url=str(u.profile_pic_url) if u.profile_pic_url else None,
        )

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

    def get_dm_threads(
        self, progress: object | None = None, since: datetime | None = None
    ) -> list[DmThread]:
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
