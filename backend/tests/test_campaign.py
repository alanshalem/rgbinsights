from __future__ import annotations

from app.application.campaign import PRESETS, estimate, render_message, warmup_cap
from app.infrastructure.instagram.fake_source import FakeInstagramSource


def test_estimate_max_preset_66_users() -> None:
    est = estimate(66, PRESETS["max"])
    assert est.per_day == 25  # daily cap
    assert est.days == 3  # ceil(66/25)


def test_estimate_zero() -> None:
    assert estimate(0, PRESETS["media"]).days == 0


def test_estimate_reports_window_and_activity() -> None:
    est = estimate(66, PRESETS["max"])
    assert est.window_hours == 12  # 11..23h
    assert est.avg_delay_seconds == 120  # (60+180)/2
    assert est.minutes_per_day == 50.0  # 25 sends * 120s / 60


def test_render_uses_first_name_and_rotates() -> None:
    templates = ["Hola {nombre}, ¿cómo estás?", "Qué hacés {nombre} 👋 (@{usuario})"]
    a = render_message(templates, "lucia.dj", "Lucía Gómez", "101")
    b = render_message(templates, "tomas_beats", "Tomás", "102")
    assert "Lucía" in a  # first name only, not full name
    assert a in {"Hola Lucía, ¿cómo estás?", "Qué hacés Lucía 👋 (@lucia.dj)"}
    # Deterministic per key.
    assert render_message(templates, "lucia.dj", "Lucía Gómez", "101") == a
    assert b  # rendered for the other user too


def test_render_no_fullname_falls_back_to_username() -> None:
    assert render_message(["Hola {nombre}"], "sofi.raver", "", "103") == "Hola sofi.raver"


def test_warmup_cap_ramps_then_reaches_daily_cap() -> None:
    # Day 0 starts low, then +8/day, never above the real cap.
    assert warmup_cap(25, 0) == 8
    assert warmup_cap(25, 1) == 16
    assert warmup_cap(25, 2) == 24
    assert warmup_cap(25, 3) == 25  # capped
    assert warmup_cap(25, 99) == 25


def test_warmup_cap_respects_small_cap_and_bad_day() -> None:
    assert warmup_cap(5, 0) == 5  # cap below the base
    assert warmup_cap(25, -3) == 8  # negative day → base


def test_fake_source_records_sends() -> None:
    source = FakeInstagramSource()
    source.send_dm("101", "hola")
    assert source.sent == [("101", "hola")]
