"""WebInstagramSource — talks to the same web endpoints the browser uses.

instagrapi's *mobile* private API rejects a browser `sessionid` (403). But the
`www.instagram.com/api/v1/...` endpoints the web app calls DO accept it, plus
the `x-ig-app-id` header. This source replays exactly those calls, so it works
with a session copied from a logged-in browser and dodges the mobile login /
checkpoint entirely.

Parsing is split into pure functions (testable without network); the class only
does HTTP + rate limiting + error mapping.
"""

from __future__ import annotations

import contextlib
import logging
import random
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import requests

from app.domain.entities import Comment, DmMessage, DmThread, IgUser, Post
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    LoginRequiredError,
    PostNotFoundError,
    RateLimitedError,
)

logger = logging.getLogger(__name__)

_WEB_APP_ID = "936619743392459"  # public Instagram web app id
_BASE = "https://www.instagram.com/api/v1"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
_SHORTCODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_SHORTCODE_RE = re.compile(r"/(?:p|reel|reels|tv)/([^/?#]+)")


# ------------------------------------------------------------------ pure helpers


def extract_shortcode(url: str) -> str | None:
    m = _SHORTCODE_RE.search(url)
    return m.group(1) if m else None


def shortcode_to_pk(shortcode: str) -> int:
    """Instagram shortcodes are base64 of the numeric media pk."""
    pk = 0
    for char in shortcode:
        pk = pk * 64 + _SHORTCODE_ALPHABET.index(char)
    return pk


def pk_from_sessionid(sessionid: str) -> str:
    """The sessionid is `<user_pk>:<...>` (URL-encoded colons as %3A)."""
    return unquote(sessionid).split(":", 1)[0]


def _ts(value: Any) -> datetime | None:
    """Instagram timestamps are seconds (sometimes microseconds) since epoch."""
    if not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    if seconds > 1e12:  # microseconds
        seconds /= 1e6
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _to_user(node: dict[str, Any]) -> IgUser:
    return IgUser(
        pk=str(node.get("pk") or node.get("id") or node.get("pk_id") or ""),
        username=str(node.get("username", "")),
        full_name=str(node.get("full_name", "") or ""),
        profile_pic_url=node.get("profile_pic_url"),
        is_private=bool(node.get("is_private", False)),
    )


def parse_media_info(data: dict[str, Any]) -> Post:
    items = data.get("items") or []
    if not items:
        raise PostNotFoundError("empty media info")
    item = items[0]
    code = str(item.get("code", ""))
    caption = item.get("caption") or {}
    return Post(
        media_pk=str(item.get("pk", "")),
        shortcode=code,
        url=f"https://instagram.com/p/{code}/",
        caption=str(caption.get("text", "") if isinstance(caption, dict) else ""),
        taken_at=_ts(item.get("taken_at")),
    )


def parse_comments(data: dict[str, Any]) -> list[Comment]:
    out: list[Comment] = []
    for c in data.get("comments") or []:
        user = c.get("user")
        if not isinstance(user, dict):
            continue
        out.append(
            Comment(
                user=_to_user(user),
                text=str(c.get("text", "")),
                created_at=_ts(c.get("created_at")),
            )
        )
    return out


def parse_likers(data: dict[str, Any]) -> list[IgUser]:
    return [_to_user(u) for u in data.get("users") or [] if isinstance(u, dict)]


def parse_inbox(data: dict[str, Any], our_pk: str) -> list[DmThread]:
    """Build DM threads from a direct_v2/inbox payload.

    Only 1:1 threads map to a user (group threads are skipped). Direction is
    derived from the message window returned by the inbox — enough for the
    semáforo, though a reply older than the window could be missed.
    """
    threads: list[DmThread] = []
    inbox = data.get("inbox") or {}
    for thread in inbox.get("threads") or []:
        users = [u for u in thread.get("users") or [] if isinstance(u, dict)]
        if len(users) != 1:
            continue  # group or self thread
        other = _to_user(users[0])
        items = thread.get("items") or []
        messages = [
            DmMessage(user_pk=str(i.get("user_id", "")), created_at=_ts(i.get("timestamp")))
            for i in items
            if isinstance(i, dict)
        ]
        last = thread.get("last_permanent_item") or {}
        last_at = _ts(last.get("timestamp")) if isinstance(last, dict) else None
        threads.append(
            DmThread(
                thread_id=str(thread.get("thread_id", "")),
                user=other,
                messages=messages,
                last_message_at=last_at or (messages[0].created_at if messages else None),
            )
        )
    return threads


# ------------------------------------------------------------------ the source


