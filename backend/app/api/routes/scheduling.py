import uuid
from datetime import date, datetime

import anyio
import jwt
from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, Admin, Member, Viewer, client_ip
from app.core.config import get_settings
from app.core.errors import AppError, IntegrationError, NotFound
from app.core.security import create_state_token, decode_state_token, encrypt_json
from app.models import Appointment, AppointmentStatus, CalendarIntegration, Technician
from app.schemas.scheduling import (
    AppointmentIn, AppointmentOut, GoogleCalendarOut, IntegrationOut, RescheduleIn, SlotOut, TechnicianIn, TechnicianOut,
)
from app.services import audit, scheduling
from app.services.calendar import google_provider_for_org

router = APIRouter(tags=["scheduling"])


# ---------- Technicians ----------

@router.get("/technicians", response_model=list[TechnicianOut])
async def list_technicians(principal: Viewer, db: DB):
    return (await db.execute(select(Technician).where(Technician.org_id == principal.org_id).order_by(Technician.name))).scalars().all()


async def _validate_google(db, org_id, body: TechnicianIn):
    if body.calendar_provider != "google":
        return
    provider = await google_provider_for_org(db, org_id)
    ids = {c["id"] for c in await provider.list_calendars()}
    if body.calendar_id not in ids:
        raise AppError("That calendar isn't writable by the connected Google account", code="calendar_not_found")


@router.post("/technicians", response_model=TechnicianOut, status_code=201)
async def create_technician(request: Request, body: TechnicianIn, principal: Admin, db: DB):
    await _validate_google(db, principal.org_id, body)
    data = body.model_dump(exclude_none=True)
    tech = Technician(org_id=principal.org_id, **data)
    db.add(tech)
    await db.flush()
    await audit.record(db, action="technician.created", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="technician", resource_id=tech.id, ip_address=client_ip(request))
    await db.commit()
    return tech


@router.put("/technicians/{tech_id}", response_model=TechnicianOut)
async def update_technician(request: Request, tech_id: uuid.UUID, body: TechnicianIn, principal: Admin, db: DB):
    tech = await scheduling.get_technician(db, principal.org_id, tech_id)
    await _validate_google(db, principal.org_id, body)
    for k, v in body.model_dump().items():
        if k == "working_hours" and v is None:
            continue
        setattr(tech, k, v)
    await audit.record(db, action="technician.updated", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="technician", resource_id=tech.id, ip_address=client_ip(request))
    await db.commit()
    return tech


@router.delete("/technicians/{tech_id}", status_code=204)
async def delete_technician(request: Request, tech_id: uuid.UUID, principal: Admin, db: DB):
    tech = await scheduling.get_technician(db, principal.org_id, tech_id)
    upcoming = (
        await db.execute(
            select(Appointment.id).where(Appointment.technician_id == tech.id, Appointment.status == AppointmentStatus.scheduled,
                                         Appointment.starts_at >= datetime.now().astimezone())
        )
    ).first()
    if upcoming:
        raise AppError("Technician has upcoming appointments; cancel or reassign them first (or deactivate instead)", code="has_appointments")
    await db.delete(tech)
    await audit.record(db, action="technician.deleted", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="technician", resource_id=tech_id, ip_address=client_ip(request))
    await db.commit()


# ---------- Availability & appointments ----------

@router.get("/availability", response_model=list[SlotOut])
async def availability(
    principal: Viewer, db: DB, day: date, technician_id: uuid.UUID | None = None,
    duration_minutes: int = Query(60, ge=10, le=480), service: str | None = Query(None, max_length=200),
):
    return await scheduling.find_availability(db, principal.org_id, day, duration_minutes, technician_id, service)


@router.get("/appointments", response_model=list[AppointmentOut])
async def list_appointments(
    principal: Viewer, db: DB, start: datetime, end: datetime,
    technician_id: uuid.UUID | None = None, include_cancelled: bool = False,
):
    if (end - start).days > 62:
        raise AppError("Range too large (max 62 days)", code="range_too_large")
    q = (
        select(Appointment)
        .options(selectinload(Appointment.technician), selectinload(Appointment.customer))
        .where(Appointment.org_id == principal.org_id, Appointment.starts_at < end, Appointment.ends_at > start)
    )
    if technician_id:
        q = q.where(Appointment.technician_id == technician_id)
    if not include_cancelled:
        q = q.where(Appointment.status != AppointmentStatus.cancelled)
    return (await db.execute(q.order_by(Appointment.starts_at))).scalars().all()


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
async def create_appointment(request: Request, body: AppointmentIn, principal: Member, db: DB):
    appt = await scheduling.book(
        db, org_id=principal.org_id, technician_id=body.technician_id, starts_at=body.starts_at,
        duration_minutes=body.duration_minutes, customer_phone=body.customer_phone, customer_name=body.customer_name,
        service=body.service, notes=body.notes, via="dashboard",
    )
    await audit.record(db, action="appointment.created", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="appointment", resource_id=appt.id, ip_address=client_ip(request), commit=True)
    return appt


