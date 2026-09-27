"""Server-side execution of voice-agent tool calls with permission checks, strict argument
validation, caller-scoped authorization, auditing and live event publishing."""

import time
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import log
from app.models import AgentConfig, Call, CallDirection, CallOutcome, CallStatus
from app.services import audit, scheduling
from app.services.calls import add_event, promote_outcome, set_status
from app.services.rag.retriever import retrieve
from app.services.rag.sanitize import wrap_sources
from app.services.tools.registry import TOOL_SPECS, enabled_tools


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=500)


class AvailabilityArgs(BaseModel):
    date: date
    service: str | None = Field(default=None, max_length=200)
    technician_id: uuid.UUID | None = None


class BookArgs(BaseModel):
    technician_id: uuid.UUID
    start_time: AwareDatetime
    service: str = Field(min_length=1, max_length=200)
    customer_name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=1000)


class AppointmentRefArgs(BaseModel):
    appointment_id: uuid.UUID


class RescheduleArgs(AppointmentRefArgs):
    new_start_time: AwareDatetime


class TransferArgs(BaseModel):
    reason: str = Field(default="caller_request", max_length=200)


class NoArgs(BaseModel):
    pass


class EndCallArgs(BaseModel):
    reason: str = Field(default="caller_done", max_length=200)


ARG_MODELS: dict[str, type[BaseModel]] = {
    "search_knowledge_base": SearchArgs,
    "check_availability": AvailabilityArgs,
    "book_appointment": BookArgs,
    "find_my_appointments": NoArgs,
    "reschedule_appointment": RescheduleArgs,
    "cancel_appointment": AppointmentRefArgs,
    "transfer_to_human": TransferArgs,
    "end_call": EndCallArgs,
}


class ToolDenied(Exception):
    pass


def caller_phone(call: Call) -> str:
    return call.from_number if call.direction == CallDirection.inbound else call.to_number


def _fmt(dt: datetime, tz: str) -> str:
    """Speech-friendly local time, e.g. 'Tuesday March 4 at 2:30 PM' (portable, no %-d)."""
    local = dt.astimezone(ZoneInfo(tz))
    hour = local.hour % 12 or 12
    return f"{local:%A %B} {local.day} at {hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def _appt_view(a, tz: str) -> dict:
    return {
        "appointment_id": str(a.id),
        "service": a.service,
        "technician": a.technician.name,
        "when": _fmt(a.starts_at, tz),
        "start_time": a.starts_at.astimezone(ZoneInfo(tz)).isoformat(),
        "status": a.status.value,
    }


