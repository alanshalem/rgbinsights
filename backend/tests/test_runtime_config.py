"""S25 in-app configuration: safety bounds (S0), precedence, storage and the
runtime pickup by the guard (pacer, budget, cooldown, lock) and the reads.

No network: HTTP is stubbed (FakeHttp from test_ig_safety) and the reads run on
the recording StubClient of test_fewer_requests.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from app.application.runtime_config import RuntimeConfigService
from app.domain import config as cfg
from app.domain.config import FACTORY, ConfigValueError, RuntimeConfig
from app.domain.errors import BudgetExhaustedError
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.guard import IgGuard
from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource
from app.infrastructure.persistence import db, models
from app.infrastructure.persistence.config_store import SqlConfigStore
from sqlalchemy import Engine, inspect
from sqlmodel import Session, SQLModel, select

from tests.test_fewer_requests import StubClient, _comment_pages, _inbox
from tests.test_ig_safety import URL, Clock, FakeHttp, _client

# The factory values: what settings.py shipped with before S25 (L23: the defaults).
TODAY = {
    "scan_min_delay_seconds": 2.0,
    "scan_max_delay_seconds": 6.0,
    "ig_rest_every_requests": 25,
    "ig_rest_min_seconds": 45.0,
    "ig_rest_max_seconds": 150.0,
    "ig_max_requests_per_hour": 200,
    "ig_max_requests_per_day": 1500,
    "ig_throttle_cooldown_minutes": 60.0,
    "ig_lock_wait_seconds": 600.0,
    "recent_posts_limit": 50,
    "dm_threads_limit": 60,
    "scan_comments_limit": 200,
    "relationship_fetch_max": 0,
    "enrich_profiles_per_run": 60,
    "enrich_profiles_per_day": 150,
    "relationship_cache_hours": 12.0,
    "rescan_skip_hours": 6.0,
    "relationship_full_refresh_days": 7.0,
}


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = db.build_engine(f"sqlite:///{tmp_path / 'config.db'}")
    db.create_db_and_tables(eng)
    yield eng
    eng.dispose()


def _store(engine: Engine) -> SqlConfigStore:
    return SqlConfigStore(lambda: Session(engine))


def _service(
    engine: Engine,
    defaults: RuntimeConfig = FACTORY,
) -> RuntimeConfigService:
    service = RuntimeConfigService(_store(engine), lambda: defaults)
    service.load()
    return service


def _stored(engine: Engine) -> dict[str, str]:
    with Session(engine) as s:
        return {r.key: r.value for r in s.exec(select(models.ConfigOverride))}


# -- defaults -----------------------------------------------------------------------


def test_factory_values_are_the_previous_code_defaults() -> None:
    assert {s.key: s.factory for s in cfg.SPECS} == TODAY
    # Settings (the legacy-env defaults) ship the very same values.
    assert Settings(_env_file=None).runtime_defaults() == FACTORY


def test_dm_incremental_is_not_configurable_any_more() -> None:
    assert "dm_incremental" not in cfg.SPEC_BY_KEY
    with pytest.raises(ConfigValueError, match="no es un ajuste"):
        cfg.validate("dm_incremental", False)


# -- S0: only towards the safer side -----------------------------------------------

_FASTER = [
    # waits/rests/cooldown/cache: never shorter than the factory value
    (
        "scan_min_delay_seconds",
        1.9,
        "«Espera mínima entre pedidos» no puede ser menor que 2 s (el valor de fábrica): "
        "solo se permite ir hacia lo más seguro.",
    ),
    ("scan_max_delay_seconds", 5.5, "no puede ser menor que 6 s (el valor de fábrica)"),
    ("ig_rest_min_seconds", 44, "no puede ser menor que 45 s (el valor de fábrica)"),
    ("ig_rest_max_seconds", 149, "no puede ser menor que 150 s (el valor de fábrica)"),
    ("ig_throttle_cooldown_minutes", 59, "no puede ser menor que 60 min (el valor de fábrica)"),
    ("relationship_cache_hours", 11.5, "no puede ser menor que 12 h (el valor de fábrica)"),
    ("rescan_skip_hours", 5, "no puede ser menor que 6 h (el valor de fábrica)"),
    ("relationship_full_refresh_days", 6, "no puede ser menor que 7 días (el valor de fábrica)"),
    # resting less often is faster
    ("ig_rest_every_requests", 26, "no puede ser mayor que 25 pedidos (el valor de fábrica)"),
    # budgets and caps: never above the factory value
    (
        "ig_max_requests_per_hour",
        201,
        "«Tope de pedidos por hora» no puede ser mayor que 200 pedidos (el valor de fábrica): "
        "solo se permite ir hacia lo más seguro; más pedidos a Instagram suben el riesgo de "
        "bloqueo.",
    ),
    ("ig_max_requests_per_day", 1501, "mayor que 1500 pedidos (el valor de fábrica)"),
    ("recent_posts_limit", 51, "mayor que 50 posts (el valor de fábrica)"),
    ("dm_threads_limit", 61, "mayor que 60 chats (el valor de fábrica)"),
    ("scan_comments_limit", 201, "mayor que 200 comentarios (el valor de fábrica)"),
    ("enrich_profiles_per_run", 61, "mayor que 60 perfiles (el valor de fábrica)"),
    ("enrich_profiles_per_day", 151, "mayor que 150 perfiles (el valor de fábrica)"),
]


@pytest.mark.parametrize(("key", "value", "message"), _FASTER, ids=[f[0] for f in _FASTER])
def test_a_value_faster_than_the_factory_one_is_refused(
    key: str, value: float, message: str
) -> None:
    with pytest.raises(ConfigValueError) as info:
        cfg.validate(key, value)
    assert message in str(info.value)


_OUT_OF_RANGE = [
    ("scan_min_delay_seconds", 60.5, "no puede ser mayor que 60 s."),
    ("scan_max_delay_seconds", 61, "no puede ser mayor que 60 s."),
    ("ig_rest_max_seconds", 901, "no puede ser mayor que 900 s."),
    ("ig_throttle_cooldown_minutes", 1441, "no puede ser mayor que 1440 min."),
    ("relationship_cache_hours", 169, "no puede ser mayor que 168 h."),
    ("relationship_full_refresh_days", 91, "no puede ser mayor que 90 días."),
    ("ig_rest_every_requests", 4, "no puede ser menor que 5 pedidos."),
    ("ig_max_requests_per_hour", 0, "no puede ser menor que 1 pedido."),  # A3
    ("scan_comments_limit", 0, "no puede ser menor que 1 comentario."),  # 0 = no cap
    ("dm_threads_limit", 0, "no puede ser menor que 1 chat."),
    ("recent_posts_limit", 0, "no puede ser menor que 1 post."),
    ("enrich_profiles_per_run", 0, "no puede ser menor que 1 perfil."),
    ("ig_lock_wait_seconds", 29, "no puede ser menor que 30 s."),
    ("ig_lock_wait_seconds", 3601, "no puede ser mayor que 3600 s."),
    ("relationship_fetch_max", -1, "no puede ser menor que 0 personas."),
]


@pytest.mark.parametrize(("key", "value", "message"), _OUT_OF_RANGE)
def test_values_outside_the_sane_range_are_refused(key: str, value: float, message: str) -> None:
    with pytest.raises(ConfigValueError) as info:
        cfg.validate(key, value)
    assert str(info.value).endswith(message)
    assert "valor de fábrica" not in str(info.value)


@pytest.mark.parametrize("spec", cfg.SPECS, ids=[s.key for s in cfg.SPECS])
def test_every_bound_itself_is_accepted(spec: cfg.SettingSpec) -> None:
    assert spec.min is not None and spec.max is not None
    assert cfg.validate(spec.key, spec.min) == spec.min
    assert cfg.validate(spec.key, spec.max) == spec.max
    assert cfg.validate(spec.key, spec.factory) == spec.factory


def test_relationship_cap_takes_any_size_since_a_cap_only_lowers_requests() -> None:
    assert [cfg.validate("relationship_fetch_max", v) for v in (0, 1, 500, 1_000_000)] == [
        0,
        1,
        500,
        1_000_000,
    ]


@pytest.mark.parametrize(
    ("key", "raw", "message"),
    [
        ("dm_threads_limit", 2.5, "«Chats por sincronización» tiene que ser un número entero."),
        ("dm_threads_limit", "30", "«Chats por sincronización» tiene que ser un número."),
        ("scan_min_delay_seconds", True, "«Espera mínima entre pedidos» tiene que ser un número."),
        (
            "scan_min_delay_seconds",
            math.nan,
            "«Espera mínima entre pedidos» tiene que ser un número.",
        ),
        ("scan_min_delay_seconds", None, "«Espera mínima entre pedidos» tiene que ser un número."),
        ("ig_country", "US", "«ig_country» no es un ajuste que se pueda cambiar."),
        ("ig_source", "fake", "«ig_source» no es un ajuste que se pueda cambiar."),  # L27
    ],
)
def test_wrong_types_and_unknown_keys_are_refused(key: str, raw: Any, message: str) -> None:
    with pytest.raises(ConfigValueError) as info:
        cfg.validate(key, raw)
    assert str(info.value) == message


def test_whole_number_floats_are_fine_for_integer_settings() -> None:
    assert cfg.validate("dm_threads_limit", 30.0) == 30
    assert isinstance(cfg.validate("dm_threads_limit", 30.0), int)
    assert cfg.validate("scan_min_delay_seconds", 3) == 3.0


# -- precedence: DB override > env (legacy .env) > factory ---------------------------


def _env_settings(tmp_path: Path, text: str) -> Settings:
    env_file = tmp_path / "settings_file.txt"
    env_file.write_text(text, encoding="utf-8")
    return Settings(_env_file=env_file)


def test_db_override_beats_env_which_beats_factory(engine: Engine, tmp_path: Path) -> None:
    env = _env_settings(tmp_path, "SCAN_MIN_DELAY_SECONDS=3\nRECENT_POSTS_LIMIT=20\n")
    service = _service(engine, env.runtime_defaults())

    assert service.current().scan_min_delay_seconds == 3.0  # env
    assert service.current().scan_max_delay_seconds == 6.0  # factory
    assert service.current().recent_posts_limit == 20  # env

    service.update({"scan_min_delay_seconds": 4})
    assert service.current().scan_min_delay_seconds == 4.0  # DB

    service.reset("scan_min_delay_seconds")
    assert service.current().scan_min_delay_seconds == 3.0  # back to env
    assert _service(engine).current().scan_min_delay_seconds == 2.0  # no env: factory


def test_an_old_env_value_faster_than_the_factory_one_is_pulled_back(
    engine: Engine, tmp_path: Path
) -> None:
    env = _env_settings(
        tmp_path,
        "SCAN_MIN_DELAY_SECONDS=0.5\nIG_MAX_REQUESTS_PER_HOUR=999\nSCAN_COMMENTS_LIMIT=0\n"
        "IG_REST_MIN_SECONDS=400\nIG_REST_MAX_SECONDS=150\n",
    )
    current = _service(engine, env.runtime_defaults()).current()

    assert current.scan_min_delay_seconds == 2.0
    assert current.ig_max_requests_per_hour == 200
    assert current.scan_comments_limit == 1  # 0 meant "no cap": the safest cap instead
    # A max below its min is raised to the min (the longer, safer side).
    assert (current.ig_rest_min_seconds, current.ig_rest_max_seconds) == (400.0, 400.0)


def test_stored_values_are_read_leniently(engine: Engine) -> None:
    with Session(engine) as s:
        s.add(models.ConfigOverride(key="scan_min_delay_seconds", value="0.1"))  # too fast
        s.add(models.ConfigOverride(key="dm_threads_limit", value="not json"))
        s.add(models.ConfigOverride(key="removed_setting", value="1"))
        s.add(models.ConfigOverride(key="ig_source", value='"fake"'))  # the L25 mode (L27)
        s.commit()

    current = _service(engine).current()

    assert current.scan_min_delay_seconds == 2.0  # clamped to the bound
    assert current.dm_threads_limit == 60  # unreadable: the default
    entries = {e.spec.key: e for e in _service(engine).entries()}
    assert entries["dm_threads_limit"].overridden is False  # A4: ignored, so not "cambiado"
    assert entries["scan_min_delay_seconds"].overridden is True


_UNSAFE_ROWS = {
    "scan_min_delay_seconds": "0.1",
    "scan_max_delay_seconds": "0.2",
    "ig_rest_every_requests": "100",
    "ig_rest_min_seconds": "-5",
    "ig_max_requests_per_hour": "99999",
    "ig_max_requests_per_day": "NaN",
    "ig_throttle_cooldown_minutes": "Infinity",
    "ig_lock_wait_seconds": "-Infinity",
    "dm_threads_limit": '"300"',
    "recent_posts_limit": "true",
    "scan_comments_limit": "0",
    "enrich_profiles_per_run": "{not json",
    "enrich_profiles_per_day": "1e9",
    "relationship_cache_hours": "[]",
    "rescan_skip_hours": "null",
    "relationship_full_refresh_days": "0.001",
    "relationship_fetch_max": "-1",
    "an_unknown_key": "5",
}


def test_raw_unsafe_rows_never_make_the_app_faster(engine: Engine) -> None:
    """L29: whatever sits in app_config (hand edits, older versions, junk), every
    effective value stays within its bounds, on the safe side of the factory."""
    with Session(engine) as s:
        for key, raw in _UNSAFE_ROWS.items():
            s.add(models.ConfigOverride(key=key, value=raw))
        s.commit()

    service = _service(engine)
    current = service.current()

    for spec in cfg.SPECS:
        value = getattr(current, spec.key)
        assert spec.min is not None and spec.max is not None
        assert spec.min <= value <= spec.max, spec.key
        assert not isinstance(value, bool) and math.isfinite(value), spec.key
        if spec.factory_bound == "min":
            assert value >= spec.factory, spec.key
        if spec.factory_bound == "max":
            assert value <= spec.factory, spec.key
        assert current.scan_min_delay_seconds <= current.scan_max_delay_seconds
    unreadable = {
        "ig_max_requests_per_day",
        "ig_throttle_cooldown_minutes",
        "ig_lock_wait_seconds",
        "dm_threads_limit",
        "recent_posts_limit",
        "enrich_profiles_per_run",
        "relationship_cache_hours",
        "rescan_skip_hours",
    }
    for entry in service.entries():
        if entry.spec.key in unreadable:
            assert entry.overridden is False, entry.spec.key
            assert entry.value == entry.default, entry.spec.key


# -- A2: an old .env value that had to be clamped is reported -----------------------


def test_a_clamped_env_value_is_reported_and_logged_once(
    engine: Engine, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = _env_settings(
        tmp_path, "SCAN_MIN_DELAY_SECONDS=0.5\nIG_MAX_REQUESTS_PER_HOUR=999\nDM_THREADS_LIMIT=30\n"
    )
    with caplog.at_level("WARNING"):
        service = _service(engine, env.runtime_defaults())
        service.entries()
        service.current()

    entries = {e.spec.key: e for e in service.entries()}
    assert (
        entries["scan_min_delay_seconds"].clamped_from,
        entries["scan_min_delay_seconds"].default,
    ) == (0.5, 2.0)
    assert (
        entries["ig_max_requests_per_hour"].clamped_from,
        entries["ig_max_requests_per_hour"].default,
    ) == (999, 200)
    assert entries["dm_threads_limit"].clamped_from is None  # 30 is safe: used as is
    assert entries["dm_threads_limit"].default == 30
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 2
    assert any("scan_min_delay_seconds" in w and "0.5" in w for w in warnings)


# -- storage + migration ------------------------------------------------------------


def test_an_existing_db_gets_the_config_table_and_keeps_its_data(tmp_path: Path) -> None:
    eng = db.build_engine(f"sqlite:///{tmp_path / 'old.db'}")
    older = [t for t in SQLModel.metadata.sorted_tables if t.name != "app_config"]
    SQLModel.metadata.create_all(eng, tables=older)  # a DB from before S25
    with Session(eng) as s:
        s.add(models.AppState(key="dms_synced_at", value="2026-11-01T00:00:00+00:00"))
        s.commit()
    assert "app_config" not in inspect(eng).get_table_names()

    db.create_db_and_tables(eng)
    db.create_db_and_tables(eng)  # idempotent

    assert "app_config" in inspect(eng).get_table_names()
    with Session(eng) as s:
        assert s.get(models.AppState, "dms_synced_at") is not None
    store = _store(eng)
    store.save({"dm_threads_limit": 40, "ig_source": "instagrapi"})
    store.save({"dm_threads_limit": 30})
    assert store.load() == {"dm_threads_limit": 30, "ig_source": "instagrapi"}
    store.delete(["dm_threads_limit"])
    assert store.load() == {"ig_source": "instagrapi"}
    store.delete()
    assert store.load() == {}
    eng.dispose()


def test_saved_values_survive_a_restart(engine: Engine) -> None:
    _service(engine).update({"dm_threads_limit": 40, "ig_rest_every_requests": 10})

    restarted = _service(engine)

    assert restarted.current().dm_threads_limit == 40
    assert restarted.current().ig_rest_every_requests == 10
    entries = {e.spec.key: e for e in restarted.entries()}
    assert entries["dm_threads_limit"].overridden is True
    assert entries["dm_threads_limit"].default == 60
    assert entries["scan_min_delay_seconds"].overridden is False


# -- the service ---------------------------------------------------------------------


def test_an_update_is_all_or_nothing(engine: Engine) -> None:
    service = _service(engine)

    with pytest.raises(ConfigValueError):
        service.update({"dm_threads_limit": 30, "scan_min_delay_seconds": 1})

    assert service.current() == FACTORY
    assert _stored(engine) == {}


def test_a_min_above_its_max_is_refused(engine: Engine) -> None:
    service = _service(engine)

    with pytest.raises(ConfigValueError) as info:
        service.update({"scan_min_delay_seconds": 10})

    assert str(info.value) == (
        "«Espera mínima entre pedidos» (10 s) no puede ser mayor que "
        "«Espera máxima entre pedidos» (6 s)."
    )
    assert _stored(engine) == {}
    service.update({"scan_min_delay_seconds": 10, "scan_max_delay_seconds": 12.5})
    assert service.current().scan_max_delay_seconds == 12.5


def test_reset_one_or_all(engine: Engine) -> None:
    service = _service(engine)
    service.update({"dm_threads_limit": 30, "recent_posts_limit": 10})

    service.reset("dm_threads_limit")
    assert (service.current().dm_threads_limit, service.current().recent_posts_limit) == (60, 10)
    assert set(_stored(engine)) == {"recent_posts_limit"}

    service.reset()
    assert service.current() == FACTORY
    assert _stored(engine) == {}
    with pytest.raises(ConfigValueError, match="no es un ajuste"):
        service.reset("nope")


# -- runtime pickup: the next Instagram request uses the saved values ------------------


def _live_guard(
    tmp_path: Path, service: RuntimeConfigService, clock: Clock, sleeps: list[float]
) -> IgGuard:
    settings = Settings(_env_file=None, ig_guard_file=str(tmp_path / "ig_guard.json"))
    return IgGuard(
        settings, config=service.current, clock=clock, sleep=sleeps.append, rng=random.Random(5)
    )


def test_pacer_uses_a_saved_slower_pace_from_the_next_request(
    engine: Engine, tmp_path: Path
) -> None:
    service = _service(engine)
    sleeps: list[float] = []
    guard = _live_guard(tmp_path, service, Clock(), sleeps)
    client = _client(FakeHttp())
    guard.install(client)

    client.private.get(URL)
    assert 2.0 <= sleeps[-1] <= 6.0 * 4  # factory pace (+ a possible distraction)

    service.update(
        {
            "scan_min_delay_seconds": 30,
            "scan_max_delay_seconds": 40,
            "ig_rest_every_requests": 5,
            "ig_rest_min_seconds": 600,
            "ig_rest_max_seconds": 700,
        }
    )
    for _ in range(4):
        client.private.get(URL)

    assert all(s >= 30.0 for s in sleeps[1:])
    assert sleeps[4] >= 30.0 + 600.0  # the 5th request rests with the new values


def test_budget_uses_a_saved_lower_cap_and_keeps_what_was_spent(
    engine: Engine, tmp_path: Path
) -> None:
    service = _service(engine)
    http = FakeHttp()
    guard = _live_guard(tmp_path, service, Clock(), [])
    client = _client(http)
    guard.install(client)
    for _ in range(3):
        client.private.get(URL)

    service.update({"ig_max_requests_per_hour": 2})  # below the 3 already spent

    with pytest.raises(BudgetExhaustedError) as info:
        client.private.get(URL)
    assert len(http.calls) == 3  # blocked until the hour rolls, nothing sent
    assert "tope de seguridad de 2 pedidos a Instagram por hora" in str(info.value)


def test_cooldown_and_lock_wait_use_the_saved_values(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(engine)
    clock = Clock()
    guard = _live_guard(tmp_path, service, clock, [])
    client = _client(FakeHttp((429, "Too Many Requests")))
    guard.install(client)

    service.update({"ig_throttle_cooldown_minutes": 180, "ig_lock_wait_seconds": 45})
    waits: list[float] = []
    real = guard._lock

    class Recording:
        def acquire(self, timeout: float) -> bool:
            waits.append(timeout)
            return real.acquire(timeout=timeout)

        def release(self) -> None:
            real.release()

    monkeypatch.setattr(guard, "_lock", Recording())
    with guard.operation():
        pass
    assert waits == [45.0]

    client.private.get(URL)  # Instagram answers 429
    assert guard.snapshot().blocked_until == clock.now + timedelta(minutes=180)


def test_reads_use_the_saved_caps_from_the_next_read(engine: Engine, tmp_path: Path) -> None:
    service = _service(engine)
    settings = Settings(
        _env_file=None,
        ig_guard_file=str(tmp_path / "ig_guard.json"),
        ig_session_file=str(tmp_path / "session.json"),
    )
    guard = IgGuard(settings, config=service.current, sleep=lambda _: None)
    source = InstagrapiInstagramSource(settings, guard=guard, config=service.current)
    client = StubClient()
    source._client = client
    source.get_post("https://instagram.com/p/C5/")

    service.update({"scan_comments_limit": 3, "dm_threads_limit": 20})
    client.pages = _comment_pages("media/5_77/comments/", pages=4, per_page=5)
    comments = source.get_comments("5")
    newest = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    client.inbox = [(_inbox(0, 20, newest), "c1"), (_inbox(20, 20, newest), "c2")]
    inbox = source.get_dm_threads()

    assert len(comments) == 3
    assert len(inbox.threads) == 20  # one inbox page instead of three
    assert [e for e in client.endpoints() if e == "direct_v2/inbox/"] == ["direct_v2/inbox/"]


def test_without_a_configuration_the_guard_keeps_its_settings_values(tmp_path: Path) -> None:
    """Preserve: a guard built from plain Settings (tests, old callers) still
    uses those values as they are."""
    settings = Settings(
        _env_file=None, ig_guard_file=str(tmp_path / "g.json"), ig_max_requests_per_hour=1
    )
    guard = IgGuard(settings, clock=Clock(), sleep=lambda _: None)
    client = _client(FakeHttp())
    guard.install(client)
    client.private.get(URL)
    with pytest.raises(BudgetExhaustedError):
        client.private.get(URL)


# -- L30 X2: an old value on the SAFE side is kept, even beyond the editable range --


def test_old_env_slower_values_are_kept() -> None:
    raw = replace(FACTORY, scan_max_delay_seconds=100, ig_rest_every_requests=3)
    safe = cfg.safe_defaults(raw)
    assert safe.scan_max_delay_seconds >= 100 and safe.ig_rest_every_requests <= 3


_SLOWER = [
    ("scan_min_delay_seconds", 90.0),  # its max (6) is raised to 90 too: still slower
    ("scan_max_delay_seconds", 100.0),
    ("ig_rest_every_requests", 3),
    ("ig_rest_min_seconds", 1000.0),
    ("ig_rest_max_seconds", 1200.0),
    ("ig_throttle_cooldown_minutes", 2000.0),
    ("relationship_cache_hours", 200.0),
    ("rescan_skip_hours", 500.0),
    ("relationship_full_refresh_days", 120.0),
    ("ig_max_requests_per_hour", 1),
    ("scan_comments_limit", 1),
]


@pytest.mark.parametrize(("key", "slower"), _SLOWER, ids=[k for k, _ in _SLOWER])
def test_each_slower_env_value_is_kept_and_not_reported(key: str, slower: float) -> None:
    raw = replace(FACTORY, **{key: slower})  # type: ignore[arg-type]
    safe = cfg.safe_defaults(raw)
    assert getattr(safe, key) == slower
    assert key not in cfg.clamped_defaults(raw)  # nothing was moved: no "tu .env pedía"


@pytest.mark.parametrize(
    ("key", "unsafe", "used"),
    [
        ("ig_rest_every_requests", 0, 1),  # 0 would switch the long rests off
        ("ig_rest_every_requests", -4, 1),
        ("scan_comments_limit", 0, 1),  # 0 would mean "no cap"
        ("ig_max_requests_per_day", 0, 1),
        ("scan_max_delay_seconds", 1.0, 6.0),
        ("relationship_cache_hours", 0.0, 12.0),
    ],
)
def test_values_on_the_unsafe_side_are_still_moved_and_reported(
    key: str, unsafe: float, used: float
) -> None:
    raw = replace(FACTORY, **{key: unsafe})  # type: ignore[arg-type]
    assert getattr(cfg.safe_defaults(raw), key) == used
    assert cfg.clamped_defaults(raw)[key] == unsafe


def test_a_stored_slower_value_beyond_the_range_is_kept(engine: Engine) -> None:
    with Session(engine) as s:
        s.add(models.ConfigOverride(key="scan_max_delay_seconds", value="100"))
        s.add(models.ConfigOverride(key="ig_rest_every_requests", value="3"))
        s.commit()
    service = _service(engine)

    assert service.current().scan_max_delay_seconds == 100.0
    assert service.current().ig_rest_every_requests == 3
    entry = {e.spec.key: e for e in service.entries()}["scan_max_delay_seconds"]
    assert (entry.value, entry.overridden, entry.clamped_from) == (100.0, True, None)
    with pytest.raises(ConfigValueError, match="no puede ser mayor que 60 s"):
        service.update({"scan_max_delay_seconds": 100})  # the screen's range still holds


def test_unusable_stored_values_are_logged_once(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    with Session(engine) as s:
        s.add(models.ConfigOverride(key="dm_threads_limit", value='"300"'))
        s.add(models.ConfigOverride(key="recent_posts_limit", value="true"))
        s.add(models.ConfigOverride(key="ig_source", value='"fake"'))
        s.commit()
    with caplog.at_level("WARNING"):
        _service(engine)

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 3
    assert any("dm_threads_limit" in w and "'300'" in w for w in warnings)
    assert any("ig_source" in w for w in warnings)
