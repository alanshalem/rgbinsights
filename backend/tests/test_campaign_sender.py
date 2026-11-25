"""The campaign send loop (S3 pause rules, S6 Argentina time, S22).

Runs `CampaignSender._run` synchronously against an in-memory DB with a stub
source; sleeps and activity logging are stubbed so nothing waits or touches the
real DB/IG.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.application import campaign_sender
from app.application.campaign_sender import CampaignSender
from app.application.runtime_config import RuntimeConfigService
from app.domain.config import FACTORY
from app.domain.errors import (
    BudgetExhaustedError,
    ChallengeRequiredError,
    IgBusyError,
    InstagramError,
    IpBlockedError,
    LoginRequiredError,
    RateLimitedError,
    RecipientUnavailableError,
    SendBlockedError,
    SendRetryableError,
)
from app.infrastructure.config.settings import Settings
from app.infrastructure.instagram.guard import IgGuard
from app.infrastructure.instagram.instagrapi_source import InstagrapiInstagramSource
from app.infrastructure.persistence import models
from app.infrastructure.persistence.campaigns import SqlCampaignStore
from app.infrastructure.persistence.config_store import SqlConfigStore
from instagrapi.exceptions import ChallengeRequired
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

NOON_AR = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)  # 12:00 in Argentina


class StubSource:
    """Raises the queued errors in order, then sends fine."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.attempts: list[str] = []
        self.sent: list[tuple[str, str]] = []

    def send_dm(self, user_pk: str, text: str) -> None:
        self.attempts.append(user_pk)
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append((user_pk, text))


