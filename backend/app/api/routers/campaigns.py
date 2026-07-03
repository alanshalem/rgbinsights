from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, func, select

from app.api.deps import raise_for_err, session_dep, source_dep
from app.api.schemas import (
    CampaignCreate,
    CampaignOut,
    CampaignPreviewOut,
    EstimateOut,
    MessageSample,
    PresetOut,
    SendParamsIn,
)
from app.application import campaign as camp
from app.application import campaign_sender
from app.application.dto import UserView
from app.application.use_cases import ListUsersUseCase
from app.domain.result import Err, ErrorCode
from app.domain.traffic_light import TrafficLight
from app.infrastructure.instagram.base import InstagramSource
from app.infrastructure.instagram.errors import InstagramError
from app.infrastructure.persistence import models
from app.infrastructure.persistence.repositories import EventRepository

router = APIRouter(tags=["campaigns"])


def _params(body: SendParamsIn) -> camp.SendParams:
    if body.delay_max < body.delay_min:
        raise HTTPException(422, detail={"code": "bad_request", "message": "delay_max<delay_min"})
    if body.hour_end <= body.hour_start:
        raise HTTPException(422, detail={"code": "bad_request", "message": "hour_end<=hour_start"})
    return camp.SendParams(
        delay_min=body.delay_min,
        delay_max=body.delay_max,
        daily_cap=body.daily_cap,
        hour_start=body.hour_start,
        hour_end=body.hour_end,
    )


def _reds(session: Session, event_id: int) -> list[UserView]:
    return ListUsersUseCase(session).execute(event=event_id, status=TrafficLight.RED)


def _require_event(session: Session, event_id: int) -> None:
    if EventRepository(session).get(event_id) is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "fiesta"})


@router.get("/campaigns/presets", response_model=list[PresetOut])
def presets() -> list[PresetOut]:
    return [
        PresetOut(
            name=name,
            delay_min=p.delay_min,
            delay_max=p.delay_max,
            daily_cap=p.daily_cap,
            hour_start=p.hour_start,
            hour_end=p.hour_end,
        )
        for name, p in camp.PRESETS.items()
    ]


@router.post("/events/{event_id}/campaign/preview", response_model=CampaignPreviewOut)
def preview(
    event_id: int, body: CampaignCreate, session: Session = Depends(session_dep)
) -> CampaignPreviewOut:
    _require_event(session, event_id)
    params = _params(body)
    reds = _reds(session, event_id)
    est = camp.estimate(len(reds), params)
    samples = [
        MessageSample(
            username=u.username,
            message=camp.render_message(body.templates, u.username, u.full_name, u.pk),
        )
        for u in reds[:5]
    ]
    return CampaignPreviewOut(
        targets_count=len(reds),
        estimate=EstimateOut(
            per_day=est.per_day, days=est.days, avg_delay_seconds=est.avg_delay_seconds
        ),
        samples=samples,
    )


@router.post("/events/{event_id}/campaign/test", response_model=MessageSample)
def test_send(
    event_id: int,
    body: CampaignCreate,
    session: Session = Depends(session_dep),
    source: InstagramSource = Depends(source_dep),
) -> MessageSample:
    """Send ONE real DM to the first red — verify it lands before the batch."""
    _require_event(session, event_id)
    reds = _reds(session, event_id)
    if not reds:
        raise HTTPException(422, detail={"code": "bad_request", "message": "no hay usuarios rojos"})
    target = reds[0]
    message = camp.render_message(body.templates, target.username, target.full_name, target.pk)
    try:
        source.send_dm(target.pk, message)
    except InstagramError as exc:
        raise_for_err(Err(ErrorCode.CHALLENGE_REQUIRED, str(exc)))
    return MessageSample(username=target.username, message=message)


@router.post("/events/{event_id}/campaign", response_model=CampaignOut)
def create_campaign(
    event_id: int, body: CampaignCreate, session: Session = Depends(session_dep)
) -> CampaignOut:
    _require_event(session, event_id)
    params = _params(body)

    active = session.exec(
        select(models.Campaign).where(col(models.Campaign.status).in_(["running", "paused"]))
    ).first()
    if active is not None:
        raise HTTPException(
            409,
            detail={"code": "conflict", "message": "ya hay una campaña activa; pausala o esperá"},
        )

    reds = _reds(session, event_id)
    if not reds:
        raise HTTPException(422, detail={"code": "bad_request", "message": "no hay usuarios rojos"})

    now = datetime.now(UTC)
    campaign = models.Campaign(
        event_id=event_id,
        status="running",
        templates=json.dumps(body.templates),
        delay_min=params.delay_min,
        delay_max=params.delay_max,
        daily_cap=params.daily_cap,
        hour_start=params.hour_start,
        hour_end=params.hour_end,
        sent_today_date=now.date().isoformat(),
        created_at=now,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    for u in reds:
        session.add(
            models.CampaignTarget(
                campaign_id=campaign.id,
                user_pk=u.pk,
                username=u.username,
                message=camp.render_message(body.templates, u.username, u.full_name, u.pk),
            )
        )
    session.commit()

    assert campaign.id is not None
    campaign_sender.start(campaign.id)
    return _to_out(session, campaign)


@router.get("/events/{event_id}/campaign", response_model=CampaignOut | None)
def latest_campaign(
    event_id: int, session: Session = Depends(session_dep)
) -> CampaignOut | None:
    campaign = session.exec(
        select(models.Campaign)
        .where(models.Campaign.event_id == event_id)
        .order_by(col(models.Campaign.id).desc())
    ).first()
    return _to_out(session, campaign) if campaign is not None else None


@router.post("/campaigns/{campaign_id}/stop", response_model=CampaignOut)
def stop_campaign(campaign_id: int, session: Session = Depends(session_dep)) -> CampaignOut:
    campaign = _get(session, campaign_id)
    if campaign.status == "running":
        campaign.status = "paused"
        session.add(campaign)
        session.commit()
    return _to_out(session, campaign)


@router.post("/campaigns/{campaign_id}/resume", response_model=CampaignOut)
def resume_campaign(campaign_id: int, session: Session = Depends(session_dep)) -> CampaignOut:
    campaign = _get(session, campaign_id)
    if campaign.status in ("paused", "blocked"):
        campaign.status = "running"
        campaign.error = None
        session.add(campaign)
        session.commit()
        assert campaign.id is not None
        campaign_sender.start(campaign.id)
    return _to_out(session, campaign)


def _get(session: Session, campaign_id: int) -> models.Campaign:
    campaign = session.get(models.Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "campaña"})
    return campaign


def _to_out(session: Session, campaign: models.Campaign) -> CampaignOut:
    assert campaign.id is not None
    counts: dict[str, int] = {"pending": 0, "sent": 0, "failed": 0}
    rows = session.exec(
        select(models.CampaignTarget.status, func.count())
        .where(models.CampaignTarget.campaign_id == campaign.id)
        .group_by(col(models.CampaignTarget.status))
    )
    for status, n in rows:
        counts[status] = n
    total = counts["pending"] + counts["sent"] + counts["failed"]
    return CampaignOut(
        id=campaign.id,
        event_id=campaign.event_id,
        status=campaign.status,
        total=total,
        sent=counts["sent"],
        pending=counts["pending"],
        failed=counts["failed"],
        sent_today=campaign.sent_today,
        daily_cap=campaign.daily_cap,
        delay_min=campaign.delay_min,
        delay_max=campaign.delay_max,
        hour_start=campaign.hour_start,
        hour_end=campaign.hour_end,
        last_sent_at=campaign.last_sent_at,
        error=campaign.error,
    )