class _RequestBudget:
    def __init__(self, min_delay: float, max_delay: float, max_requests: int) -> None:
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._max_requests = max_requests
        self._count = 0

    def spend(self) -> None:
        self._count += 1
        if self._count > self._max_requests:
            raise RateLimitedError(
                f"request cap reached ({self._max_requests}); stopping to stay safe"
            )
        time.sleep(random.uniform(self._min_delay, self._max_delay))


class WebInstagramSource:
    """InstagramSource backed by the web (browser) API, authed via sessionid."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._budget = _RequestBudget(
            settings.scan_min_delay_seconds,
            settings.scan_max_delay_seconds,
            settings.scan_max_requests,
        )
        self._session: requests.Session | None = None

    # -- session ---------------------------------------------------------

    def _http(self) -> requests.Session:
        if self._session is not None:
            return self._session
        sessionid = self._settings.ig_sessionid.strip()
        if not sessionid:
            raise LoginRequiredError("IG_SESSIONID vacío. Pegá la cookie del navegador.")

        s = requests.Session()
        if self._settings.ig_proxy:
            s.proxies.update({"http": self._settings.ig_proxy, "https": self._settings.ig_proxy})
        s.headers.update(
            {
                "User-Agent": _UA,
                "X-IG-App-ID": _WEB_APP_ID,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://www.instagram.com/",
                "Accept": "*/*",
            }
        )
        s.cookies.set("sessionid", sessionid, domain=".instagram.com")
        # Prime csrftoken (the web API needs the X-CSRFToken header).
        with contextlib.suppress(requests.RequestException):
            s.get("https://www.instagram.com/", timeout=15)
        csrf = s.cookies.get("csrftoken")
        if csrf:
            s.headers["X-CSRFToken"] = csrf
        self._session = s
        return s

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._budget.spend()
        session = self._http()
        try:
            resp = session.get(f"{_BASE}{path}", params=params, timeout=20)
        except requests.RequestException as exc:
            raise LoginRequiredError(f"network error: {exc}") from exc

        if resp.status_code in (401, 403):
            raise LoginRequiredError(
                "Instagram rechazó la sesión (login_required). El sessionid venció "
                "o no tiene permiso; sacá uno nuevo del navegador."
            )
        if resp.status_code == 404:
            raise PostNotFoundError(path)
        if resp.status_code == 429:
            raise RateLimitedError("Instagram pidió esperar (429). Bajá el ritmo.")

        try:
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise LoginRequiredError("respuesta no-JSON (probable pantalla de login)") from exc

        if data.get("message") == "checkpoint_required" or data.get("require_login"):
            raise ChallengeRequiredError("Instagram pidió verificación (checkpoint).")
        return data

    # -- port methods ----------------------------------------------------

    def current_user_pk(self) -> str:
        return pk_from_sessionid(self._settings.ig_sessionid)

    def get_post(self, url: str) -> Post:
        shortcode = extract_shortcode(url)
        if shortcode is None:
            raise PostNotFoundError(url)
        pk = shortcode_to_pk(shortcode)
        return parse_media_info(self._get(f"/media/{pk}/info/"))

    def get_recent_posts(self, limit: int) -> list[Post]:
        pk = self.current_user_pk()
        data = self._get(f"/feed/user/{pk}/", {"count": limit})
        return [parse_media_info({"items": [item]}) for item in data.get("items") or []][:limit]

    def get_likers(self, media_pk: str) -> list[IgUser]:
        return parse_likers(self._get(f"/media/{media_pk}/likers/"))

    def get_comments(self, media_pk: str) -> list[Comment]:
        comments: list[Comment] = []
        params: dict[str, Any] = {"can_support_threading": "true", "permalink_enabled": "false"}
        for _ in range(10):  # follow pagination, bounded
            data = self._get(f"/media/{media_pk}/comments/", params)
            comments.extend(parse_comments(data))
            next_min_id = data.get("next_min_id")
            if not next_min_id:
                break
            params["min_id"] = next_min_id
        return comments

    def get_dm_threads(self) -> list[DmThread]:
        our_pk = self.current_user_pk()
        threads: list[DmThread] = []
        params: dict[str, Any] = {
            "visual_message_return_type": "unseen",
            "thread_message_limit": 20,
            "persistentBadging": "true",
            "limit": 20,
        }
        for _ in range(20):  # paginate inbox, bounded
            data = self._get("/direct_v2/inbox/", params)
            threads.extend(parse_inbox(data, our_pk))
            inbox = data.get("inbox") or {}
            if not inbox.get("has_older"):
                break
            cursor = inbox.get("oldest_cursor")
            if not cursor:
                break
            params["cursor"] = cursor
        return threads
