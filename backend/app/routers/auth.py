"""Auth endpoints.

Flow:  POST /auth/login            -> login_token + list of memberships
       POST /auth/select-agency    -> access_token for ONE agency
       (every other endpoint)      -> Authorization: Bearer <access_token>

The same email can hold memberships in several agencies with different roles
(Rahul: staff at Pixel, client at Northwind). Login returns all of them; the user
picks one, and only that agency's data is reachable with the resulting token.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    Ctx,
    get_ctx,
    get_user_id_from_any_token,
    hash_password,
    make_access_token,
    make_login_token,
    verify_password,
)
from app.db import get_db
from app.models import Agency, Client, Membership, Role, User
from app.schemas import (
    AccessTokenOut,
    LoginIn,
    LoginOut,
    MeOut,
    MembershipOut,
    RegisterIn,
    SelectAgencyIn,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _memberships_for(db: Session, user_id: uuid.UUID, agency_id: uuid.UUID | None = None):
    """Active memberships for a user, joined with agency and client names."""
    q = (
        select(Membership, Agency.name, Client.name)
        .join(Agency, Agency.id == Membership.agency_id)
        .outerjoin(Client, Client.id == Membership.client_id)
        .where(Membership.user_id == user_id, Membership.is_active.is_(True))
        .order_by(Agency.name)
    )
    if agency_id is not None:
        q = q.where(Membership.agency_id == agency_id)
    return [
        MembershipOut(
            agency_id=m.agency_id,
            agency_name=agency_name,
            role=m.role,
            client_id=m.client_id,
            client_name=client_name,
        )
        for m, agency_name, client_name in db.execute(q).all()
    ]


@router.post("/register", response_model=AccessTokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    """Create a person + a new agency + an admin membership, in one transaction."""
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered; log in instead")

    user = User(
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
    )
    agency = Agency(name=body.agency_name)
    db.add_all([user, agency])
    try:
        db.flush()
        db.add(Membership(user_id=user.id, agency_id=agency.id, role=Role.agency_admin))
        db.commit()
    except IntegrityError:
        # Two simultaneous registrations with one email: the UNIQUE on users.email
        # lets exactly one win; the other lands here instead of creating a duplicate.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered; log in instead")

    return AccessTokenOut(
        access_token=make_access_token(user.id, agency.id),
        membership=_memberships_for(db, user.id, agency.id)[0],
    )


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        # Same message for "no such email" and "wrong password": no account probing.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    return LoginOut(
        login_token=make_login_token(user.id),
        memberships=_memberships_for(db, user.id),
    )


@router.post("/select-agency", response_model=AccessTokenOut)
def select_agency(
    body: SelectAgencyIn,
    user_id: uuid.UUID = Depends(get_user_id_from_any_token),
    db: Session = Depends(get_db),
):
    found = _memberships_for(db, user_id, body.agency_id)
    if not found:
        # 404, not 403: don't confirm that an agency with this id exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No membership in that agency")

    return AccessTokenOut(
        access_token=make_access_token(user_id, body.agency_id),
        membership=found[0],
    )


@router.get("/me", response_model=MeOut)
def me(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    user = db.get(User, ctx.user_id)
    return MeOut(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        membership=_memberships_for(db, ctx.user_id, ctx.agency_id)[0],
    )
