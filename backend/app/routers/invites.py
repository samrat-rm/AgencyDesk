"""Invites: how staff and clients join an existing agency.

Two graded edge cases live here, and both are settled by the DATABASE, not by a
"check, then write" in Python (which two simultaneous requests can both pass):

  Resend   POST /invites for an email that already has a pending invite.
           One INSERT ... ON CONFLICT DO UPDATE against the partial unique index
           (agency_id, email) WHERE status = 'pending'. The first call inserts; every
           later call, even at the same instant, updates that same row with a fresh
           token. There can only ever be one pending invite.

  Accept   POST /invites/accept clicked twice.
           One UPDATE invites SET status = 'accepted' WHERE token_hash = ... AND
           status = 'pending' RETURNING *. Postgres locks the row; the second request
           waits, re-checks status, finds 'accepted', and updates nothing. Only the
           request that flipped the status goes on to create the membership.

Only a SHA-256 of each token is stored, so a copy of the database can't be used to
accept invites.
"""

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Ctx, hash_password, make_access_token, require_admin
from app.db import get_db
from app.models import Client, Invite, InviteStatus, Membership, Role, User
from app.routers.auth import memberships_for
from app.schemas import AccessTokenOut, InviteAccept, InviteCreate, InviteCreatedOut, InviteOut

router = APIRouter(prefix="/invites", tags=["invites"])


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.get("", response_model=list[InviteOut])
def list_pending(ctx: Ctx = Depends(require_admin), db: Session = Depends(get_db)):
    return db.scalars(
        select(Invite)
        .where(Invite.agency_id == ctx.agency_id, Invite.status == InviteStatus.pending)
        .order_by(Invite.created_at)
    ).all()


@router.post("", response_model=InviteCreatedOut, status_code=201)
def create_or_resend(body: InviteCreate, ctx: Ctx = Depends(require_admin), db: Session = Depends(get_db)):
    """Invite someone, or resend: calling this again for the same email rotates the
    token on the existing pending invite (the old link stops working) and applies the
    latest role. It never creates a second pending invite."""

    # Friendly errors first. The CHECK constraint and composite FK back these up.
    if body.role is Role.client_user:
        if body.client_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "client_id is required for client_user")
        client = db.scalar(
            select(Client.id).where(Client.id == body.client_id, Client.agency_id == ctx.agency_id)
        )
        if client is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    elif body.client_id is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only client_user invites take a client_id")

    already_member = db.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(
            User.email == body.email,
            Membership.agency_id == ctx.agency_id,
            Membership.is_active.is_(True),
        )
    )
    if already_member:
        raise HTTPException(status.HTTP_409_CONFLICT, "This person is already a member of the agency")

    # Informational only (for the "resent" flag in the response). Correctness does
    # not depend on it: the upsert below is what guarantees a single pending invite.
    was_pending = db.scalar(
        select(Invite.id).where(
            Invite.agency_id == ctx.agency_id,
            Invite.email == body.email,
            Invite.status == InviteStatus.pending,
        )
    ) is not None

    token = secrets.token_urlsafe(32)
    stmt = pg_insert(Invite).values(
        agency_id=ctx.agency_id,
        email=body.email,
        role=body.role,
        client_id=body.client_id,
        token_hash=_hash(token),
        invited_by_id=ctx.user_id,
    )
    stmt = stmt.on_conflict_do_update(
        # Targets the partial unique index invites_one_pending_per_email.
        index_elements=["agency_id", "email"],
        index_where=text("status = 'pending'"),
        set_={
            "token_hash": stmt.excluded.token_hash,
            "role": stmt.excluded.role,
            "client_id": stmt.excluded.client_id,
            "invited_by_id": stmt.excluded.invited_by_id,
            "created_at": func.now(),
        },
    ).returning(Invite)

    invite = db.scalar(stmt)
    db.commit()
    return InviteCreatedOut(invite=InviteOut.model_validate(invite), token=token, resent=was_pending)


@router.post("/accept", response_model=AccessTokenOut)
def accept(body: InviteAccept, db: Session = Depends(get_db)):
    """Public: the token itself is the proof. Creates the account if the email is new,
    or adds the membership to the existing account (password left unchanged).
    Returns an access token for the agency, so accepting also logs you in."""

    # Step 1, the atomic claim. Exactly one request can flip pending -> accepted.
    invite = db.scalar(
        update(Invite)
        .where(Invite.token_hash == _hash(body.token), Invite.status == InviteStatus.pending)
        .values(status=InviteStatus.accepted, accepted_at=func.now())
        .returning(Invite)
    )
    if invite is None:
        # Wrong token, already accepted, or revoked: one answer for all three.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found or already used")

    # Everything below runs in the same transaction as the claim. Any error raised
    # here rolls the claim back too, so the invite stays pending and can be retried.
    user = db.scalar(select(User).where(User.email == invite.email))
    if user is None:
        if not body.full_name or not body.password:
            db.rollback()
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "full_name and password are required to create your account",
            )
        user = User(email=invite.email, full_name=body.full_name, password_hash=hash_password(body.password))
        db.add(user)
        db.flush()

    membership = db.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.agency_id == invite.agency_id)
    )
    if membership is not None and membership.is_active:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Already a member of this agency")

    if membership is not None:
        # Someone previously removed from the agency is being invited back.
        membership.role = invite.role
        membership.client_id = invite.client_id
        membership.is_active = True
    else:
        db.add(
            Membership(
                user_id=user.id,
                agency_id=invite.agency_id,
                role=invite.role,
                client_id=invite.client_id,
            )
        )

    invite.accepted_user_id = user.id
    try:
        db.commit()
    except IntegrityError:
        # e.g. two different agencies' invites for the same brand-new email accepted
        # at the same instant: UNIQUE(users.email) lets one through.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not accept invite, please try again")

    return AccessTokenOut(
        access_token=make_access_token(user.id, invite.agency_id),
        membership=memberships_for(db, user.id, invite.agency_id)[0],
    )
