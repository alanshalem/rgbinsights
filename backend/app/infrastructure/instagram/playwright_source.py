"""PlaywrightInstagramSource — drives a real logged-in browser.

The pure-`requests` web source can only reach `/users/*`; Instagram serves
media/comments/likers/DMs only to its in-browser SPA (dynamic tokens). So here
we run a headless Chromium with a *persistent* profile (logged in once, by
hand) and make the page itself call `fetch('/api/v1/...')`. Inside the real
origin those calls return JSON — exactly what the app fetches — with none of
the tokens to replicate.

All Playwright calls run on a single dedicated worker thread (Playwright's sync
API is thread-affine), so this is safe under FastAPI's threadpool.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from app.domain.entities import Comment, DmThread, Friendship, IgUser, Post, ProfileInfo
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.chrome_cdp import (
    cdp_url,
    find_chrome,
    is_cdp_up,
    launch_chrome,
    wait_for_cdp,
)
from app.infrastructure.instagram.errors import (
    ChallengeRequiredError,
    InstagramError,
    LoginRequiredError,
    PostNotFoundError,
    SendBlockedError,
)
from app.infrastructure.instagram.throttle import RequestBudget
from app.infrastructure.instagram.web_source import (
    extract_shortcode,
    parse_comments,
    parse_inbox,
    parse_likers,
    parse_media_info,
    shortcode_to_pk,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)

_WEB_APP_ID = "936619743392459"
_HOME = "https://www.instagram.com/"

# Job = a function to run on the browser thread with the live Page.
_Job = Callable[["Page"], Any]


def _safe_terminate(proc: Any) -> None:
    with contextlib.suppress(Exception):  # best-effort cleanup
        proc.terminate()


class _BrowserWorker:
    """Owns the browser on one thread; other threads submit jobs and wait.

    Starts a plain Chrome (the login profile) and *attaches* over CDP — never
    launching through Playwright, so the session stays undetectable.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._queue: queue.Queue[tuple[_Job, Future[Any]] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, job: _Job) -> Any:
        self._ensure_started()
        fut: Future[Any] = Future()
        self._queue.put((job, fut))
        return fut.result()

    def stop(self) -> None:
        """Break the loop, close the browser and kill its Chrome, then join.

        Needed to free the locked profile before a headed login can open it.
        """
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is None:
            return
        self._queue.put(None)
        thread.join(timeout=15)

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

    def _run(self) -> None:
        from playwright.sync_api import sync_playwright

        port = self._settings.ig_cdp_port
        proc = None
        # Reuse a Chrome already listening (e.g. from --reload or a prior run)
        # instead of launching a second one on the same locked profile.
        if not is_cdp_up(port):
            chrome = find_chrome(self._settings.ig_chrome_path)
            proc = launch_chrome(
                chrome,
                self._settings.ig_browser_dir,
                port,
                headless=self._settings.ig_browser_headless,
            )
            atexit.register(_safe_terminate, proc)
            wait_for_cdp(port)
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(cdp_url(port))
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                _mask_headless_ua(page)
                page.goto(_HOME, wait_until="domcontentloaded")
                _seed_from_store(page)
                while True:
                    item = self._queue.get()
                    if item is None:
                        break
                    job, fut = item
                    try:
                        fut.set_result(job(page))
                    except Exception as exc:  # noqa: BLE001 — relayed to caller
                        fut.set_exception(exc)
                browser.close()
        finally:
            if proc is not None:
                _safe_terminate(proc)


_COOKIE_KEYS = ("name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite")


