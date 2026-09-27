"""Backend side of the call flow: Twilio webhook â†’ session start â†’ worker transcript/tool calls â†’ end."""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest
from sqlalchemy import select
from twilio.request_validator import RequestValidator

from app.models import AgentConfig, Call, PhoneNumber, User
from app.services import livekit_service as lk_module
from app.services.telephony import get_telephony
from tests.conftest import register

BASE = "https://voice.example.com"
HOURS = {d: [["00:00", "23:59"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def signed(path: str, params: dict) -> dict:
    sig = RequestValidator("twilio-test-auth-token").compute_signature(BASE + path, params)
    return {"X-Twilio-Signature": sig, "Content-Type": "application/x-www-form-urlencoded"}


@pytest.fixture
def sessions(monkeypatch):
    started = []

    async def fake_start(call_id, org_id, agent_id, max_minutes):
        started.append(call_id)
        return f"call-{call_id}"

    async def fake_end(room):
        return None

    monkeypatch.setattr(lk_module.livekit_service, "start_session", fake_start)
    monkeypatch.setattr(lk_module.livekit_service, "end_session", fake_end)
    return started


async def _setup_number(client, db, e164="+15550009999", **agent_fields):
    h = await register(client)
    user = (await db.execute(select(User))).scalars().first()
    agent = (await db.execute(select(AgentConfig).where(AgentConfig.org_id == user.org_id))).scalar_one()
    agent.working_hours = HOURS
    for k, v in agent_fields.items():
        setattr(agent, k, v)
    db.add(PhoneNumber(org_id=user.org_id, agent_id=agent.id, e164=e164))
    await db.commit()
    return h, agent


async def _inbound(client, call_sid="CA" + "1" * 32, frm="+15551230000", to="+15550009999"):
    params = {"CallSid": call_sid, "From": frm, "To": to, "CallStatus": "ringing"}
    return await client.post("/api/twilio/voice", content=urlencode(params), headers=signed("/api/twilio/voice", params))


async def test_rejects_unsigned_webhook(client):
    params = {"CallSid": "CA1", "From": "+1555", "To": "+1666"}
    r = await client.post("/api/twilio/voice", content=urlencode(params),
                          headers={"X-Twilio-Signature": "forged", "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 403


async def test_unknown_number_is_rejected_politely(client, sessions):
    r = await _inbound(client, to="+15550000000")
    assert r.status_code == 200 and "<Hangup" in r.text and "not in service" in r.text
    assert sessions == []


async def test_inbound_call_bridges_to_livekit_sip(client, db, sessions):
    await _setup_number(client, db)
    r = await _inbound(client)
    assert r.status_code == 200
    call = (await db.execute(select(Call))).scalar_one()
    assert call.provider_call_sid == "CA" + "1" * 32
    assert call.status.value == "ringing" and call.livekit_room == f"call-{call.id}"
    assert f"sip:call-{call.id}@test.sip.livekit.cloud" in r.text
    assert 'answerOnBridge="true"' in r.text
    assert sessions == [call.id]

    # Twilio retry of the same webhook must not create a second call/session
    r2 = await _inbound(client)
    assert r2.status_code == 200 and len((await db.execute(select(Call))).scalars().all()) == 1


async def test_session_failure_falls_back_to_human(client, db, monkeypatch):
    await _setup_number(client, db, transfer_enabled=True, transfer_number="+15557770000")

    async def boom(*a, **k):
        raise RuntimeError("livekit down")

    monkeypatch.setattr(lk_module.livekit_service, "start_session", boom)
    r = await _inbound(client)
    assert "<Dial" in r.text and "+15557770000" in r.text
    call = (await db.execute(select(Call))).scalar_one()
    assert call.status.value == "transferred" and call.end_reason == "agent_unavailable"


async def test_full_worker_flow_books_appointment(client, db, sessions, internal_headers, _env):
    h, agent = await _setup_number(client, db)
    tech = (await client.post("/api/technicians", headers=h, json={"name": "Marcus", "skills": ["plumbing"], "working_hours": HOURS})).json()
    await client.post("/api/knowledge/faqs", headers=h, json={"question": "What is the service call fee?", "answer": "The service call fee is $89."})
    await _inbound(client)
    call = (await db.execute(select(Call))).scalar_one()
    base = f"/api/internal/calls/{call.id}"

    # internal API requires the service token
    assert (await client.get(f"{base}/context")).status_code == 401

    ctx = (await client.get(f"{base}/context", headers=internal_headers)).json()
    assert ctx["caller_phone"] == "+15551230000"
    assert "search_knowledge_base" in ctx["tools"] and "book_appointment" in ctx["tools"]
    assert "never invent" in ctx["system_prompt"].lower()
    assert "transfer_to_human" not in ctx["tools"]  # transfer disabled for this agent

    assert (await client.post(f"{base}/answered", headers=internal_headers)).status_code == 200
    r = await client.post(f"{base}/transcript", headers=internal_headers, json={"role": "user", "text": "How much is a service call?"})
    assert r.json()["sequence"] == 1

    kb = (await client.post(f"{base}/tools/search_knowledge_base", headers=internal_headers,
                            json={"arguments": {"query": "service call fee"}})).json()
    assert kb["found"] is True and "$89" in kb["context"] and "<knowledge_source" in kb["context"]

    day = (datetime.now(timezone.utc) + timedelta(days=2)).date()
    avail = (await client.post(f"{base}/tools/check_availability", headers=internal_headers,
                               json={"arguments": {"date": day.isoformat(), "service": "plumbing"}})).json()
    assert avail["ok"] and avail["slots"]
    slot = avail["slots"][0]

    booked = (await client.post(f"{base}/tools/book_appointment", headers=internal_headers, json={"arguments": {
        "technician_id": slot["technician_id"], "start_time": slot["start_time"], "service": "Leak repair", "customer_name": "Dana",
    }})).json()
    assert booked["ok"] and booked["confirmed"]
    assert booked["appointment"]["technician"] == tech["name"]

    mine = (await client.post(f"{base}/tools/find_my_appointments", headers=internal_headers, json={"arguments": {}})).json()
    assert len(mine["appointments"]) == 1

    await client.post(f"{base}/transcript", headers=internal_headers, json={"role": "assistant", "text": "You're booked!"})
    r = await client.post(f"{base}/end", headers=internal_headers, json={"reason": "caller_hangup", "metrics": {"avg_response_latency_ms": 820}})
    assert r.status_code == 200

    detail = (await client.get(f"/api/calls/{call.id}", headers=h)).json()
    assert detail["status"] == "completed" and detail["outcome"] == "appointment_booked"
    assert [s["role"] for s in detail["segments"]] == ["user", "assistant"]
    types = [e["type"] for e in detail["events"]]
    assert "retrieval" in types and types.count("tool_call") == 3
    retrieval = next(e for e in detail["events"] if e["type"] == "retrieval")
    assert retrieval["data"]["sources"][0]["document_title"] == "What is the service call fee?"
    assert detail["metrics"]["avg_response_latency_ms"] == 820

    # live events were published for the dashboard
    published = [m for _, m in _env.messages]
    assert any('"type": "transcript"' in m for m in published) and any('"type": "tool_call"' in m for m in published)

    # tools are refused once the call has ended
    late = (await client.post(f"{base}/tools/find_my_appointments", headers=internal_headers, json={"arguments": {}})).json()
    assert late["ok"] is False


async def test_tool_permissions_and_caller_scoping(client, db, sessions, internal_headers):
    h, agent = await _setup_number(client, db)
    tech = (await client.post("/api/technicians", headers=h, json={"name": "Marcus", "working_hours": HOURS})).json()
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    other = (await client.post("/api/appointments", headers=h, json={
        "technician_id": tech["id"], "service": "x", "starts_at": start.isoformat(), "customer_phone": "+15559990000",
    })).json()

    await _inbound(client)
    call = (await db.execute(select(Call))).scalar_one()
    base = f"/api/internal/calls/{call.id}/tools"
    await client.post(f"/api/internal/calls/{call.id}/answered", headers=internal_headers)

    # A caller cannot cancel someone else's appointment, even with its exact id.
    r = (await client.post(f"{base}/cancel_appointment", headers=internal_headers, json={"arguments": {"appointment_id": other["id"]}})).json()
    assert r["ok"] is False and "caller's phone number" in r["error"]

    # Invalid arguments are rejected by validation, not passed through
    r = (await client.post(f"{base}/book_appointment", headers=internal_headers, json={"arguments": {"technician_id": "nope"}})).json()
    assert r["ok"] is False and "Invalid arguments" in r["error"]

    # Disabled actions are denied server-side
    agent_row = await db.get(AgentConfig, agent.id)
    await db.refresh(agent_row)
    agent_row.allowed_actions = ["check_availability"]
    await db.commit()
    r = (await client.post(f"{base}/book_appointment", headers=internal_headers, json={"arguments": {}})).json()
    assert r["ok"] is False and "not enabled" in r["error"]
    r = (await client.post(f"{base}/delete_everything", headers=internal_headers, json={"arguments": {}})).json()
    assert r["ok"] is False and "Unknown tool" in r["error"]


async def test_status_callback_finalizes_call(client, db, sessions):
    await _setup_number(client, db)
    await _inbound(client)
    params = {"CallSid": "CA" + "1" * 32, "CallStatus": "completed", "CallDuration": "42"}
    r = await client.post("/api/twilio/status", content=urlencode(params), headers=signed("/api/twilio/status", params))
    assert r.status_code == 204
    call = (await db.execute(select(Call))).scalar_one()
    await db.refresh(call)
    assert call.status.value == "completed" and call.outcome.value == "abandoned"


async def test_dial_failure_falls_back(client, db, sessions):
    await _setup_number(client, db, transfer_enabled=True, transfer_number="+15557770000")
    await _inbound(client)
    call = (await db.execute(select(Call))).scalar_one()
    path = f"/api/twilio/dial-action?call_id={call.id}"
    params = {"CallSid": "CA" + "1" * 32, "DialCallStatus": "failed"}
    r = await client.post(path, content=urlencode(params), headers=signed(path, params))
    assert "<Dial" in r.text and "+15557770000" in r.text


async def test_calls_list_and_overview(client, db, sessions):
    h, _ = await _setup_number(client, db)
    await _inbound(client)
    page = (await client.get("/api/calls", headers=h)).json()
    assert page["total"] == 1 and page["items"][0]["direction"] == "inbound"
    assert len((await client.get("/api/calls/active", headers=h)).json()) == 1
    ov = (await client.get("/api/overview", headers=h)).json()
    assert ov["calls_today"] == 1 and ov["active_calls"] == 1 and len(ov["calls_per_day"]) == 14
    other = await register(client, email="z@z-example.com", org="Zed Org")
    assert (await client.get("/api/calls", headers=other)).json()["total"] == 0
    call_id = page["items"][0]["id"]
    assert (await client.get(f"/api/calls/{call_id}", headers=other)).status_code == 404
    assert (await client.get(f"/api/calls/{uuid.uuid4()}", headers=h)).status_code == 404


def test_twiml_provider_is_twilio():
    assert get_telephony().name == "twilio"
