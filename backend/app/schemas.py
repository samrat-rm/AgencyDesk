"""Pydantic request and response shapes. Requests never accept agency_id: the agency
always comes from the access token, so a client can't ask to act in another agency."""

import uuid

from pydantic import BaseModel, Field, field_validator

from app.models import Role


def _normalise_email(value: str) -> str:
    value = value.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("not a valid email address")
    return value


# ---------------------------------------------------------------- auth


class RegisterIn(BaseModel):
    """Sign up a new agency. The person registering becomes its first admin."""

    email: str
    password: str = Field(min_length=8, max_length=72)  # bcrypt ignores bytes past 72
    full_name: str = Field(min_length=1, max_length=200)
    agency_name: str = Field(min_length=1, max_length=200)

    _email = field_validator("email")(_normalise_email)


class LoginIn(BaseModel):
    email: str
    password: str

    _email = field_validator("email")(_normalise_email)


class MembershipOut(BaseModel):
    agency_id: uuid.UUID
    agency_name: str
    role: Role
    client_id: uuid.UUID | None
    client_name: str | None


class LoginOut(BaseModel):
    login_token: str
    memberships: list[MembershipOut]


class SelectAgencyIn(BaseModel):
    agency_id: uuid.UUID


class AccessTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    membership: MembershipOut


class MeOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    membership: MembershipOut
