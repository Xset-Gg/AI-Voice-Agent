from datetime import datetime

from app.models import Technician
from app.services.calendar.base import CalendarProvider, EventDetails


class InternalCalendarProvider(CalendarProvider):
    """For businesses without an external calendar: the platform's appointments table is the
    calendar. Busy time comes solely from those appointments (added by the scheduling service)."""

    name = "internal"

    async def busy_intervals(self, technician: Technician, start: datetime, end: datetime):
        return []

    async def create_event(self, technician: Technician, event: EventDetails) -> str | None:
        return None

    async def update_event(self, technician: Technician, event_id: str, event: EventDetails) -> None:
        return None

    async def delete_event(self, technician: Technician, event_id: str) -> None:
        return None
