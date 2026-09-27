import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, DateTime, JSONType, Timestamps, UUIDPk, utcnow


class PhoneNumber(UUIDPk, Timestamps, Base):
    __tablename__ = "phone_numbers"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    e164: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    friendly_name: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(32), default="twilio")
    provider_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    agent: Mapped["AgentConfig | None"] = relationship(back_populates="phone_numbers")  # noqa: F821


class Customer(UUIDPk, Timestamps, Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("org_id", "phone", name="uq_customers_org_phone"),)

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class CallDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class CallStatus(str, enum.Enum):
    ringing = "ringing"
    in_progress = "in_progress"
    transferring = "transferring"
    completed = "completed"
    transferred = "transferred"
    failed = "failed"
    no_answer = "no_answer"


ACTIVE_STATUSES = (CallStatus.ringing, CallStatus.in_progress, CallStatus.transferring)


class CallOutcome(str, enum.Enum):
    resolved = "resolved"
    appointment_booked = "appointment_booked"
    appointment_rescheduled = "appointment_rescheduled"
    appointment_cancelled = "appointment_cancelled"
    transferred = "transferred"
    unresolved = "unresolved"
    abandoned = "abandoned"
    error = "error"


class Call(UUIDPk, Timestamps, Base):
    __tablename__ = "calls"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("phone_numbers.id", ondelete="SET NULL"), nullable=True
    )
    direction: Mapped[CallDirection] = mapped_column(Enum(CallDirection, name="call_direction"))
    status: Mapped[CallStatus] = mapped_column(Enum(CallStatus, name="call_status"), default=CallStatus.ringing, index=True)
    outcome: Mapped[CallOutcome | None] = mapped_column(Enum(CallOutcome, name="call_outcome"), nullable=True)
    from_number: Mapped[str] = mapped_column(String(32))
    to_number: Mapped[str] = mapped_column(String(32))
    provider_call_sid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    livekit_room: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_turns: Mapped[int] = mapped_column(Integer, default=0)
    # Aggregated latency / usage metrics reported by the voice worker
    metrics: Mapped[dict] = mapped_column(JSONType, default=dict)

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="call", order_by="TranscriptSegment.sequence", cascade="all, delete-orphan"
    )
    events: Mapped[list["CallEvent"]] = relationship(
        back_populates="call", order_by="CallEvent.created_at", cascade="all, delete-orphan"
    )


class TranscriptSegment(UUIDPk, Base):
    __tablename__ = "transcript_segments"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    text: Mapped[str] = mapped_column(Text)
    interrupted: Mapped[bool] = mapped_column(default=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    call: Mapped[Call] = relationship(back_populates="segments")


class CallEvent(UUIDPk, Base):
    """Timeline of everything that happened during a call: status changes, intents,
    knowledge retrievals (with sources), tool calls, transfers, errors, metrics."""

    __tablename__ = "call_events"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    call: Mapped[Call] = relationship(back_populates="events")
