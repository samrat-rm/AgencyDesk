"""THE access-control module. Every read in the app goes through these functions.

Each function returns a SELECT that already contains every restriction the caller is
subject to. Routers add their own filters (status, search, one id...) ON TOP of it,
and an extra WHERE can only narrow a query, never widen it. So no filter, search or
lookup by id can reach a row this module didn't already allow.

Three walls, applied in this order:

  1. Agency wall      always:  row.agency_id == the agency in the access token
  2. Project wall     agency_member: only projects they're assigned to
                      client_user:   only projects of THEIR client
  3. Visibility wall  client_user:   only rows marked visibility = 'client'

Scoping is built upward: tasks are limited to visible projects, comments and
attachments to visible tasks. So a rule written once for projects automatically
covers everything underneath it.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import Select, exists, select
from sqlalchemy.orm import Session

from app.auth import Ctx
from app.models import (
    Attachment,
    Comment,
    Project,
    ProjectMember,
    Role,
    Task,
    TimeEntry,
    Visibility,
)

# ---------------------------------------------------------------- projects


def scoped_projects(ctx: Ctx) -> Select:
    q = select(Project).where(Project.agency_id == ctx.agency_id)  # wall 1

    if ctx.role is Role.client_user:  # wall 2, clients
        q = q.where(Project.client_id == ctx.client_id)

    elif ctx.role is Role.agency_member:  # wall 2, members
        # EXISTS rather than JOIN: answers "is there a matching row?" without
        # duplicating projects in the result.
        q = q.where(
            exists().where(
                ProjectMember.project_id == Project.id,
                ProjectMember.agency_id == ctx.agency_id,
                ProjectMember.user_id == ctx.user_id,
            )
        )

    # agency_admin: no extra wall, they see the whole agency.
    return q


def visible_project_ids(ctx: Ctx) -> Select:
    """The same rule as scoped_projects, returning only ids, for use as a subquery."""
    return scoped_projects(ctx).with_only_columns(Project.id)


# ---------------------------------------------------------------- tasks


def scoped_tasks(ctx: Ctx) -> Select:
    q = select(Task).where(
        Task.agency_id == ctx.agency_id,  # wall 1
        Task.project_id.in_(visible_project_ids(ctx)),  # wall 2, inherited
    )
    if ctx.role is Role.client_user:  # wall 3
        q = q.where(Task.visibility == Visibility.client)
    return q


def visible_task_ids(ctx: Ctx) -> Select:
    return scoped_tasks(ctx).with_only_columns(Task.id)


# ---------------------------------------------------------------- things on a task


def scoped_comments(ctx: Ctx) -> Select:
    q = select(Comment).where(
        Comment.agency_id == ctx.agency_id,
        Comment.task_id.in_(visible_task_ids(ctx)),  # walls 2 and 3 for the task
    )
    if ctx.role is Role.client_user:
        # The comment needs its OWN check: an internal note on a client-visible task
        # would otherwise leak through the task's visibility.
        q = q.where(Comment.visibility == Visibility.client)
    return q


def scoped_attachments(ctx: Ctx) -> Select:
    q = select(Attachment).where(
        Attachment.agency_id == ctx.agency_id,
        Attachment.task_id.in_(visible_task_ids(ctx)),
    )
    if ctx.role is Role.client_user:
        q = q.where(Attachment.visibility == Visibility.client)
    return q


def scoped_time_entries(ctx: Ctx) -> Select:
    # Time has no visibility flag of its own; it follows its task. A client therefore
    # only ever counts hours logged on tasks they are allowed to open.
    return select(TimeEntry).where(
        TimeEntry.agency_id == ctx.agency_id,
        TimeEntry.task_id.in_(visible_task_ids(ctx)),
    )


# ---------------------------------------------------------------- fetch one


def get_or_404(db: Session, scoped_query: Select, model, row_id: uuid.UUID):
    """Fetch one row by id THROUGH a scoped query.

    Another agency's row, a project you're not on, and an internal task seen by a
    client all give the same 404 as an id that doesn't exist. A 403 would confirm
    the row is real.
    """
    row = db.scalar(scoped_query.where(model.id == row_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return row
