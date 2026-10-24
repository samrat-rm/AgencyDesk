"""AgencyDesk schema.

Three rules shape every table below:

1. Every tenant-owned table carries agency_id and UNIQUE (id, agency_id).
2. Every reference between tenant-owned tables is a COMPOSITE foreign key
   (child_ref_id, agency_id) -> parent(id, agency_id). Because both rows must share
   the same agency_id, the database itself refuses a cross-agency link.
3. visibility defaults to 'internal', so anything created without an explicit
   decision is hidden from clients (fails closed).

People are split in two: `users` is global identity (one row per human, one login),
`memberships` is one row per (user, agency) carrying the role in that agency.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


# ---------------------------------------------------------------- enums


class Role(str, enum.Enum):
    agency_admin = "agency_admin"
    agency_member = "agency_member"
    client_user = "client_user"


class Visibility(str, enum.Enum):
    internal = "internal"
    client = "client"


class TaskStatus(str, enum.Enum):
    todo = "todo"
    in_progress = "in_progress"
    in_review = "in_review"
    done = "done"


class TaskPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    changes_requested = "changes_requested"


class InviteStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


def pg_enum(enum_cls, name):
    # Store the enum's string values in a real Postgres ENUM type.
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


role_enum = pg_enum(Role, "role_enum")
visibility_enum = pg_enum(Visibility, "visibility_enum")
task_status_enum = pg_enum(TaskStatus, "task_status_enum")
task_priority_enum = pg_enum(TaskPriority, "task_priority_enum")
approval_status_enum = pg_enum(ApprovalStatus, "approval_status_enum")
invite_status_enum = pg_enum(InviteStatus, "invite_status_enum")


# ---------------------------------------------------------------- helpers


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


def agency_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )


def created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------- global tables


class Agency(Base):
    """The tenant. The only table with no agency_id, because it IS the agency."""

    __tablename__ = "agencies"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = created_at()


class User(Base):
    """Global identity: one row per human, one email, one password.

    Deliberately has no agency_id and no role. Those live on Membership, which is
    what lets the same person be staff at one agency and a client at another.
    """

    __tablename__ = "users"
    __table_args__ = (
        # Emails are stored lowercased so 'Maya@x.com' and 'maya@x.com' can't be two users.
        CheckConstraint("email = lower(email)", name="users_email_lowercase"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = created_at()


# ---------------------------------------------------------------- tenant-owned tables


class Client(Base):
    """A company the agency works for (e.g. Bloom Bakery)."""

    __tablename__ = "clients"
    __table_args__ = (
        # Target for composite FKs: lets children prove "this client is in MY agency".
        UniqueConstraint("id", "agency_id", name="clients_id_agency_uq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    agency_id: Mapped[uuid.UUID] = agency_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = created_at()


class Membership(Base):
    """One row per (person, agency): the role that person has inside that agency."""

    __tablename__ = "memberships"
    __table_args__ = (
        # One role per person per agency. Also the target for every "which person"
        # composite FK below (assignee, author, uploader...).
        UniqueConstraint("user_id", "agency_id", name="memberships_user_agency_uq"),
        # A client_user must point at a client in the SAME agency.
        ForeignKeyConstraint(
            ["client_id", "agency_id"],
            ["clients.id", "clients.agency_id"],
            name="memberships_client_fk",
        ),
        # client_user <=> has a client_id. Staff never have one.
        CheckConstraint(
            "(role = 'client_user' AND client_id IS NOT NULL) OR "
            "(role <> 'client_user' AND client_id IS NULL)",
            name="memberships_client_user_has_client",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agency_id: Mapped[uuid.UUID] = agency_fk()
    role: Mapped[Role] = mapped_column(role_enum, nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = created_at()


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="projects_id_agency_uq"),
        # A project can only belong to a client of the same agency.
        ForeignKeyConstraint(
            ["client_id", "agency_id"],
            ["clients.id", "clients.agency_id"],
            name="projects_client_fk",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    agency_id: Mapped[uuid.UUID] = agency_fk()
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = created_at()


class ProjectMember(Base):
    """Which agency staff are assigned to which project (drives agency_member scoping)."""

    __tablename__ = "project_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "agency_id"],
            ["projects.id", "projects.agency_id"],
            ondelete="CASCADE",
            name="project_members_project_fk",
        ),
        # The person must hold a membership in the same agency as the project.
        ForeignKeyConstraint(
            ["user_id", "agency_id"],
            ["memberships.user_id", "memberships.agency_id"],
            ondelete="CASCADE",
            name="project_members_membership_fk",
        ),
        Index("project_members_user_idx", "agency_id", "user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = agency_fk()
    created_at: Mapped[datetime] = created_at()


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "agency_id", name="tasks_id_agency_uq"),
        ForeignKeyConstraint(
            ["project_id", "agency_id"],
            ["projects.id", "projects.agency_id"],
            ondelete="CASCADE",
            name="tasks_project_fk",
        ),
        # Assignee must be a person in this agency. NULL assignee = unassigned.
        ForeignKeyConstraint(
            ["assignee_id", "agency_id"],
            ["memberships.user_id", "memberships.agency_id"],
            name="tasks_assignee_fk",
        ),
        ForeignKeyConstraint(
            ["created_by_id", "agency_id"],
            ["memberships.user_id", "memberships.agency_id"],
            name="tasks_created_by_fk",
        ),
        Index("tasks_project_idx", "agency_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    agency_id: Mapped[uuid.UUID] = agency_fk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    status: Mapped[TaskStatus] = mapped_column(
        task_status_enum, nullable=False, default=TaskStatus.todo, server_default="todo"
    )
    priority: Mapped[TaskPriority] = mapped_column(
        task_priority_enum,
        nullable=False,
        default=TaskPriority.medium,
        server_default="medium",
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    due_date: Mapped[date | None] = mapped_column(Date)
    # Fails closed: forget to set it and the client never sees the task.
    visibility: Mapped[Visibility] = mapped_column(
        visibility_enum,
        nullable=False,
        default=Visibility.internal,
        server_default="internal",
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "agency_id"],
            ["tasks.id", "tasks.agency_id"],
            ondelete="CASCADE",
            name="comments_task_fk",
        ),
        ForeignKeyConstraint(
            ["author_id", "agency_id"],
            ["memberships.user_id", "memberships.agency_id"],
            name="comments_author_fk",
        ),
        Index("comments_task_idx", "agency_id", "task_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    agency_id: Mapped[uuid.UUID] = agency_fk()
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Same flag as tasks: an internal note on a client-visible task stays hidden.
    visibility: Mapped[Visibility] = mapped_column(
        visibility_enum,
        nullable=False,
        default=Visibility.internal,
        server_default="internal",
    )
    created_at: Mapped[datetime] = created_at()


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "agency_id"],
            ["tasks.id", "tasks.agency_id"],
            ondelete="CASCADE",
            name="attachments_task_fk",
        ),
        ForeignKeyConstraint(
            ["uploaded_by_id", "agency_id"],
            ["memberships.user_id", "memberships.agency_id"],
            name="attachments_uploaded_by_fk",
        ),
        ForeignKeyConstraint(
            ["reviewed_by_id", "agency_id"],
            ["memberships.user_id", "memberships.agency_id"],
            name="attachments_reviewed_by_fk",
        ),
        # A review decision and its reviewer travel together.
        CheckConstraint(
            "(approval_status = 'pending' AND reviewed_by_id IS NULL) OR "
            "(approval_status <> 'pending' AND reviewed_by_id IS NOT NULL)",
            name="attachments_review_consistent",
        ),
        CheckConstraint("size_bytes >= 0", name="attachments_size_nonneg"),
        Index("attachments_task_idx", "agency_id", "task_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    agency_id: Mapped[uuid.UUID] = agency_fk()
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    visibility: Mapped[Visibility] = mapped_column(
        visibility_enum,
        nullable=False,
        default=Visibility.internal,
        server_default="internal",
    )
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        approval_status_enum,
        nullable=False,
        default=ApprovalStatus.pending,
        server_default="pending",
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class TimeEntry(Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "agency_id"],
            ["tasks.id", "tasks.agency_id"],
            ondelete="CASCADE",
            name="time_entries_task_fk",
        ),
        ForeignKeyConstraint(
            ["user_id", "agency_id"],
            ["memberships.user_id", "memberships.agency_id"],
            name="time_entries_user_fk",
        ),
        # Stored in whole minutes; one entry can't be zero, negative, or over a day.
        CheckConstraint(
            "minutes > 0 AND minutes <= 1440", name="time_entries_minutes_range"
        ),
        Index("time_entries_task_idx", "agency_id", "task_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    agency_id: Mapped[uuid.UUID] = agency_fk()
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = created_at()


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["client_id", "agency_id"],
            ["clients.id", "clients.agency_id"],
            name="invites_client_fk",
        ),
        ForeignKeyConstraint(
            ["invited_by_id", "agency_id"],
            ["memberships.user_id", "memberships.agency_id"],
            name="invites_invited_by_fk",
        ),
        # Same rule as memberships, so an invite can never produce a broken membership.
        CheckConstraint(
            "(role = 'client_user' AND client_id IS NOT NULL) OR "
            "(role <> 'client_user' AND client_id IS NULL)",
            name="invites_client_user_has_client",
        ),
        CheckConstraint("email = lower(email)", name="invites_email_lowercase"),
        # THE invite-race guard: at most one PENDING invite per (agency, email).
        # Accepted/revoked invites are history and may repeat.
        Index(
            "invites_one_pending_per_email",
            "agency_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    agency_id: Mapped[uuid.UUID] = agency_fk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[Role] = mapped_column(role_enum, nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Only a SHA-256 of the token is stored, so a DB leak can't be used to accept invites.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[InviteStatus] = mapped_column(
        invite_status_enum,
        nullable=False,
        default=InviteStatus.pending,
        server_default="pending",
    )
    invited_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = created_at()
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
