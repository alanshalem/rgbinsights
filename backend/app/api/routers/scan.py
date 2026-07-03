from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import raise_for_err, session_dep, source_dep
from app.api.schemas import (
    ScanBatchResultOut,
    ScanPostRequest,
    ScanPostsRequest,
    ScanResultOut,
)
from app.application.use_cases import ScanPostsUseCase, ScanPostUseCase
from app.domain.result import Err
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.instagram.base import InstagramSource

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("/post", response_model=ScanResultOut)
def scan_post(
    body: ScanPostRequest,
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
) -> ScanResultOut:
    result = ScanPostUseCase(source, session).execute(body.url, body.event_id)
    if isinstance(result, Err):
        raise_for_err(result)
    return ScanResultOut.model_validate(result.value, from_attributes=True)


@router.post("/posts", response_model=ScanBatchResultOut)
def scan_posts(
    body: ScanPostsRequest,
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
) -> ScanBatchResultOut:
    use_case = ScanPostsUseCase(source, session, settings.recent_posts_limit)
    if body.urls:
        result = use_case.by_urls(body.urls, body.event_id)
    elif body.date_from and body.date_to:
        result = use_case.by_date_range(body.date_from, body.date_to, body.event_id)
    else:
        raise HTTPException(
            status_code=422, detail={"code": "bad_request", "message": "provide urls or from+to"}
        )
    if isinstance(result, Err):
        raise_for_err(result)
    return ScanBatchResultOut.model_validate(result.value, from_attributes=True)
