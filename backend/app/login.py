"""One-time interactive Instagram login.

Run this ONCE from your normal home connection to resolve any verification
(challenge / 2FA) by typing the code, and save the session to disk. After that
the API just reuses the saved session and never logs in from scratch — which is
the single best way to avoid Instagram challenges.

Usage:
    python -m app.login
"""

from __future__ import annotations

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


def main() -> int:
    settings = get_settings()

    if not settings.ig_username or not settings.ig_password:
        print("Faltan IG_USERNAME / IG_PASSWORD en backend/.env", file=sys.stderr)
        return 1

    # Lazy import so this module loads even without instagrapi installed.
    from instagrapi.exceptions import (
        ChallengeRequired,
        LoginRequired,
        TwoFactorRequired,
    )

    client = build_client(settings, _interactive_challenge)

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
        print(
            "\nInstagram sigue pidiendo verificación y no se pudo resolver.\n"
            "Entrá a Instagram desde la app oficial (misma red/wifi), aprobá el\n"
            '"¿Fuiste vos?" y volvé a correr:  python -m app.login',
            file=sys.stderr,
        )
        return 2
    except LoginRequired as exc:
        print(f"\nLogin rechazado: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\nFalló el login: {exc}", file=sys.stderr)
        return 2

    # Validate the session with a lightweight call before trusting it.
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
