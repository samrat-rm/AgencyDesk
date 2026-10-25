"""Time tracking: schema plus one endpoint (by design, see README Scope).
Hours are summed into the dashboard."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import Ctx, require_staff
from app.db import get_db
from app.models import Task, TimeEntry
from app.schemas import TimeEntryCreate, TimeEntryOut
from app.scoping import get_or_404, scoped_tasks

router = APIRouter(prefix="/time-entries", tags=["time"])


@router.post("", response_model=TimeEntryOut, status_code=201)
def log_time(body: TimeEntryCreate, ctx: Ctx = Depends(require_staff), db: Session = Depends(get_db)):
    # The task must be one this person can see: members only on their own projects.
    task = get_or_404(db, scoped_tasks(ctx), Task, body.task_id)

    entry = TimeEntry(
        agency_id=ctx.agency_id,
        task_id=task.id,
        user_id=ctx.user_id,  # you log your own time, never someone else's
        minutes=body.minutes,
        note=body.note,
        entry_date=body.entry_date or date.today(),
    )
    db.add(entry)
    db.commit()
    return entry
