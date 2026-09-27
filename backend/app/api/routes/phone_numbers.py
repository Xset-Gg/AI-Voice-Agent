import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import DB, Admin, Viewer, client_ip
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound
from app.models import AgentConfig, PhoneNumber
from app.schemas.agents import PhoneNumberIn, PhoneNumberOut, PhoneNumberUpdate
from app.services import audit
from app.services.telephony import get_telephony

router = APIRouter(prefix="/phone-numbers", tags=["phone numbers"])


async def _agent_in_org(db, org_id, agent_id):
    if agent_id is None:
        return
    agent = await db.get(AgentConfig, agent_id)
    if agent is None or agent.org_id != org_id:
        raise NotFound("Agent")


async def _get(db, org_id, number_id) -> PhoneNumber:
    num = await db.get(PhoneNumber, number_id)
    if num is None or num.org_id != org_id:
        raise NotFound("Phone number")
    return num


@router.get("", response_model=list[PhoneNumberOut])
async def list_numbers(principal: Viewer, db: DB):
    return (await db.execute(select(PhoneNumber).where(PhoneNumber.org_id == principal.org_id).order_by(PhoneNumber.created_at))).scalars().all()


@router.get("/provider")
async def provider_numbers(principal: Admin, db: DB):
    """Numbers in the connected Twilio account, flagged if already claimed on this platform."""
    s = get_settings()
    claimed = {n for (n,) in (await db.execute(select(PhoneNumber.e164))).all()}
    return [
        {"sid": n.sid, "e164": n.e164, "friendly_name": n.friendly_name, "voice_url": n.voice_url,
         "claimed": n.e164 in claimed, "points_here": (n.voice_url or "").startswith(s.public_base_url)}
        for n in await get_telephony().list_numbers()
    ]


@router.post("", response_model=PhoneNumberOut, status_code=201)
async def add_number(request: Request, body: PhoneNumberIn, principal: Admin, db: DB):
    """Claim a Twilio number for this business and point its voice webhook at the platform."""
    await _agent_in_org(db, principal.org_id, body.agent_id)
    if (await db.execute(select(PhoneNumber.id).where(PhoneNumber.e164 == body.e164))).first():
        raise Conflict("This number is already registered")

    s = get_settings()
    provider_num = next((n for n in await get_telephony().list_numbers() if n.e164 == body.e164), None)
    if provider_num is None:
        raise NotFound("That number in your Twilio account")
    await get_telephony().configure_number(
        provider_num.sid, f"{s.public_base_url}/api/twilio/voice", f"{s.public_base_url}/api/twilio/status"
    )
    num = PhoneNumber(
        org_id=principal.org_id, agent_id=body.agent_id, e164=body.e164,
        friendly_name=body.friendly_name or provider_num.friendly_name, provider_sid=provider_num.sid,
    )
    db.add(num)
    await db.flush()
    await audit.record(db, action="phone_number.added", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="phone_number", resource_id=num.id, data={"e164": body.e164}, ip_address=client_ip(request))
    await db.commit()
    return num


@router.patch("/{number_id}", response_model=PhoneNumberOut)
async def update_number(request: Request, number_id: uuid.UUID, body: PhoneNumberUpdate, principal: Admin, db: DB):
    num = await _get(db, principal.org_id, number_id)
    changes = body.model_dump(exclude_unset=True)
    if "agent_id" in changes:
        await _agent_in_org(db, principal.org_id, changes["agent_id"])
    for k, v in changes.items():
        setattr(num, k, v)
    await audit.record(db, action="phone_number.updated", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="phone_number", resource_id=num.id, data={k: str(v) for k, v in changes.items()},
                       ip_address=client_ip(request))
    await db.commit()
    return num


@router.delete("/{number_id}", status_code=204)
async def remove_number(request: Request, number_id: uuid.UUID, principal: Admin, db: DB):
    num = await _get(db, principal.org_id, number_id)
    await db.delete(num)
    await audit.record(db, action="phone_number.removed", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="phone_number", resource_id=number_id, data={"e164": num.e164}, ip_address=client_ip(request))
    await db.commit()
