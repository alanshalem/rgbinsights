"""Session for the instagrapi adapter: the one logged-in client.

The only way in is a sessionid pasted in the app (chip IG -> "Pegá tu sesión",
L24): it is validated once and saved to session.json (which also keeps a stable
device), then reused across restarts. There is no username/password login and
no automatic relogin: a dead session just surfaces as LoginRequiredError and
waits for a new paste. Every attempt runs inside an IgGuard operation: a
failure that reached Instagram opens the login breaker, a success closes it.
instagrapi is imported lazily to keep it optional at import time.
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
from app.infrastructure.instagram.error_mapping import (
    DEAD_SESSION,
    classify_login_error,
    is_dead_session,
)
from app.infrastructure.instagram.guard import IgGuard
from app.infrastructure.instagram.session import build_client

if TYPE_CHECKING:
    from instagrapi import Client

logger = logging.getLogger(__name__)

NO_SESSION = (
    "No hay una sesión de Instagram guardada: pegá tu sessionid desde el chip IG "
    "(arriba a la derecha)."
)


class IgLogin:
    """Owns the instagrapi client: the saved session, the sessionid paste, and
    dropping a dead session (never replaced by a login: a new paste is needed)."""

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
        """The logged-in client: the one in memory, else the saved session.json
        (loaded by build_client, reuses the device) validated with one cheap probe.

        No saved session -> LoginRequiredError without any request. Never a
        login: a dead session needs a new paste. Always runs inside a guard
        operation: a probe that fails opens the login breaker (15 min -> 1 h ->
        6 h), so a dead session.json is re-checked at most that often.
        """
        if self.client is not None:
            return self.client
        session_path = Path(self._settings.ig_session_file)
        if not session_path.exists():
            raise LoginRequiredError(NO_SESSION)
        client = build_client(self._settings, self._challenge_code_handler)
        self._probe(client)
        logger.info("reusing saved IG session")
        return self._logged_in(client)

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
                raise classify_login_error(exc, pasted=True) from exc
            self._persist(client, Path(self._settings.ig_session_file))
            return str(self._logged_in(client).user_id)

    def _logged_in(self, client: Client) -> Client:
        self.client = client
        self._guard.login_ok()
        return client

    def _probe(self, client: Client) -> None:
        """Cheap authed probe of the saved session.

        Uses account_info() (/accounts/current_user/) on purpose: it is gentler
        than the timeline feed, which IG heavily monitors and 403s on the
        slightest throttle/flag even when the session is fine for scraping. An IP
        block or a challenge keeps its own message; anything else means the
        session is dead.
        """
        try:
            client.account_info()
        except InstagramError:
            raise  # our own rails (cooldown, budget) or the challenge handler
        except Exception as exc:  # noqa: BLE001 — classified below
            domain = classify_login_error(exc)
            if isinstance(domain, IpBlockedError | ChallengeRequiredError):
                raise domain from exc
            raise LoginRequiredError(DEAD_SESSION) from exc

    def _persist(self, client: Client, session_path: Path) -> None:
        try:
            client.dump_settings(session_path)
            logger.info("saved IG session to %s", session_path)
        except Exception:  # noqa: BLE001 — persistence is best-effort
            logger.warning("could not save IG session", exc_info=True)

    def _challenge_code_handler(self, username: str, choice: Any) -> str:
        # We can't prompt interactively from the API. Surface it as a handled
        # error so the app informs the user instead of crashing.
        raise ChallengeRequiredError(
            f"Instagram pidió un código de verificación para {username}: "
            "confirmá que sos vos desde el celu y volvé a conectar."
        )