async def execute(db: AsyncSession, call: Call, agent: AgentConfig, name: str, raw_args: dict) -> dict:
    started = time.perf_counter()
    result: dict
    status = "ok"
    # Snapshot what we need afterwards: a rollback expires ORM instances.
    call_id, agent_id = call.id, agent.id
    suggest_on_error = "tool_error" in agent.transfer_triggers and agent.transfer_enabled
    try:
        if name not in TOOL_SPECS:
            raise ToolDenied(f"Unknown tool '{name}'")
        if name not in enabled_tools(agent.allowed_actions, agent.transfer_enabled):
            raise ToolDenied(f"The action '{name}' is not enabled for this business")
        if call.status not in (CallStatus.in_progress, CallStatus.ringing):
            raise ToolDenied("Call is no longer active")
        try:
            args = ARG_MODELS[name].model_validate(raw_args or {})
        except ValidationError as e:
            status = "invalid_arguments"
            result = {"ok": False, "error": "Invalid arguments: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())}
        else:
            result = await _dispatch(db, call, agent, name, args)
            if not result.get("ok", True):
                status = "failed"
    except ToolDenied as e:
        status = "denied"
        result = {"ok": False, "error": str(e)}
    except AppError as e:
        await db.rollback()
        status = "failed"
        result = {"ok": False, "error": e.message, "code": e.code}
    except Exception as e:
        await db.rollback()
        log.exception("tool_error", tool=name, call_id=str(call_id))
        status = "error"
        result = {"ok": False, "error": "The system had a problem completing that action."}

    call = await db.get(Call, call_id)
    duration_ms = int((time.perf_counter() - started) * 1000)
    if status in ("failed", "error") and suggest_on_error:
        result["suggest_transfer"] = True

    # Knowledge retrievals get their own event type so the dashboard can show sources.
    event_type = "retrieval" if name == "search_knowledge_base" else "tool_call"
    event_data = {"tool": name, "arguments": raw_args, "status": status, "duration_ms": duration_ms}
    if event_type == "retrieval":
        event_data["query"] = raw_args.get("query")
        event_data["sources"] = result.pop("_sources", [])
        event_data["found"] = bool(event_data["sources"])
    else:
        event_data["result"] = {k: v for k, v in result.items() if k != "context"}
    await add_event(db, call, event_type, event_data, commit=False)
    if TOOL_SPECS.get(name) and TOOL_SPECS[name].mutates and status == "ok":
        await audit.record(
            db, action=f"voice_agent.{name}", actor="voice_agent", org_id=call.org_id,
            resource_type="call", resource_id=call.id, data={"arguments": raw_args, "result": event_data.get("result")},
        )
    await db.commit()
    return result


async def _dispatch(db: AsyncSession, call: Call, agent: AgentConfig, name: str, args) -> dict:
    tz = agent.timezone
    phone = caller_phone(call)

    if name == "search_knowledge_base":
        sources = await retrieve(db, call.org_id, args.query)
        return {
            "ok": True,
            "found": bool(sources),
            "context": wrap_sources(sources),
            "_sources": [
                {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in s.items() if k != "text"}
                | {"excerpt": s["text"][:300]}
                for s in sources
            ],
        }

    if name == "check_availability":
        today = datetime.now(ZoneInfo(tz)).date()
        if args.date < today:
            return {"ok": False, "error": "That date is in the past."}
        slots = await scheduling.find_availability(
            db, call.org_id, args.date, agent.appointment_duration_minutes,
            technician_id=args.technician_id, service=args.service,
        )
        return {
            "ok": True,
            "date": args.date.isoformat(),
            "slots": [
                {
                    "technician_id": str(s["technician_id"]),
                    "technician": s["technician_name"],
                    "start_time": s["starts_at"].astimezone(ZoneInfo(tz)).isoformat(),
                    "spoken": _fmt(s["starts_at"], tz),
                }
                for s in slots[:12]
            ],
            "note": "No open times that day." if not slots else "Offer the caller two or three of these options.",
        }

    if name == "book_appointment":
        appt = await scheduling.book(
            db, org_id=call.org_id, technician_id=args.technician_id, starts_at=args.start_time,
            duration_minutes=agent.appointment_duration_minutes, customer_phone=phone,
            customer_name=args.customer_name, service=args.service, notes=args.notes,
            call_id=call.id, via="voice_agent",
        )
        call = await db.get(Call, call.id)
        call.customer_id = appt.customer_id
        promote_outcome(call, CallOutcome.appointment_booked)
        return {"ok": True, "confirmed": True, "appointment": _appt_view(appt, tz)}

    if name == "find_my_appointments":
        appts = await scheduling.upcoming_for_phone(db, call.org_id, phone)
        return {"ok": True, "appointments": [_appt_view(a, tz) for a in appts]}

    if name in ("reschedule_appointment", "cancel_appointment"):
        # Authorization: callers may only change appointments booked under their own phone number.
        owned = {a.id for a in await scheduling.upcoming_for_phone(db, call.org_id, phone)}
        if args.appointment_id not in owned:
            return {"ok": False, "error": "No upcoming appointment with that id is booked under the caller's phone number."}
        if name == "reschedule_appointment":
            appt = await scheduling.reschedule(
                db, org_id=call.org_id, appointment_id=args.appointment_id, starts_at=args.new_start_time, via="voice_agent"
            )
            outcome = CallOutcome.appointment_rescheduled
        else:
            appt = await scheduling.cancel(db, org_id=call.org_id, appointment_id=args.appointment_id)
            outcome = CallOutcome.appointment_cancelled
        call = await db.get(Call, call.id)
        promote_outcome(call, outcome)
        return {"ok": True, "confirmed": True, "appointment": _appt_view(appt, tz)}

    if name == "transfer_to_human":
        return await start_transfer(db, call, agent, args.reason)

    if name == "end_call":
        return {"ok": True, "action": "hangup", "reason": args.reason}

    raise ToolDenied(f"Unhandled tool {name}")


async def start_transfer(db: AsyncSession, call: Call, agent: AgentConfig, reason: str) -> dict:
    """Transfer the caller to a human. Inbound Twilio calls are redirected via the Twilio REST API;
    other calls are handed back to the worker to perform a SIP REFER."""
    from app.services.telephony import get_telephony

    if not agent.transfer_enabled or not agent.transfer_number:
        return {"ok": False, "error": "Transfers are not configured for this business."}
    await set_status(db, call, CallStatus.transferring)
    await add_event(db, call, "transfer", {"reason": reason, "to": agent.transfer_number}, commit=False)
    if call.provider_call_sid:
        await get_telephony().transfer(call.provider_call_sid, agent.transfer_number, "")
        call.outcome = CallOutcome.transferred
        await set_status(db, call, CallStatus.transferred, end_reason=f"transferred:{reason}"[:64])
        return {"ok": True, "method": "carrier_redirect", "say_first": False}
    call.outcome = CallOutcome.transferred
    await db.commit()
    return {"ok": True, "method": "sip_refer", "transfer_to": f"tel:{agent.transfer_number}"}
