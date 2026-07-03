"""Quick check that the configured source works (identity + DMs + one post).

Usage:
    python -m app.web_check                       # checks identity + DM inbox
    python -m app.web_check <post_url>            # also probes post endpoints

Each post endpoint is tried independently so one failure doesn't hide the rest.
"""

from __future__ import annotations

import logging
import sys

from app.infrastructure.config.settings import get_settings
from app.infrastructure.instagram.factory import build_source
from app.infrastructure.instagram.web_source import extract_shortcode, shortcode_to_pk


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()

    source = build_source(settings)
    print(f"Fuente: {settings.resolved_source()}")

    try:
        pk = source.current_user_pk()
        print(f"Usuario (pk): {pk}")
    except Exception as exc:  # noqa: BLE001 — surface any auth failure
        print(f"\nNo hay sesión: {exc}", file=sys.stderr)
        return 2

    try:
        threads = source.get_dm_threads()
        print(f"Hilos de DM: {len(threads)}")
        for t in threads[:5]:
            out = any(m.user_pk == pk for m in t.messages)
            inc = any(m.user_pk != pk for m in t.messages)
            print(f"  @{t.user.username}: saliente={out} entrante={inc}")
    except Exception as exc:  # noqa: BLE001
        print(f"DMs FALLARON: {exc}")

    if len(sys.argv) > 1:
        url = sys.argv[1]
        shortcode = extract_shortcode(url)
        media_pk = str(shortcode_to_pk(shortcode)) if shortcode else ""
        print(f"\nPost {shortcode} (pk {media_pk}):")
        checks = [
            ("info", lambda: source.get_post(url)),
            ("comentarios", lambda: source.get_comments(media_pk)),
            ("likers", lambda: source.get_likers(media_pk)),
        ]
        for name, fn in checks:
            try:
                result = fn()
                count = len(result) if isinstance(result, list) else 1
                print(f"  {name}: OK ({count})")
            except Exception as exc:  # noqa: BLE001 — report each independently
                print(f"  {name}: FALLO — {exc}")

    print("\nListo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
