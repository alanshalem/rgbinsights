from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import session_dep
from app.api.schemas import StatusCountsOut, UserOut
from app.application.use_cases import ListUsersUseCase
from app.domain.traffic_light import TrafficLight

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    event: int | None = Query(default=None, description="filter to a fiesta id"),
    post: str | None = Query(default=None, description="filter to a post media_pk"),
    status: TrafficLight | None = Query(default=None),
    search: str | None = Query(default=None, description="username / full name contains"),
    order: str = Query(default="status", pattern="^(username|status|fans)$"),
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(session_dep),
) -> list[UserOut]:
    views = ListUsersUseCase(session).execute(
        event=event,
        post=post,
        status=status,
        search=search,
        order=order,
        limit=limit,
        offset=offset,
    )
    return [UserOut.model_validate(v, from_attributes=True) for v in views]


@router.get("/users/counts", response_model=StatusCountsOut)
def user_counts(
    event: int | None = Query(default=None),
    post: str | None = Query(default=None),
    search: str | None = Query(default=None),
    session: Session = Depends(session_dep),
) -> StatusCountsOut:
    counts = ListUsersUseCase(session).counts(event=event, post=post, search=search)
    return StatusCountsOut.model_validate(counts, from_attributes=True)
