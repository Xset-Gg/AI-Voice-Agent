import uuid
from datetime import date, datetime

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, model_validator

from app.models import AppointmentStatus
from app.schemas.common import E164, ORM, Timezone, WorkingHours


class TechnicianIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    skills: list[str] = Field(default_factory=list, max_length=50)
    calendar_provider: str = Field(default="internal", pattern="^(internal|google)$")
    calendar_id: str | None = Field(default=None, max_length=320)
    timezone: Timezone = "UTC"
    working_hours: WorkingHours | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def google_needs_calendar(self):
        if self.calendar_provider == "google" and not self.calendar_id:
            raise ValueError("calendar_id is required for Google Calendar technicians")
        return self


class TechnicianOut(ORM):
    id: uuid.UUID
    name: str
    email: str | None
    skills: list[str]
    calendar_provider: str
    calendar_id: str | None
    timezone: str
    working_hours: dict
    is_active: bool


class CustomerOut(ORM):
    id: uuid.UUID
    phone: str
    name: str
    email: str | None


class AppointmentIn(BaseModel):
    technician_id: uuid.UUID
    service: str = Field(min_length=1, max_length=200)
    starts_at: AwareDatetime
    duration_minutes: int = Field(default=60, ge=10, le=480)
    customer_phone: E164
    customer_name: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=2000)


class RescheduleIn(BaseModel):
    starts_at: AwareDatetime
    duration_minutes: int | None = Field(default=None, ge=10, le=480)


class AppointmentOut(ORM):
    id: uuid.UUID
    technician_id: uuid.UUID
    customer_id: uuid.UUID | None
    call_id: uuid.UUID | None
    service: str
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    external_event_id: str | None
    notes: str
    created_via: str
    technician: TechnicianOut
    customer: CustomerOut | None


class SlotOut(BaseModel):
    technician_id: uuid.UUID
    technician_name: str
    starts_at: datetime
    ends_at: datetime


class AvailabilityQuery(BaseModel):
    day: date
    technician_id: uuid.UUID | None = None
    duration_minutes: int = Field(default=60, ge=10, le=480)


class IntegrationOut(ORM):
    id: uuid.UUID
    provider: str
    account_email: str
    created_at: datetime


class GoogleCalendarOut(BaseModel):
    id: str
    summary: str
    primary: bool = False
