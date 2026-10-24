"""Seed data for the demo and the video.

Run:  python -m app.seed      (wipes and refills every table; safe to re-run)

Cast:
  Pixel & Co (agency A)
    priya@pixel.co        agency_admin
    arjun@pixel.co        agency_member  -> Bloom website project
    rahul@devmail.com     agency_member  -> Harbor app project
    maya@bloombakery.com  client_user    -> client Bloom Bakery
  Northwind Studio (agency B)
    nora@northwind.studio agency_admin
    maya@bloombakery.com  client_user    -> client Bloom Bakery (a DIFFERENT row)
    rahul@devmail.com     client_user    -> client Rahul Mehta (his own portfolio)

Rahul is the "one person, two agencies, different roles" case.
Maya is the "same person is a client of two agencies" case.
Every project has a mix of internal and client-visible tasks.
"""

import hashlib
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from app.auth import hash_password
from app.db import SessionLocal
from app.models import (
    Agency,
    Attachment,
    Client,
    Comment,
    Invite,
    Membership,
    Project,
    ProjectMember,
    Role,
    Task,
    TaskPriority,
    TaskStatus,
    TimeEntry,
    User,
    Visibility,
)

PASSWORD = "password123"
UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "uploads"
DEMO_INVITE_TOKEN = "demo-invite-token-harbor"

C, I = Visibility.client, Visibility.internal
S = TaskStatus
P = TaskPriority


def wipe(db):
    db.execute(
        text(
            "TRUNCATE time_entries, attachments, comments, tasks, project_members, "
            "invites, projects, memberships, clients, users, agencies CASCADE"
        )
    )


