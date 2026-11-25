from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.deps import source_dep, start_job, uow_factory_dep
from app.api.schemas import ScanPostsRequest, TaskOut
from app.application.ports import InstagramSource, UnitOfWork, UnitOfWorkFactory
from app.application.tasks import Task, scan_summary
from app.application.use_cases import ScanPostsUseCase, event_counts
from app.infrastructure.config.settings import Settings, get_settings

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("/posts", response_model=TaskOut, status_code=202)
def scan_posts(
    body: ScanPostsRequest,
    response: Response,
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
    new_uow: UnitOfWorkFactory = Depends(uow_factory_dep),
) -> TaskOut:
    """Background job (202 + the job): progress/result via /tasks/stream or /tasks/{id}."""
    urls, date_from, date_to = body.urls, body.date_from, body.date_to
    if not urls and not (date_from and date_to):
        raise HTTPException(
            status_code=422,
            detail={"code": "bad_request", "message": "provide urls or from+to"},
        )
    recent_limit = settings.recent_posts_limit

    def work(task: Task, uow: UnitOfWork) -> None:
        use_case = ScanPostsUseCase(source, uow)
        before = event_counts(uow, body.event_id)
        if urls:
            result = use_case.by_urls(urls, body.event_id, task.progress)
        else:
            assert date_from is not None and date_to is not None
            result = use_case.by_date_range(
                date_from, date_to, body.event_id, recent_limit=recent_limit
            )
        batch = task.unwrap(result)
        task.set_result(scan_summary(batch, before, event_counts(uow, body.event_id)))

    return start_job(
        kind="scan",
        label="Escaneando posts",
        params=body.model_dump(mode="json"),
        work=work,
        new_uow=new_uow,
        response=response,
    )
