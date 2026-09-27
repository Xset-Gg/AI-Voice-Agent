"""Google Calendar adapter (OAuth2, per-organization credentials encrypted at rest)."""

from datetime import datetime

import anyio
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import get_settings
from app.core.errors import IntegrationError
from app.models import Technician
from app.services.calendar.base import CalendarProvider, EventDetails

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def credentials_from_dict(data: dict) -> Credentials:
    s = get_settings()
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        scopes=data.get("scopes", SCOPES),
    )


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class GoogleCalendarProvider(CalendarProvider):
    name = "google"

    def __init__(self, credentials: Credentials):
        self.credentials = credentials

    def _service(self):
        if not self.credentials.valid:
            self.credentials.refresh(GoogleRequest())
        return build("calendar", "v3", credentials=self.credentials, cache_discovery=False)

    async def _run(self, fn):
        try:
            return await anyio.to_thread.run_sync(fn)
        except HttpError as e:
            raise IntegrationError(f"Google Calendar error: {e.status_code} {e.reason}") from e
        except Exception as e:
            raise IntegrationError(f"Google Calendar unavailable: {e}") from e

    async def list_calendars(self) -> list[dict]:
        def go():
            items = self._service().calendarList().list(minAccessRole="writer").execute().get("items", [])
            return [{"id": c["id"], "summary": c.get("summary", c["id"]), "primary": c.get("primary", False)} for c in items]

        return await self._run(go)

    async def busy_intervals(self, technician: Technician, start: datetime, end: datetime):
        def go():
            body = {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "items": [{"id": technician.calendar_id}]}
            resp = self._service().freebusy().query(body=body).execute()
            cal = resp["calendars"].get(technician.calendar_id, {})
            if cal.get("errors"):
                raise IntegrationError(f"Cannot read calendar {technician.calendar_id}: {cal['errors']}")
            return [(_parse(b["start"]), _parse(b["end"])) for b in cal.get("busy", [])]

        return await self._run(go)

    def _body(self, event: EventDetails) -> dict:
        body = {
            "summary": event.summary,
            "description": event.description,
            "start": {"dateTime": event.starts_at.isoformat(), "timeZone": event.timezone},
            "end": {"dateTime": event.ends_at.isoformat(), "timeZone": event.timezone},
            "reminders": {"useDefault": True},
        }
        if event.attendee_email:
            body["attendees"] = [{"email": event.attendee_email}]
        return body

    async def create_event(self, technician: Technician, event: EventDetails) -> str | None:
        def go():
            created = self._service().events().insert(calendarId=technician.calendar_id, body=self._body(event)).execute()
            return created["id"]

        return await self._run(go)

    async def update_event(self, technician: Technician, event_id: str, event: EventDetails) -> None:
        def go():
            self._service().events().patch(
                calendarId=technician.calendar_id, eventId=event_id, body=self._body(event)
            ).execute()

        await self._run(go)

    async def delete_event(self, technician: Technician, event_id: str) -> None:
        def go():
            try:
                self._service().events().delete(calendarId=technician.calendar_id, eventId=event_id).execute()
            except HttpError as e:
                if e.status_code not in (404, 410):  # already gone is fine
                    raise

        await self._run(go)
