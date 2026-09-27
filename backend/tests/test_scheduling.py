from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.scheduling import compute_slots, subtract_interval, within_working_hours
from tests.conftest import register

HOURS = {d: [["09:00", "17:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def _utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_compute_slots_excludes_busy_and_past():
    day = date(2030, 1, 7)
    busy = [(_utc(2030, 1, 7, 10, 0), _utc(2030, 1, 7, 11, 30))]
    slots = compute_slots(HOURS, "UTC", day, busy, timedelta(hours=1), now=_utc(2030, 1, 7, 8, 0))
    starts = [s.strftime("%H:%M") for s, _ in slots]
    assert "09:00" in starts
    assert "09:30" not in starts and "10:00" not in starts and "11:00" not in starts
    assert "11:30" in starts and starts[-1] == "16:00"


def test_compute_slots_respects_timezone():
    day = date(2030, 1, 7)
    slots = compute_slots(HOURS, "America/New_York", day, [], timedelta(hours=1), now=_utc(2030, 1, 1))
    assert slots[0][0] == _utc(2030, 1, 7, 14, 0)  # 09:00 EST


def test_closed_day_has_no_slots():
    hours = {**HOURS, "sun": []}
    assert compute_slots(hours, "UTC", date(2030, 1, 6), [], timedelta(hours=1), now=_utc(2030, 1, 1)) == []


def test_within_working_hours():
    assert within_working_hours(HOURS, "UTC", _utc(2030, 1, 7, 9), _utc(2030, 1, 7, 10))
    assert not within_working_hours(HOURS, "UTC", _utc(2030, 1, 7, 16, 30), _utc(2030, 1, 7, 17, 30))


def test_subtract_interval_splits_merged_blocks():
    merged = [(_utc(2030, 1, 7, 9), _utc(2030, 1, 7, 12))]
    out = subtract_interval(merged, (_utc(2030, 1, 7, 10), _utc(2030, 1, 7, 11)))
    assert out == [(_utc(2030, 1, 7, 9), _utc(2030, 1, 7, 10)), (_utc(2030, 1, 7, 11), _utc(2030, 1, 7, 12))]


async def _tech(client, h, name="Marcus"):
    r = await client.post("/api/technicians", headers=h, json={"name": name, "skills": ["plumbing"], "timezone": "UTC", "working_hours": HOURS})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _future_slot(days=3, hour=10):
    d = datetime.now(timezone.utc) + timedelta(days=days)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0)


async def test_book_conflict_reschedule_cancel(client):
    h = await register(client)
    tech = await _tech(client, h)
    start = _future_slot()
    body = {"technician_id": tech, "service": "Leak repair", "starts_at": start.isoformat(), "duration_minutes": 60,
            "customer_phone": "+15550001111", "customer_name": "Jo"}
    r = await client.post("/api/appointments", headers=h, json=body)
    assert r.status_code == 201, r.text
    appt = r.json()
    assert appt["customer"]["phone"] == "+15550001111"

    # overlapping booking is refused
    clash = await client.post("/api/appointments", headers=h, json={**body, "starts_at": (start + timedelta(minutes=30)).isoformat()})
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "slot_unavailable"

    # availability no longer offers the booked hour
    slots = (await client.get("/api/availability", headers=h, params={"day": start.date().isoformat()})).json()
    assert start.isoformat().replace("+00:00", "") not in [s["starts_at"].replace("Z", "").replace("+00:00", "") for s in slots]

    new_start = start + timedelta(hours=3)
    r = await client.post(f"/api/appointments/{appt['id']}/reschedule", headers=h, json={"starts_at": new_start.isoformat()})
    assert r.status_code == 200
    assert datetime.fromisoformat(r.json()["starts_at"].replace("Z", "+00:00")) == new_start

    r = await client.post(f"/api/appointments/{appt['id']}/cancel", headers=h)
    assert r.json()["status"] == "cancelled"
    # slot is free again
    assert (await client.post("/api/appointments", headers=h, json={**body, "starts_at": new_start.isoformat()})).status_code == 201


async def test_booking_outside_hours_or_past_rejected(client):
    h = await register(client)
    tech = await _tech(client, h)
    base = {"technician_id": tech, "service": "x", "duration_minutes": 60, "customer_phone": "+15550001111"}
    late = _future_slot(hour=17)
    assert (await client.post("/api/appointments", headers=h, json={**base, "starts_at": late.isoformat()})).status_code == 409
    past = datetime.now(timezone.utc) - timedelta(days=1)
    assert (await client.post("/api/appointments", headers=h, json={**base, "starts_at": past.isoformat()})).status_code == 409
    naive = await client.post("/api/appointments", headers=h, json={**base, "starts_at": "2031-01-07T10:00:00"})
    assert naive.status_code == 422


async def test_google_technician_requires_integration(client):
    h = await register(client)
    r = await client.post("/api/technicians", headers=h, json={"name": "G", "calendar_provider": "google", "calendar_id": "x@group.calendar.google.com"})
    assert r.status_code == 502 and "not connected" in r.json()["error"]["message"]


@pytest.mark.parametrize("bad", [{"mon": [["9:00", "17:00"]]}, {"funday": []}])
async def test_technician_hours_validation(client, bad):
    h = await register(client)
    r = await client.post("/api/technicians", headers=h, json={"name": "T", "working_hours": bad})
    assert r.status_code == 422