class Harness:
    def __init__(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        self.engine = engine
        self.monkeypatch = monkeypatch
        self.sleeps: list[float] = []
        self.logs: list[tuple[str, str, str]] = []
        self.now = NOON_AR

    def sender(self, source: StubSource | InstagrapiInstagramSource) -> CampaignSender:
        sender = CampaignSender(
            SqlCampaignStore(lambda: Session(self.engine)),
            lambda: source,  # type: ignore[arg-type,return-value]
            Settings(_env_file=None).local_tz(),
            lambda *args: self.logs.append(args),
            clock=lambda: self.now,
        )
        self.monkeypatch.setattr(sender, "_sleep_or_stopped", self.fake_sleep)
        return sender

    def run(self, source: StubSource | InstagrapiInstagramSource) -> None:
        self.sender(source)._run(1)

    def fake_sleep(self, campaign_id: int, seconds: float) -> bool:
        self.sleeps.append(seconds)
        return seconds == campaign_sender._IDLE_SECONDS  # stop when it would idle-wait

    def campaign(self) -> models.Campaign:
        with Session(self.engine) as s:
            row = s.get(models.Campaign, 1)
            assert row is not None
            return row

    def targets(self) -> list[models.CampaignTarget]:
        with Session(self.engine) as s:
            return list(s.exec(select(models.CampaignTarget)).all())


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    h = Harness(engine, monkeypatch)
    monkeypatch.setattr(campaign_sender, "_IDLE_SECONDS", 60, raising=False)
    yield h
    engine.dispose()


def _seed(
    h: Harness,
    targets: int = 2,
    hours: tuple[int, int] = (0, 24),
    **campaign: Any,
) -> None:
    with Session(h.engine) as s:
        s.add(
            models.Campaign(
                id=1,
                event_id=1,
                status=campaign.pop("status", "running"),
                templates="[]",
                delay_min=10,
                delay_max=10,
                daily_cap=25,
                hour_start=hours[0],
                hour_end=hours[1],
                sent_today_date=campaign.pop("sent_today_date", "2026-11-24"),
                created_at=campaign.pop("created_at", datetime(2026, 11, 1, tzinfo=UTC)),
                **campaign,
            )
        )
        for i in range(1, targets + 1):
            s.add(
                models.CampaignTarget(
                    campaign_id=1, user_pk=str(i), username=f"u{i}", message=f"m{i}"
                )
            )
        s.commit()


# -- previous behaviour that must still hold -------------------------------


def test_send_loop_sends_every_target_then_finishes(harness: Harness) -> None:
    _seed(harness)
    source = StubSource()

    harness.run(source)

    assert source.sent == [("1", "m1"), ("2", "m2")]
    assert harness.campaign().status == "done"
    assert harness.campaign().sent_today == 2
    assert [t.status for t in harness.targets()] == ["sent", "sent"]


@pytest.mark.parametrize(
    "error",
    [SendBlockedError("action-block"), ChallengeRequiredError("challenge")],
    ids=["send_blocked", "challenge"],
)
def test_action_block_still_blocks_the_campaign(harness: Harness, error: Exception) -> None:
    _seed(harness)
    source = StubSource(error)

    harness.run(source)

    assert source.attempts == ["1"]
    assert harness.campaign().status == "blocked"
    assert harness.campaign().error == str(error)
    assert [t.status for t in harness.targets()] == ["pending", "pending"]


def test_recipient_unavailable_skips_only_that_target(harness: Harness) -> None:
    _seed(harness)
    source = StubSource(RecipientUnavailableError("@1 no acepta mensajes nuevos"))

    harness.run(source)

    assert [t.status for t in harness.targets()] == ["failed", "sent"]
    assert harness.campaign().status == "done"


# -- S3: account-level failures pause the campaign -------------------------


@pytest.mark.parametrize(
    "error",
    [
        LoginRequiredError("La sesión venció."),
        IpBlockedError("Instagram marcó tu conexión (IP)."),
        RateLimitedError("Instagram pidió frenar."),
    ],
    ids=["login", "ip_blocked", "rate_limited"],
)
def test_account_level_failure_pauses_with_reason(harness: Harness, error: Exception) -> None:
    _seed(harness)
    source = StubSource(error)

    harness.run(source)

    assert source.attempts == ["1"]  # no next target, no re-login per target
    campaign = harness.campaign()
    assert campaign.status == "paused"
    assert campaign.error == str(error)
    assert [t.status for t in harness.targets()] == ["pending", "pending"]
    assert harness.logs and "pausada" in harness.logs[-1][2]


@pytest.mark.parametrize(
    "error",
    [SendRetryableError("timeout"), InstagramError("Instagram falló la operación")],
    ids=["retryable", "generic"],
)
def test_transient_failure_marks_target_and_keeps_pacing(
    harness: Harness, error: Exception
) -> None:
    _seed(harness)
    source = StubSource(error)

    harness.run(source)

    assert [t.status for t in harness.targets()] == ["failed", "sent"]
    assert harness.campaign().status == "done"
    assert harness.sleeps == [10, 10]  # the per-send gap also follows a failed attempt


def test_busy_instagram_waits_and_retries_the_same_target(harness: Harness) -> None:
    _seed(harness, targets=1)
    source = StubSource(IgBusyError("Instagram está ocupado"))

    harness.run(source)

    assert source.attempts == ["1", "1"]
    assert [t.status for t in harness.targets()] == ["sent"]
    assert harness.campaign().status == "done"


# -- S6: Argentina local time ----------------------------------------------


def test_active_hours_are_argentina_local(harness: Harness) -> None:
    _seed(harness, targets=1, hours=(11, 23))
    harness.now = datetime(2026, 11, 25, 1, 30, tzinfo=UTC)  # 22:30 in Argentina
    source = StubSource()

    harness.run(source)

    assert source.sent == [("1", "m1")]


def test_outside_argentina_hours_does_not_send(harness: Harness) -> None:
    _seed(harness, targets=1, hours=(11, 23))
    harness.now = datetime(2026, 11, 24, 13, 30, tzinfo=UTC)  # 10:30 in Argentina
    source = StubSource()

    harness.run(source)

    assert source.attempts == []
    assert harness.sleeps == [60]


def test_daily_counter_rolls_over_at_argentina_midnight(harness: Harness) -> None:
    _seed(harness, targets=1, sent_today=5, sent_today_date="2026-11-24")
    harness.now = datetime(2026, 11, 25, 1, 30, tzinfo=UTC)  # still the 24th in Argentina
    harness.run(StubSource())

    campaign = harness.campaign()
    assert campaign.sent_today == 6
    assert campaign.sent_today_date == "2026-11-24"


def test_raw_challenge_from_instagrapi_blocks_the_campaign(
    harness: Harness, tmp_path: Path
) -> None:
    """End to end through the real adapter: instagrapi's own ChallengeRequired on
    direct_send must stop the campaign, not burn targets one by one."""

    def challenged(*args: Any, **kwargs: Any) -> None:
        raise ChallengeRequired("challenge_required")

    settings = Settings(
        _env_file=None,
        ig_guard_file=str(tmp_path / "ig_guard.json"),
        ig_session_file=str(tmp_path / "session.json"),
    )
    source = InstagrapiInstagramSource(settings, guard=IgGuard(settings, sleep=lambda _: None))
    source._client = SimpleNamespace(user_id=1, direct_send=challenged)
    _seed(harness)

    harness.run(source)

    assert harness.campaign().status == "blocked"
    assert [t.status for t in harness.targets()] == ["pending", "pending"]


def test_preserve_send_loop_through_the_adapter_with_the_default_config(
    harness: Harness, tmp_path: Path
) -> None:
    """S25: the real adapter wired to the in-app configuration (nothing stored:
    the factory values) still sends every target, paced by the campaign."""
    runtime = RuntimeConfigService(SqlConfigStore(lambda: Session(harness.engine)), lambda: FACTORY)
    runtime.load()
    settings = Settings(
        _env_file=None,
        ig_guard_file=str(tmp_path / "ig_guard.json"),
        ig_session_file=str(tmp_path / "session.json"),
    )
    guard = IgGuard(settings, config=runtime.current, sleep=lambda _: None)
    source = InstagrapiInstagramSource(settings, guard=guard, config=runtime.current)
    sent: list[list[str]] = []
    source._client = SimpleNamespace(
        user_id=1, direct_send=lambda text, user_ids: sent.append([text, *map(str, user_ids)])
    )
    _seed(harness)

    harness.run(source)

    assert sent == [["m1", "1"], ["m2", "2"]]
    assert harness.campaign().status == "done"
    assert harness.sleeps[:2] == [10.0, 10.0]  # the campaign's own delay between sends


# -- L10 R4-1: a spent request budget waits for its window, it never pauses ----


def test_spent_budget_waits_for_the_window_then_continues(harness: Harness) -> None:
    _seed(harness)
    retry_at = NOON_AR + timedelta(minutes=30)
    source = StubSource(BudgetExhaustedError("Se alcanzó el tope por hora.", retry_at=retry_at))

    harness.run(source)

    assert source.attempts == ["1", "1", "2"]  # same target after the wait, no other call
    assert harness.campaign().status == "done"
    assert harness.campaign().error is None
    assert [t.status for t in harness.targets()] == ["sent", "sent"]
    wait = harness.sleeps[0]
    assert 30 * 60 < wait <= 30 * 60 + campaign_sender._BUDGET_JITTER_SECONDS[1]
    assert harness.logs[0][1] == "error" and "espera" in harness.logs[0][2]


def test_budget_already_reopened_still_waits_a_little(harness: Harness) -> None:
    _seed(harness, targets=1)
    source = StubSource(BudgetExhaustedError("tope", retry_at=NOON_AR - timedelta(minutes=1)))

    harness.run(source)

    assert harness.sleeps[0] >= campaign_sender._BUDGET_JITTER_SECONDS[0]
    assert harness.campaign().status == "done"


def test_instagram_cooldown_still_pauses_not_waits(harness: Harness) -> None:
    _seed(harness)
    source = StubSource(RateLimitedError("Instagram pidió frenar (HTTP 429)."))

    harness.run(source)

    assert source.attempts == ["1"]
    assert harness.campaign().status == "paused"
    assert harness.sleeps == []


# -- S22: the daily cap, warm-up and the loop's own bookkeeping -----------------


def test_a_new_local_day_resets_the_counter_and_still_enforces_the_cap(harness: Harness) -> None:
    """Yesterday's count resets once and is saved, so today's sends count
    against the cap (they used to be counted on the stale value and the cap
    never stopped the day)."""
    _seed(harness, targets=30, sent_today=25, sent_today_date="2026-11-23")
    source = StubSource()

    harness.run(source)

    assert len(source.sent) == 25  # the daily cap (campaign created weeks ago: no warm-up)
    campaign = harness.campaign()
    assert (campaign.sent_today, campaign.sent_today_date) == (25, "2026-11-24")
    assert campaign.status == "running"  # waits for tomorrow, never "done" early
    assert harness.sleeps[-1] == campaign_sender._IDLE_SECONDS


def test_warm_up_caps_a_brand_new_campaign(harness: Harness) -> None:
    _seed(harness, targets=20, created_at=NOON_AR)
    source = StubSource()

    harness.run(source)

    assert len(source.sent) == 8  # day 0 of the warm-up ramp
    assert harness.sleeps[-1] == campaign_sender._IDLE_SECONDS


def test_finishing_logs_the_day_count(harness: Harness) -> None:
    _seed(harness, targets=1, sent_today=3)
    harness.run(StubSource())
    assert harness.logs[-1] == ("campaign", "done", "campaña terminada (4 hoy)")


def test_a_stopped_campaign_never_sends(harness: Harness) -> None:
    _seed(harness, targets=1, status="paused", sent_today=5, sent_today_date="2026-11-23")
    source = StubSource()

    harness.run(source)

    assert source.attempts == []
    campaign = harness.campaign()
    assert (campaign.status, campaign.sent_today) == ("paused", 5)  # left untouched


def test_resume_all_restarts_only_running_campaigns(harness: Harness) -> None:
    _seed(harness, targets=1)
    with Session(harness.engine) as s:
        for cid, status in ((2, "paused"), (3, "running"), (4, "done")):
            s.add(
                models.Campaign(
                    id=cid,
                    event_id=1,
                    status=status,
                    templates="[]",
                    delay_min=10,
                    delay_max=10,
                    daily_cap=25,
                    hour_start=0,
                    hour_end=24,
                    created_at=NOON_AR,
                )
            )
        s.commit()
    sender = harness.sender(StubSource())
    started: list[int] = []
    harness.monkeypatch.setattr(sender, "start", started.append)

    sender.resume_all()

    assert started == [1, 3]


def test_waiting_ends_as_soon_as_the_campaign_is_stopped(harness: Harness) -> None:
    _seed(harness, targets=1, status="paused")
    sender = CampaignSender(
        SqlCampaignStore(lambda: Session(harness.engine)),
        StubSource,  # type: ignore[arg-type]
        Settings(_env_file=None).local_tz(),
        lambda *args: None,
    )
    assert sender._sleep_or_stopped(1, 3600) is True  # no sleep at all
