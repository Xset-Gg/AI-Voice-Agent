"""Appointment scheduling: availability, booking, rescheduling, cancellation."""

import uuid
import zlib
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, Conflict, NotFound
from app.models import Appointment, AppointmentStatus, Customer, Technician
from app.services.calendar import EventDetails, provider_for

WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SLOT_STEP_MINUTES = 30


class SlotUnavailable(Conflict):
    def __init__(self, message: str = "That time is no longer available"):
        super().__init__(message)
        self.code = "slot_unavailable"


def working_windows(working_hours: dict, tz: str, day: date) -> list[tuple[datetime, datetime]]:
    zone = ZoneInfo(tz)
    windows = []
    for start_s, end_s in working_hours.get(WEEKDAY_KEYS[day.weekday()], []):
        start = datetime.combine(day, time.fromisoformat(start_s), zone)
        end = datetime.combine(day, time.fromisoformat(end_s), zone)
        windows.append((start, end))
    return windows


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def compute_slots(
    working_hours: dict,
    tz: str,
    day: date,
    busy: list[tuple[datetime, datetime]],
    duration: timedelta,
    now: datetime | None = None,
    step: timedelta = timedelta(minutes=SLOT_STEP_MINUTES),
    lead_time: timedelta = timedelta(minutes=30),
) -> list[tuple[datetime, datetime]]:
    """Free slots of `duration` inside working hours that don't overlap any busy interval."""
    now = now or datetime.now(timezone.utc)
    earliest = now + lead_time
    slots = []
    for w_start, w_end in working_windows(working_hours, tz, day):
        cursor = w_start
        while cursor + duration <= w_end:
            end = cursor + duration
            if cursor >= earliest and not any(_overlaps(cursor, end, b0, b1) for b0, b1 in busy):
                slots.append((cursor, end))
            cursor += step
    return slots


def subtract_interval(busy: list[tuple[datetime, datetime]], cut: tuple[datetime, datetime]):
    out = []
    for b0, b1 in busy:
        if not _overlaps(b0, b1, *cut):
            out.append((b0, b1))
            continue
        if b0 < cut[0]:
            out.append((b0, cut[0]))
        if b1 > cut[1]:
            out.append((cut[1], b1))
    return out


def within_working_hours(working_hours: dict, tz: str, start: datetime, end: datetime) -> bool:
    local = start.astimezone(ZoneInfo(tz))
    return any(w0 <= start and end <= w1 for w0, w1 in working_windows(working_hours, tz, local.date()))


async def _db_busy(db: AsyncSession, technician_id: uuid.UUID, start: datetime, end: datetime, exclude: uuid.UUID | None = None):
    q = select(Appointment.starts_at, Appointment.ends_at).where(
        Appointment.technician_id == technician_id,
        Appointment.status == AppointmentStatus.scheduled,
        Appointment.starts_at < end,
        Appointment.ends_at > start,
    )
    if exclude:
        q = q.where(Appointment.id != exclude)
    return [(_aware(s), _aware(e)) for s, e in (await db.execute(q)).all()]


def _aware(dt: datetime) -> datetime:
    # SQLite drops tzinfo; Postgres keeps it. Normalise to aware UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _busy(db, technician: Technician, start, end, exclude: uuid.UUID | None = None):
    provider = await provider_for(db, technician)
    external = await provider.busy_intervals(technician, start, end)
    return external + await _db_busy(db, technician.id, start, end, exclude)


async def get_technician(db: AsyncSession, org_id: uuid.UUID, technician_id: uuid.UUID) -> Technician:
    tech = await db.get(Technician, technician_id)
    if tech is None or tech.org_id != org_id:
        raise NotFound("Technician")
    return tech


async def list_technicians(db: AsyncSession, org_id: uuid.UUID, service: str | None = None) -> list[Technician]:
    techs = (
        await db.execute(
            select(Technician).where(Technician.org_id == org_id, Technician.is_active.is_(True)).order_by(Technician.name)
        )
    ).scalars().all()
    if service:
        needle = service.lower()
        skilled = [t for t in techs if any(needle in s.lower() or s.lower() in needle for s in t.skills)]
        # Fall back to everyone if nobody lists a matching skill.
        return skilled or list(techs)
    return list(techs)


async def find_availability(
    db: AsyncSession,
    org_id: uuid.UUID,
    day: date,
    duration_minutes: int,
    technician_id: uuid.UUID | None = None,
    service: str | None = None,
    now: datetime | None = None,
) -> list[dict]:
    techs = [await get_technician(db, org_id, technician_id)] if technician_id else await list_technicians(db, org_id, service)
    duration = timedelta(minutes=duration_minutes)
    results = []
    for tech in techs:
        windows = working_windows(tech.working_hours, tech.timezone, day)
        if not windows:
            continue
        busy = await _busy(db, tech, windows[0][0], windows[-1][1])
        for s, e in compute_slots(tech.working_hours, tech.timezone, day, busy, duration, now=now):
            results.append({"technician_id": tech.id, "technician_name": tech.name, "starts_at": s, "ends_at": e})
    results.sort(key=lambda r: (r["starts_at"], r["technician_name"]))
    return results


async def _lock_technician(db: AsyncSession, technician_id: uuid.UUID) -> None:
    """Serialise bookings per technician for the duration of the transaction (Postgres only)."""
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": zlib.crc32(technician_id.bytes)})


async def upsert_customer(db: AsyncSession, org_id: uuid.UUID, phone: str, name: str = "") -> Customer:
    cust = (
        await db.execute(select(Customer).where(Customer.org_id == org_id, Customer.phone == phone))
    ).scalar_one_or_none()
    if cust is None:
        cust = Customer(org_id=org_id, phone=phone, name=name.strip())
        db.add(cust)
        await db.flush()
    elif name.strip() and not cust.name:
        cust.name = name.strip()
    return cust


