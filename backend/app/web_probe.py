"""Diagnostic probe: hit Instagram web endpoints (with referer/host variants)
and report which return JSON vs the HTML app shell.

Usage:
    python -m app.web_probe <post_url>
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
IAPI = "https://i.instagram.com/api/v1"

# name, url, params, extra headers (referer override)
Target = tuple[str, str, "dict[str, str] | None", "dict[str, str] | None"]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    if not settings.ig_sessionid.strip():
        print("Falta IG_SESSIONID en backend/.env", file=sys.stderr)
        return 1

    source = WebInstagramSource(settings)
    pk = source.current_user_pk()

    direct_ref = {"Referer": "https://www.instagram.com/direct/inbox/"}

    targets: list[Target] = [
        ("profile", f"{WWW}/users/web_profile_info/", {"username": settings.ig_username}, None),
        ("inbox", f"{WWW}/direct_v2/inbox/", {"limit": "5"}, None),
        ("inbox+referer", f"{WWW}/direct_v2/inbox/", {"limit": "5"}, direct_ref),
        ("inbox i.host", f"{IAPI}/direct_v2/inbox/", {"limit": "5"}, direct_ref),
    ]

    if len(sys.argv) > 1:
        shortcode = extract_shortcode(sys.argv[1])
        if shortcode:
            media_pk = shortcode_to_pk(shortcode)
            post_ref = {"Referer": f"https://www.instagram.com/p/{shortcode}/"}
            targets += [
                ("media www", f"{WWW}/media/{media_pk}/info/", None, post_ref),
                ("media i.host", f"{IAPI}/media/{media_pk}/info/", None, post_ref),
                ("comments+ref", f"{WWW}/media/{media_pk}/comments/", None, post_ref),
                ("likers+ref", f"{WWW}/media/{media_pk}/likers/", None, post_ref),
                (
                    "permalink __a=1",
                    f"https://www.instagram.com/p/{shortcode}/",
                    {"__a": "1", "__d": "dis"},
                    post_ref,
                ),
            ]

    print(f"\npk={pk}\n")
    for name, url, params, headers in targets:
        try:
            status, ctype, snippet = source.probe(url, params, headers)
        except Exception as exc:  # noqa: BLE001 — diagnostic, report anything
            print(f"{name:16} ERROR {exc}")
            continue
        kind = "JSON" if "json" in ctype else "HTML/other"
        print(f"{name:16} {status} {kind:10} {ctype}")
        if kind != "JSON":
            print(f"                 ↳ {snippet[:90]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