def _seed_from_store(page: Page) -> None:
    """Re-seed this headless browser from the saved login cookies, if needed.

    Runs at every worker startup so a single human login survives app restarts:
    if the live context has no sessionid, load the ones saved by ig_login.finish()
    and inject them. A dead/expired stored session is simply cleared by Instagram
    on the reload — harmless. Local import avoids an import cycle with ig_login.
    """
    from app.infrastructure.instagram import ig_login

    if any(c.get("name") == "sessionid" for c in page.context.cookies()):
        return
    saved = ig_login.load_saved_cookies()
    if not saved:
        return
    cleaned = [{k: c[k] for k in _COOKIE_KEYS if k in c} for c in saved]
    with contextlib.suppress(Exception):  # best-effort; never wedge startup
        page.context.add_cookies(cleaned)
        page.goto(_HOME, wait_until="domcontentloaded")
        logger.info("seeded %d saved login cookies into the headless browser", len(cleaned))


def _mask_headless_ua(page: Page) -> None:
    """Drop the 'Headless' marker from the browser's user-agent.

    Headless Chrome sends 'HeadlessChrome/…' in its UA. Instagram flags that as a
    bot and INVALIDATES the session (sessionid gets cleared on the next request),
    so a freshly-logged-in session dies instantly. Override the UA to the normal
    Chrome string before we touch instagram.com, keeping the session alive.
    """
    try:
        ua = str(page.evaluate("() => navigator.userAgent"))
        if "Headless" not in ua:
            return
        clean = ua.replace("HeadlessChrome", "Chrome").replace("Headless", "")
        cdp = page.context.new_cdp_session(page)
        cdp.send("Network.setUserAgentOverride", {"userAgent": clean})
        logger.info("masked headless UA -> %s", clean)
    except Exception:  # noqa: BLE001 — best-effort; never block startup on this
        logger.warning("could not mask headless UA", exc_info=True)


def _fetch_json(page: Page, path: str) -> dict[str, Any]:
    """Run fetch() inside the page (same-origin, fully authed) and return JSON."""
    result = page.evaluate(
        """async ({ path, appId }) => {
            const headers = { 'X-IG-App-ID': appId };
            // Some endpoints (e.g. likers) require the CSRF token from the cookie.
            const m = document.cookie.match(/csrftoken=([^;]+)/);
            if (m) headers['X-CSRFToken'] = m[1];
            const r = await fetch(path, { headers, credentials: 'include' });
            const body = await r.text();
            return { status: r.status, ct: r.headers.get('content-type') || '', body };
        }""",
        {"path": path, "appId": _WEB_APP_ID},
    )
    status = int(result["status"])
    ctype = str(result["ct"])
    body = str(result["body"])
    snippet = " ".join(body[:200].split())

    if status == 404:
        raise PostNotFoundError(path)
    if "json" not in ctype:
        raise LoginRequiredError(f"non-JSON from {path} (status {status}, ct {ctype}): {snippet}")

    data: dict[str, Any] = json.loads(body)
    message = str(data.get("message", ""))
    if message == "checkpoint_required" or data.get("require_login"):
        raise ChallengeRequiredError("Instagram requested verification (checkpoint).")
    # IG's own backend (TAO/MySQL) sometimes times out: 400 + status "fail" +
    # a NodeTaoSystemException/tao_errno message. That is NOT a dead session —
    # retrying works — so don't send the user to reconnect. Surface as transient.
    if _is_transient_ig_error(message):
        raise InstagramError(f"Instagram lento/caído, reintentá ({path} -> {status})")
    if status in (401, 403) or data.get("status") == "fail":
        raise LoginRequiredError(f"{path} -> status {status}: {snippet}")
    return data


def _is_transient_ig_error(message: str) -> bool:
    """True for IG-side backend blips (their DB/timeout), not our session."""
    m = message.lower()
    return any(s in m for s in ("nodetao", "tao_errno", "timed out", "please wait a few minutes"))


def _path(base: str, params: dict[str, Any] | None = None) -> str:
    return f"{base}?{urlencode(params)}" if params else base