def _event(appt_service: str, customer: Customer, notes: str, start, end, tz, via: str) -> EventDetails:
    who = customer.name or "Customer"
    desc = f"Customer: {who}\nPhone: {customer.phone}\nService: {appt_service}\nBooked via: {via}"
    if notes:
        desc += f"\nNotes: {notes}"
    return EventDetails(
        summary=f"{appt_service} — {who}", description=desc, starts_at=start, ends_at=end,
        timezone=tz, attendee_email=customer.email,
    )


async def book(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    technician_id: uuid.UUID,
    starts_at: datetime,
    duration_minutes: int,
    customer_phone: str,
    customer_name: str = "",
    service: str,
    notes: str = "",
    call_id: uuid.UUID | None = None,
    via: str = "dashboard",
) -> Appointment:
    if starts_at.tzinfo is None:
        raise AppError("starts_at must include a timezone offset", code="invalid_time")
    tech = await get_technician(db, org_id, technician_id)
    ends_at = starts_at + timedelta(minutes=duration_minutes)
    if starts_at < datetime.now(timezone.utc):
        raise SlotUnavailable("That time is in the past")
    if not within_working_hours(tech.working_hours, tech.timezone, starts_at, ends_at):
        raise SlotUnavailable(f"{tech.name} is not working at that time")

    await _lock_technician(db, tech.id)
    busy = await _busy(db, tech, starts_at, ends_at)
    if any(_overlaps(starts_at, ends_at, b0, b1) for b0, b1 in busy):
        raise SlotUnavailable()

    customer = await upsert_customer(db, org_id, customer_phone, customer_name)
    provider = await provider_for(db, tech)
    external_id = await provider.create_event(
        tech, _event(service, customer, notes, starts_at, ends_at, tech.timezone, via)
    )
    appt = Appointment(
        org_id=org_id, technician_id=tech.id, customer_id=customer.id, call_id=call_id, service=service,
        starts_at=starts_at, ends_at=ends_at, external_event_id=external_id, notes=notes, created_via=via,
    )
    db.add(appt)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        if external_id:  # don't leave an orphaned calendar event behind
            await provider.delete_event(tech, external_id)
        raise
    return await get_appointment(db, org_id, appt.id)


async def get_appointment(db: AsyncSession, org_id: uuid.UUID, appointment_id: uuid.UUID) -> Appointment:
    appt = (
        await db.execute(
            select(Appointment)
            .options(selectinload(Appointment.technician), selectinload(Appointment.customer))
            .where(Appointment.id == appointment_id, Appointment.org_id == org_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if appt is None:
        raise NotFound("Appointment")
    return appt


async def reschedule(
    db: AsyncSession, *, org_id: uuid.UUID, appointment_id: uuid.UUID, starts_at: datetime,
    duration_minutes: int | None = None, via: str = "dashboard",
) -> Appointment:
    appt = await get_appointment(db, org_id, appointment_id)
    if appt.status != AppointmentStatus.scheduled:
        raise Conflict("Only scheduled appointments can be rescheduled")
    tech = appt.technician
    duration = timedelta(minutes=duration_minutes) if duration_minutes else _aware(appt.ends_at) - _aware(appt.starts_at)
    ends_at = starts_at + duration
    if starts_at < datetime.now(timezone.utc):
        raise SlotUnavailable("That time is in the past")
    if not within_working_hours(tech.working_hours, tech.timezone, starts_at, ends_at):
        raise SlotUnavailable(f"{tech.name} is not working at that time")

    await _lock_technician(db, tech.id)
    provider = await provider_for(db, tech)
    busy = await _db_busy(db, tech.id, starts_at, ends_at, exclude=appt.id)
    external_busy = await provider.busy_intervals(tech, starts_at, ends_at)
    old = (_aware(appt.starts_at), _aware(appt.ends_at))
    # The appointment's own external event shows up as busy (possibly merged with neighbours).
    busy += subtract_interval(external_busy, old)
    if any(_overlaps(starts_at, ends_at, b0, b1) for b0, b1 in busy):
        raise SlotUnavailable()

    customer = appt.customer or Customer(phone="", name="")
    if appt.external_event_id:
        await provider.update_event(
            tech, appt.external_event_id, _event(appt.service, customer, appt.notes, starts_at, ends_at, tech.timezone, via)
        )
    appt.starts_at, appt.ends_at = starts_at, ends_at
    await db.commit()
    return await get_appointment(db, org_id, appt.id)


async def cancel(db: AsyncSession, *, org_id: uuid.UUID, appointment_id: uuid.UUID) -> Appointment:
    appt = await get_appointment(db, org_id, appointment_id)
    if appt.status == AppointmentStatus.cancelled:
        return appt
    if appt.external_event_id:
        provider = await provider_for(db, appt.technician)
        await provider.delete_event(appt.technician, appt.external_event_id)
    appt.status = AppointmentStatus.cancelled
    await db.commit()
    return await get_appointment(db, org_id, appt.id)


async def upcoming_for_phone(db: AsyncSession, org_id: uuid.UUID, phone: str) -> list[Appointment]:
    return list(
        (
            await db.execute(
                select(Appointment)
                .join(Customer, Appointment.customer_id == Customer.id)
                .options(selectinload(Appointment.technician), selectinload(Appointment.customer))
                .where(
                    Appointment.org_id == org_id,
                    Customer.phone == phone,
                    Appointment.status == AppointmentStatus.scheduled,
                    Appointment.starts_at >= datetime.now(timezone.utc),
                )
                .order_by(Appointment.starts_at)
            )
        ).scalars().all()
    )
