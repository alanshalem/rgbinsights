from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.api.deps import (
    fail_job,
    raise_for_err,
    session_dep,
    session_factory_dep,
    source_dep,
    start_job,
)
from app.api.schemas import ScanPostRequest, ScanPostsRequest, ScanResultOut, TaskOut
from app.application.tasks import SessionFactory, Task, scan_summary
from app.application.use_cases import ScanPostsUseCase, ScanPostUseCase, event_counts
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


@router.post("/posts", response_model=TaskOut, status_code=202)
def scan_posts(
    body: ScanPostsRequest,
    response: Response,
    source: InstagramSource = Depends(source_dep),
    settings: Settings = Depends(get_settings),
    new_session: SessionFactory = Depends(session_factory_dep),
) -> TaskOut:
    """Background job (202 + the job): progress/result via /tasks/stream or /tasks/{id}."""
    urls, date_from, date_to = body.urls, body.date_from, body.date_to
    if not urls and not (date_from and date_to):
        raise HTTPException(
            status_code=422,
            detail={"code": "bad_request", "message": "provide urls or from+to"},
        )
    recent_limit = settings.recent_posts_limit

    def work(task: Task, session: Session) -> None:
        use_case = ScanPostsUseCase(source, session, recent_limit)
        before = event_counts(session, body.event_id)
        if urls:
            result = use_case.by_urls(urls, body.event_id, task.progress)
        else:
            assert date_from is not None and date_to is not None
            result = use_case.by_date_range(date_from, date_to, body.event_id)
        if isinstance(result, Err):
            fail_job(task, result)
            return
        task.set_result(scan_summary(result.value, before, event_counts(session, body.event_id)))

    return start_job(
        kind="scan",
        label="Escaneando posts",
        params=body.model_dump(mode="json"),
        work=work,
        session_factory=new_session,
        response=response,
    )