def _send_dm(page: Page, user_pk: str, text: str) -> None:
    """POST the DM from inside the page (the web app's broadcast endpoint)."""
    result = page.evaluate(
        """async ({ userPk, text, appId }) => {
            const headers = {
                'X-IG-App-ID': appId,
                'content-type': 'application/x-www-form-urlencoded',
            };
            const m = document.cookie.match(/csrftoken=([^;]+)/);
            if (m) headers['X-CSRFToken'] = m[1];
            const ctx = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
            const params = new URLSearchParams();
            params.set('action', 'send_item');
            params.set('client_context', ctx);
            params.set('mutation_token', ctx);
            params.set('offline_threading_id', ctx);
            params.set('recipient_users', JSON.stringify([[userPk]]));
            params.set('text', text);
            const r = await fetch('/api/v1/direct_v2/threads/broadcast/text/', {
                method: 'POST', headers, credentials: 'include', body: params.toString(),
            });
            const body = await r.text();
            return { status: r.status, ct: r.headers.get('content-type') || '', body };
        }""",
        {"userPk": user_pk, "text": text, "appId": _WEB_APP_ID},
    )
    status = int(result["status"])
    body = str(result["body"])
    snippet = " ".join(body[:200].split())
    if "json" not in str(result["ct"]):
        # 200 + HTML almost always means IG served a login/checkpoint page
        # instead of the API JSON: the session needs reconnecting, not a spam
        # block. Distinguish so the user gets the right fix (and see the body).
        low = body[:500].lower()
        if "<html" in low or "checkpoint" in low or "login" in low:
            raise ChallengeRequiredError(
                f"sesión no válida para enviar (status {status}): {snippet}"
            )
        raise SendBlockedError(f"respuesta no-JSON al enviar (status {status}): {snippet}")
    data = json.loads(body)
    if data.get("status") == "ok":
        return
    raise SendBlockedError(str(data.get("message") or f"status {status}"))