def run():
    db = SessionLocal()
    wipe(db)
    today = date.today()
    pw = hash_password(PASSWORD)  # hash once; bcrypt is deliberately slow

    # ---- people (global identity, no roles here)
    users = {
        key: User(email=email, full_name=name, password_hash=pw)
        for key, email, name in [
            ("priya", "priya@pixel.co", "Priya Shah"),
            ("arjun", "arjun@pixel.co", "Arjun Rao"),
            ("rahul", "rahul@devmail.com", "Rahul Mehta"),
            ("maya", "maya@bloombakery.com", "Maya Lin"),
            ("nora", "nora@northwind.studio", "Nora Quinn"),
        ]
    }
    db.add_all(users.values())

    # ---- tenants
    pixel = Agency(name="Pixel & Co")
    north = Agency(name="Northwind Studio")
    db.add_all([pixel, north])
    db.flush()

    # ---- clients (Bloom Bakery exists once PER agency: separate rows, separate data)
    bloom_px = Client(agency_id=pixel.id, name="Bloom Bakery")
    harbor_px = Client(agency_id=pixel.id, name="Harbor Fitness")
    bloom_nw = Client(agency_id=north.id, name="Bloom Bakery")
    rahul_nw = Client(agency_id=north.id, name="Rahul Mehta")
    db.add_all([bloom_px, harbor_px, bloom_nw, rahul_nw])
    db.flush()

    # ---- memberships: the role lives here, per agency
    def member(user, agency, role, client=None):
        db.add(
            Membership(
                user_id=users[user].id,
                agency_id=agency.id,
                role=role,
                client_id=client.id if client else None,
            )
        )

    member("priya", pixel, Role.agency_admin)
    member("arjun", pixel, Role.agency_member)
    member("rahul", pixel, Role.agency_member)
    member("maya", pixel, Role.client_user, bloom_px)
    member("nora", north, Role.agency_admin)
    member("maya", north, Role.client_user, bloom_nw)
    member("rahul", north, Role.client_user, rahul_nw)
    db.flush()

    # ---- projects
    web = Project(agency_id=pixel.id, client_id=bloom_px.id, name="Bloom website redesign")
    app_ = Project(agency_id=pixel.id, client_id=harbor_px.id, name="Harbor app launch")
    social = Project(agency_id=north.id, client_id=bloom_nw.id, name="Bloom social media")
    folio = Project(agency_id=north.id, client_id=rahul_nw.id, name="Rahul portfolio site")
    db.add_all([web, app_, social, folio])
    db.flush()

    db.add_all(
        [
            ProjectMember(project_id=web.id, user_id=users["arjun"].id, agency_id=pixel.id),
            ProjectMember(project_id=app_.id, user_id=users["rahul"].id, agency_id=pixel.id),
        ]
    )

    # ---- tasks: (project, title, visibility, status, priority, assignee, due_in_days, creator)
    def task(project, title, vis, status, prio, assignee, due, creator):
        t = Task(
            agency_id=project.agency_id,
            project_id=project.id,
            title=title,
            visibility=vis,
            status=status,
            priority=prio,
            assignee_id=users[assignee].id if assignee else None,
            due_date=today + timedelta(days=due) if due is not None else None,
            created_by_id=users[creator].id,
        )
        db.add(t)
        return t

    homepage = task(web, "Design homepage mockup", C, S.in_progress, P.high, "arjun", 3, "priya")
    task(web, "Write About page copy", C, S.todo, P.medium, None, 7, "priya")
    task(web, "Launch checklist", C, S.todo, P.low, None, 21, "priya")
    staging = task(web, "Set up staging server", I, S.done, P.medium, "arjun", None, "arjun")
    task(web, "Negotiate freelancer rates", I, S.todo, P.high, None, 2, "priya")
    task(web, "Budget overrun review", I, S.in_review, P.urgent, None, 1, "priya")

    onboarding = task(app_, "Onboarding screens", C, S.in_progress, P.high, "rahul", 5, "priya")
    task(app_, "App store listing", C, S.todo, P.medium, None, 14, "priya")
    task(app_, "Pick push notification vendor", I, S.todo, P.medium, "rahul", 4, "priya")

    task(social, "Instagram content calendar", C, S.in_progress, P.medium, None, 6, "nora")
    task(social, "Ad spend review", I, S.todo, P.high, None, 3, "nora")

    task(folio, "Portfolio wireframes", C, S.todo, P.medium, None, 10, "nora")
    task(folio, "Estimate hours and margin", I, S.todo, P.low, None, 2, "nora")
    db.flush()

    # ---- comments: a client-visible thread plus an internal note on the SAME task
    db.add_all(
        [
            Comment(agency_id=pixel.id, task_id=homepage.id, author_id=users["arjun"].id,
                    body="First draft is attached, keen to hear your thoughts.", visibility=C),
            Comment(agency_id=pixel.id, task_id=homepage.id, author_id=users["maya"].id,
                    body="Love it. Can the logo be a bit bigger?", visibility=C),
            Comment(agency_id=pixel.id, task_id=homepage.id, author_id=users["arjun"].id,
                    body="INTERNAL: their logo files are low-res, chase them for vectors.",
                    visibility=I),
        ]
    )

    # ---- attachments: one client-visible, one internal, on the same task
    def attachment(task_row, filename, content_type, vis, uploader, body: bytes):
        folder = UPLOAD_ROOT / str(task_row.agency_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"seed-{filename}"
        path.write_bytes(body)
        db.add(
            Attachment(
                agency_id=task_row.agency_id,
                task_id=task_row.id,
                uploaded_by_id=users[uploader].id,
                filename=filename,
                storage_path=str(path.relative_to(UPLOAD_ROOT)),
                content_type=content_type,
                size_bytes=len(body),
                visibility=vis,
            )
        )

    attachment(homepage, "homepage-v1.png", "image/png", C, "arjun", b"placeholder image")
    attachment(homepage, "freelancer-pricing.csv", "text/csv", I, "arjun", b"role,rate\ndesigner,40\n")

    # ---- time entries (minutes)
    db.add_all(
        [
            TimeEntry(agency_id=pixel.id, task_id=homepage.id, user_id=users["arjun"].id,
                      minutes=180, note="First draft", entry_date=today),
            TimeEntry(agency_id=pixel.id, task_id=staging.id, user_id=users["arjun"].id,
                      minutes=90, note="Server setup", entry_date=today - timedelta(days=1)),
            TimeEntry(agency_id=pixel.id, task_id=onboarding.id, user_id=users["rahul"].id,
                      minutes=120, note="Flows", entry_date=today),
        ]
    )

    # ---- one pending invite, so the accept flow can be demoed
    db.add(
        Invite(
            agency_id=pixel.id,
            email="owner@harborfitness.com",
            role=Role.client_user,
            client_id=harbor_px.id,
            token_hash=hashlib.sha256(DEMO_INVITE_TOKEN.encode()).hexdigest(),
            invited_by_id=users["priya"].id,
        )
    )

    db.commit()
    db.close()

    print("Seeded. Every account's password is:", PASSWORD)
    print("  Pixel & Co:       priya@pixel.co (admin), arjun@pixel.co (member),")
    print("                    rahul@devmail.com (member), maya@bloombakery.com (client)")
    print("  Northwind Studio: nora@northwind.studio (admin), maya@bloombakery.com (client),")
    print("                    rahul@devmail.com (client)")
    print("  Pending invite token for owner@harborfitness.com:", DEMO_INVITE_TOKEN)


if __name__ == "__main__":
    run()
