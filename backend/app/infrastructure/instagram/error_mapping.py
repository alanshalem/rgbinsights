"""instagrapi/network failures -> the domain InstagramError family.

The adapter boundary: every raw exception from instagrapi or requests is turned
into a domain error here, with the specific, actionable (Spanish) message the
UI shows. instagrapi is imported lazily to keep it optional at import time.
"""

from __future__ import annotations

from app.domain.errors import (
    ChallengeRequiredError,
    InstagramError,
    IpBlockedError,
    LoginRequiredError,
)


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
    # A checkpoint (often a 400 "checkpoint_required" with no typed exception) is a
    # challenge too: the account must be verified before anything else works.
    if isinstance(exc, (ChallengeRequired, TwoFactorRequired)) or any(
        k in s for k in ("challenge", "checkpoint")
    ):
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
    if "403" in s or "forbidden" in s or "feedback_required" in s:
        # Authenticated but IG refuses every call — the account/IP is blocked or
        # under review. The sessionid is likely fine; retrying makes it worse.
        return LoginRequiredError(
            "El sessionid está bien, pero Instagram rechaza las llamadas de la cuenta "
            "(403). No es el código: la cuenta o la IP está bloqueada / en revisión. "
            "Esperá 12-48h sin automatizar, usá la cuenta a mano desde el celu, y "
            "probá desde otra red. No reintentes seguido — lo alarga."
        )
    return LoginRequiredError(
        "La sesión venció o el sessionid es inválido. Pegá un sessionid nuevo del "
        "navegador donde estés logueado a la cuenta."
    )


def to_instagram_error(exc: Exception) -> InstagramError:
    """Convert a raw instagrapi/requests failure into our InstagramError family.

    The adapter is the boundary: every method must surface an InstagramError so
    use cases map it to a clean Result/HTTP error instead of leaking a 500.
    Our own errors pass through unchanged; login/redirect/challenge/IP get the
    specific, actionable messages from classify_login_error.
    """
    if isinstance(exc, InstagramError):
        return exc
    if is_session_error(exc):
        return classify_login_error(exc)
    return InstagramError(f"Instagram falló la operación: {exc}")


_LOGIN_MARKERS = (
    "login_required",
    "login required",
    "not logged in",
    "challenge",
    "checkpoint",
    "redirect",
    "blacklist",
    "ip address",
    "change your ip",
    "two_factor",
    "csrf",
)


def is_session_error(exc: Exception) -> bool:
    """True if the failure is about the session/login/IP, not the request itself:
    a typed instagrapi session error, or a generic one whose message says so."""
    from instagrapi.exceptions import ProxyAddressIsBlocked

    if isinstance(exc, (*session_error_types(), ProxyAddressIsBlocked)):
        return True
    s = str(exc).lower()
    return any(k in s for k in _LOGIN_MARKERS)


def session_error_types() -> tuple[type[Exception], ...]:
    """instagrapi exceptions that mean the session/login is unusable."""
    from instagrapi.exceptions import (
        BadPassword,
        ChallengeRequired,
        ClientLoginRequired,
        LoginRequired,
        ReloginAttemptExceeded,
        TwoFactorRequired,
    )

    return (
        BadPassword,
        ChallengeRequired,
        ClientLoginRequired,
        LoginRequired,
        ReloginAttemptExceeded,
        TwoFactorRequired,
    )


def is_dead_session(err: InstagramError) -> bool:
    """The client's cookies are gone (expired or challenged session): log in
    from scratch next time. An IP block keeps the client — the session is fine."""
    return isinstance(err, (LoginRequiredError, ChallengeRequiredError))


def send_block_message(exc: object) -> str:
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
