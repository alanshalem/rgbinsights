"""Quick check that the web sessionid works.

Usage:
    python -m app.web_check                       # checks identity + DM inbox
    python -m app.web_check <post_url>            # also scans one post

Prints counts so you can confirm the browser session grants access before
running the full app.
"""

from __future__ import annotations

import logging
import sys

from app.infrastructure.config.settings import get_settings
from app.infrastructure.instagram.errors import InstagramError
from app.infrastructure.instagram.web_source import WebInstagramSource


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    if not settings.ig_sessionid.strip():
        print("Falta IG_SESSIONID en backend/.env", file=sys.stderr)
        return 1

    source = WebInstagramSource(settings)
    try:
        pk = source.current_user_pk()
        print(f"Usuario (pk desde sessionid): {pk}")

        threads = source.get_dm_threads()
        print(f"Hilos de DM leídos: {len(threads)}")
        for t in threads[:5]:
            out = any(m.user_pk == pk for m in t.messages)
            inc = any(m.user_pk != pk for m in t.messages)
            print(f"  @{t.user.username}: saliente={out} entrante={inc}")

        if len(sys.argv) > 1:
            url = sys.argv[1]
            post = source.get_post(url)
            comments = source.get_comments(post.media_pk)
            likers = source.get_likers(post.media_pk)
            print(f"\nPost {post.shortcode}: {len(comments)} comentarios, {len(likers)} likes")
    except InstagramError as exc:
        print(f"\nFalló: {exc}", file=sys.stderr)
        return 2

    print("\n✔ La sesión web funciona.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
