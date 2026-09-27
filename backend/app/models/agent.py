import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType, Timestamps, UUIDPk

# Default weekly schedule: {weekday: [[start, end], ...]} in the agent's timezone.
DEFAULT_WORKING_HOURS = {
    "mon": [["09:00", "17:00"]],
    "tue": [["09:00", "17:00"]],
    "wed": [["09:00", "17:00"]],
    "thu": [["09:00", "17:00"]],
    "fri": [["09:00", "17:00"]],
    "sat": [],
    "sun": [],
}


class AgentConfig(UUIDPk, Timestamps, Base):
    """Per-business AI voice agent: personality, knowledge scope, allowed actions, fallback."""

    __tablename__ = "agent_configs"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))  # the persona's spoken name, e.g. "Ava"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(16), default="en")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")

    greeting: Mapped[str] = mapped_column(Text, default="")
    after_hours_greeting: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    system_instructions: Mapped[str] = mapped_column(Text, default="")
    business_info: Mapped[str] = mapped_column(Text, default="")
    working_hours: Mapped[dict] = mapped_column(JSONType, default=lambda: dict(DEFAULT_WORKING_HOURS))
    allowed_actions: Mapped[list] = mapped_column(JSONType, default=list)

    # Voice pipeline
    llm_model: Mapped[str] = mapped_column(String(100), default="gpt-4o-mini")
    fallback_llm_model: Mapped[str] = mapped_column(String(100), default="gemini-3.5-flash-lite")
    stt_model: Mapped[str] = mapped_column(String(100), default="nova-3")
    tts_provider: Mapped[str] = mapped_column(String(32), default="openai")
    tts_voice: Mapped[str] = mapped_column(String(100), default="alloy")
    temperature: Mapped[float] = mapped_column(Float, default=0.4)

    # Conversation timing
    min_endpointing_delay: Mapped[float] = mapped_column(Float, default=0.5)
    max_endpointing_delay: Mapped[float] = mapped_column(Float, default=5.0)
    allow_interruptions: Mapped[bool] = mapped_column(Boolean, default=True)
    silence_timeout_seconds: Mapped[int] = mapped_column(Integer, default=12)
    max_call_minutes: Mapped[int] = mapped_column(Integer, default=20)

    # Human fallback
    transfer_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Reasons that should trigger a handoff: caller_request, low_confidence, repeated_failure, sensitive_topic, tool_error
    transfer_triggers: Mapped[list] = mapped_column(
        JSONType, default=lambda: ["caller_request", "repeated_failure", "tool_error"]
    )
    max_failed_turns: Mapped[int] = mapped_column(Integer, default=2)
    fallback_message: Mapped[str] = mapped_column(
        Text, default="I'm not able to help with that safely. Let me connect you with someone from our team."
    )
    appointment_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)

    phone_numbers: Mapped[list["PhoneNumber"]] = relationship(back_populates="agent")  # noqa: F821
