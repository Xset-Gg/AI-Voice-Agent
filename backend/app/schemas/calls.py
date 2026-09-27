import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import CallDirection, CallOutcome, CallStatus
from app.schemas.common import ORM


class SegmentOut(ORM):
    id: uuid.UUID
    sequence: int
    role: str
    text: str
    interrupted: bool
    created_at: datetime


class EventOut(ORM):
    id: uuid.UUID
    type: str
    data: dict
    created_at: datetime


class CallSummaryOut(ORM):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    direction: CallDirection
    status: CallStatus
    outcome: CallOutcome | None
    from_number: str
    to_number: str
    intent: str | None
    summary: str
    started_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    end_reason: str | None


class CallDetailOut(CallSummaryOut):
    livekit_room: str | None
    provider_call_sid: str | None
    metrics: dict
    segments: list[SegmentOut]
    events: list[EventOut]


class CallPage(BaseModel):
    items: list[CallSummaryOut]
    total: int
    page: int
    page_size: int


class OverviewOut(BaseModel):
    calls_today: int
    active_calls: int
    avg_duration_seconds: float | None
    resolution_rate: float | None
    transfer_rate: float | None
    appointments_booked_7d: int
    outcomes_7d: dict[str, int]
    intents_7d: dict[str, int]
    calls_per_day: list[dict]
    documents_ready: int
    avg_response_latency_ms: float | None
