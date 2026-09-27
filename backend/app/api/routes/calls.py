import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, Member, Viewer, client_ip
from app.core.errors import AppError, NotFound
from app.core.logging import log
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import (
    ACTIVE_STATUSES, AgentConfig, Appointment, Call, CallDirection, CallEvent, CallOutcome, CallStatus,
    DocumentStatus, KnowledgeDocument, PhoneNumber, User,
)
from app.core.config import get_settings
from app.schemas.agents import OutboundCallIn, TestCallIn
from app.schemas.calls import CallDetailOut, CallPage, CallSummaryOut, OverviewOut
from app.services import audit, events
from app.services.calls import get_call, set_status
from app.services.livekit_service import livekit_service

router = APIRouter(tags=["calls"])


@router.get("/calls", response_model=CallPage)
async def list_calls(
    principal: Viewer,
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status: CallStatus | None = None,
    outcome: CallOutcome | None = None,
    direction: CallDirection | None = None,
    q: str | None = Query(None, max_length=100, description="Search phone number or summary"),
    since: datetime | None = None,
    until: datetime | None = None,
):
    filters = [Call.org_id == principal.org_id]
    if status:
        filters.append(Call.status == status)
    if outcome:
        filters.append(Call.outcome == outcome)
    if direction:
        filters.append(Call.direction == direction)
    if since:
        filters.append(Call.started_at >= since)
    if until:
        filters.append(Call.started_at <= until)
    if q:
        like = f"%{q}%"
        filters.append(or_(Call.from_number.ilike(like), Call.to_number.ilike(like), Call.summary.ilike(like)))
    total = (await db.execute(select(func.count()).select_from(Call).where(and_(*filters)))).scalar_one()
    rows = (
        await db.execute(
            select(Call).where(and_(*filters)).order_by(Call.started_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return CallPage(items=rows, total=total, page=page, page_size=page_size)


@router.get("/calls/active", response_model=list[CallSummaryOut])
async def active_calls(principal: Viewer, db: DB):
    return (
        await db.execute(
            select(Call).where(Call.org_id == principal.org_id, Call.status.in_(ACTIVE_STATUSES)).order_by(Call.started_at.desc())
        )
    ).scalars().all()


@router.get("/calls/{call_id}", response_model=CallDetailOut)
async def call_detail(call_id: uuid.UUID, principal: Viewer, db: DB):
    call = (
        await db.execute(
            select(Call)
            .options(selectinload(Call.segments), selectinload(Call.events))
            .where(Call.id == call_id, Call.org_id == principal.org_id)
        )
    ).scalar_one_or_none()
    if call is None:
        raise NotFound("Call")
    return call


@router.post("/calls/outbound", response_model=CallSummaryOut, status_code=201)
async def outbound_call(request: Request, body: OutboundCallIn, principal: Member, db: DB):
    num = await db.get(PhoneNumber, body.from_number_id)
    if num is None or num.org_id != principal.org_id:
        raise NotFound("Phone number")
    if num.agent_id is None:
        raise AppError("Assign an agent to this phone number first", code="no_agent")
    agent = await db.get(AgentConfig, num.agent_id)
    call = Call(
        org_id=principal.org_id, agent_id=agent.id, phone_number_id=num.id, direction=CallDirection.outbound,
        from_number=num.e164, to_number=body.to, summary=body.purpose,
    )
    db.add(call)
    await db.flush()
    call.livekit_room = await livekit_service.start_session(call.id, principal.org_id, agent.id, agent.max_call_minutes)
    await audit.record(db, action="call.outbound_started", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="call", resource_id=call.id, data={"to": body.to}, ip_address=client_ip(request))
    await db.commit()
    try:
        await livekit_service.dial_out(call.livekit_room, body.to, num.e164, agent.max_call_minutes)
    except Exception as e:
        await set_status(db, call, CallStatus.failed, end_reason="dial_failed")
        raise AppError(f"Could not place call: {e}", code="dial_failed", status_code=502)
    return call


@router.post("/calls/test", status_code=201)
async def test_call(request: Request, body: TestCallIn, principal: Member, db: DB):
    """Try an agent before going live. Either talk from the browser (returns a room token), or pass
    `dial_number` and the agent phones that number (e.g. the owner's mobile) over the outbound SIP trunk."""
    agent = await db.get(AgentConfig, body.agent_id)
    if agent is None or agent.org_id != principal.org_id:
        raise NotFound("Agent")

    caller_id = None
    if body.dial_number:
        if not get_settings().livekit_outbound_trunk_id:
            raise AppError("Phone calls aren't set up yet: run `python -m app.setup_outbound` with your Twilio keys.",
                           code="outbound_not_configured")
        own = (
            await db.execute(select(PhoneNumber.e164).where(PhoneNumber.org_id == principal.org_id).order_by(PhoneNumber.created_at))
        ).scalars().first()
        caller_id = own or get_settings().twilio_caller_id
        if not caller_id:
            raise AppError("No Twilio number to call from: set TWILIO_CALLER_ID or connect a number", code="no_caller_id")

    call = Call(
        org_id=principal.org_id, agent_id=agent.id,
        direction=CallDirection.outbound if body.dial_number else CallDirection.inbound,
        from_number=caller_id or body.caller_phone, to_number=body.dial_number or "browser-test",
        summary="The business owner asked for this test call from the dashboard to try you out. "
                "Greet them warmly, say you're their AI receptionist, and ask what they'd like to try." if body.dial_number else "",
    )
    db.add(call)
    await db.flush()
    try:
        call.livekit_room = await livekit_service.start_session(call.id, principal.org_id, agent.id, agent.max_call_minutes)
    except Exception:
        await db.rollback()
        raise
    await audit.record(db, action="call.test_started", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="call", resource_id=call.id, data={"phone": body.dial_number} if body.dial_number else {},
                       ip_address=client_ip(request))
    await db.commit()
    await db.refresh(call)

    if body.dial_number:
        try:
            await livekit_service.dial_out(call.livekit_room, body.dial_number, caller_id, agent.max_call_minutes)
        except Exception as e:
            await set_status(db, call, CallStatus.failed, end_reason="dial_failed")
            raise AppError(f"Could not call {body.dial_number}: {e}", code="dial_failed", status_code=502)
        return {"call": CallSummaryOut.model_validate(call), "url": None, "token": None}

    token = livekit_service.participant_token(
        call.livekit_room, identity=f"web-{principal.user.id}", name=principal.user.full_name, ttl_minutes=agent.max_call_minutes + 5,
    )
    return {"call": CallSummaryOut.model_validate(call), "url": get_settings().livekit_url, "token": token}


@router.post("/calls/{call_id}/hangup", response_model=CallSummaryOut)
async def hangup(request: Request, call_id: uuid.UUID, principal: Member, db: DB):
    call = await get_call(db, call_id, principal.org_id)
    if call.status not in ACTIVE_STATUSES:
        raise AppError("Call is not active", code="not_active")
    if call.livekit_room:
        await livekit_service.end_session(call.livekit_room)
    await audit.record(db, action="call.hangup", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="call", resource_id=call.id, ip_address=client_ip(request))
    await set_status(db, call, CallStatus.completed, end_reason="ended_by_staff")
    return call


@router.websocket("/calls/live")
async def live(ws: WebSocket, token: str = Query(...)):
    """Real-time call events for the caller's organization. Auth via ?token=<JWT>
    (browsers can't set headers on WebSocket connections)."""
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        await ws.close(code=4401)
        return
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
    if user is None or not user.is_active:
        await ws.close(code=4401)
        return
    await ws.accept()

    async def pump():
        async for message in events.subscribe(user.org_id):
            await ws.send_text(message)

    task = asyncio.create_task(pump())
    try:
        while True:
            # Keep-alive / detect disconnect; client may send pings.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("ws_error", error=str(e))
    finally:
        task.cancel()


@router.get("/overview", response_model=OverviewOut)
async def overview(principal: Viewer, db: DB):
    org = principal.org_id
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    in_org = Call.org_id == org

    calls_today = (await db.execute(select(func.count()).where(in_org, Call.started_at >= day_start))).scalar_one()
    active = (await db.execute(select(func.count()).where(in_org, Call.status.in_(ACTIVE_STATUSES)))).scalar_one()
    avg_dur = (await db.execute(select(func.avg(Call.duration_seconds)).where(in_org, Call.started_at >= week_ago))).scalar_one()

    outcome_rows = (
        await db.execute(select(Call.outcome, func.count()).where(in_org, Call.started_at >= week_ago).group_by(Call.outcome))
    ).all()
    outcomes = {(o.value if o else "in_progress"): c for o, c in outcome_rows}
    finished = sum(c for o, c in outcome_rows if o is not None)
    resolved = sum(outcomes.get(k, 0) for k in ("resolved", "appointment_booked", "appointment_rescheduled", "appointment_cancelled"))

    intent_rows = (
        await db.execute(
            select(Call.intent, func.count()).where(in_org, Call.started_at >= week_ago, Call.intent.is_not(None)).group_by(Call.intent)
        )
    ).all()

    booked = (
        await db.execute(
            select(func.count()).select_from(Appointment).where(Appointment.org_id == org, Appointment.created_at >= week_ago)
        )
    ).scalar_one()
    docs = (
        await db.execute(
            select(func.count()).select_from(KnowledgeDocument).where(
                KnowledgeDocument.org_id == org, KnowledgeDocument.status == DocumentStatus.ready
            )
        )
    ).scalar_one()

    recent = (await db.execute(select(Call.started_at, Call.metrics).where(in_org, Call.started_at >= now - timedelta(days=14)))).all()
    per_day: dict[str, int] = {}
    latencies = []
    for started, metrics in recent:
        per_day[started.date().isoformat()] = per_day.get(started.date().isoformat(), 0) + 1
        if metrics and metrics.get("avg_response_latency_ms"):
            latencies.append(metrics["avg_response_latency_ms"])
    series = []
    for i in range(13, -1, -1):
        d = (now - timedelta(days=i)).date().isoformat()
        series.append({"date": d, "calls": per_day.get(d, 0)})

    return OverviewOut(
        calls_today=calls_today,
        active_calls=active,
        avg_duration_seconds=float(avg_dur) if avg_dur is not None else None,
        resolution_rate=(resolved / finished) if finished else None,
        transfer_rate=(outcomes.get("transferred", 0) / finished) if finished else None,
        appointments_booked_7d=booked,
        outcomes_7d=outcomes,
        intents_7d={i: c for i, c in intent_rows},
        calls_per_day=series,
        documents_ready=docs,
        avg_response_latency_ms=(sum(latencies) / len(latencies)) if latencies else None,
    )


@router.get("/audit-logs")
async def audit_logs(principal: Member, db: DB, limit: int = Query(100, ge=1, le=500), action: str | None = None):
    from app.models import AuditLog

    q = select(AuditLog).where(AuditLog.org_id == principal.org_id)
    if action:
        q = q.where(AuditLog.action.ilike(f"{action}%"))
    rows = (await db.execute(q.order_by(AuditLog.created_at.desc()).limit(limit))).scalars().all()
    return [
        {"id": r.id, "actor": r.actor, "action": r.action, "resource_type": r.resource_type, "resource_id": r.resource_id,
         "user_id": r.user_id, "data": r.data, "ip_address": r.ip_address, "created_at": r.created_at}
        for r in rows
    ]
