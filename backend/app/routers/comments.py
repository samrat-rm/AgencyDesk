"""Comments on a task. Clients may comment (on tasks they can see), and whatever they
write is always client-visible: a client can't write an "internal" note they
themselves would then be unable to read."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import Ctx, get_ctx
from app.db import get_db
from app.models import Comment, Task, User, Visibility
from app.schemas import CommentCreate, CommentOut
from app.scoping import get_or_404, scoped_comments, scoped_tasks

router = APIRouter(prefix="/tasks/{task_id}/comments", tags=["comments"])


def _out(comment: Comment, author_name: str) -> CommentOut:
    return CommentOut(
        id=comment.id,
        task_id=comment.task_id,
        author_id=comment.author_id,
        author_name=author_name,
        body=comment.body,
        visibility=comment.visibility,
        created_at=comment.created_at,
    )


@router.get("", response_model=list[CommentOut])
def list_comments(task_id: uuid.UUID, ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    get_or_404(db, scoped_tasks(ctx), Task, task_id)  # can't list comments of a hidden task
    query = (
        scoped_comments(ctx)
        .where(Comment.task_id == task_id)
        .add_columns(User.full_name)  # author's name, for display
        .join(User, User.id == Comment.author_id)
        .order_by(Comment.created_at)
    )
    return [_out(comment, name) for comment, name in db.execute(query)]


@router.post("", response_model=CommentOut, status_code=201)
def create_comment(
    task_id: uuid.UUID,
    body: CommentCreate,
    ctx: Ctx = Depends(get_ctx),  # clients allowed: the brief says they can comment
    db: Session = Depends(get_db),
):
    task = get_or_404(db, scoped_tasks(ctx), Task, task_id)
    visibility = Visibility.client if ctx.is_client else body.visibility

    comment = Comment(
        agency_id=ctx.agency_id,
        task_id=task.id,
        author_id=ctx.user_id,
        body=body.body,
        visibility=visibility,
    )
    db.add(comment)
    db.commit()
    return _out(comment, db.get(User, ctx.user_id).full_name)
