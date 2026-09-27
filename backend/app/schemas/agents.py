import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import E164, ORM, Timezone, WorkingHours

TRANSFER_TRIGGERS = {"caller_request", "low_confidence", "repeated_failure", "sensitive_topic", "tool_error"}


def validate_actions(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    from app.services.tools.registry import TOOL_SPECS

    unknown = set(v) - set(TOOL_SPECS)
    if unknown:
        raise ValueError(f"Unknown actions: {sorted(unknown)}")
    return sorted(set(v))


def validate_triggers(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    unknown = set(v) - TRANSFER_TRIGGERS
    if unknown:
        raise ValueError(f"Unknown transfer triggers: {sorted(unknown)}")
    return sorted(set(v))


class AgentBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_active: bool = True
    language: str = Field(default="en", max_length=16)
    timezone: Timezone = "UTC"
    greeting: str = Field(default="", max_length=1000)
    after_hours_greeting: str = Field(default="", max_length=1000)
    personality: str = Field(default="", max_length=4000)
    system_instructions: str = Field(default="", max_length=12000)
    business_info: str = Field(default="", max_length=20000)
    working_hours: WorkingHours | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    llm_model: str = Field(default="gpt-4o-mini", max_length=100)
    fallback_llm_model: str = Field(default="gemini-3.5-flash-lite", max_length=100)
    stt_model: str = Field(default="nova-3", max_length=100)
    tts_provider: str = Field(default="openai", pattern="^(openai|cartesia)$")
    tts_voice: str = Field(default="alloy", max_length=100)
    temperature: float = Field(default=0.4, ge=0, le=1.5)
    min_endpointing_delay: float = Field(default=0.5, ge=0.1, le=3)
    max_endpointing_delay: float = Field(default=5.0, ge=0.5, le=15)
    allow_interruptions: bool = True
    silence_timeout_seconds: int = Field(default=12, ge=3, le=120)
    max_call_minutes: int = Field(default=20, ge=1, le=120)
    transfer_enabled: bool = False
    transfer_number: E164 | None = None
    transfer_triggers: list[str] = Field(default_factory=lambda: ["caller_request", "repeated_failure", "tool_error"])
    max_failed_turns: int = Field(default=2, ge=1, le=10)
    fallback_message: str = Field(
        default="I'm not able to help with that safely. Let me connect you with someone from our team.",
        max_length=1000,
    )
    appointment_duration_minutes: int = Field(default=60, ge=10, le=480)

    @field_validator("allowed_actions")
    @classmethod
    def _actions(cls, v):
        return validate_actions(v)

    @field_validator("transfer_triggers")
    @classmethod
    def _triggers(cls, v):
        return validate_triggers(v)


class AgentCreate(AgentBase):
    pass


class AgentUpdate(BaseModel):
    """Partial update: every field optional, same validation as AgentBase."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None
    language: str | None = Field(default=None, max_length=16)
    timezone: Timezone | None = None
    greeting: str | None = Field(default=None, max_length=1000)
    after_hours_greeting: str | None = Field(default=None, max_length=1000)
    personality: str | None = Field(default=None, max_length=4000)
    system_instructions: str | None = Field(default=None, max_length=12000)
    business_info: str | None = Field(default=None, max_length=20000)
    working_hours: WorkingHours | None = None
    allowed_actions: list[str] | None = None
    llm_model: str | None = Field(default=None, max_length=100)
    fallback_llm_model: str | None = Field(default=None, max_length=100)
    stt_model: str | None = Field(default=None, max_length=100)
    tts_provider: str | None = Field(default=None, pattern="^(openai|cartesia)$")
    tts_voice: str | None = Field(default=None, max_length=100)
    temperature: float | None = Field(default=None, ge=0, le=1.5)
    min_endpointing_delay: float | None = Field(default=None, ge=0.1, le=3)
    max_endpointing_delay: float | None = Field(default=None, ge=0.5, le=15)
    allow_interruptions: bool | None = None
    silence_timeout_seconds: int | None = Field(default=None, ge=3, le=120)
    max_call_minutes: int | None = Field(default=None, ge=1, le=120)
    transfer_enabled: bool | None = None
    transfer_number: E164 | None = None
    transfer_triggers: list[str] | None = None
    max_failed_turns: int | None = Field(default=None, ge=1, le=10)
    fallback_message: str | None = Field(default=None, max_length=1000)
    appointment_duration_minutes: int | None = Field(default=None, ge=10, le=480)

    @field_validator("allowed_actions")
    @classmethod
    def _actions(cls, v):
        return validate_actions(v)

    @field_validator("transfer_triggers")
    @classmethod
    def _triggers(cls, v):
        return validate_triggers(v)


class AgentOut(ORM, AgentBase):
    id: uuid.UUID
    working_hours: dict
    transfer_number: str | None
    created_at: datetime
    updated_at: datetime


class PhoneNumberIn(BaseModel):
    e164: E164
    friendly_name: str = Field(default="", max_length=120)
    agent_id: uuid.UUID | None = None


class PhoneNumberUpdate(BaseModel):
    friendly_name: str | None = Field(default=None, max_length=120)
    agent_id: uuid.UUID | None = None


class PhoneNumberOut(ORM):
    id: uuid.UUID
    e164: str
    friendly_name: str
    provider: str
    provider_sid: str | None
    agent_id: uuid.UUID | None
    created_at: datetime


class TestCallIn(BaseModel):
    agent_id: uuid.UUID
    # The phone number the agent treats as the caller's (used for booking/finding appointments).
    caller_phone: E164 = "+15550100000"
    # When set, the agent phones this number instead of talking in the browser.
    dial_number: E164 | None = None


class OutboundCallIn(BaseModel):
    to: E164
    from_number_id: uuid.UUID
    purpose: str = Field(default="", max_length=500)