@router.post("/appointments/{appt_id}/reschedule", response_model=AppointmentOut)
async def reschedule_appointment(request: Request, appt_id: uuid.UUID, body: RescheduleIn, principal: Member, db: DB):
    appt = await scheduling.reschedule(db, org_id=principal.org_id, appointment_id=appt_id, starts_at=body.starts_at,
                                       duration_minutes=body.duration_minutes)
    await audit.record(db, action="appointment.rescheduled", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="appointment", resource_id=appt.id, data={"starts_at": body.starts_at.isoformat()},
                       ip_address=client_ip(request), commit=True)
    return appt


@router.post("/appointments/{appt_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment(request: Request, appt_id: uuid.UUID, principal: Member, db: DB):
    appt = await scheduling.cancel(db, org_id=principal.org_id, appointment_id=appt_id)
    await audit.record(db, action="appointment.cancelled", org_id=principal.org_id, user_id=principal.user.id,
                       resource_type="appointment", resource_id=appt.id, ip_address=client_ip(request), commit=True)
    return appt


# ---------- Google Calendar integration ----------

@router.get("/integrations", response_model=list[IntegrationOut])
async def list_integrations(principal: Viewer, db: DB):
    return (await db.execute(select(CalendarIntegration).where(CalendarIntegration.org_id == principal.org_id))).scalars().all()


def _flow():
    from google_auth_oauthlib.flow import Flow

    from app.services.calendar.google import SCOPES

    s = get_settings()
    if not (s.google_client_id and s.google_client_secret):
        raise IntegrationError("Google OAuth is not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET)")
    flow = Flow.from_client_config(
        {"web": {"client_id": s.google_client_id, "client_secret": s.google_client_secret,
                 "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}},
        scopes=SCOPES, redirect_uri=s.google_redirect_uri,
    )
    # We don't use PKCE across the stateless redirect; confidentiality comes from the client secret.
    flow.autogenerate_code_verifier = False
    return flow


@router.post("/integrations/google/authorize")
async def google_authorize(principal: Admin):
    state = create_state_token({"org": str(principal.org_id), "uid": str(principal.user.id)})
    url, _ = _flow().authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true", state=state)
    return {"authorization_url": url}


@router.get("/integrations/google/callback", include_in_schema=False)
async def google_callback(request: Request, db: DB, state: str, code: str | None = None, error: str | None = None):
    s = get_settings()
    if error or not code:
        return RedirectResponse(f"{s.frontend_url}/calendar?google=error")
    try:
        st = decode_state_token(state)
    except jwt.PyJWTError:
        return RedirectResponse(f"{s.frontend_url}/calendar?google=invalid_state")
    org_id, user_id = uuid.UUID(st["org"]), uuid.UUID(st["uid"])

    flow = _flow()
    await anyio.to_thread.run_sync(lambda: flow.fetch_token(code=code))
    creds = flow.credentials
    if not creds.refresh_token:
        return RedirectResponse(f"{s.frontend_url}/calendar?google=no_refresh_token")

    email = ""
    try:
        from googleapiclient.discovery import build

        info = await anyio.to_thread.run_sync(lambda: build("oauth2", "v2", credentials=creds, cache_discovery=False).userinfo().get().execute())
        email = info.get("email", "")
    except Exception:
        pass

    payload = {"token": creds.token, "refresh_token": creds.refresh_token, "token_uri": creds.token_uri, "scopes": list(creds.scopes or [])}
    integ = (
        await db.execute(select(CalendarIntegration).where(CalendarIntegration.org_id == org_id, CalendarIntegration.provider == "google"))
    ).scalar_one_or_none()
    if integ is None:
        integ = CalendarIntegration(org_id=org_id, provider="google", encrypted_credentials=encrypt_json(payload), account_email=email)
        db.add(integ)
    else:
        integ.encrypted_credentials = encrypt_json(payload)
        integ.account_email = email
    await audit.record(db, action="integration.google_connected", org_id=org_id, user_id=user_id, data={"account": email},
                       ip_address=client_ip(request))
    await db.commit()
    return RedirectResponse(f"{s.frontend_url}/calendar?google=connected")


@router.get("/integrations/google/calendars", response_model=list[GoogleCalendarOut])
async def google_calendars(principal: Admin, db: DB):
    return await (await google_provider_for_org(db, principal.org_id)).list_calendars()


@router.delete("/integrations/google", status_code=204)
async def google_disconnect(request: Request, principal: Admin, db: DB):
    integ = (
        await db.execute(select(CalendarIntegration).where(CalendarIntegration.org_id == principal.org_id, CalendarIntegration.provider == "google"))
    ).scalar_one_or_none()
    if integ is None:
        raise NotFound("Google integration")
    in_use = (
        await db.execute(select(Technician.id).where(Technician.org_id == principal.org_id, Technician.calendar_provider == "google"))
    ).first()
    if in_use:
        raise AppError("Switch technicians off Google Calendar before disconnecting", code="integration_in_use")
    await db.delete(integ)
    await audit.record(db, action="integration.google_disconnected", org_id=principal.org_id, user_id=principal.user.id,
                       ip_address=client_ip(request))
    await db.commit()
