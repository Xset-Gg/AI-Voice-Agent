"""Twilio voice webhooks: incoming call → LiveKit voice session, with human fallback."""

import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from twilio.twiml.voice_response import VoiceResponse

from app.api.deps import DB
from app.core.config import get_settings
from app.core.logging import log
from app.models import ACTIVE_STATUSES, AgentConfig, Call, CallDirection, CallStatus, Customer, PhoneNumber
from app.services import audit
from app.services.calls import add_event, set_status
from app.services.livekit_service import livekit_service, sip_uri_for
from app.services.scheduling import upsert_customer
from app.services.telephony import get_telephony

router = APIRouter(prefix="/twilio", tags=["twilio webhooks"], include_in_schema=True)

TWIML = "application/xml"


async def _validated_form(request: Request) -> dict:
    form = dict(await request.form())
    s = get_settings()
    # Twilio signs the exact public URL it called (incl. query string), not our internal URL.
    url = f"{s.public_base_url}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    if not get_telephony().validate_request(url, form, request.headers.get("X-Twilio-Signature")):
        log.warning("twilio_signature_invalid", path=request.url.path)
        raise HTTPException(403, "Invalid Twilio signature")
    return form


def _xml(body: str) -> Response:
    return Response(content=body, media_type=TWIML)


def _fallback_twiml(agent: AgentConfig | None, message: str) -> str:
    """When the AI can't take the call: go to a human if configured, else apologise."""
    if agent and agent.transfer_enabled and agent.transfer_number:
        resp = VoiceResponse()
        resp.say(message)
        resp.dial(agent.transfer_number, timeout=30)
        return str(resp)
    return get_telephony().reject(message + " Please try again later. Goodbye.")


@router.post("/voice")
async def incoming_call(request: Request, db: DB):
    form = await _validated_form(request)
    call_sid, from_n, to_n = form.get("CallSid"), form.get("From", ""), form.get("To", "")
    if not call_sid:
        raise HTTPException(400, "Missing CallSid")
    s = get_settings()

    # Idempotency: Twilio may retry the webhook.
    existing = (await db.execute(select(Call).where(Call.provider_call_sid == call_sid))).scalar_one_or_none()
    if existing and existing.livekit_room:
        return _xml(get_telephony().bridge_to_sip(
            sip_uri_for(existing.livekit_room),
            f"{s.public_base_url}/api/twilio/dial-action?call_id={existing.id}",
            f"{s.public_base_url}/api/twilio/sip-status?call_id={existing.id}",
        ))

    number = (await db.execute(select(PhoneNumber).where(PhoneNumber.e164 == to_n))).scalar_one_or_none()
    if number is None:
        log.warning("call_to_unknown_number", to=to_n)
        return _xml(get_telephony().reject("Sorry, this number is not in service."))
    agent = await db.get(AgentConfig, number.agent_id) if number.agent_id else None
    if agent is None or not agent.is_active:
        return _xml(_fallback_twiml(agent, "Sorry, no one is available to take your call right now."))

    customer: Customer | None = None
    if from_n.startswith("+"):
        customer = await upsert_customer(db, number.org_id, from_n)
    call = Call(
        org_id=number.org_id, agent_id=agent.id, phone_number_id=number.id, customer_id=customer.id if customer else None,
        direction=CallDirection.inbound, from_number=from_n or "unknown", to_number=to_n, provider_call_sid=call_sid,
    )
    db.add(call)
    await db.flush()
    await audit.record(db, action="call.inbound", actor="twilio", org_id=number.org_id, resource_type="call",
                       resource_id=call.id, data={"from": from_n, "to": to_n})
    await db.commit()
    await add_event(db, call, "status", {"status": "ringing", "from_number": from_n, "to_number": to_n, "direction": "inbound"})

    try:
        call.livekit_room = await livekit_service.start_session(call.id, call.org_id, agent.id, agent.max_call_minutes)
        await db.commit()
        twiml = get_telephony().bridge_to_sip(
            sip_uri_for(call.livekit_room),
            f"{s.public_base_url}/api/twilio/dial-action?call_id={call.id}",
            f"{s.public_base_url}/api/twilio/sip-status?call_id={call.id}",
        )
    except Exception as e:
        log.exception("voice_session_start_failed", call_id=str(call.id))
        await add_event(db, call, "error", {"stage": "session_start", "error": str(e)[:500]})
        if agent.transfer_enabled and agent.transfer_number:
            await set_status(db, call, CallStatus.transferred, end_reason="agent_unavailable")
        else:
            await set_status(db, call, CallStatus.failed, end_reason="agent_unavailable")
        return _xml(_fallback_twiml(agent, "Sorry, our assistant is unavailable right now."))
    return _xml(twiml)


@router.post("/dial-action")
async def dial_action(request: Request, db: DB, call_id: uuid.UUID):
    """Called when the SIP leg to LiveKit ends. If it never connected, fall back to a human."""
    form = await _validated_form(request)
    call = await db.get(Call, call_id)
    if call is None:
        return _xml(str(VoiceResponse()))
    dial_status = form.get("DialCallStatus", "")
    agent = await db.get(AgentConfig, call.agent_id) if call.agent_id else None
    if dial_status in ("failed", "busy", "no-answer") and call.answered_at is None:
        await add_event(db, call, "error", {"stage": "sip_bridge", "dial_status": dial_status})
        if agent and agent.transfer_enabled and agent.transfer_number:
            await set_status(db, call, CallStatus.transferred, end_reason="agent_unreachable")
        else:
            await set_status(db, call, CallStatus.failed, end_reason="agent_unreachable")
        return _xml(_fallback_twiml(agent, "Sorry, we're having trouble connecting you."))
    resp = VoiceResponse()
    resp.hangup()
    return _xml(str(resp))


@router.post("/sip-status")
async def sip_status(request: Request, db: DB, call_id: uuid.UUID):
    form = await _validated_form(request)
    call = await db.get(Call, call_id)
    if call is not None and form.get("CallStatus") == "in-progress" and call.status == CallStatus.ringing:
        await set_status(db, call, CallStatus.in_progress)
    return Response(status_code=204)


@router.post("/status")
async def call_status(request: Request, db: DB):
    """Final status for the parent PSTN call (number-level status callback)."""
    form = await _validated_form(request)
    call = (await db.execute(select(Call).where(Call.provider_call_sid == form.get("CallSid")))).scalar_one_or_none()
    if call is None:
        return Response(status_code=204)
    tw_status = form.get("CallStatus")
    mapping = {"completed": CallStatus.completed, "busy": CallStatus.no_answer, "no-answer": CallStatus.no_answer,
               "canceled": CallStatus.no_answer, "failed": CallStatus.failed}
    if tw_status in mapping and call.status in ACTIVE_STATUSES:
        await set_status(db, call, mapping[tw_status], end_reason=call.end_reason or f"carrier:{tw_status}")
        if call.livekit_room:
            try:
                await livekit_service.end_session(call.livekit_room)
            except Exception as e:
                log.warning("room_cleanup_failed", error=str(e))
    if form.get("CallDuration") and call.duration_seconds is None:
        call.duration_seconds = int(form["CallDuration"])
        await db.commit()
    return Response(status_code=204)
