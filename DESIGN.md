# AgencyDesk design

## How the schema enforces tenant isolation

All agencies share one set of tables, and every tenant-owned row carries `agency_id`.
Each of those tables also has `UNIQUE (id, agency_id)`, and every reference between them
is a **composite foreign key**: a task stores `(project_id, agency_id)` and that pair
must match `projects(id, agency_id)`. A child and its parent therefore always belong to
the same agency, so a cross-agency link (a Pixel task on a Northwind project, a Northwind
admin assigned to a Pixel task) is rejected by Postgres itself, even if application code
is wrong. People are referenced through `memberships(user_id, agency_id)` for the same
reason.

The schema protects writes; reads are protected by one module, `app/scoping.py`. Every
query starts with `agency_id` = the agency in the access token (never a value from the
request body), and routers can only add filters on top, which can narrow a result but
never widen it. Rows outside your scope return **404, not 403**, so the API never
confirms that another agency's id exists.

## How a client is blocked from internal content

`visibility` is a column on tasks, comments and attachments, and it **defaults to
`internal`**, so anything created without a decision is hidden. For a `client_user`,
scoping adds three conditions: same agency, a project of *their* client, and
`visibility = 'client'`. Comments and attachments are scoped through their task **and**
checked against their own flag, so an internal note on a client-visible task stays
hidden. Because list, detail, filters, search, comments, downloads and the dashboard all
start from the same scoped query, there is no side path that skips the rule; the
dashboard's counts equal exactly what the client can open.

## How one person works across two agencies

`users` holds identity only (email, password). `memberships` holds one row per
(person, agency) with that agency's role, and a CHECK constraint requires a `client_id`
for `client_user` and forbids it for staff. Rahul is one user with two memberships:
member at Pixel, client at Northwind. Login returns his memberships and a short-lived
login token that can't read data; choosing an agency returns an access token for that
agency only. The role is read from `memberships` on every request rather than stored in
the token, so removing someone takes effect on their next request.

## An edge case I'm proud of: invite races

Resending an invite is a single `INSERT ... ON CONFLICT DO UPDATE` against a **partial
unique index** on `(agency_id, email) WHERE status = 'pending'`. There can only ever be
one pending invite per email per agency; a resend updates that row with a fresh token
(the old link stops working), while accepted invites remain as history. Accepting is a
single `UPDATE invites SET status = 'accepted' WHERE token_hash = ... AND status =
'pending' RETURNING *`: Postgres serialises concurrent attempts on the row, so only one
request flips the status and goes on to create the membership. Neither relies on a
"check, then write" in Python, which two simultaneous requests can both pass. The tests
fire bursts of truly simultaneous requests at both and confirm one pending invite and
one account.
