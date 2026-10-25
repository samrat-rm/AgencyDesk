"""The visibility wall: what a client_user can see and do."""

from datetime import date, timedelta

from app.models import TaskStatus, TimeEntry


def test_client_cannot_see_internal(client, login, find):
    """client_user gets zero internal items, through every read path, not just the
    main list: filters, search, fetch by id, comments, attachments, downloads."""
    maya = login("maya@bloombakery.com", "Pixel & Co")
    internal_task = find.task("Negotiate freelancer rates")
    homepage = find.task("Design homepage mockup")  # client-visible, has an internal comment + file
    internal_file = find.attachment("freelancer-pricing.csv")

    tasks = client.get("/tasks", headers=maya).json()
    assert sorted(t["title"] for t in tasks) == ["Design homepage mockup", "Launch checklist", "Write About page copy"]
    assert {t["visibility"] for t in tasks} == {"client"}

    # Side doors. Each would leak if the visibility rule lived only in the list endpoint.
    assert client.get("/tasks", headers=maya, params={"visibility": "internal"}).json() == []
    assert client.get("/tasks", headers=maya, params={"q": "freelancer"}).json() == []
    assert client.get("/tasks", headers=maya, params={"status": "done"}).json() == []  # only done task is internal
    assert client.get(f"/tasks/{internal_task.id}", headers=maya).status_code == 404
    assert client.get(f"/tasks/{internal_task.id}/comments", headers=maya).status_code == 404

    # An internal comment / file on a task she CAN see stays hidden: each has its own flag.
    comments = client.get(f"/tasks/{homepage.id}/comments", headers=maya).json()
    assert len(comments) == 2 and {c["visibility"] for c in comments} == {"client"}
    files = client.get(f"/tasks/{homepage.id}/attachments", headers=maya).json()
    assert [f["filename"] for f in files] == ["homepage-v1.png"]
    assert client.get(f"/attachments/{internal_file.id}/download", headers=maya).status_code == 404

    # Her company's other agency work is invisible too: Harbor is another client.
    assert client.get(f"/tasks/{find.task('Onboarding screens').id}", headers=maya).status_code == 404


def test_client_dashboard_counts(client, login, find, db):
    """Dashboard counts match exactly what the client can open. Counting is a read:
    a higher number would reveal that hidden tasks exist."""
    maya = login("maya@bloombakery.com", "Pixel & Co")
    priya = login("priya@pixel.co", "Pixel & Co")
    website = find.project("Bloom website redesign")

    # Make the test meaningful: an internal task that is overdue and has time logged.
    internal = find.task("Negotiate freelancer rates")
    internal.due_date = date.today() - timedelta(days=3)
    db.add(TimeEntry(agency_id=internal.agency_id, task_id=internal.id, user_id=find.user("priya@pixel.co").id,
                     minutes=600, entry_date=date.today()))
    db.commit()

    for params in ({"project_id": str(website.id)}, {}):  # one project, and everything
        dash = client.get("/dashboard", headers=maya, params=params).json()
        openable = client.get("/tasks", headers=maya, params=params).json()

        assert dash["total_tasks"] == len(openable)
        expected = {s.value: 0 for s in TaskStatus}
        for t in openable:
            expected[t["status"]] += 1
        assert dash["tasks_by_status"] == expected
        assert dash["overdue_tasks"] == 0  # the overdue task is internal

    # Hours: only time on tasks she can see (homepage: 180 seeded minutes).
    assert client.get("/dashboard", headers=maya, params={"project_id": str(website.id)}).json()["hours_logged"] == 3.0

    # Control: the agency admin's numbers DO include the internal work.
    admin = client.get("/dashboard", headers=priya, params={"project_id": str(website.id)}).json()
    assert admin["total_tasks"] == 6
    assert admin["overdue_tasks"] == 1
    assert admin["hours_logged"] == 3.0 + 1.5 + 10.0  # homepage + staging + the internal 600 min


def test_client_cannot_mutate(client, login, find, db):
    """client POST /tasks -> 403; PATCH status -> 403, even on a task she can see.
    Commenting, which the brief allows, still works."""
    maya = login("maya@bloombakery.com", "Pixel & Co")
    website = find.project("Bloom website redesign")
    homepage = find.task("Design homepage mockup")

    r = client.post("/tasks", headers=maya, json={"project_id": str(website.id), "title": "x"})
    assert r.status_code == 403

    r = client.patch(f"/tasks/{homepage.id}", headers=maya, json={"status": "done"})
    assert r.status_code == 403
    db.refresh(homepage)
    assert homepage.status is TaskStatus.in_progress  # unchanged

    assert client.post("/time-entries", headers=maya, json={"task_id": str(homepage.id), "minutes": 30}).status_code == 403
    r = client.post(f"/tasks/{homepage.id}/attachments", headers=maya, files={"file": ("a.txt", b"a")})
    assert r.status_code == 403
    assert client.post("/projects", headers=maya, json={"client_id": str(website.client_id), "name": "x"}).status_code == 403

    # Allowed: commenting. Whatever visibility she asks for, it's stored as client.
    r = client.post(f"/tasks/{homepage.id}/comments", headers=maya, json={"body": "Looks great", "visibility": "internal"})
    assert r.status_code == 201
    assert r.json()["visibility"] == "client"
