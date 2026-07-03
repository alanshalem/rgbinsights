"""One-time browser login for the Playwright source.

Opens a real Chromium window with a persistent profile. You log in by hand
(resolving any checkpoint like a human); the session is saved to disk so the
app can then drive the browser headless.

Usage:
    python -m app.login_browser
"""

from __future__ import annotations

import sys

from app.infrastructure.config.settings import get_settings


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

    print("Abriendo Chromium… logueate con la cuenta en la ventana.")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            settings.ig_browser_dir,
            headless=False,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")

        input(
            "\nCuando estés adentro (feed cargado, sin checkpoint), volvé acá\n"
            "y apretá Enter para guardar la sesión…"
        )

        # Confirm we ended up logged in by checking the ds_user_id cookie.
        pk = next(
            (c.get("value") for c in context.cookies() if c.get("name") == "ds_user_id"),
            None,
        )
        context.close()

    if not pk:
        print("\nNo detecté sesión (falta ds_user_id). ¿Terminaste de loguearte?", file=sys.stderr)
        return 2
    print(f"\n✔ Sesión del navegador guardada (pk {pk}) en {settings.ig_browser_dir}.")
    print("Poné IG_SOURCE=playwright en .env y levantá la app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
