"""S25 HTTP contract: GET/PUT /config and POST /config/reset, and the routes
reading the effective configuration (demo/real switch, read limits).

Everything runs on a temp DB and FakeInstagramSource: no Instagram traffic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from app.api.deps import (
    instagram_dep,
    runtime_config_dep,
    session_dep,
    session_factory_dep,
    source_dep,
)
from app.application.runtime_config import RuntimeConfigService
from app.bootstrap import InstagramAccess
from app.domain import config as cfg
from app.domain.entities import Post
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.fake_source import FakeInstagramSource
from app.infrastructure.persistence import db, models
from app.infrastructure.persistence.config_store import SqlConfigStore
from app.main import app
from sqlalchemy import Engine
from sqlmodel import Session, select

from tests.test_jobs_api import _call, _job_result, _wait_idle

GROUPS = ["Ritmo humano", "Presupuesto de pedidos", "Frenos", "Lectura de datos", "Caché"]


class RecordingSource(FakeInstagramSource):
    def __init__(self) -> None:
        super().__init__()
        self.recent_limits: list[int] = []

    def get_recent_posts(self, limit: int) -> list[Post]:
        self.recent_limits.append(limit)
        return super().get_recent_posts(limit)


class Wiring:
    def __init__(self, engine: Engine, tmp_path: Path) -> None:
        self.engine = engine
        # Tests force the dev fake source explicitly (the app always uses the real one).
        self.settings = Settings(
            _env_file=None, dev_fake_instagram=True, ig_session_file=str(tmp_path / "session.json")
        )
        self.source = RecordingSource()
        self.runtime = self.restart()

    def restart(self) -> RuntimeConfigService:
        """A new service over the same DB (as after an app restart)."""
        service = RuntimeConfigService(
            SqlConfigStore(lambda: Session(self.engine)),
            lambda: self.settings.runtime_defaults(),
        )
        service.load()
        return service


@pytest.fixture
def wiring(tmp_path: Path) -> Iterator[Wiring]:
    engine = db.build_engine(f"sqlite:///{tmp_path / 'api.db'}")
    db.create_db_and_tables(engine)
    w = Wiring(engine, tmp_path)

    def session() -> Iterator[Session]:
        with Session(engine) as s:
            yield s

    overrides: dict[Callable[..., Any], Callable[..., Any]] = {
        session_dep: session,
        session_factory_dep: lambda: lambda: Session(engine),
        get_settings: lambda: w.settings,
        runtime_config_dep: lambda: w.runtime,
        source_dep: lambda: w.source,
        instagram_dep: lambda: InstagramAccess(lambda _: w.source, lambda _: None),  # type: ignore[arg-type,return-value]
    }
    app.dependency_overrides.update(overrides)
    try:
        yield w
    finally:
        _wait_idle()
        for dep in overrides:
            app.dependency_overrides.pop(dep, None)
        engine.dispose()


def _entries(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["key"]: e for e in body["entries"]}


def _stored(w: Wiring) -> dict[str, str]:
    with Session(w.engine) as s:
        return {r.key: r.value for r in s.exec(select(models.ConfigOverride))}


def test_get_config_lists_every_setting_with_its_metadata(wiring: Wiring) -> None:
    status, _, body = _call("GET", "/config")

    assert status == 200
    entries = _entries(body)
    assert len(entries) == 18
    assert "dm_incremental" not in entries  # fixed on: lighter reads only
    assert entries["scan_min_delay_seconds"] == {
        "key": "scan_min_delay_seconds",
        "kind": "float",
        "value": 2.0,
        "default": 2.0,
        "min": 2.0,
        "max": 60.0,
        "unit": "s",
        "group": "Ritmo humano",
        "label": "Espera mínima entre pedidos",
        "help": entries["scan_min_delay_seconds"]["help"],
        "overridden": False,
        "at_most": "scan_max_delay_seconds",
        "clamped_from": None,
    }
    assert entries["scan_min_delay_seconds"]["help"].startswith("Antes de cada pedido")
    assert entries["ig_max_requests_per_hour"]["kind"] == "int"
    assert (
        entries["ig_max_requests_per_hour"]["min"],
        entries["ig_max_requests_per_hour"]["max"],
    ) == (1, 200)
    assert [g for g in GROUPS if any(e["group"] == g for e in body["entries"])] == GROUPS
    assert all(e["label"] and e["help"] for e in body["entries"])


@pytest.mark.parametrize(
    ("method", "path", "body", "message"),
    [
        ("PUT", "/config", {}, 'Mandá los ajustes a cambiar así: {"values": {"clave": número}}.'),
        (
            "PUT",
            "/config",
            {"values": 5},
            'Mandá los ajustes a cambiar así: {"values": {"clave": número}}.',
        ),
        (
            "PUT",
            "/config",
            [1, 2],
            'Mandá los ajustes a cambiar así: {"values": {"clave": número}}.',
        ),
        (
            "POST",
            "/config/reset",
            {"key": 5},
            'Mandá {"key": "clave"} para restaurar un ajuste, o {} para restaurar todos.',
        ),
    ],
    ids=["empty", "values-not-object", "not-object", "reset-key-not-text"],
)
def test_malformed_bodies_get_a_spanish_422(
    wiring: Wiring, method: str, path: str, body: Any, message: str
) -> None:
    status, _, out = _call(method, path, body=body)
    assert status == 422
    assert out == {"detail": {"code": "bad_request", "message": message}}
    assert _stored(wiring) == {}


def test_other_routes_keep_the_default_validation_errors(wiring: Wiring) -> None:
    status, _, out = _call("POST", "/scan/posts", body={"urls": "nope"})
    assert status == 422
    assert isinstance(out["detail"], list)  # FastAPI's own shape, unchanged


def _unsafe_and_safe(spec: Any) -> tuple[list[float], list[float]]:
    step = 1 if spec.kind.value == "int" else 0.5
    if spec.factory_bound == "min":  # waits: shorter is unsafe
        return [spec.factory - step, spec.max + step], [spec.factory + step]
    if spec.factory_bound == "max":  # budgets/caps: higher is unsafe
        return [spec.factory + step, spec.min - step], [spec.factory - step]
    return [spec.min - step, spec.max + step], [spec.min, spec.max]


@pytest.mark.parametrize("spec", cfg.SPECS, ids=[s.key for s in cfg.SPECS])
def test_every_setting_refuses_the_unsafe_side_and_keeps_the_db(wiring: Wiring, spec: Any) -> None:
    unsafe, safe = _unsafe_and_safe(spec)
    pair = {spec.key: None}
    for value in unsafe:
        status, _, body = _call("PUT", "/config", body={"values": {spec.key: value}})
        assert status == 422, (spec.key, value)
        assert body["detail"]["code"] == "bad_request"
        assert spec.label in body["detail"]["message"]
        assert _stored(wiring) == {}
    for value in safe:
        values: dict[str, float] = {spec.key: value}
        if spec.at_most:  # keep the pair valid
            values[spec.at_most] = cfg.SPEC_BY_KEY[spec.at_most].max  # type: ignore[assignment]
        status, _, body = _call("PUT", "/config", body={"values": values})
        assert status == 200, (spec.key, value, body)
    del pair


def test_the_app_mode_is_not_a_setting(wiring: Wiring) -> None:
    """L27: demo mode left the app: no mode entry, and trying to set or restore
    it is a Spanish 422 that changes nothing."""
    _, _, body = _call("GET", "/config")
    assert "ig_source" not in _entries(body)
    assert set(body) == {"entries"}
    assert not any(e["kind"] == "choice" or "choices" in e for e in body["entries"])

    status, _, put = _call("PUT", "/config", body={"values": {"ig_source": "fake"}})
    assert status == 422
    assert put == {
        "detail": {
            "code": "bad_request",
            "message": "«ig_source» no es un ajuste que se pueda cambiar.",
        }
    }
    status, _, reset = _call("POST", "/config/reset", body={"key": "ig_source"})
    assert status == 422
    assert reset["detail"]["message"] == "«ig_source» no es un ajuste que se pueda cambiar."
    assert _stored(wiring) == {}


def test_a_stored_mode_from_an_older_version_is_ignored(wiring: Wiring) -> None:
    with Session(wiring.engine) as s:
        s.add(models.ConfigOverride(key="ig_source", value='"fake"'))
        s.commit()
    wiring.settings = Settings(_env_file=None)  # no env override: the real account
    wiring.runtime = wiring.restart()

    _, _, health = _call("GET", "/health")
    status, _, body = _call("GET", "/config")
    saved, _, _ = _call("PUT", "/config", body={"values": {"dm_threads_limit": 30}})

    assert health == {"status": "ok", "using_fake_instagram": False}
    assert status == 200 and "ig_source" not in _entries(body)
    assert saved == 200
    _call("POST", "/config/reset", body={})
    assert _stored(wiring) == {}  # "Restaurar todo" also clears the old row


def test_put_saves_a_partial_update(wiring: Wiring) -> None:
    status, _, body = _call(
        "PUT", "/config", body={"values": {"dm_threads_limit": 40, "scan_max_delay_seconds": 9.5}}
    )

    assert status == 200
    entries = _entries(body)
    assert entries["dm_threads_limit"]["value"] == 40
    assert entries["dm_threads_limit"]["overridden"] is True
    assert entries["dm_threads_limit"]["default"] == 60
    assert entries["scan_max_delay_seconds"]["value"] == 9.5
    assert entries["recent_posts_limit"]["overridden"] is False
    assert _stored(wiring) == {"dm_threads_limit": "40", "scan_max_delay_seconds": "9.5"}
    assert wiring.restart().current().dm_threads_limit == 40


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {"ig_max_requests_per_day": 2000},
            "«Tope de pedidos por día» no puede ser mayor que 1500 pedidos (el valor de "
            "fábrica): solo se permite ir hacia lo más seguro; más pedidos a Instagram suben "
            "el riesgo de bloqueo.",
        ),
        (
            {"scan_min_delay_seconds": 1},
            "«Espera mínima entre pedidos» no puede ser menor que 2 s (el valor de fábrica): "
            "solo se permite ir hacia lo más seguro.",
        ),
        (
            {"ig_rest_min_seconds": 200},
            "«Descanso mínimo» (200 s) no puede ser mayor que «Descanso máximo» (150 s).",
        ),
        (
            {"use_fake_instagram": False},
            "«use_fake_instagram» no es un ajuste que se pueda cambiar.",
        ),
        ({"dm_threads_limit": "veinte"}, "«Chats por sincronización» tiene que ser un número."),
    ],
    ids=["budget-up", "faster-pace", "min-above-max", "unknown", "not-a-number"],
)
def test_put_refuses_with_a_spanish_422_and_changes_nothing(
    wiring: Wiring, values: dict[str, Any], message: str
) -> None:
    status, _, body = _call("PUT", "/config", body={"values": {"dm_threads_limit": 30, **values}})

    assert status == 422
    assert body == {"detail": {"code": "bad_request", "message": message}}
    assert _stored(wiring) == {}
    assert wiring.runtime.current().dm_threads_limit == 60


def test_reset_one_setting_or_all(wiring: Wiring) -> None:
    _call("PUT", "/config", body={"values": {"dm_threads_limit": 30, "recent_posts_limit": 5}})

    status, _, body = _call("POST", "/config/reset", body={"key": "dm_threads_limit"})
    assert status == 200
    entries = _entries(body)
    assert (entries["dm_threads_limit"]["value"], entries["dm_threads_limit"]["overridden"]) == (
        60,
        False,
    )
    assert entries["recent_posts_limit"]["value"] == 5

    status, _, body = _call("POST", "/config/reset", body={})
    assert status == 200
    assert not any(e["overridden"] for e in body["entries"])
    assert _stored(wiring) == {}

    status, _, body = _call("POST", "/config/reset", body={"key": "nope"})
    assert status == 422
    assert body["detail"]["message"] == "«nope» no es un ajuste que se pueda cambiar."


def test_a_saved_limit_reaches_the_next_job(wiring: Wiring) -> None:
    _call("PUT", "/config", body={"values": {"recent_posts_limit": 10}})

    done = _job_result(
        "POST",
        "/scan/posts",
        "scan",
        body={"from": "2026-11-01T00:00:00Z", "to": "2026-11-30T00:00:00Z"},
    )

    assert done["status"] == "done"
    assert wiring.source.recent_limits == [10]


# -- preserve: with nothing stored everything behaves as before ---------------------


def test_preserve_scan_job_uses_the_default_limit(wiring: Wiring) -> None:
    done = _job_result(
        "POST",
        "/scan/posts",
        "scan",
        body={"from": "2026-11-01T00:00:00Z", "to": "2026-11-30T00:00:00Z"},
    )
    assert done["status"] == "done"
    assert wiring.source.recent_limits == [50]


def test_preserve_status_and_health_with_the_dev_fake_source(wiring: Wiring) -> None:
    status, _, ig = _call("GET", "/ig/status")
    _, _, health = _call("GET", "/health")

    assert status == 200
    assert (ig["demo"], ig["source"], ig["state"]) == (True, "fake", "connected")
    assert ig["has_saved_session"] is False
    assert health == {"status": "ok", "using_fake_instagram": True}


def test_preserve_shared_source_follows_the_effective_mode(tmp_path: Path) -> None:
    """The campaign sender and the jobs share InstagramAccess.source(): it builds
    the source of the effective demo/real switch, once, until it is reset."""
    built: list[str] = []
    mode = ["fake"]

    def build(settings: Settings) -> Any:
        built.append(settings.ig_source)
        return object()

    access = InstagramAccess(
        build,
        lambda _: None,  # type: ignore[arg-type,return-value]
        settings=lambda: Settings(_env_file=None, dev_fake_instagram=mode[0] == "fake"),
    )
    first = access.source()
    assert access.source() is first and built == ["fake"]
    mode[0] = "instagrapi"
    access.reset()
    access.source()
    assert built == ["fake", "instagrapi"]


def test_status_reports_a_saved_session_file(wiring: Wiring) -> None:
    Path(wiring.settings.ig_session_file).write_text("{}", encoding="utf-8")
    _, _, ig = _call("GET", "/ig/status")
    assert ig["has_saved_session"] is True
    assert "has_credentials" not in ig
