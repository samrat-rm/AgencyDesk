"""Authentication: passwords, tokens, and the per-request context (Ctx).

Two kinds of token:

  login token   proves WHO you are. Issued by /auth/login. Grants no data access;
                its only use is choosing an agency via /auth/select-agency.
  access token  proves who you are AND which agency you are working in. Required by
                every data endpoint.

Neither token carries the role. On every request get_ctx looks up the membership in
the database and takes the role from there, so removing someone or changing their
role takes effect on their very next request, not when the token expires.
"""

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Membership, Role

JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me")
JWT_ALG = "HS256"
LOGIN_TOKEN_TTL = timedelta(minutes=10)
ACCESS_TOKEN_TTL = timedelta(hours=8)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------- passwords


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd.verify(raw, hashed)


# ---------------------------------------------------------------- tokens


def _encode(claims: dict, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({**claims, "iat": now, "exp": now + ttl}, JWT_SECRET, JWT_ALG)


def make_login_token(user_id: uuid.UUID) -> str:
    return _encode({"sub": str(user_id), "typ": "login"}, LOGIN_TOKEN_TTL)


def make_access_token(user_id: uuid.UUID, agency_id: uuid.UUID) -> str:
    # Only the agency CHOICE goes in the token. The role is always read from the DB.
    return _encode(
        {"sub": str(user_id), "agency_id": str(agency_id), "typ": "access"},
        ACCESS_TOKEN_TTL,
    )


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def _decode(creds: HTTPAuthorizationCredentials | None) -> dict:
    if creds is None:
        raise _unauthorized()
    try:
        return jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError:
        raise _unauthorized("Invalid or expired token")


# ---------------------------------------------------------------- request context


@dataclass(frozen=True)
class Ctx:
    """Everything access control needs to know about the caller, for one request."""

    user_id: uuid.UUID
    agency_id: uuid.UUID  # from the token, never from the request body
    role: Role  # from the database, never from the token
    client_id: uuid.UUID | None  # set only for client_user

    @property
    def is_client(self) -> bool:
        return self.role is Role.client_user

    @property
    def is_admin(self) -> bool:
        return self.role is Role.agency_admin


def get_user_id_from_any_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> uuid.UUID:
    """Accepts a login OR access token. Used only by /auth/select-agency, so a
    logged-in user can also switch agencies without logging in again."""
    claims = _decode(creds)
    if claims.get("typ") not in ("login", "access"):
        raise _unauthorized("Invalid token type")
    return uuid.UUID(claims["sub"])


def get_ctx(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Ctx:
    """The dependency every data endpoint uses. No access token, no data."""
    claims = _decode(creds)
    if claims.get("typ") != "access":
        # A login token must not reach data endpoints: it isn't scoped to an agency.
        raise _unauthorized("Select an agency first")

    user_id = uuid.UUID(claims["sub"])
    agency_id = uuid.UUID(claims["agency_id"])

    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.agency_id == agency_id,
            Membership.is_active.is_(True),
        )
    )
    if membership is None:
        # Removed from the agency since the token was issued: refused immediately.
        raise _unauthorized("No active membership in this agency")

    return Ctx(
        user_id=user_id,
        agency_id=agency_id,
        role=membership.role,
        client_id=membership.client_id,
    )


# ---------------------------------------------------------------- role guards


def require_staff(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    """Agency admins and members only. Clients get 403."""
    if ctx.is_client:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agency staff only")
    return ctx


def require_admin(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    if not ctx.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agency admins only")
    return ctx
