from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import session_dep
from app.api.schemas import PostOut
from app.infrastructure.persistence.repositories import PostRepository

router = APIRouter(tags=["posts"])


@router.get("/posts", response_model=list[PostOut])
def list_posts(
    event: int | None = Query(default=None, description="filter to a fiesta id"),
    session: Session = Depends(session_dep),
) -> list[PostOut]:
    posts = PostRepository(session).list_all(event_id=event)
    return [PostOut.model_validate(p, from_attributes=True) for p in posts]
