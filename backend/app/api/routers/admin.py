"""Danger zone: wipe every scraped record so the tool starts from scratch.

Destructive and irreversible (only re-scanning brings data back), so it's
gated behind a typed confirmation phrase and refuses while a campaign runs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, col, delete, func, select

from app.api.deps import session_dep
from app.api.schemas import ResetIn, ResetOut
from app.infrastructure.persistence import models

router = APIRouter(tags=["admin"])

CONFIRM_PHRASE = "BORRAR TODO"

# Children before parents (harmless without FK enforcement, but explicit).
_TABLES: list[tuple[str, type[SQLModel]]] = [
    ("campaign_targets", models.CampaignTarget),
    ("campaigns", models.Campaign),
    ("engagements", models.Engagement),
    ("dm_threads", models.DmThread),
    ("posts", models.Post),
    ("events", models.Event),
    ("activity_log", models.ActivityLog),
    ("users", models.User),
]


@router.post("/reset", response_model=ResetOut)
def reset_all(body: ResetIn, session: Session = Depends(session_dep)) -> ResetOut:
    if body.confirm.strip() != CONFIRM_PHRASE:
        raise HTTPException(
            422,
            detail={"code": "bad_request", "message": f'escribí "{CONFIRM_PHRASE}" para confirmar'},
        )

    active = session.exec(
        select(models.Campaign).where(col(models.Campaign.status).in_(["running", "paused"]))
    ).first()
    if active is not None:
        raise HTTPException(
            409,
            detail={"code": "conflict", "message": "hay una campaña activa; pausala primero"},
        )

    deleted: dict[str, int] = {}
    for name, model in _TABLES:
        count = session.exec(select(func.count()).select_from(model)).one()
        session.exec(delete(model))
        deleted[name] = int(count)
    session.commit()
    return ResetOut(deleted=deleted)
