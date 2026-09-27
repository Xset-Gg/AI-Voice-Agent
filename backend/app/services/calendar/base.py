from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.models import Technician


@dataclass
class EventDetails:
    summary: str
    description: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    attendee_email: str | None = None


class CalendarProvider(ABC):
    """Adapter interface for calendar backends. Add Outlook/CalDAV/etc. by implementing this."""

    name: str

    @abstractmethod
    async def busy_intervals(
        self, technician: Technician, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        """Busy periods reported by the external calendar (platform appointments are added separately)."""

    @abstractmethod
    async def create_event(self, technician: Technician, event: EventDetails) -> str | None:
        """Create the event; return the provider's event id (None when there is no external calendar)."""

    @abstractmethod
    async def update_event(self, technician: Technician, event_id: str, event: EventDetails) -> None: ...

    @abstractmethod
    async def delete_event(self, technician: Technician, event_id: str) -> None: ...
