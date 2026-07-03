"""One-time interactive Instagram login.

Run this ONCE from your normal home connection to resolve any verification
(challenge / 2FA) by typing the code, and save the session to disk. After that
the API just reuses the saved session and never logs in from scratch — which is
the single best way to avoid Instagram challenges.

Usage:
    python -m app.login
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.infrastructure.config.settings import get_settings
from app.infrastructure.instagram.session import build_client

logging.basicConfig(level=logging.WARNING)


def _interactive_challenge(username: str, choice: Any) -> str:
    print(f"\nInstagram pidió verificación para @{username}.")
    print("Te tiene que haber llegado un código por email o SMS.")
    return input("Ingresá el código de verificación: ").strip()


def _dump_challenge(client: Any) -> None:
    """Print the raw challenge payload so we can see WHAT Instagram is asking."""
    detail = getattr(client, "last_json", None)
    if not detail:
        return
    print("\n--- detalle del challenge (copiámelo si necesitás ayuda) ---", file=sys.stderr)
    try:
        print(json.dumps(detail, indent=2, ensure_ascii=False)[:2000], file=sys.stderr)
    except (TypeError, ValueError):
        print(str(detail)[:2000], file=sys.stderr)
    url = ""
    if isinstance(detail, dict):
        challenge = detail.get("challenge")
        if isinstance(challenge, dict):
            url = str(challenge.get("url", ""))
    if url:
        print(f"\nAbrí este link en el navegador (logueado con la cuenta): {url}", file=sys.stderr)


def main() -> int:
    settings = get_settings()

    # Lazy import so this module loads even without instagrapi installed.
    from instagrapi.exceptions import (
        ChallengeRequired,
        LoginRequired,
        TwoFactorRequired,
    )

    client = build_client(settings, _interactive_challenge)
    sessionid = settings.ig_sessionid.strip()

    if sessionid:
        # Preferred path: reuse a real browser session. No login, no challenge.
        print("Usando IG_SESSIONID (sesión del navegador) …")
        try:
            client.login_by_sessionid(sessionid)
        except Exception as exc:
            print(
                f"\nEl sessionid no funcionó ({exc}).\n"
                "Sacá uno nuevo: logueate en instagram.com en el navegador, "
                "DevTools (F12) -> Application -> Cookies -> copiá el valor de "
                "'sessionid' y pegalo en IG_SESSIONID en backend/.env",
                file=sys.stderr,
            )
            return 2
        return _finish(client, settings)

    if not settings.ig_username or not settings.ig_password:
        print("Faltan IG_USERNAME / IG_PASSWORD en backend/.env", file=sys.stderr)
        return 1

    print(f"Logueando como @{settings.ig_username} …")
    try:
        code = ""
        secret = settings.ig_2fa_secret.strip()
        if secret:
            code = str(client.totp_generate_code(secret))
        client.login(settings.ig_username, settings.ig_password, verification_code=code)
    except TwoFactorRequired:
        # 2FA app code (no seed configured): ask for the current 6-digit code.
        code = input("Código 2FA de tu app de autenticación (6 dígitos): ").strip()
        client.login(settings.ig_username, settings.ig_password, verification_code=code)
    except ChallengeRequired:
        _dump_challenge(client)
        print(
            "\nInstagram pidió verificación y no llegó al paso de código.\n"
            "1) Abrí Instagram en la app/navegador con la cuenta (misma red).\n"
            '2) Aprobá el "¿Fuiste vos?" / resolvé el checkpoint que aparezca.\n'
            "3) Volvé a correr:  .venv\\Scripts\\python.exe -m app.login",
            file=sys.stderr,
        )
        return 2
    except LoginRequired as exc:
        _dump_challenge(client)
        print(f"\nLogin rechazado: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        _dump_challenge(client)
        print(f"\nFalló el login: {exc}", file=sys.stderr)
        return 2

    return _finish(client, settings)


def _finish(client: Any, settings: Any) -> int:
    """Validate the session with a lightweight call, then persist it."""
    try:
        client.get_timeline_feed()
    except Exception as exc:
        print(f"\nLa sesión no quedó válida: {exc}", file=sys.stderr)
        return 2

    client.dump_settings(settings.ig_session_file)
    print(
        f"\n✔ Sesión guardada en {settings.ig_session_file}.\n"
        "Ya podés levantar la app: la API reusa esta sesión y no vuelve a loguear."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
