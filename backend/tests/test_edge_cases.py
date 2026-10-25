"""The edge cases called out in the brief (cross-tenant access and internal leakage are
covered in the other two files)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import Invite, InviteStatus, Membership, Task, TaskStatus, User


def test_two_agencies_one_email(client, login, find):
    """Same user, two tokens, two different role sets. One login, one password."""
    r = client.post("/auth/login", json={"email": "rahul@devmail.com", "password": "password123"})
    roles = {m["agency_name"]: m["role"] for m in r.json()["memberships"]}
    assert roles == {"Pixel & Co": "agency_member", "Northwind Studio": "client_user"}

    as_staff = login("rahul@devmail.com", "Pixel & Co")
    as_client = login("rahul@devmail.com", "Northwind Studio")
    assert client.get("/auth/me", headers=as_staff).json()["membership"]["role"] == "agency_member"
    assert client.get("/auth/me", headers=as_client).json()["membership"]["role"] == "client_user"

    # At Pixel he's staff on Harbor: sees internal work, can create tasks.
    pixel_tasks = client.get("/tasks", headers=as_staff).json()
    assert "internal" in {t["visibility"] for t in pixel_tasks}
    harbor = find.project("Harbor app launch")
    assert client.post("/tasks", headers=as_staff, json={"project_id": str(harbor.id), "title": "x"}).status_code == 201

    # At Northwind he's a client of his own portfolio project: client-visible only, read-only.
    nw_tasks = client.get("/tasks", headers=as_client).json()
    assert [t["title"] for t in nw_tasks] == ["Portfolio wireframes"]
    folio = find.project("Rahul portfolio site")
    assert client.post("/tasks", headers=as_client, json={"project_id": str(folio.id), "title": "x"}).status_code == 403

    # Each token is locked to its own agency: no task id leaks between the two.
    assert {t["id"] for t in pixel_tasks}.isdisjoint({t["id"] for t in nw_tasks})
    assert client.get(f"/tasks/{nw_tasks[0]['id']}", headers=as_staff).status_code == 404
    assert client.get(f"/tasks/{pixel_tasks[0]['id']}", headers=as_client).status_code == 404


def _pending(db, email):
    db.expire_all()
    return db.scalar(
        select(func.count()).select_from(Invite).where(Invite.email == email, Invite.status == InviteStatus.pending)
    )


def test_invite_resend_idempotent(client, login, db, simultaneously):
    """Resending leaves exactly one pending invite, including when the resends arrive
    at the same instant. Guaranteed by the partial unique index, not by Python."""
    priya = login("priya@pixel.co", "Pixel & Co")

    first = client.post("/invites", headers=priya, json={"email": "Sam@Studio.io", "role": "agency_member"}).json()
    again = client.post("/invites", headers=priya, json={"email": "sam@studio.io", "role": "agency_member"}).json()
    assert (first["resent"], again["resent"]) == (False, True)
    assert first["invite"]["id"] == again["invite"]["id"]
    assert _pending(db, "sam@studio.io") == 1

    # The resend rotated the token: the old link is dead, the new one works.
    assert client.post("/invites/accept", json={"token": first["token"], "full_name": "S", "password": "password123"}).status_code == 404
    assert client.post("/invites/accept", json={"token": again["token"], "full_name": "S", "password": "password123"}).status_code == 200

    # Bursts of clicks at the same instant. A race only shows up when requests
    # overlap, so it's repeated to give a check-then-insert bug many chances to fail.
    for round_ in range(6):
        email = f"race{round_}@studio.io"
        codes = simultaneously(10, lambda c: c.post("/invites", headers=priya, json={"email": email, "role": "agency_member"}).status_code)
        assert set(codes) == {201}
        assert _pending(db, email) == 1

    # Timing-independent proof of what makes the above safe: the database itself
    # refuses a second pending invite for the same (agency, email).
    existing = db.scalar(select(Invite).where(Invite.email == "race0@studio.io"))
    db.add(Invite(agency_id=existing.agency_id, email=existing.email, role=existing.role,
                  token_hash="0" * 64, invited_by_id=existing.invited_by_id))
    with pytest.raises(IntegrityError) as err:
        db.flush()
    assert err.value.orig.diag.constraint_name == "invites_one_pending_per_email"
    db.rollback()


def test_invite_accept_twice(client, login, db, simultaneously):
    """Second accept fails, and exactly one account and one membership exist,
    including when the clicks arrive at the same instant."""
    priya = login("priya@pixel.co", "Pixel & Co")

    def invite(email):
        r = client.post("/invites", headers=priya, json={"email": email, "role": "agency_member"})
        assert r.status_code == 201
        return r.json()["token"]

    def counts(email):
        db.expire_all()
        user_id = db.scalar(select(User.id).where(User.email == email))
        users = db.scalar(select(func.count()).select_from(User).where(User.email == email))
        memberships = db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == user_id))
        return users, memberships

    # One after the other.
    token = invite("alex@studio.io")
    body = {"token": token, "full_name": "Alex", "password": "password123"}
    assert client.post("/invites/accept", json=body).status_code == 200
    second = client.post("/invites/accept", json=body)
    assert second.status_code == 404
    assert counts("alex@studio.io") == (1, 1)

    # Six clicks at the same instant: the atomic UPDATE ... WHERE status='pending' lets one through.
    token = invite("double@studio.io")
    codes = simultaneously(6, lambda c: c.post("/invites/accept", json={"token": token, "full_name": "D", "password": "password123"}).status_code)
    assert sorted(codes) == [200, 404, 404, 404, 404, 404]
    assert counts("double@studio.io") == (1, 1)


def test_member_removal(client, login, find, db):
    """Removed member's unfinished tasks get assignee NULL and survive; done tasks
    keep the assignee as a record; the member loses access immediately."""
    priya = login("priya@pixel.co", "Pixel & Co")
    arjun = login("arjun@pixel.co", "Pixel & Co")
    website = find.project("Bloom website redesign")
    arjun_id = find.user("arjun@pixel.co").id
    in_progress = find.task("Design homepage mockup")  # assigned to Arjun, in progress
    finished = find.task("Set up staging server")  # assigned to Arjun, done
    tasks_before = db.scalar(select(func.count()).select_from(Task))

    r = client.delete(f"/projects/{website.id}/members/{arjun_id}", headers=priya)
    assert r.status_code == 200
    assert r.json() == {"removed": True, "tasks_unassigned": 1}

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Task)) == tasks_before  # nothing deleted
    assert db.get(Task, in_progress.id).assignee_id is None
    assert db.get(Task, finished.id).assignee_id == arjun_id
    assert db.get(Task, finished.id).status is TaskStatus.done

    # It shows up as unassigned work for the admin...
    unassigned = client.get("/tasks", headers=priya, params={"project_id": str(website.id)}).json()
    assert "Design homepage mockup" in [t["title"] for t in unassigned if t["assignee_id"] is None]
    # ...and Arjun, still holding a valid token, can no longer see the project.
    assert client.get("/projects", headers=arjun).json() == []
    assert client.get(f"/tasks/{in_progress.id}", headers=arjun).status_code == 404
