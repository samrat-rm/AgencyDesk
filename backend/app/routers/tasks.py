"""Tasks. Everyone reads through scoped_tasks; only staff can create or change them."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Ctx, get_ctx, require_staff
from app.db import get_db
from app.models import Project, ProjectMember, Task, TaskStatus, Visibility
from app.schemas import TaskCreate, TaskOut, TaskUpdate
from app.scoping import get_or_404, scoped_projects, scoped_tasks

router = APIRouter(prefix="/tasks", tags=["tasks"])

# Columns that are NOT NULL in the database: an explicit null in a PATCH is an error.
_NOT_NULLABLE = {"title", "description", "status", "priority", "visibility"}


def _check_assignee(db: Session, ctx: Ctx, project_id: uuid.UUID, assignee_id: uuid.UUID | None):
    """An assignee must be on the project. The composite FK already guarantees they're
    in this agency; this adds the project-level rule the schema can't express."""
    if assignee_id is None:
        return
    on_project = db.get(ProjectMember, {"project_id": project_id, "user_id": assignee_id})
    if on_project is None or on_project.agency_id != ctx.agency_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Assignee must be a member of this project"
        )


@router.get("", response_model=list[TaskOut])
def list_tasks(
    project_id: uuid.UUID | None = None,
    status_: TaskStatus | None = Query(default=None, alias="status"),
    visibility: Visibility | None = None,
    assignee_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=200, description="Search in titles"),
    ctx: Ctx = Depends(get_ctx),
    db: Session = Depends(get_db),
):
    # Every filter below is an extra WHERE on the already-scoped query, so it can only
    # narrow the result. A client asking for visibility=internal, or searching for the
    # title of an internal task, simply gets an empty list.
    query = scoped_tasks(ctx)
    if project_id is not None:
        query = query.where(Task.project_id == project_id)
    if status_ is not None:
        query = query.where(Task.status == status_)
    if visibility is not None:
        query = query.where(Task.visibility == visibility)
    if assignee_id is not None:
        query = query.where(Task.assignee_id == assignee_id)
    if q:
        query = query.where(Task.title.ilike(f"%{q}%"))
    return db.scalars(query.order_by(Task.created_at)).all()


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: uuid.UUID, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    return get_or_404(db, scoped_tasks(ctx), Task, task_id)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, ctx: Ctx = Depends(require_staff), db: Session = Depends(get_db)):
    # The project must be one this caller can see. Another agency's project (or one a
    # member isn't assigned to) is a 404, exactly as if it didn't exist.
    project = get_or_404(db, scoped_projects(ctx), Project, body.project_id)
    _check_assignee(db, ctx, project.id, body.assignee_id)

    task = Task(
        **body.model_dump(),
        agency_id=ctx.agency_id,  # from the token, never from the request
        created_by_id=ctx.user_id,
    )
    db.add(task)
    db.commit()
    return task


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    ctx: Ctx = Depends(require_staff),  # clients can't change status or anything else
    db: Session = Depends(get_db),
):
    task = get_or_404(db, scoped_tasks(ctx), Task, task_id)
    changes = body.model_dump(exclude_unset=True)  # only fields the caller actually sent

    for field in _NOT_NULLABLE & changes.keys():
        if changes[field] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} cannot be null")
    if "assignee_id" in changes:
        _check_assignee(db, ctx, task.project_id, changes["assignee_id"])

    for field, value in changes.items():
        setattr(task, field, value)
    db.commit()
    return task
