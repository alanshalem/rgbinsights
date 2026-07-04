from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, col, select

from app.api.deps import session_dep
from app.api.schemas import ActivityOut, TaskOut
from app.application.tasks import registry
from app.infrastructure.persistence import models

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks() -> list[TaskOut]:
    return [TaskOut.model_validate(t, from_attributes=True) for t in registry.list()]


@router.get("/activity", response_model=list[ActivityOut])
def list_activity(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(session_dep),
) -> list[ActivityOut]:
    rows = session.exec(
        select(models.ActivityLog).order_by(col(models.ActivityLog.id).desc()).limit(limit)
    )
    return [ActivityOut.model_validate(r, from_attributes=True) for r in rows]
