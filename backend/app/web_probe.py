"""Diagnostic probe: hit several Instagram web endpoints and report which ones
return JSON vs the HTML app shell.

Usage:
    python -m app.web_probe <post_url>

Helps pinpoint whether the sessionid is accepted and which endpoints work,
before wiring them into the app.
"""

from __future__ import annotations

import logging
import sys

from app.infrastructure.config.settings import get_settings
from app.infrastructure.instagram.web_source import (
    WebInstagramSource,
    extract_shortcode,
    shortcode_to_pk,
)

WWW = "https://www.instagram.com/api/v1"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    if not settings.ig_sessionid.strip():
        print("Falta IG_SESSIONID en backend/.env", file=sys.stderr)
        return 1

    source = WebInstagramSource(settings)
    pk = source.current_user_pk()

    targets: list[tuple[str, str, dict[str, str] | None]] = [
        ("profile (canary)", f"{WWW}/users/web_profile_info/", {"username": settings.ig_username}),
        ("my info", f"{WWW}/users/{pk}/info/", None),
        ("dm inbox", f"{WWW}/direct_v2/inbox/", {"limit": "5"}),
    ]
    if len(sys.argv) > 1:
        shortcode = extract_shortcode(sys.argv[1])
        if shortcode:
            media_pk = shortcode_to_pk(shortcode)
            targets.append(("media info", f"{WWW}/media/{media_pk}/info/", None))
            targets.append(("comments", f"{WWW}/media/{media_pk}/comments/", None))
            targets.append(("likers", f"{WWW}/media/{media_pk}/likers/", None))

    print(f"\npk={pk}\n")
    for name, url, params in targets:
        try:
            status, ctype, snippet = source.probe(url, params)
        except Exception as exc:  # noqa: BLE001 — diagnostic, report anything
            print(f"{name:16} ERROR {exc}")
            continue
        kind = "JSON" if "json" in ctype else "HTML/other"
        print(f"{name:16} {status} {kind:10} {ctype}")
        if kind != "JSON":
            print(f"                 ↳ {snippet[:100]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
