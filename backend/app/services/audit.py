import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record(
    db: AsyncSession,
    *,
    action: str,
    actor: str = "user",
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | uuid.UUID | None = None,
    data: dict | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> None:
    """Append an audit entry. Callers normally commit it with their own transaction."""
    db.add(
        AuditLog(
            org_id=org_id,
            user_id=user_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            data=data or {},
            ip_address=ip_address,
        )
    )
    if commit:
        await db.commit()
