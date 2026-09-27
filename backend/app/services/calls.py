"""Call lifecycle, transcript and event persistence (+ live fan-out to the dashboard)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.models import ACTIVE_STATUSES, Call, CallEvent, CallOutcome, CallStatus, TranscriptSegment
from app.services import events


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def get_call(db: AsyncSession, call_id: uuid.UUID, org_id: uuid.UUID | None = None) -> Call:
    call = await db.get(Call, call_id)
    if call is None or (org_id is not None and call.org_id != org_id):
        raise NotFound("Call")
    return call


async def add_event(db: AsyncSession, call: Call, type_: str, data: dict, commit: bool = True) -> CallEvent:
    ev = CallEvent(call_id=call.id, type=type_, data=data)
    db.add(ev)
    if commit:
        await db.commit()
    await events.publish(call.org_id, call.id, type_, {**data, "event_id": ev.id, "at": ev.created_at})
    return ev


async def add_segment(
    db: AsyncSession, call: Call, role: str, text: str, interrupted: bool = False, confidence: float | None = None
) -> TranscriptSegment:
    seq = (
        await db.execute(select(func.coalesce(func.max(TranscriptSegment.sequence), 0)).where(TranscriptSegment.call_id == call.id))
    ).scalar_one()
    seg = TranscriptSegment(
        call_id=call.id, sequence=seq + 1, role=role, text=text, interrupted=interrupted, confidence=confidence
    )
    db.add(seg)
    await db.commit()
    await events.publish(
        call.org_id, call.id, "transcript",
        {"segment_id": seg.id, "sequence": seg.sequence, "role": role, "text": text, "interrupted": interrupted, "at": seg.created_at},
    )
    return seg


async def set_status(db: AsyncSession, call: Call, status: CallStatus, **fields) -> Call:
    now = datetime.now(timezone.utc)
    call.status = status
    if status == CallStatus.in_progress and call.answered_at is None:
        call.answered_at = now
    for k, v in fields.items():
        setattr(call, k, v)
    if status not in ACTIVE_STATUSES and call.ended_at is None:
        call.ended_at = now
        start = _aware(call.answered_at) or _aware(call.started_at)
        call.duration_seconds = max(int((now - start).total_seconds()), 0)
        if call.outcome is None:
            call.outcome = {
                CallStatus.transferred: CallOutcome.transferred,
                CallStatus.failed: CallOutcome.error,
                CallStatus.no_answer: CallOutcome.abandoned,
            }.get(status, CallOutcome.unresolved if call.answered_at else CallOutcome.abandoned)
    await db.commit()
    await events.publish(
        call.org_id, call.id, "status",
        {
            "status": call.status.value,
            "outcome": call.outcome.value if call.outcome else None,
            "duration_seconds": call.duration_seconds,
            "from_number": call.from_number,
            "to_number": call.to_number,
            "direction": call.direction.value,
            "started_at": call.started_at,
            "answered_at": call.answered_at,
        },
    )
    return call


OUTCOME_PRIORITY = {
    None: 0, CallOutcome.abandoned: 1, CallOutcome.unresolved: 1, CallOutcome.error: 1, CallOutcome.resolved: 2,
    CallOutcome.appointment_cancelled: 3, CallOutcome.appointment_rescheduled: 3,
    CallOutcome.appointment_booked: 4, CallOutcome.transferred: 5,
}


def promote_outcome(call: Call, outcome: CallOutcome) -> None:
    """Keep the most significant outcome reached during the call."""
    if OUTCOME_PRIORITY[outcome] >= OUTCOME_PRIORITY[call.outcome]:
        call.outcome = outcome
