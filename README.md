# AgencyDesk

Multi-tenant client and project management platform for agencies. Agencies run projects,
tasks, time tracking and file approvals, and invite clients into a portal that shows only
their own client-visible work. Tenant isolation is enforced by the schema via composite
foreign keys. FastAPI, React, PostgreSQL.

- **[DESIGN.md](DESIGN.md)**: how isolation, client visibility and the identity model work
- **[docs/API.md](docs/API.md)**: every endpoint and who may call it
- **Tests**: `backend/tests/`, ten tests proving tenant isolation and client visibility

---

## Run it (about 5 minutes)

**You need:** Docker, Python 3.10+, Node 18+.

**1. Database** (Postgres 16 in Docker, on port 5433 so it won't clash with a local Postgres)

```bash
docker compose up -d
```

**2. Backend** (new terminal)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head               # create the tables
python -m app.seed                 # load demo data (safe to re-run; it resets everything)
uvicorn app.main:app --reload      # http://localhost:8000, API docs at /docs
```

**3. Frontend** (another terminal)

```bash
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

No environment variables are needed for this path: the defaults point at the Docker
database. Optional settings are listed in `backend/.env.example` and `frontend/.env.example`.

### Without Docker

Use any local Postgres 13+ and create the user and both databases:

```bash
psql postgres -c "CREATE USER agencydesk WITH PASSWORD 'agencydesk' CREATEDB;" \
              -c "CREATE DATABASE agencydesk OWNER agencydesk;" \
              -c "CREATE DATABASE agencydesk_test OWNER agencydesk;"
export DATABASE_URL=postgresql+psycopg://agencydesk:agencydesk@localhost:5432/agencydesk
export TEST_DATABASE_URL=postgresql+psycopg://agencydesk:agencydesk@localhost:5432/agencydesk_test
```

Then run step 2 in that same terminal (the exports only last for that terminal). Step 3
needs no changes.

---

## Run the tests

```bash
cd backend
source .venv/bin/activate
pytest -v
```

The tests use the separate `agencydesk_test` database (created automatically by Docker),
rebuild its schema from the migrations on every run, and reload the seed data before each
test. As a safety net they refuse to run against any database whose name doesn't end in
`_test`.

| File | Tests |
|---|---|
| `test_tenant_isolation.py` | reading and writing another agency's data (API and database level), members limited to assigned projects |
| `test_client_visibility.py` | no internal content through lists, filters, search, ids, comments, files or the dashboard; clients can't create or edit |
| `test_edge_cases.py` | one person in two agencies, invite resend and double-accept (including simultaneous requests), removing a member mid-task |

---

## Demo accounts

Every password is `password123`.

| Email | Pixel & Co | Northwind Studio |
|---|---|---|
| priya@pixel.co | agency_admin | |
| arjun@pixel.co | agency_member (Bloom website project) | |
| rahul@devmail.com | agency_member (Harbor app project) | client_user (his own portfolio site) |
| maya@bloombakery.com | client_user (Bloom Bakery) | client_user (Bloom Bakery) |
| nora@northwind.studio | | agency_admin |

**Things to try**

1. Log in as **Priya**, open *Bloom website redesign*: six tasks, three marked `[INTERNAL]`, plus an internal comment and an internal file on the homepage task.
2. In another browser tab, log in as **Maya** at Pixel and open the same project: three tasks, no internal comment, no internal file, and a dashboard that counts only what she can see. She can comment and approve files, but can't create or edit tasks.
3. Log in as **Rahul**: one login, two agencies. Staff at Pixel, client at Northwind; use *Switch agency* to move between them.
4. Log in as **Arjun**: he only sees the one project he's assigned to.

Each browser tab keeps its own session, so two people can be signed in side by side.

---

## Project layout

```
docker-compose.yml        Postgres 16 (dev + test databases)
backend/
  app/
    models.py             the schema: tables, composite FKs, CHECKs, partial unique index
    scoping.py            the single access-control module every read goes through
    auth.py               passwords, tokens, per-request context, role guards
    routers/              auth, projects, tasks, comments, invites, time, files, dashboard
    seed.py               demo data
  alembic/versions/       migrations
  tests/                  the ten tests
frontend/src/
  pages/                  Login, Projects, Tasks (agency view), ClientPortal
docs/API.md               endpoint and permission reference
```

---

## Scope and tradeoffs

The brief says this is about data modeling and access control, not screen count. Given
a one-day window, time went to the schema, the access rules and the tests first.

### Built fully

- Schema with composite foreign keys, CHECK constraints, fail-closed visibility defaults and a partial unique index, created by Alembic migrations
- Auth: register (new agency), login, choose agency, per-request role lookup
- One scoping module used by every read, including the dashboard
- Projects, tasks (with filters and title search), comments
- Invites with race-safe resend and accept
- All five edge cases, each covered by a test
- Seed data: 2 agencies, a shared email with different roles in each, mixed visibility

### Built as API with minimal or no UI

- **Time tracking:** `POST /time-entries`, hours summed into the dashboard. No time-entry screen.
- **Files:** upload via the API, listed with download on both views; clients can approve or request changes in the portal. No upload screen.
- **Dashboard:** one plain-text line per project.
- **Frontend:** four unstyled screens, enough to show the access rules working.

### Decisions worth knowing

- **Shared tables + `agency_id`, not a schema or database per agency.** People belong to several agencies, isolation is enforced by foreign keys inside Postgres, and there's one migration path. A separate schema per agency would push isolation into a per-request `search_path` setting and multiply migrations.
- **404, not 403,** for anything outside your scope, so ids can't be probed.
- **Role is never in the token.** It's read from the membership on every request; deactivating a membership locks the person out immediately.
- **Removing a member from a project** unassigns their unfinished tasks there (they show as unassigned for an admin to hand on); done tasks keep the assignee as a record. Nothing is deleted.
- **Clients' comments are always client-visible,** whatever they send.
- **Only clients approve files;** staff can't approve on a client's behalf.
- **Clients see hours** logged on their client-visible tasks only (suits agencies that bill hourly; hiding hours entirely is a one-line change).

### Known gaps

- Invite tokens are returned by the API because there's no email service; in production they'd only be emailed. No invite expiry or revoke.
- Accepting an invite for an email that already has an account adds the membership without that account's password (holding the token is the proof, as with most invite links).
- Login timing differs for known and unknown emails (bcrypt only runs for real accounts). No rate limiting, refresh tokens or logout endpoint (deactivating a membership revokes access).
- Deactivating someone from a whole agency doesn't unassign their tasks; only project removal does.
- No pagination, soft deletes, editing or deleting comments, time entries or files. A failed DB write after an upload leaves the file on disk.

### What I'd add next

1. **Postgres row-level security** as defence in depth, so even a query that bypassed `scoping.py` couldn't cross agencies.
2. Invite emails, expiry and revocation.
3. Pagination and an audit log of who changed what.
4. Object storage (S3 or similar) instead of local disk for files.

### Timeline / Gantt (discussion only, per the brief)

Tasks already have due dates. A timeline needs a `start_date` on tasks and a
`task_dependencies (task_id, depends_on_id, agency_id)` table with the same composite
foreign keys, so a dependency can't cross agencies or point at a task the viewer can't
see. The view would read through `scoped_tasks`, so a client's timeline would show only
client-visible tasks.

---

MIT License. See [LICENSE](LICENSE).
