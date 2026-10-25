"""Dashboard: task counts and hours.

Every number is computed from the SAME scoped queries the lists use. Counting is a
read: if a client's dashboard counted 6 tasks while they could only open 3, the
difference would reveal 3 internal tasks exist.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import Ctx, get_ctx
from app.db import get_db
from app.models import Project, Task, TaskStatus, TimeEntry
from app.schemas import DashboardOut
from app.scoping import get_or_404, scoped_projects, scoped_tasks, scoped_time_entries

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardOut)
def dashboard(
    project_id: uuid.UUID | None = None,
    ctx: Ctx = Depends(get_ctx),
    db: Session = Depends(get_db),
):
    tasks = scoped_tasks(ctx)
    if project_id is not None:
        get_or_404(db, scoped_projects(ctx), Project, project_id)
        tasks = tasks.where(Task.project_id == project_id)

    by_status = {s: 0 for s in TaskStatus}
    for task_status, count in db.execute(
        tasks.with_only_columns(Task.status, func.count()).group_by(Task.status)
    ):
        by_status[task_status] = count

    overdue = db.scalar(
        tasks.with_only_columns(func.count()).where(
            Task.due_date < date.today(), Task.status != TaskStatus.done
        )
    )

    # Hours only from tasks this caller can see, and only those counted above.
    minutes = db.scalar(
        scoped_time_entries(ctx)
        .with_only_columns(func.coalesce(func.sum(TimeEntry.minutes), 0))
        .where(TimeEntry.task_id.in_(tasks.with_only_columns(Task.id)))
    )

    return DashboardOut(
        project_id=project_id,
        total_tasks=sum(by_status.values()),
        tasks_by_status=by_status,
        overdue_tasks=overdue,
        hours_logged=round(minutes / 60, 2),
    )
