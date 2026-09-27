import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import Role
from app.schemas.common import ORM, Timezone


class RegisterIn(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    timezone: Timezone = "UTC"

    @field_validator("password")
    @classmethod
    def strong(cls, v: str) -> str:
        if not any(c.isdigit() for c in v) or not any(c.isalpha() for c in v):
            raise ValueError("Password must contain letters and numbers")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OrgOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool


class MeOut(BaseModel):
    user: UserOut
    organization: OrgOut


class InviteUserIn(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: Role = Role.member
    password: str = Field(min_length=10, max_length=128)


class UpdateUserIn(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class UpdateOrgIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    timezone: Timezone | None = None
