"""Clients and projects, plus who is assigned to each project.

Reads go through scoping. Writes are admin-only, and every id in a request body is
re-checked against the caller's agency before use.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.auth import Ctx, get_ctx, require_admin, require_staff
from app.db import get_db
from app.models import Client, Membership, Project, ProjectMember, Role, Task, TaskStatus, User
from app.schemas import (
    ClientOut,
    MemberRemovedOut,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberOut,
    ProjectOut,
)
from app.scoping import get_or_404, scoped_projects

router = APIRouter(tags=["projects"])


# ---------------------------------------------------------------- clients


@router.get("/clients", response_model=list[ClientOut])
def list_clients(ctx: Ctx = Depends(require_staff), db: Session = Depends(get_db)):
    # Staff only: clients have no reason to see the agency's other customers.
    return db.scalars(
        select(Client).where(Client.agency_id == ctx.agency_id).order_by(Client.name)
    ).all()


# ---------------------------------------------------------------- projects


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    return db.scalars(scoped_projects(ctx).order_by(Project.name)).all()


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    return get_or_404(db, scoped_projects(ctx), Project, project_id)


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, ctx: Ctx = Depends(require_admin), db: Session = Depends(get_db)):
    client = db.scalar(
        select(Client).where(Client.id == body.client_id, Client.agency_id == ctx.agency_id)
    )
    if client is None:
        # Another agency's client looks exactly like a client that doesn't exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")

    project = Project(agency_id=ctx.agency_id, client_id=client.id, name=body.name)
    db.add(project)
    db.commit()
    return project


# ---------------------------------------------------------------- project members


@router.get("/projects/{project_id}/members", response_model=list[ProjectMemberOut])
def list_members(project_id: uuid.UUID, ctx: Ctx = Depends(require_staff), db: Session = Depends(get_db)):
    get_or_404(db, scoped_projects(ctx), Project, project_id)
    rows = db.execute(
        select(User.id, User.full_name, User.email, Membership.role)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .join(
            Membership,
            (Membership.user_id == User.id) & (Membership.agency_id == ctx.agency_id),
        )
        .where(ProjectMember.project_id == project_id, ProjectMember.agency_id == ctx.agency_id)
        .order_by(User.full_name)
    ).all()
    return [ProjectMemberOut(user_id=r[0], full_name=r[1], email=r[2], role=r[3]) for r in rows]


@router.post("/projects/{project_id}/members", status_code=201)
def add_member(
    project_id: uuid.UUID,
    body: ProjectMemberAdd,
    ctx: Ctx = Depends(require_admin),
    db: Session = Depends(get_db),
):
    get_or_404(db, scoped_projects(ctx), Project, project_id)

    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == body.user_id,
            Membership.agency_id == ctx.agency_id,
            Membership.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this agency")
    if membership.role is Role.client_user:
        # The schema can't express "staff only" in this FK, so the API enforces it.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Clients cannot be project members")

    already = db.get(ProjectMember, {"project_id": project_id, "user_id": body.user_id})
    if already is None:
        db.add(ProjectMember(project_id=project_id, user_id=body.user_id, agency_id=ctx.agency_id))
        db.commit()
    return {"added": already is None}


@router.delete("/projects/{project_id}/members/{user_id}", response_model=MemberRemovedOut)
def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: Ctx = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """EDGE CASE: removing a team member mid-task.

    Decision: the member's UNFINISHED tasks on THIS project become unassigned. Tasks
    are never deleted (the work still needs doing, and comments and time logged on
    them are history), and they show as unassigned so an admin can hand them on.
    Tasks already marked done keep their assignee as a record of who did the work.
    Both changes happen in one transaction: there is no moment where the member is
    off the project but still listed as the assignee.
    """
    get_or_404(db, scoped_projects(ctx), Project, project_id)

    removed = db.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.agency_id == ctx.agency_id,
        )
    ).rowcount
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not a member of this project")

    unassigned = db.execute(
        update(Task)
        .where(
            Task.agency_id == ctx.agency_id,
            Task.project_id == project_id,
            Task.assignee_id == user_id,
            Task.status != TaskStatus.done,
        )
        .values(assignee_id=None)
    ).rowcount
    db.commit()
    return MemberRemovedOut(removed=True, tasks_unassigned=unassigned)
