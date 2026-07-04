from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import raise_for_err, session_dep, source_dep
from app.api.schemas import SyncResultOut
from app.application.tasks import registry as tasks
from app.application.use_cases import SyncDmsUseCase
from app.domain.result import Err
from app.infrastructure.instagram.base import InstagramSource

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/dms", response_model=SyncResultOut)
def sync_dms(
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
) -> SyncResultOut:
    with tasks.track("sync", "Sincronizando DMs") as task:
        result = SyncDmsUseCase(source, session).execute(task.progress)
        if isinstance(result, Err):
            task.fail(result.message or result.code.value)
            raise_for_err(result)
        task.result = {
            "hilos": result.value.threads_synced,
            "relaciones": result.value.follows_synced,
        }
        out = SyncResultOut.model_validate(result.value, from_attributes=True)
    return out
