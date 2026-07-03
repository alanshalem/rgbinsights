"""One-time browser login for the Playwright source.

Opens a *plain* Chrome (no automation flags, so Instagram's reCAPTCHA behaves
normally) at the login page. You log in by hand; the session is saved in the
dedicated profile dir. We only attach over CDP *after* you're in, just to
confirm and read the account id — the login itself never sees automation.

Usage:
    python -m app.login_browser
"""

from __future__ import annotations

import sys

from app.infrastructure.config.settings import get_settings
from app.infrastructure.instagram.chrome_cdp import (
    cdp_url,
    find_chrome,
    launch_chrome,
    wait_for_cdp,
)

LOGIN_URL = "https://www.instagram.com/accounts/login/"


def main() -> int:
    settings = get_settings()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Falta Playwright. Instalá:\n"
            "  pip install playwright && python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    try:
        chrome = find_chrome(settings.ig_chrome_path)
    except FileNotFoundError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1

    port = settings.ig_cdp_port
    print("Abriendo Chrome… logueate con la cuenta en la ventana que se abre.")
    proc = launch_chrome(chrome, settings.ig_browser_dir, port, headless=False, start_url=LOGIN_URL)

    try:
        input(
            "\nCuando estés adentro (feed cargado, sin recaptcha), volvé acá\n"
            "y apretá Enter para guardar la sesión…"
        )
        wait_for_cdp(port)
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(cdp_url(port))
            context = browser.contexts[0] if browser.contexts else None
            cookies = context.cookies() if context else []
            pk = next(
                (c.get("value") for c in cookies if c.get("name") == "ds_user_id"),
                None,
            )
            browser.close()
    finally:
        proc.terminate()

    if not pk:
        print("\nNo detecté sesión (falta ds_user_id). ¿Terminaste de loguearte?", file=sys.stderr)
        return 2
    print(f"\n✔ Sesión del navegador guardada (pk {pk}) en {settings.ig_browser_dir}.")
    print("Ya podés correr:  python -m app.web_check <url_de_un_post>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
