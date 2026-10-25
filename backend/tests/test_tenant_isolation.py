"""The agency wall and the project wall."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import Task


def test_tenant_isolation_read(client, login, find):
    """Agency A user GETs Agency B's task id -> 404, indistinguishable from an id
    that doesn't exist, on every read path."""
    nora = login("nora@northwind.studio", "Northwind Studio")  # admin, but of Northwind
    pixel_task = find.task("Design homepage mockup")
    pixel_project = find.project("Bloom website redesign")
    pixel_file = find.attachment("homepage-v1.png")

    r = client.get(f"/tasks/{pixel_task.id}", headers=nora)
    assert r.status_code == 404

    # The response for a REAL foreign id must equal the one for a random id, so the
    # API never confirms that another agency's task exists.
    missing = client.get(f"/tasks/{uuid.uuid4()}", headers=nora)
    assert (r.status_code, r.json()) == (missing.status_code, missing.json())

    assert client.get(f"/projects/{pixel_project.id}", headers=nora).status_code == 404
    assert client.get(f"/tasks/{pixel_task.id}/comments", headers=nora).status_code == 404
    assert client.get(f"/tasks/{pixel_task.id}/attachments", headers=nora).status_code == 404
    assert client.get(f"/attachments/{pixel_file.id}/download", headers=nora).status_code == 404
    assert client.get("/dashboard", headers=nora, params={"project_id": pixel_project.id}).status_code == 404

    # Lists and filters can't reach across either: they only narrow the scoped query.
    assert client.get("/tasks", headers=nora, params={"project_id": pixel_project.id}).json() == []
    northwind = find.agency("Northwind Studio")
    northwind_task_ids = {str(i) for i in find.s.scalars(select(Task.id).where(Task.agency_id == northwind.id))}
    seen = {t["id"] for t in client.get("/tasks", headers=nora).json()}
    assert seen == northwind_task_ids  # all of her own agency, nothing of Pixel's


def test_tenant_isolation_write(client, login, find, db):
    """Agency A creates a task on Agency B's project -> rejected by the API (404), and
    rejected AGAIN by the database itself if the code were ever bypassed."""
    nora = login("nora@northwind.studio", "Northwind Studio")
    pixel_project = find.project("Bloom website redesign")
    pixel_task = find.task("Design homepage mockup")
    before = db.scalar(select(func.count()).select_from(Task))

    r = client.post("/tasks", headers=nora, json={"project_id": str(pixel_project.id), "title": "Planted"})
    assert r.status_code == 404
    assert client.patch(f"/tasks/{pixel_task.id}", headers=nora, json={"status": "done"}).status_code == 404
    assert client.post(f"/tasks/{pixel_task.id}/comments", headers=nora, json={"body": "hi"}).status_code == 404
    assert db.scalar(select(func.count()).select_from(Task)) == before

    # Layer 2: skip the API and insert directly. The composite foreign key
    # (project_id, agency_id) -> projects(id, agency_id) refuses the row.
    northwind = find.agency("Northwind Studio")
    nora_user = find.user("nora@northwind.studio")
    db.add(Task(agency_id=northwind.id, project_id=pixel_project.id, title="Planted", created_by_id=nora_user.id))
    with pytest.raises(IntegrityError) as err:
        db.flush()
    assert err.value.orig.diag.constraint_name == "tasks_project_fk"
    db.rollback()


def test_member_scoped_to_projects(client, login, find):
    """agency_member sees only projects they're assigned to (and ALL tasks on them,
    internal included), and gains access only when assigned."""
    arjun = login("arjun@pixel.co", "Pixel & Co")
    priya = login("priya@pixel.co", "Pixel & Co")
    website, harbor = find.project("Bloom website redesign"), find.project("Harbor app launch")
    harbor_task = find.task("Onboarding screens")

    assert [p["name"] for p in client.get("/projects", headers=arjun).json()] == ["Bloom website redesign"]

    tasks = client.get("/tasks", headers=arjun).json()
    assert {t["project_id"] for t in tasks} == {str(website.id)}
    assert {t["visibility"] for t in tasks} == {"client", "internal"}  # staff see internal work

    assert client.get(f"/projects/{harbor.id}", headers=arjun).status_code == 404
    assert client.get(f"/tasks/{harbor_task.id}", headers=arjun).status_code == 404
    r = client.post("/tasks", headers=arjun, json={"project_id": str(harbor.id), "title": "x"})
    assert r.status_code == 404
    assert client.get("/clients", headers=arjun).status_code == 200  # staff, so allowed
    assert client.post("/projects", headers=arjun, json={"client_id": str(harbor.client_id), "name": "x"}).status_code == 403

    # Access follows the assignment, not anything stored on Arjun himself.
    r = client.post(f"/projects/{harbor.id}/members", headers=priya, json={"user_id": str(find.user("arjun@pixel.co").id)})
    assert r.status_code == 201
    assert client.get(f"/tasks/{harbor_task.id}", headers=arjun).status_code == 200
