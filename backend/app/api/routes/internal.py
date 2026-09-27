"""Service-to-service API used by the LiveKit voice worker. Authenticated with INTERNAL_API_TOKEN."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import DB, require_internal_token
from app.core.errors import AppError
from app.core.logging import log
from app.models import ACTIVE_STATUSES, AgentConfig, CallStatus, Customer, Organization
from app.services import jobs
from app.services.calls import add_event, add_segment, get_call, set_status
from app.services.prompt import build_system_prompt, greeting_for
from app.services.tools import executor
from app.services.tools.registry import enabled_tools

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_token)], include_in_schema=False)


async def _call_and_agent(db, call_id: uuid.UUID):
    call = await get_call(db, call_id)
    if call.agent_id is None:
        raise AppError("Call has no agent", code="no_agent")
    agent = await db.get(AgentConfig, call.agent_id)
    return call, agent


@router.get("/calls/{call_id}/context")
async def call_context(call_id: uuid.UUID, db: DB):
    call, agent = await _call_and_agent(db, call_id)
    org = await db.get(Organization, call.org_id)
    customer = await db.get(Customer, call.customer_id) if call.customer_id else None
    caller_name = customer.name if customer and customer.name else None
    return {
        "call_id": str(call.id),
        "org_id": str(call.org_id),
        "direction": call.direction.value,
        "caller_phone": executor.caller_phone(call),
        "business_name": org.name,
        "system_prompt": build_system_prompt(agent, org.name, caller_name),
        "greeting": greeting_for(agent, org.name),
        "outbound_purpose": call.summary if call.direction.value == "outbound" else "",
        "tools": enabled_tools(agent.allowed_actions, agent.transfer_enabled),
        "agent": {
            "name": agent.name,
            "language": agent.language,
            "llm_model": agent.llm_model,
            "fallback_llm_model": agent.fallback_llm_model,
            "stt_model": agent.stt_model,
            "tts_provider": agent.tts_provider,
            "tts_voice": agent.tts_voice,
            "temperature": agent.temperature,
            "min_endpointing_delay": agent.min_endpointing_delay,
            "max_endpointing_delay": agent.max_endpointing_delay,
            "allow_interruptions": agent.allow_interruptions,
            "silence_timeout_seconds": agent.silence_timeout_seconds,
            "max_call_minutes": agent.max_call_minutes,
            "max_failed_turns": agent.max_failed_turns,
            "transfer_enabled": agent.transfer_enabled and bool(agent.transfer_number),
            "transfer_triggers": agent.transfer_triggers,
            "fallback_message": agent.fallback_message,
        },
    }


@router.post("/calls/{call_id}/answered")
async def answered(call_id: uuid.UUID, db: DB):
    call = await get_call(db, call_id)
    if call.status == CallStatus.ringing:
        await set_status(db, call, CallStatus.in_progress)
    return {"ok": True}


class TranscriptIn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)
    interrupted: bool = False
    confidence: float | None = None


@router.post("/calls/{call_id}/transcript")
async def transcript(call_id: uuid.UUID, body: TranscriptIn, db: DB):
    call = await get_call(db, call_id)
    seg = await add_segment(db, call, body.role, body.text, body.interrupted, body.confidence)
    if body.role == "user" and len(body.text.split()) >= 2:
        try:
            await jobs.enqueue_intent(call.id, body.text)
        except Exception as e:  # intent is non-critical
            log.warning("intent_enqueue_failed", error=str(e))
    return {"ok": True, "sequence": seg.sequence}


class ToolIn(BaseModel):
    arguments: dict = Field(default_factory=dict)


@router.post("/calls/{call_id}/tools/{tool_name}")
async def run_tool(call_id: uuid.UUID, tool_name: str, body: ToolIn, db: DB):
    call, agent = await _call_and_agent(db, call_id)
    return await executor.execute(db, call, agent, tool_name, body.arguments)


class EventIn(BaseModel):
    type: Literal["agent_state", "user_state", "interruption", "silence", "failed_turn", "error", "metrics", "llm_fallback"]
    data: dict = Field(default_factory=dict)


@router.post("/calls/{call_id}/events")
async def event(call_id: uuid.UUID, body: EventIn, db: DB):
    call = await get_call(db, call_id)
    if body.type == "failed_turn":
        call.failed_turns += 1
    # High-frequency state changes go live only; the rest are persisted too.
    if body.type in ("agent_state", "user_state"):
        from app.services import events

        await events.publish(call.org_id, call.id, body.type, body.data)
        await db.commit()
    else:
        await add_event(db, call, body.type, body.data)
    return {"ok": True, "failed_turns": call.failed_turns}


class EndIn(BaseModel):
    reason: str = Field(max_length=64)
    metrics: dict = Field(default_factory=dict)


@router.post("/calls/{call_id}/end")
async def end_call(call_id: uuid.UUID, body: EndIn, db: DB):
    call = await get_call(db, call_id)
    call.metrics = {**(call.metrics or {}), **body.metrics}
    if call.status in ACTIVE_STATUSES:
        if call.status == CallStatus.transferring:
            final = CallStatus.transferred
        elif body.reason == "no_answer" and call.answered_at is None:
            final = CallStatus.no_answer
        else:
            final = CallStatus.completed
        await set_status(db, call, final, end_reason=body.reason)
    else:
        await db.commit()
    try:
        await jobs.enqueue_summary(call.id)
    except Exception as e:
        log.warning("summary_enqueue_failed", error=str(e))
    return {"ok": True}


@router.post("/calls/{call_id}/transfer")
async def transfer(call_id: uuid.UUID, db: DB, reason: str = "caller_request"):
    call, agent = await _call_and_agent(db, call_id)
    return await executor.start_transfer(db, call, agent, reason)
