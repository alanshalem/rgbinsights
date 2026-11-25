"""S0: after the adapter split, every instagrapi client call runs inside a guard operation."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource


class _Guard:
    def __init__(self) -> None:
        self.depth = 0

    @contextlib.contextmanager
    def operation(self, fresh_sessionid: str | None = None) -> Iterator[None]:
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1

    def note_sessionid(self, sessionid: str) -> None: ...

    def login_ok(self) -> None: ...


def test_every_client_call_runs_inside_a_guard_operation(tmp_path: Path) -> None:
    guard, outside = _Guard(), []
    canned: dict[str, Any] = {
        "private_request": {"users": [{"pk": 7}]},
        "user_following": [8],
        "direct_threads_chunk": ([], None),
        "user_medias": [],
    }

    class Client:
        user_id, rank_token = 42, "rt"

        def __getattr__(self, name: str) -> Any:
            def call(*args: Any, **kwargs: Any) -> Any:
                if guard.depth == 0:
                    outside.append(name)
                return canned.get(name)

            return call

    settings = Settings(_env_file=None, ig_session_file=str(tmp_path / "s.json"))
    src = InstagrapiInstagramSource(settings, guard=guard)  # type: ignore[arg-type]
    src._client = Client()
    src.current_user_pk()
    src.get_follow_graph()
    src.get_recent_posts(3)
    src.get_dm_threads()
    src.send_dm("123", "hola")
    assert outside == []
