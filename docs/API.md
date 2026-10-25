# AgencyDesk API: endpoints and permissions

This covers every endpoint: auth, clients, projects, tasks, comments, invites, time
entries, attachments and the dashboard.

Interactive version: run the backend and open `http://localhost:8000/docs`.

---

## 1. How access works

### Two tokens

| Token | Comes from | Proves | Can be used for |
|---|---|---|---|
| Login token (10 min) | `POST /auth/login` | who you are | `POST /auth/select-agency` only |
| Access token (8 h) | `POST /auth/select-agency` or `POST /auth/register` | who you are + which agency you chose | every other endpoint |

Send it as `Authorization: Bearer <token>`.

The access token holds only your user id and the agency you chose. **Your role is
never in the token.** On every request the server looks up your membership in that
agency and reads the role from the database. If the membership has been deactivated,
the request is refused at once, even with an unexpired token.

### Three roles (per agency)

| Role | Who | Sees |
|---|---|---|
| `agency_admin` | Agency owner or manager | Everything in their agency |
| `agency_member` | Designer, developer, account manager | Only projects they're assigned to (via `project_members`), all tasks on them, internal included |
| `client_user` | Contact at a client company | Only their own company's projects, and only items marked `visibility = client` |

The same person can hold different roles in different agencies (one membership per
agency). Rahul in the seed data is `agency_member` at Pixel and `client_user` at
Northwind.

### Three walls

Every read goes through `app/scoping.py`, which applies:

1. **Agency wall** (everyone): only rows whose `agency_id` matches the token.
2. **Project wall**: members only see assigned projects; clients only see their company's projects.
3. **Visibility wall** (clients only): only rows with `visibility = client`. Tasks, comments and attachments each have their own flag, so an internal comment on a client-visible task stays hidden.

Filters, search and lookups by id are added **on top of** the scoped query, so they
can only narrow the result, never widen it.

### Status codes

| Code | Meaning here |
|---|---|
| 200 / 201 | OK / created |
| 401 | Not authenticated: no token, bad token, expired token, login token used where an access token is needed, or membership removed |
| 403 | You're authenticated, but your **role** can't do this action (e.g. a client creating a task). Never depends on which row was asked for |
| 404 | The row doesn't exist **for you**. Another agency's row, a project you're not on, and an internal task seen by a client all look identical to a missing id, so the API never confirms that a hidden row exists |
| 409 | Conflict (email already registered, person already in the agency) |
| 413 | Uploaded file larger than 10 MB |
| 422 | Request is the wrong shape, or breaks a business rule (assignee not on the project, a client added as a project member) |

---

## 2. Permission matrix

`scoped` = allowed, but the result only contains what that role may see.

| Endpoint | admin | member | client |
|---|---|---|---|
| `POST /auth/register` | public | public | public |
| `POST /auth/login` | public | public | public |
| `POST /auth/select-agency` | yes | yes | yes |
| `GET /auth/me` | yes | yes | yes |
| `GET /clients` | yes | yes | 403 |
| `GET /projects` | all | assigned | own company's |
| `GET /projects/{id}` | yes | if assigned, else 404 | if own company's, else 404 |
| `POST /projects` | yes | 403 | 403 |
| `GET /projects/{id}/members` | yes | if assigned, else 404 | 403 |
| `POST /projects/{id}/members` | yes | 403 | 403 |
| `DELETE /projects/{id}/members/{user_id}` | yes | 403 | 403 |
| `GET /tasks` | all | on assigned projects | client-visible, own company's |
| `GET /tasks/{id}` | yes | if on assigned project, else 404 | if client-visible + own company's, else 404 |
| `POST /tasks` | yes | on assigned projects | 403 |
| `PATCH /tasks/{id}` | yes | on assigned projects | 403 |
| `GET /tasks/{id}/comments` | all | all (on assigned projects) | client-visible only |
| `POST /tasks/{id}/comments` | yes | yes | yes, always stored as client-visible |
| `GET /invites` | yes | 403 | 403 |
| `POST /invites` (create or resend) | yes | 403 | 403 |
| `POST /invites/accept` | public (the token is the proof) | | |
| `POST /time-entries` | yes | on assigned projects | 403 |
| `POST /tasks/{id}/attachments` | yes | on assigned projects | 403 |
| `GET /tasks/{id}/attachments` | all | all (on assigned projects) | client-visible only |
| `GET /attachments/{id}/download` | yes | if on assigned project, else 404 | if client-visible + own company's, else 404 |
| `POST /attachments/{id}/review` | 403 | 403 | if client-visible + own company's, else 404 |
| `GET /dashboard` | all | assigned projects | client-visible, own company's |

---

## 3. Endpoints

### Auth (`app/routers/auth.py`)

