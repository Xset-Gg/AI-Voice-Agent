import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import IntegrationError
from app.core.security import decrypt_json
from app.models import CalendarIntegration, Technician
from app.services.calendar.base import CalendarProvider, EventDetails
from app.services.calendar.internal import InternalCalendarProvider

__all__ = ["CalendarProvider", "EventDetails", "provider_for"]


async def google_provider_for_org(db: AsyncSession, org_id: uuid.UUID):
    from app.services.calendar.google import GoogleCalendarProvider, credentials_from_dict

    integ = (
        await db.execute(
            select(CalendarIntegration).where(
                CalendarIntegration.org_id == org_id, CalendarIntegration.provider == "google"
            )
        )
    ).scalar_one_or_none()
    if integ is None:
        raise IntegrationError("Google Calendar is not connected for this organization")
    return GoogleCalendarProvider(credentials_from_dict(decrypt_json(integ.encrypted_credentials)))


async def provider_for(db: AsyncSession, technician: Technician) -> CalendarProvider:
    if technician.calendar_provider == "google":
        return await google_provider_for_org(db, technician.org_id)
    return InternalCalendarProvider()
