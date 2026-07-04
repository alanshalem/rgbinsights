from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas import TaskOut
from app.application.tasks import registry

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks() -> list[TaskOut]:
    return [TaskOut.model_validate(t, from_attributes=True) for t in registry.list()]
