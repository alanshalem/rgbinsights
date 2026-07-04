from __future__ import annotations

from app.api.routers.ig import ig_status
from app.infrastructure.config.settings import Settings
from sqlmodel import Session


def _fake_settings() -> Settings:
    return Settings(use_fake_instagram=True, ig_source="")


def test_ig_status_connected_in_demo(session: Session) -> None:
    out = ig_status(session=session, settings=_fake_settings())
    assert out.demo is True
    assert out.state == "connected"
    assert out.pk  # fake account pk
    assert out.last_ok_at is not None  # recorded on a successful check
