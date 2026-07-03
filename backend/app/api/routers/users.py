from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import session_dep
from app.api.schemas import UserOut
from app.application.use_cases import ListUsersUseCase
from app.domain.traffic_light import TrafficLight

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserOut])
def list_users(
    post: str | None = Query(default=None, description="filter to a post media_pk"),
    status: TrafficLight | None = Query(default=None),
    search: str | None = Query(default=None, description="username contains"),
    order: str = Query(default="username", pattern="^(username|status)$"),
    session: Session = Depends(session_dep),
) -> list[UserOut]:
    views = ListUsersUseCase(session).execute(post=post, status=status, search=search, order=order)
    return [UserOut.model_validate(v, from_attributes=True) for v in views]
