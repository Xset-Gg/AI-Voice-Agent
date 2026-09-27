import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, DateTime, JSONType, Timestamps, UUIDPk
from app.models.agent import DEFAULT_WORKING_HOURS


class CalendarIntegration(UUIDPk, Timestamps, Base):
    __tablename__ = "calendar_integrations"
    __table_args__ = (UniqueConstraint("org_id", "provider", name="uq_calendar_integrations_org_provider"),)

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # google
    account_email: Mapped[str] = mapped_column(String(320), default="")
    # Fernet-encrypted JSON credentials (refresh token etc.) — never returned by the API
    encrypted_credentials: Mapped[str] = mapped_column(Text)


class Technician(UUIDPk, Timestamps, Base):
    __tablename__ = "technicians"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    skills: Mapped[list] = mapped_column(JSONType, default=list)
    # "google" uses the org's Google integration; "internal" uses the platform's own appointment table.
    calendar_provider: Mapped[str] = mapped_column(String(32), default="internal")
    calendar_id: Mapped[str | None] = mapped_column(String(320), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    working_hours: Mapped[dict] = mapped_column(JSONType, default=lambda: dict(DEFAULT_WORKING_HOURS))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AppointmentStatus(str, enum.Enum):
    scheduled = "scheduled"
    cancelled = "cancelled"
    completed = "completed"


class Appointment(UUIDPk, Timestamps, Base):
    __tablename__ = "appointments"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    technician_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("technicians.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"), nullable=True)
    service: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, name="appointment_status"), default=AppointmentStatus.scheduled, index=True
    )
    external_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_via: Mapped[str] = mapped_column(String(32), default="dashboard")  # dashboard | voice_agent

    technician: Mapped[Technician] = relationship()
    customer: Mapped["Customer | None"] = relationship()  # noqa: F821
