"""Session/login for the instagrapi adapter: the one logged-in client.

Good-behaviour rule: log in once and reuse the session (saved to session.json,
which also keeps a stable device). Every login runs inside an IgGuard
operation: a failure that reached Instagram opens the login breaker, a success
closes it. instagrapi is imported lazily to keep it optional at import time.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.domain.errors import (
    ChallengeRequiredError,
    InstagramError,
    IpBlockedError,
    LoginRequiredError,
)
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.error_mapping import classify_login_error, is_dead_session
from app.infrastructure.instagram.guard import IgGuard
from app.infrastructure.instagram.session import build_client

if TYPE_CHECKING:
    from instagrapi import Client

logger = logging.getLogger(__name__)


class IgLogin:
    """Owns the instagrapi client: layered login, sessionid connect, and
    dropping a dead session so the next operation logs in from scratch."""

    def __init__(self, settings: Settings, guard: IgGuard) -> None:
        self._settings = settings
        self._guard = guard
        self.client: Client | None = None

    def cached_user_pk(self) -> str | None:
        """Our pk if a logged-in client is in memory — never touches the network."""
        return str(self.client.user_id) if self.client is not None else None

    def forget_if_dead(self, err: InstagramError) -> None:
        """A dead or challenged session leaves the client unusable."""
        if is_dead_session(err):
            self.client = None

    def client_or_login(self) -> Client:
        """The logged-in client, authenticating with the cheapest/lowest-risk path first.

        1. A saved session.json (reuses the device; no network login) — validated.
        2. IG_SESSIONID from a real browser (low ban risk; recommended bootstrap).
        3. username/password (+ TOTP) — auto-renews when the session finally dies.

        Every success is persisted to session.json so the next start reuses it and
        the account keeps a stable device. This is what makes the login survive
        restarts and self-heal on expiry.

        Always runs inside a guard operation: a failure that reached Instagram
        opens the login breaker, a success closes it.
        """
        if self.client is not None:
            return self.client

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
            return self._logged_in(client)

        # 2. Bootstrap from a browser sessionid.
        sessionid = self._settings.ig_sessionid.strip()
        if sessionid:
            self._guard.note_sessionid(sessionid)
            try:
                client.login_by_sessionid(sessionid)
                self._persist(client, session_path)
                return self._logged_in(client)
            except (ChallengeRequired, LoginRequired) as exc:
                errors.append(f"sessionid vencido/rechazado: {exc}")
            except Exception as exc:  # noqa: BLE001 — surfaced below as handled
                if isinstance(domain := classify_login_error(exc), IpBlockedError):
                    raise domain from exc  # a flagged IP breaks every path — stop now
                errors.append(f"sessionid: {exc}")

        # 3. username/password (auto-renews when the session dies).
        if self._settings.has_password_login:
            try:
                verification_code = self._totp_code(client)
                client.login(
                    self._settings.ig_username,
                    self._settings.ig_password,
                    verification_code=verification_code,
                )
                self._persist(client, session_path)
                return self._logged_in(client)
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

    def connect_sessionid(self, sessionid: str) -> str:
        """Explicit user action: adopt a sessionid pasted from a real browser.

        Validated with one cheap probe and persisted to session.json. A sessionid
        other than the one whose login failed may skip an open login breaker once
        (never an IP block or a cooldown). On failure the current client, if
        any, is kept.
        """
        with self._guard.operation(fresh_sessionid=sessionid):
            client = build_client(self._settings, self._challenge_code_handler)
            try:
                client.login_by_sessionid(sessionid)
                # login_by_sessionid only sets the cookie; probe once so a blocked
                # account (403) or a dead cookie surfaces here as a clear message.
                client.account_info()
            except InstagramError:
                raise  # already classified (challenge handler / guard rails)
            except Exception as exc:  # noqa: BLE001 — classify 403/IP-block/expired session
                raise classify_login_error(exc) from exc
            self._persist(client, Path(self._settings.ig_session_file))
            return str(self._logged_in(client).user_id)

    def _logged_in(self, client: Client) -> Client:
        self.client = client
        self._guard.login_ok()
        return client

    def _session_valid(self, client: Client) -> bool:
        """Cheap authed probe: True if the loaded session still works.

        Uses account_info() (/accounts/current_user/) on purpose: it is gentler
        than the timeline feed, which IG heavily monitors and 403s on the
        slightest throttle/flag even when the session is fine for scraping. We'd
        rather keep a usable-but-throttled session connected than mark it dead.
        """
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
                "IG_2FA_SECRET no es una semilla TOTP válida (base32); "
                "dejalo vacío si la cuenta no tiene 2FA."
            ) from exc

    def _challenge_code_handler(self, username: str, choice: Any) -> str:
        # We can't prompt interactively from the API. Surface it as a handled
        # error so the app informs the user instead of crashing.
        raise ChallengeRequiredError(
            f"Instagram pidió un código de verificación para {username}: "
            "confirmá que sos vos desde el celu y volvé a conectar."
        )
