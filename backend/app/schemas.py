"""Pydantic request and response shapes. Requests never accept agency_id: the agency
always comes from the access token, so a client can't ask to act in another agency."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Role, TaskPriority, TaskStatus, Visibility


def _normalise_email(value: str) -> str:
    value = value.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("not a valid email address")
    return value


# ---------------------------------------------------------------- auth


class RegisterIn(BaseModel):
    """Sign up a new agency. The person registering becomes its first admin."""

    email: str
    password: str = Field(min_length=8, max_length=72)  # bcrypt ignores bytes past 72
    full_name: str = Field(min_length=1, max_length=200)
    agency_name: str = Field(min_length=1, max_length=200)

    _email = field_validator("email")(_normalise_email)


class LoginIn(BaseModel):
    email: str
    password: str

    _email = field_validator("email")(_normalise_email)


class MembershipOut(BaseModel):
    agency_id: uuid.UUID
    agency_name: str
    role: Role
    client_id: uuid.UUID | None
    client_name: str | None


class LoginOut(BaseModel):
    login_token: str
    memberships: list[MembershipOut]


class SelectAgencyIn(BaseModel):
    agency_id: uuid.UUID


class AccessTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    membership: MembershipOut


class MeOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    membership: MembershipOut


# ---------------------------------------------------------------- shared


class ORMOut(BaseModel):
    """Response models that can be built straight from SQLAlchemy rows."""

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- clients and projects


class ClientOut(ORMOut):
    id: uuid.UUID
    name: str


class ProjectOut(ORMOut):
    id: uuid.UUID
    client_id: uuid.UUID
    name: str
    created_at: datetime


class ProjectCreate(BaseModel):
    client_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)


class ProjectMemberAdd(BaseModel):
    user_id: uuid.UUID


class ProjectMemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    role: Role


class MemberRemovedOut(BaseModel):
    removed: bool
    tasks_unassigned: int


# ---------------------------------------------------------------- tasks


class TaskOut(ORMOut):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    assignee_id: uuid.UUID | None
    due_date: date | None
    visibility: Visibility
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    status: TaskStatus = TaskStatus.todo
    priority: TaskPriority = TaskPriority.medium
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    # Same default as the database: leaving it out means internal.
    visibility: Visibility = Visibility.internal


class TaskUpdate(BaseModel):
    """Every field optional: only the fields actually sent are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    visibility: Visibility | None = None


# ---------------------------------------------------------------- comments


class CommentOut(ORMOut):
    id: uuid.UUID
    task_id: uuid.UUID
    author_id: uuid.UUID
    body: str
    visibility: Visibility
    created_at: datetime


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)
    # Staff choose; for clients the server overrides this to 'client'.
    visibility: Visibility = Visibility.internal
