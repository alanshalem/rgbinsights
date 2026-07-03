"""Launch a plain Chrome and attach over CDP.

Instagram walls Playwright-launched browsers behind a reCAPTCHA that never
renders (it detects the automation flags). The workaround: start a *normal*
Chrome process ourselves (no automation flags, no webdriver) so the human login
looks genuine, and only *attach* via CDP afterwards to read data. API fetches
don't trigger the reCAPTCHA — only the login page does, and that stays human.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def find_chrome(explicit_path: str = "") -> str:
    """Locate a real Chrome/Chromium binary, or raise with guidance."""
    if explicit_path:
        if Path(explicit_path).exists():
            return explicit_path
        raise FileNotFoundError(f"IG_CHROME_PATH no existe: {explicit_path}")

    candidates = [
        rf"{os.environ.get('PROGRAMFILES', '')}\Google\Chrome\Application\chrome.exe",
        rf"{os.environ.get('PROGRAMFILES(X86)', '')}\Google\Chrome\Application\chrome.exe",
        rf"{os.environ.get('LOCALAPPDATA', '')}\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(
        "No encontré Google Chrome. Instalalo o poné la ruta en IG_CHROME_PATH (.env)."
    )


def launch_chrome(
    chrome_path: str,
    user_data_dir: str,
    port: int,
    *,
    headless: bool,
    start_url: str | None = None,
) -> subprocess.Popen[bytes]:
    """Start a normal Chrome with a debugging port and a dedicated profile."""
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={Path(user_data_dir).resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-crash-restore-bubble",
    ]
    if headless:
        args.append("--headless=new")
    if start_url:
        args.append(start_url)
    logger.info("launching Chrome on CDP port %d (headless=%s)", port, headless)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def is_cdp_up(port: int) -> bool:
    """True if a Chrome with a DevTools endpoint is already listening."""
    try:
        with urllib.request.urlopen(  # noqa: S310 — localhost only
            f"http://127.0.0.1:{port}/json/version", timeout=1
        ):
            return True
    except OSError:
        return False


def wait_for_cdp(port: int, timeout: float = 30.0) -> None:
    """Block until Chrome's DevTools endpoint answers."""
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):  # noqa: S310 — localhost only
                return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"Chrome no expuso CDP en el puerto {port} a tiempo")


def cdp_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"
