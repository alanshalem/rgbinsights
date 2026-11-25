from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import uow_dep
from app.api.schemas import StatusCountsOut, UserOut
from app.application.ports import UnitOfWork
from app.application.use_cases import (
    DEFAULT_ORDER,
    ORDER_PATTERN,
    ExportUsersUseCase,
    ListUsersUseCase,
)
from app.domain.traffic_light import TrafficLight
from app.infrastructure.config.settings import Settings, get_settings
from app.infrastructure.export import (
    PDF_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    render_pdf,
    render_xlsx,
)

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    event: int | None = Query(default=None, description="filter to a fiesta id"),
    post: str | None = Query(default=None, description="filter to a post media_pk"),
    status: TrafficLight | None = Query(default=None),
    search: str | None = Query(default=None, description="username / full name contains"),
    order: str = Query(default=DEFAULT_ORDER, pattern=ORDER_PATTERN),
    follows: bool | None = Query(default=None, description="true = solo los que te siguen"),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    uow: UnitOfWork = Depends(uow_dep),
) -> list[UserOut]:
    views = ListUsersUseCase(uow).execute(
        event=event,
        post=post,
        status=status,
        search=search,
        order=order,
        follows=follows,
        limit=limit,
        offset=offset,
    )
    return [UserOut.model_validate(v, from_attributes=True) for v in views]


@router.get(
    "/users/export",
    response_class=Response,
    responses={
        200: {
            "content": {XLSX_MEDIA_TYPE: {}, PDF_MEDIA_TYPE: {}},
            "description": "Archivo descargable (attachment).",
        }
    },
)
def export_users(
    format: Literal["xlsx", "pdf"] = Query(description="xlsx = Excel, pdf = PDF"),
    event: int | None = Query(default=None, description="filter to a fiesta id"),
    post: str | None = Query(default=None, description="filter to a post media_pk"),
    status: TrafficLight | None = Query(default=None),
    search: str | None = Query(default=None, description="username / full name contains"),
    order: str = Query(default=DEFAULT_ORDER, pattern=ORDER_PATTERN),
    follows: bool | None = Query(default=None, description="true = solo los que te siguen"),
    by_status: bool = Query(
        default=False, description="true = agrupado rojo/amarillo/verde, como el Board"
    ),
    uow: UnitOfWork = Depends(uow_dep),
    settings: Settings = Depends(get_settings),
) -> Response:
    """The on-screen semáforo list as a file: same filters as /users, every row.

    Reads only the local DB (never Instagram)."""
    export = ExportUsersUseCase(uow, tz=settings.local_tz()).execute(
        event=event,
        post=post,
        status=status,
        search=search,
        order=order,
        follows=follows,
        by_status=by_status,
    )
    if format == "xlsx":
        content, media_type = render_xlsx(export), XLSX_MEDIA_TYPE
    else:
        content, media_type = render_pdf(export), PDF_MEDIA_TYPE
    filename = export.filename(format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/users/counts", response_model=StatusCountsOut)
def user_counts(
    event: int | None = Query(default=None),
    post: str | None = Query(default=None),
    search: str | None = Query(default=None),
    follows: bool | None = Query(default=None),
    uow: UnitOfWork = Depends(uow_dep),
) -> StatusCountsOut:
    counts = ListUsersUseCase(uow).counts(event=event, post=post, search=search, follows=follows)
    return StatusCountsOut.model_validate(counts, from_attributes=True)
