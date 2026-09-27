import re
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.api.deps import DB, Admin, CurrentPrincipal, Owner, client_ip
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models import AgentConfig, Organization, Role, User
from app.schemas.auth import (
    InviteUserIn, LoginIn, MeOut, OrgOut, RegisterIn, TokenOut, UpdateOrgIn, UpdateUserIn, UserOut,
)
from app.services import audit
from app.services.tools.registry import DEFAULT_ALLOWED_ACTIONS

router = APIRouter(tags=["auth"])
settings = get_settings()

# Constant-time-ish login: always run bcrypt even for unknown emails.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    return slug or "org"


@router.post("/auth/register", response_model=TokenOut, status_code=201)
@limiter.limit(settings.rate_limit_auth)
async def register(request: Request, response: Response, body: RegisterIn, db: DB):
    email = body.email.lower()
    if (await db.execute(select(User.id).where(func.lower(User.email) == email))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    slug = _slugify(body.organization_name)
    if (await db.execute(select(Organization.id).where(Organization.slug == slug))).first():
        slug = f"{slug}-{secrets.token_hex(3)}"
    org = Organization(name=body.organization_name, slug=slug, timezone=body.timezone)
    db.add(org)
    await db.flush()
    user = User(org_id=org.id, email=email, full_name=body.full_name, password_hash=hash_password(body.password), role=Role.owner)
    db.add(user)
    # Every business starts with a working agent configuration they can customise.
    db.add(AgentConfig(org_id=org.id, name="Ava", timezone=body.timezone, allowed_actions=list(DEFAULT_ALLOWED_ACTIONS)))
    await db.flush()
    await audit.record(db, action="org.registered", org_id=org.id, user_id=user.id, ip_address=client_ip(request))
    await db.commit()
    return TokenOut(access_token=create_access_token(user.id, org.id, user.role.value))


@router.post("/auth/login", response_model=TokenOut)
@limiter.limit(settings.rate_limit_auth)
async def login(request: Request, response: Response, body: LoginIn, db: DB):
    user = (await db.execute(select(User).where(func.lower(User.email) == body.email.lower()))).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        await audit.record(
            db, action="auth.login_failed", org_id=user.org_id if user else None,
            data={"email": body.email.lower()}, ip_address=client_ip(request), commit=True,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    await audit.record(db, action="auth.login", org_id=user.org_id, user_id=user.id, ip_address=client_ip(request), commit=True)
    return TokenOut(access_token=create_access_token(user.id, user.org_id, user.role.value))


@router.get("/auth/me", response_model=MeOut)
async def me(principal: CurrentPrincipal, db: DB):
    org = await db.get(Organization, principal.org_id)
    return MeOut(user=UserOut.model_validate(principal.user), organization=OrgOut.model_validate(org))


@router.get("/users", response_model=list[UserOut])
async def list_users(principal: Admin, db: DB):
    return (await db.execute(select(User).where(User.org_id == principal.org_id).order_by(User.created_at))).scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
async def invite_user(request: Request, body: InviteUserIn, principal: Admin, db: DB):
    if body.role == Role.owner and principal.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can create owners")
    if (await db.execute(select(User.id).where(func.lower(User.email) == body.email.lower()))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(
        org_id=principal.org_id, email=body.email.lower(), full_name=body.full_name,
        password_hash=hash_password(body.password), role=body.role,
    )
    db.add(user)
    await db.flush()
    await audit.record(
        db, action="user.created", org_id=principal.org_id, user_id=principal.user.id,
        resource_type="user", resource_id=user.id, data={"role": body.role.value}, ip_address=client_ip(request),
    )
    await db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(request: Request, user_id: uuid.UUID, body: UpdateUserIn, principal: Admin, db: DB):
    target = (await db.execute(select(User).where(User.id == user_id, User.org_id == principal.org_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if target.id == principal.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot change your own role or status")
    if (target.role == Role.owner or body.role == Role.owner) and principal.role != Role.owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can modify owners")
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(target, k, v)
    await audit.record(
        db, action="user.updated", org_id=principal.org_id, user_id=principal.user.id,
        resource_type="user", resource_id=target.id, data={k: str(v) for k, v in changes.items()}, ip_address=client_ip(request),
    )
    await db.commit()
    return target


@router.patch("/organization", response_model=OrgOut)
async def update_org(request: Request, body: UpdateOrgIn, principal: Owner, db: DB):
    org = await db.get(Organization, principal.org_id)
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(org, k, v)
    await audit.record(db, action="organization.updated", org_id=org.id, user_id=principal.user.id, data=changes, ip_address=client_ip(request))
    await db.commit()
    return org
