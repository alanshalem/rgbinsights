from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import raise_for_err, session_dep, source_dep
from app.api.schemas import SyncResultOut
from app.application.use_cases import SyncDmsUseCase
from app.domain.result import Err
from app.infrastructure.instagram.base import InstagramSource

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/dms", response_model=SyncResultOut)
def sync_dms(
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
) -> SyncResultOut:
    result = SyncDmsUseCase(source, session).execute()
    if isinstance(result, Err):
        raise_for_err(result)
    return SyncResultOut.model_validate(result.value, from_attributes=True)