def _naive_dt(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo is not None else dt


def _page_older_than(page: list[DmThread], cut: datetime) -> bool:
    """True when every thread on this inbox page last moved before `cut`."""
    times = [_naive_dt(t.last_message_at) for t in page if t.last_message_at is not None]
    return bool(times) and all(t is not None and t < cut for t in times)


class PlaywrightInstagramSource:
    """InstagramSource backed by a logged-in headless browser."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._worker = _BrowserWorker(settings)
        self._budget = RequestBudget(
            settings.scan_min_delay_seconds,
            settings.scan_max_delay_seconds,
            settings.scan_max_requests,
        )

    def reset_budget(self) -> None:
        self._budget.reset()

    def dispose(self) -> None:
        """Shut the browser down (used before an in-app login re-opens the profile)."""
        self._worker.stop()

    def _get(self, base: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._budget.spend()
        data: dict[str, Any] = self._worker.submit(
            lambda page: _fetch_json(page, _path(base, params))
        )
        return data

    def send_dm(self, user_pk: str, text: str) -> None:
        self._worker.submit(lambda page: _send_dm(page, user_pk, text))

    def get_friendships(self, user_pks: list[str]) -> dict[str, Friendship]:
        # show_many only tells us who WE follow, not who follows US. To know
        # "te sigue" we read our own followers/following lists and test membership.
        our_pk = self.current_user_pk()
        followers = self._collect_pks(f"/api/v1/friendships/{our_pk}/followers/")
        following = self._collect_pks(f"/api/v1/friendships/{our_pk}/following/")
        # A logged-in account always has followers/following. Both empty means the
        # lists were blocked, not that they're empty — refuse, so we don't overwrite
        # good "te sigue" data with all-False on a flaky fetch.
        if not followers and not following:
            raise InstagramError("no se pudo leer seguidores/seguidos (bloqueado?)")
        return {
            pk: Friendship(following=pk in following, followed_by=pk in followers)
            for pk in set(user_pks)
        }

    def _collect_pks(self, base: str) -> set[str]:
        """Paginate a followers/following list into a set of user pks."""
        pks: set[str] = set()
        params: dict[str, Any] = {"count": 100}
        for _ in range(300):  # bounded; the request cap also limits this
            data = self._get(base, params)
            for user in data.get("users") or []:
                pk = user.get("pk") or user.get("id")
                if pk:
                    pks.add(str(pk))
            next_max = data.get("next_max_id")
            if not next_max:
                break
            params = {"count": 100, "max_id": str(next_max)}
        return pks

    def get_profile(self, username: str) -> ProfileInfo:
        data = self._get("/api/v1/users/web_profile_info/", {"username": username})
        user = (data.get("data") or {}).get("user") or {}
        followed_by = user.get("edge_followed_by") or {}
        return ProfileInfo(
            pk=str(user.get("id", "")),
            username=str(user.get("username", username)),
            full_name=str(user.get("full_name", "") or ""),
            follower_count=followed_by.get("count"),
            is_verified=bool(user.get("is_verified")),
            is_business=bool(user.get("is_business_account")),
            biography=str(user.get("biography", "") or ""),
            is_private=bool(user.get("is_private")),
            profile_pic_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
        )

    def current_user_pk(self) -> str:
        def read_pk(page: Page) -> str:
            # Require BOTH cookies. ds_user_id persists after logout, but the
            # actual login lives in sessionid — without it, GETs may still work
            # yet authed reads/DM sends bounce to a login page (200 HTML). So a
            # ds_user_id with no sessionid is NOT a live session; report none,
            # else /ig/status shows a false "connected" and sends fail opaquely.
            names = {c.get("name"): str(c.get("value", "")) for c in page.context.cookies()}
            if not names.get("sessionid"):
                return ""
            return names.get("ds_user_id", "")

        pk: str = self._worker.submit(read_pk)
        if not pk:
            raise LoginRequiredError(
                "sesión de Instagram no iniciada (falta sessionid) — reconectá desde el chip IG"
            )
        return pk

    def get_post(self, url: str) -> Post:
        shortcode = extract_shortcode(url)
        if shortcode is None:
            raise PostNotFoundError(url)
        media_pk = shortcode_to_pk(shortcode)
        return parse_media_info(self._get(f"/api/v1/media/{media_pk}/info/"))

    def get_recent_posts(self, limit: int) -> list[Post]:
        pk = self.current_user_pk()
        data = self._get(f"/api/v1/feed/user/{pk}/", {"count": limit})
        return [parse_media_info({"items": [item]}) for item in data.get("items") or []][:limit]

    def get_likers(self, media_pk: str) -> list[IgUser]:
        return parse_likers(self._get(f"/api/v1/media/{media_pk}/likers/"))

    def get_comments(self, media_pk: str) -> list[Comment]:
        comments: list[Comment] = []
        params: dict[str, Any] = {}
        for _ in range(10):
            data = self._get(f"/api/v1/media/{media_pk}/comments/", params or None)
            comments.extend(parse_comments(data))
            next_min_id = data.get("next_min_id")
            if not next_min_id:
                break
            params = {"min_id": next_min_id}
        return comments

    def get_dm_threads(
        self, progress: Any = None, since: datetime | None = None
    ) -> list[DmThread]:
        our_pk = self.current_user_pk()
        threads: list[DmThread] = []
        params: dict[str, Any] = {"thread_message_limit": 20, "limit": 20}
        cut = _naive_dt(since)
        for _ in range(20):
            data = self._get("/api/v1/direct_v2/inbox/", params)
            page = parse_inbox(data, our_pk)
            threads.extend(page)
            if progress is not None:
                progress(len(threads), None, f"{len(threads)} hilos de DM")
            # Inbox is ordered by recent activity: once a page's oldest thread is
            # older than the cutoff, everything beyond is stale — stop early.
            if cut is not None and _page_older_than(page, cut):
                break
            inbox = data.get("inbox") or {}
            if not inbox.get("has_older"):
                break
            cursor = inbox.get("oldest_cursor")
            if not cursor:
                break
            params = {"thread_message_limit": 20, "limit": 20, "cursor": cursor}
        return threads
