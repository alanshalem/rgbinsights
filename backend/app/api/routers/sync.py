from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import source_dep, start_job, uow_factory_dep
from app.api.schemas import TaskOut
from app.application.ports import InstagramSource, UnitOfWork, UnitOfWorkFactory
from app.application.tasks import Task
from app.application.use_cases import SyncDmsUseCase, event_counts, state_delta
from app.application.use_cases.sync import CAPPED_NOTE

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/dms", response_model=TaskOut, status_code=202)
def sync_dms(
    response: Response,
    force: bool = False,
    event: int | None = None,  # scope the state-delta to the selected fiesta (display only)
    source: InstagramSource = Depends(source_dep),
    new_uow: UnitOfWorkFactory = Depends(uow_factory_dep),
) -> TaskOut:
    """Background job (202 + the job): progress/result via /tasks/stream or /tasks/{id}.

    Always incremental unless forced (S25: fixed on, it is the lighter read).
    The job's `warning` says when the chats-per-sync cap cut an incremental sync
    short."""

    def work(task: Task, uow: UnitOfWork) -> None:
        before = event_counts(uow, event)
        synced = task.unwrap(SyncDmsUseCase(source, uow).execute(task.progress, force=force))
        task.set_result(
            {**state_delta(before, event_counts(uow, event)), "hilos": synced.threads_synced},
            warning=CAPPED_NOTE if synced.capped else None,
        )

    return start_job(
        kind="sync",
        label="Sincronizando DMs",
        params={"force": force, "event": event},
        work=work,
        new_uow=new_uow,
        response=response,
    )
