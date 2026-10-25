# AgencyDesk: Build Brief

## 0. Instructions for Claude working on this repo

You are helping Samrat build a take-home submission under a hard time limit. He will be
interviewed about this code and must defend every design decision himself.

**Rules:**

1. **Explain as you go.** After writing any schema, constraint or access-control code,
   state in one line *why* it is that way. Not a paragraph. One line.
2. **Flag what he must understand.** If a piece of code would be hard to defend on a
   call without understanding it, say so explicitly before moving on.
3. **Do not expand scope.** If it is not in section 2 below, do not build it. Suggest it
   as a line in "Known gaps" instead.
4. **Do not refactor for elegance.** Working and readable beats clever. There is no time.
5. **Tests before frontend.** Section 7 is graded. The UI is barely graded.
6. **Ask before adding a dependency.** The stack in section 3 is fixed.
7. **Never invent progress.** If something is stubbed or untested, say so plainly so it
   lands in the README's Scope section rather than being discovered by a reviewer.

## 1. What is graded

| Area | What they want |
|---|---|
| Schema design | Normalisation, constraints, isolation enforced by the schema itself |
| Multi-tenancy & RBAC | No cross-tenant leaks, roles correctly scoped |
| Edge cases | Five specific cases handled explicitly, with tests |
| Code quality | Clear layering, readable, consistent |
| Understanding | DESIGN.md and interview answers show real understanding |

Feature completeness is not on that list. Build accordingly.

## 2. Hard scope

**Build fully:** schema with composite FKs and migrations; auth (register, login,
select-agency, JWT carrying agency context); the scoping helper with projects / tasks /
comments on top; all five edge cases; the ten tests in section 7; seed data; DESIGN.md,
README, video.

**Schema plus one endpoint only, no UI:** `POST /time-entries` with hours summed into the
dashboard; `POST /tasks/{id}/attachments` to local disk plus an approve endpoint; one
dashboard endpoint returning counts and hours.

**Skip:** styling, bonus features, pagination, search, rate limiting, soft deletes,
Postgres RLS.

**Frontend, four unstyled screens:** login and agency picker; project list; task list
showing the visibility flag; client portal view of the same project.

## 3. Stack (fixed)

```
backend:   FastAPI, SQLAlchemy 2.0, Alembic, psycopg 3, python-jose, passlib[bcrypt], pytest, httpx
frontend:  React + Vite, React Router, fetch. No Redux, no Next.js, no Tailwind.
infra:     docker-compose for Postgres only (host port 5433)
```

## 4. Schema (source of truth: backend/app/models.py + alembic/versions/0001)

- Every tenant-owned table carries `agency_id` and `UNIQUE (id, agency_id)`. Children
  reference parents compositely: `FOREIGN KEY (project_id, agency_id) REFERENCES
  projects(id, agency_id)`. Cross-tenant references are physically impossible.
- People references (assignee, author, uploader, time-entry user) point at
  `memberships(user_id, agency_id)`, so a person must belong to the same agency.
- `users` holds identity only. `memberships` holds role per agency, one row per
  (user, agency), with a CHECK tying `client_user` to a non-null `client_id`.
- `visibility` defaults to `'internal'` on tasks, comments and attachments.
- `invites` has a partial unique index: one pending invite per (agency, email).

## 5. Access control

One helper in `app/scoping.py`. Every read goes through it, the dashboard included.
`agency_id` comes from the JWT, never the request body. Another tenant's row returns
404, not 403.

## 6. Build order

| Box | Output | Status |
|---|---|---|
| 1 | Scaffold, docker-compose, models, migration | done |
| 2 | Seed script | done |
| 3 | Auth: register, login, select-agency JWT | done |
| 4 | `scoping.py`, projects / tasks / comments routers | done |
| 5 | Time entries, attachments, dashboard, invites | done |
| 6 | The ten tests | done |
| 7 | Four React screens | |
| 8 | DESIGN.md, README, video | |

If behind, cut from box 7 first, then box 5. Never from 6 or 8.

## 7. The ten tests

```
test_tenant_isolation_read        Agency A user GETs Agency B's task id        -> 404
test_tenant_isolation_write       Agency A creates a task on B's project       -> rejected
test_client_cannot_see_internal   client_user lists tasks   -> zero internal tasks
test_client_dashboard_counts      counts match exactly what the client can open
test_client_cannot_mutate         client POST /tasks -> 403; PATCH status -> 403
test_member_scoped_to_projects    agency_member sees only assigned projects
test_two_agencies_one_email       same user, two tokens, two different role sets
test_invite_resend_idempotent     resending leaves exactly one pending invite
test_invite_accept_twice          second accept fails, exactly one membership exists
test_member_removal               removed member's tasks have assignee NULL, task survives
```
