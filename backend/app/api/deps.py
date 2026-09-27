import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import constant_time_equals, decode_access_token
from app.db.session import get_db
from app.models import ROLE_RANK, Role, User

bearer = HTTPBearer(auto_error=False)

DB = Annotated[AsyncSession, Depends(get_db)]


@dataclass
class Principal:
    user: User

    @property
    def org_id(self) -> uuid.UUID:
        return self.user.org_id

    @property
    def role(self) -> Role:
        return self.user.role


async def get_principal(
    request: Request,
    db: DB,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(creds.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", {"WWW-Authenticate": "Bearer"})
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or not found")
    request.state.user_id = str(user.id)
    return Principal(user=user)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_role(minimum: Role):
    """Dependency factory enforcing a minimum role within the caller's organization."""

    async def checker(principal: CurrentPrincipal) -> Principal:
        if ROLE_RANK[principal.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {minimum.value} role or higher")
        return principal

    return checker


Viewer = Annotated[Principal, Depends(require_role(Role.viewer))]
Member = Annotated[Principal, Depends(require_role(Role.member))]
Admin = Annotated[Principal, Depends(require_role(Role.admin))]
Owner = Annotated[Principal, Depends(require_role(Role.owner))]


async def require_internal_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """Auth for service-to-service calls from the LiveKit agent worker."""
    expected = get_settings().internal_api_token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing internal token")
    if not constant_time_equals(authorization.removeprefix("Bearer "), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal token")


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