#### `POST /auth/register`
Sign up a **new agency**. Creates the user, the agency and an `agency_admin`
membership in one transaction, and returns an access token for that agency.
Staff and clients joining an existing agency come in through invites, not here.

```json
{ "email": "zoe@newco.io", "password": "password123", "full_name": "Zoe", "agency_name": "NewCo" }
```

- Email is trimmed and lowercased. Password 8 to 72 characters (bcrypt's limit).
- **409** if the email is already registered. Two simultaneous sign-ups with one email: the `UNIQUE` on `users.email` lets one win, the other gets 409.

#### `POST /auth/login`
```json
{ "email": "rahul@devmail.com", "password": "password123" }
```
Returns a `login_token` and every **active** membership (agency, role, client).
Grants no data access by itself.

- **401** `Invalid email or password`, the same message for an unknown email and a wrong password.

#### `POST /auth/select-agency`
Auth: login token **or** access token (so a signed-in user can switch agencies).
```json
{ "agency_id": "..." }
```
Returns an `access_token` for that agency.

- **404** if you have no active membership there (not 403, so it doesn't confirm the agency exists).

#### `GET /auth/me`
Auth: access token. Returns the user and their membership in the current agency.
Useful to check which role you're acting as.

---

### Clients and projects (`app/routers/projects.py`)

#### `GET /clients`
Staff only (**403** for clients). Lists the agency's clients.

#### `GET /projects`
Everyone, scoped. Admin: all projects. Member: projects they're assigned to.
Client: every project of their company (clients are not added to projects one by
one; their membership points at the company).

#### `GET /projects/{project_id}`
Everyone, scoped. **404** if outside your scope.

#### `POST /projects`
Admin only (**403** otherwise).
```json
{ "client_id": "...", "name": "Bloom menu redesign" }
```
- `agency_id` is taken from the token; the body can't set it.
- **404** if the client isn't in your agency.

#### `GET /projects/{project_id}/members`
Staff only. The project must be visible to you (members: only their own projects).

#### `POST /projects/{project_id}/members`
Admin only. Assigns a staff member to the project.
```json
{ "user_id": "..." }
```
- **404** if the user has no active membership in this agency.
- **422** if the user is a `client_user` (clients can't be project members; the schema can't express this, so the API enforces it).
- Adding someone already on the project returns `{"added": false}` rather than an error.

#### `DELETE /projects/{project_id}/members/{user_id}`
Admin only. **Edge case: removing a team member mid-task.**

- Removes the person from the project.
- Their **unfinished** tasks on this project become unassigned (`assignee_id = NULL`), so an admin can hand them on.
- Tasks already `done` keep the assignee as a record of who did the work.
- Nothing is deleted. Both changes run in one transaction.
- Returns `{"removed": true, "tasks_unassigned": 1}`. **404** if they weren't on the project.

---

### Tasks (`app/routers/tasks.py`)

#### `GET /tasks`
Everyone, scoped. Optional query filters, all applied **after** scoping:

| Param | Example |
|---|---|
| `project_id` | `?project_id=...` |
| `status` | `?status=in_progress` (`todo`, `in_progress`, `in_review`, `done`) |
| `visibility` | `?visibility=client` |
| `assignee_id` | `?assignee_id=...` |
| `q` | `?q=homepage` (case-insensitive title search) |

A client filtering `visibility=internal`, or searching for an internal task's title,
gets an empty list.

#### `GET /tasks/{task_id}`
Everyone, scoped. **404** if outside your scope.

#### `POST /tasks`
Staff only (**403** for clients).
```json
{
  "project_id": "...",
  "title": "Design footer",
  "description": "",
  "status": "todo",
  "priority": "medium",
  "assignee_id": null,
  "due_date": "2026-11-01",
  "visibility": "internal"
}
```
- Only `project_id` and `title` are required. `visibility` defaults to `internal` (fails closed).
- The project must be visible to you, else **404** (another agency's project, or one a member isn't on).
- **422** if `assignee_id` isn't a member of that project.

#### `PATCH /tasks/{task_id}`
Staff only (**403** for clients, including on tasks they can see).
Send only the fields to change:
```json
{ "status": "done" }
```
- **404** if the task is outside your scope.
- **422** for `null` on a required field (`title`, `description`, `status`, `priority`, `visibility`), or an assignee not on the project.
- `assignee_id: null` is allowed: it unassigns the task.

---

### Comments (`app/routers/comments.py`)

#### `GET /tasks/{task_id}/comments`
Everyone, scoped. The task must be visible to you (else **404**). Clients see only
`client` comments; staff see all.

#### `POST /tasks/{task_id}/comments`
Everyone, including clients (the brief allows clients to comment).
```json
{ "body": "Can the logo be bigger?", "visibility": "client" }
```
- Staff choose the visibility; it defaults to `internal`.
- For a `client_user` the server **always** stores `client`, whatever was sent. A client can't write a note they'd then be unable to read.
- **404** if the task isn't visible to you.

---

### Invites (`app/routers/invites.py`)

How staff and clients join an **existing** agency. Two graded edge cases live here,
and both are settled by the database rather than by a check-then-write in Python.

#### `GET /invites`
Admin only. Lists the agency's pending invites.

#### `POST /invites` (create or resend)
Admin only.
```json
{ "email": "owner@harborfitness.com", "role": "client_user", "client_id": "..." }
```
- `client_id` is required for `client_user` and forbidden for staff roles (**422**). **404** if the client isn't in your agency.
- **409** if the person already has an active membership in this agency.
- **Resend = call it again for the same email.** It's a single `INSERT ... ON CONFLICT DO UPDATE` against the partial unique index `(agency_id, email) WHERE status = 'pending'`. The existing pending invite gets a fresh token (the old link stops working) and the latest role; a second pending invite is never created, even if several requests arrive at the same instant.
- Response: `{ "invite": {...}, "token": "...", "resent": true|false }`. The raw token is returned because there's no email service; in production it would only be emailed. Only its SHA-256 is stored.

#### `POST /invites/accept`
Public: holding the token is the proof.
```json
{ "token": "...", "full_name": "Alex Kim", "password": "password123" }
```
- `full_name` and `password` are needed only if the email has no account yet (**422** otherwise, and the invite stays pending).
- If the email already has an account, the membership is added to it and its password is **not** changed. A person previously removed from the agency is reactivated with the invite's role.
- **Accepting twice:** the first step is one atomic `UPDATE invites SET status = 'accepted' WHERE token_hash = ... AND status = 'pending' RETURNING *`. Only the request that flips the status continues; a second click (even simultaneous) gets **404** `Invite not found or already used`, and exactly one membership exists.
- Returns an access token for the agency, so accepting also logs you in.

---

### Time entries (`app/routers/time_entries.py`)

#### `POST /time-entries`
Staff only (**403** for clients).
```json
{ "task_id": "...", "minutes": 90, "note": "First draft", "entry_date": "2026-10-25" }
```
- `minutes` 1 to 1440 (**422** otherwise; a DB CHECK backs this up). `entry_date` defaults to today.
- Always logged as the caller; you can't log time for someone else.
- **404** if the task isn't visible to you (members: only their projects).
- Hours appear in the dashboard. There's no list or edit endpoint by design (schema plus one endpoint).

---

### Attachments (`app/routers/attachments.py`)

#### `POST /tasks/{task_id}/attachments`
Staff only. Multipart form: `file`, and optional `visibility` (`internal` or `client`, default `internal`).
- Max 10 MB (**413**). Stored on local disk under `backend/uploads/<agency_id>/`.
- The uploaded filename is reduced to its last component, so `../../etc/passwd` becomes `passwd`.
- A new version of a design is a new upload, starting as `pending`.

#### `GET /tasks/{task_id}/attachments`
Everyone, scoped. Clients see only `client` files, even on a task they can see.

#### `GET /attachments/{attachment_id}/download`
Everyone, scoped. Downloading is a read like any other: an internal file requested by
a client is **404**.

#### `POST /attachments/{attachment_id}/review`
**Client users only** (**403** for staff: they can't approve on the client's behalf).
```json
{ "decision": "approved" }
```
- `decision` is `approved` or `changes_requested`. Records who reviewed and when. Can be changed later; the latest decision wins.
- **404** for an internal file or one outside the client's company.

---

### Dashboard (`app/routers/dashboard.py`)

#### `GET /dashboard`
Everyone, scoped. Optional `?project_id=...` (**404** if that project isn't visible to you).
```json
{
  "project_id": "...",
  "total_tasks": 3,
  "tasks_by_status": { "todo": 2, "in_progress": 1, "in_review": 0, "done": 0 },
  "overdue_tasks": 0,
  "hours_logged": 3.75
}
```
- Every number comes from the **same scoped queries** as the lists. A client's counts match exactly the tasks they can open; otherwise the difference would reveal that hidden tasks exist.
- `overdue_tasks`: due date in the past and not done.
- `hours_logged`: only time logged on tasks the caller can see. For a client, that's hours on client-visible tasks only.

---

## 4. Seed accounts

All passwords: `password123`.

| Email | Pixel & Co | Northwind Studio |
|---|---|---|
| priya@pixel.co | agency_admin | |
| arjun@pixel.co | agency_member (Bloom website) | |
| rahul@devmail.com | agency_member (Harbor app) | client_user (Rahul Mehta) |
| maya@bloombakery.com | client_user (Bloom Bakery) | client_user (Bloom Bakery) |
| nora@northwind.studio | | agency_admin |

Reset everything with `python -m app.seed`.
