"""File attachments on tasks, with client approval.

Staff upload (choosing internal or client-visible). Everyone lists and downloads
through scoped_attachments, so a client never sees an internal file, even on a task
they can see. Only client users can approve or request changes.
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import Ctx, get_ctx, require_client, require_staff
from app.db import get_db
from app.models import ApprovalStatus, Attachment, Task, Visibility
from app.schemas import AttachmentOut, ReviewIn
from app.scoping import get_or_404, scoped_attachments, scoped_tasks
from app.storage import MAX_UPLOAD_BYTES, UPLOAD_ROOT

router = APIRouter(tags=["attachments"])


@router.post("/tasks/{task_id}/attachments", response_model=AttachmentOut, status_code=201)
def upload(
    task_id: uuid.UUID,
    file: UploadFile = File(...),
    visibility: Visibility = Form(Visibility.internal),  # fails closed, like tasks
    ctx: Ctx = Depends(require_staff),
    db: Session = Depends(get_db),
):
    task = get_or_404(db, scoped_tasks(ctx), Task, task_id)

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File larger than 10 MB")

    # Never trust the uploaded name as a path: keep only the last component, so
    # "../../etc/passwd" becomes "passwd". The random prefix avoids collisions.
    original = Path(file.filename or "upload").name[:200] or "upload"
    relative = Path(str(ctx.agency_id)) / f"{uuid.uuid4().hex}-{original}"
    destination = UPLOAD_ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)

    attachment = Attachment(
        agency_id=ctx.agency_id,
        task_id=task.id,
        uploaded_by_id=ctx.user_id,
        filename=original,
        storage_path=str(relative),
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        visibility=visibility,
    )
    db.add(attachment)
    db.commit()
    return attachment


@router.get("/tasks/{task_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(task_id: uuid.UUID, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    get_or_404(db, scoped_tasks(ctx), Task, task_id)
    query = scoped_attachments(ctx).where(Attachment.task_id == task_id)
    return db.scalars(query.order_by(Attachment.created_at)).all()


@router.get("/attachments/{attachment_id}/download")
def download(attachment_id: uuid.UUID, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    # Downloading is a read like any other, so it goes through the same scoping.
    attachment = get_or_404(db, scoped_attachments(ctx), Attachment, attachment_id)
    path = (UPLOAD_ROOT / attachment.storage_path).resolve()
    if not path.is_relative_to(UPLOAD_ROOT) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.filename)


@router.post("/attachments/{attachment_id}/review", response_model=AttachmentOut)
def review(
    attachment_id: uuid.UUID,
    body: ReviewIn,
    ctx: Ctx = Depends(require_client),
    db: Session = Depends(get_db),
):
    """Client approves or requests changes. Can be changed later; the latest decision
    wins. A new version is uploaded as a new attachment and starts as pending."""
    attachment = get_or_404(db, scoped_attachments(ctx), Attachment, attachment_id)
    attachment.approval_status = ApprovalStatus(body.decision)
    attachment.reviewed_by_id = ctx.user_id
    attachment.reviewed_at = func.now()
    db.commit()
    db.refresh(attachment)
    return attachment
