from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.schemas import HealthOut
from app.infrastructure.config.settings import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(settings: Settings = Depends(get_settings)) -> HealthOut:
    return HealthOut(status="ok", using_fake_instagram=settings.use_fake_instagram)
