"""InstagrapiInstagramSource — the real adapter.

instagrapi is imported lazily so the app (and FakeInstagramSource) boots even
when the package isn't installed. This is the only module that knows about
instagrapi's models and exceptions; everything else sees domain entities.

Good-behaviour rules live here: session reuse (login once), randomized delays
between requests, and a hard cap on requests per run.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Callable
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
    IpBlockedError,
    LoginRequiredError,
    PostNotFoundError,
    RecipientUnavailableError,
    SendBlockedError,
    SendRetryableError,
)
from app.infrastructure.instagram.session import build_client
from app.infrastructure.instagram.throttle import RequestBudget

if TYPE_CHECKING:
    from instagrapi import Client

logger = logging.getLogger(__name__)

def _adapts[F: Callable[..., Any]](fn: F) -> F:
    """Wrap a port method so any raw instagrapi/network exception becomes an
    InstagramError (our own errors already pass through). Defined before the
    class because decorators are evaluated when the class body runs.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — normalised at the adapter boundary
            raise _to_instagram_error(exc) from exc

    return wrapper  # type: ignore[return-value]


class InstagrapiInstagramSource:
    """Adapter over instagrapi.Client implementing the InstagramSource port."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._budget = RequestBudget(settings.scan_max_requests)
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
                if isinstance(domain := classify_login_error(exc), IpBlockedError):
                    raise domain from exc  # a flagged IP breaks every path — stop now
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
                if isinstance(domain := classify_login_error(exc), IpBlockedError):
                    raise domain from exc  # a flagged IP breaks every path — stop now
                errors.append(f"user/pass: {exc}")

        detail = "; ".join(errors) if errors else "no hay sessionid ni user/pass en .env"
        raise LoginRequiredError(f"no se pudo iniciar sesión de Instagram ({detail})")

    def _session_valid(self, client: Client) -> bool:
        """Cheap authed probe: True if the loaded session still works.

        Uses get_timeline_feed() — the probe instagrapi's own docs recommend for
        session validity (lighter and less flag-prone than account_info).
        """
        try:
            client.get_timeline_feed()
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
        from instagrapi.exceptions import (
            BadPassword,
            ClientThrottledError,
            DirectMessageRequestsDisabled,
            FeedbackRequired,
            LoginRequired,
            PleaseWaitFewMinutes,
            ProxyAddressIsBlocked,
            RateLimitError,
            SentryBlock,
        )

        # No self._budget.spend() here: DM sends are governed by the campaign
        # sender's own rails (per-send delay + daily cap). The scan budget's
        # process-wide cap must NOT leak in and fake an Instagram block.
        try:
            recipient = int(user_pk)
        except (TypeError, ValueError) as exc:
            raise SendRetryableError(f"user_pk inválido: {user_pk!r}") from exc

        client = self._login()
        # instagrapi routes any text containing "http" through the link-preview
        # endpoint (broadcast/link/), which Instagram blocks far harder (403) than
        # plain text. Drop the URL scheme so it goes via broadcast/text/ — IG still
        # auto-links the bare domain, so the recipient gets a clickable link.
        safe_text = re.sub(r"https?://", "", text)
        try:
            client.direct_send(safe_text, user_ids=[recipient])
        except DirectMessageRequestsDisabled as exc:
            # The recipient closed message requests — their setting, not a block
            # on us. Skip this one and keep the campaign going.
            raise RecipientUnavailableError(
                f"@{user_pk} no acepta mensajes nuevos — se saltea"
            ) from exc
        except (BadPassword, ProxyAddressIsBlocked, LoginRequired) as exc:
            # IG rejected the (re)login triggered by the send, not the send itself.
            # Classify IP-block vs expired-session so the UI guides the right fix.
            raise classify_login_error(exc) from exc
        except (
            FeedbackRequired,
            SentryBlock,
            PleaseWaitFewMinutes,
            ClientThrottledError,
            RateLimitError,
        ) as exc:
            # A genuine Instagram push-back on sending — stop and wait.
            raise SendBlockedError(_send_block_message(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — network/timeout: transient, not a block
            raise SendRetryableError(f"envío falló (reintentable): {exc}") from exc

    @_adapts
    def get_friendships(self, user_pks: list[str]) -> dict[str, Friendship]:
        # friendships/show_many only reports who WE follow (no `followed_by`), so
        # to know "te sigue" we read our own followers/following lists and test
        # membership. Heavy + paginated — this is the slow, opt-in enrich step.
        client = self._login()
        self._budget.spend()
        our_id = str(client.user_id)
        # amount=0 fetches the whole graph (correct, but the heaviest call). On a
        # huge account set relationship_fetch_max>0 to trade completeness for far
        # fewer requests. This read is TTL-cached upstream (relationship_cache_hours).
        cap = self._settings.relationship_fetch_max
        followers = {str(pk) for pk in client.user_followers(our_id, amount=cap)}
        following = {str(pk) for pk in client.user_following(our_id, amount=cap)}
        logger.info("read graph: %d followers, %d following", len(followers), len(following))
        # A logged-in account always has some followers/following. Both empty
        # means the read was blocked — refuse rather than overwrite good "te
        # sigue" data with all-False.
        if not followers and not following:
            raise InstagramError("no se pudo leer seguidores/seguidos (bloqueado?)")
        return {
            str(pk): Friendship(following=str(pk) in following, followed_by=str(pk) in followers)
            for pk in set(user_pks)
        }

    @_adapts
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

    @_adapts
    def current_user_pk(self) -> str:
        client = self._login()
        return str(client.user_id)

    @_adapts
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

    @_adapts
    def get_recent_posts(self, limit: int) -> list[Post]:
        client = self._login()
        self._budget.spend()
        medias = client.user_medias(client.user_id, amount=limit)
        return [_to_post(m) for m in medias]

    @_adapts
    def get_likers(self, media_pk: str) -> list[IgUser]:
        client = self._login()
        self._budget.spend()
        return [_to_user(u) for u in client.media_likers(media_pk)]

    @_adapts
    def get_comments(self, media_pk: str) -> list[Comment]:
        client = self._login()
        self._budget.spend()
        comments: list[Comment] = []
        # Cap the fetch: without amount instagrapi pages EVERY comment (hundreds
        # of private-API requests on a viral post). scan_comments_limit is plenty.
        for c in client.media_comments(media_pk, amount=self._settings.scan_comments_limit):
            comments.append(
                Comment(
                    user=_to_user(c.user),
                    text=c.text,
                    created_at=_as_dt(getattr(c, "created_at_utc", None)),
                )
            )
        return comments

    @_adapts
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


def classify_login_error(exc: Exception) -> InstagramError:
    """Turn an instagrapi login/auth failure into a specific domain error so the
    UI can tell an IP block apart from an expired session.

    - IP/proxy on Instagram's blacklist  -> IpBlockedError (a new sessionid won't
      help; change network).
    - challenge / 2FA                    -> ChallengeRequiredError (verify on the
      phone, then repaste).
    - anything else (dead sessionid, bad password) -> LoginRequiredError (paste a
      fresh sessionid).
    """
    from instagrapi.exceptions import (
        ChallengeRequired,
        ProxyAddressIsBlocked,
        TwoFactorRequired,
    )

    s = str(exc).lower()
    ip_markers = ("blacklist", "ip address", "change your ip", "proxy")
    if isinstance(exc, ProxyAddressIsBlocked) or any(k in s for k in ip_markers):
        return IpBlockedError(
            "Instagram marcó tu conexión (IP), no la sesión. Un sessionid nuevo NO "
            "lo arregla. Probá desde otra red (datos del celu / otra wifi) o esperá "
            "unas horas antes de reintentar."
        )
    if isinstance(exc, (ChallengeRequired, TwoFactorRequired)):
        return ChallengeRequiredError(
            "Instagram pidió verificación (challenge). Entrá a la cuenta desde el celu, "
            "confirmá que sos vos, y volvé a pegar el sessionid."
        )
    if "redirect" in s and ("exceeded" in s or "too many" in s):
        # A redirect loop: IG bounces the request instead of authenticating.
        # Usually a mis-copied/expired sessionid; sometimes an account/IP in review.
        return LoginRequiredError(
            "Instagram rebotó la conexión (bucle de redirects). Casi siempre el "
            "sessionid quedó mal copiado o vencido: volvé a copiar el valor COMPLETO "
            "de la cookie 'sessionid', recién sacado del navegador. Si con uno fresco "
            "sigue igual, la cuenta o la IP está en revisión: esperá o probá otra red."
        )
    return LoginRequiredError(
        "La sesión venció o el sessionid es inválido. Pegá un sessionid nuevo del "
        "navegador donde estés logueado a la cuenta."
    )


def _to_instagram_error(exc: Exception) -> InstagramError:
    """Convert a raw instagrapi/requests failure into our InstagramError family.

    The adapter is the boundary: every method must surface an InstagramError so
    use cases map it to a clean Result/HTTP error instead of leaking a 500.
    Our own errors pass through unchanged; login/redirect/challenge/IP get the
    specific, actionable messages from classify_login_error.
    """
    if isinstance(exc, InstagramError):
        return exc
    s = str(exc).lower()
    login_markers = (
        "login_required",
        "login required",
        "not logged in",
        "challenge",
        "redirect",
        "blacklist",
        "ip address",
        "change your ip",
        "two_factor",
        "csrf",
    )
    if any(k in s for k in login_markers):
        return classify_login_error(exc)
    return InstagramError(f"Instagram falló la operación: {exc}")




def _send_block_message(exc: object) -> str:
    """Turn a direct_send failure into a clear, actionable message.

    A 403 / login_required / feedback_required on the broadcast endpoint means
    Instagram action-blocked the account from sending DMs — the only right move
    is to stop and wait, so we say so plainly instead of leaking the raw error.
    """
    s = str(exc).lower()
    if any(
        k in s
        for k in ("login_required", "403", "feedback_required", "spam", "action", "few minutes")
    ):
        return (
            "Instagram frenó el envío de DMs de tu cuenta (action-block). "
            "PARÁ y no reintentes — insistir alarga el bloqueo. Esperá 12-48h sin enviar, "
            "usá la cuenta a mano desde el celu, y reintentá con Máxima cautela "
            "(empezá por los que te siguen)."
        )
    return f"envío rechazado: {exc}"


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
