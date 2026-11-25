from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import settings_dep
from app.api.schemas import HealthOut
from app.infrastructure.config.settings import Settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(settings: Settings = Depends(settings_dep)) -> HealthOut:
    return HealthOut(status="ok", using_fake_instagram=settings.is_fake)
