"""Test setup.

- Tests run against a SEPARATE database (TEST_DATABASE_URL). As a safety net, the run
  refuses to start unless that database's name ends in "_test", because every test
  wipes and reseeds it.
- Once per run, the schema is torn down and rebuilt with Alembic, so every run also
  proves the migrations work on an empty database.
- Before EACH test the seed data is reloaded, so tests can't affect one another.
"""

import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ---- must happen before anything imports app.db, which reads DATABASE_URL on import
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://agencydesk:agencydesk@localhost:5433/agencydesk_test",
)
_db_name = TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]
if not _db_name.endswith("_test"):
    raise RuntimeError(
        f"Refusing to run tests against database '{_db_name}': its name must end in "
        "'_test', because the tests wipe it. Set TEST_DATABASE_URL."
    )
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="agencydesk-test-uploads-")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import seed  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Agency, Attachment, Project, Task, User  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
PASSWORD = seed.PASSWORD


@pytest.fixture(scope="session", autouse=True)
def schema():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def seeded(schema, capsys):
    seed.run()
    capsys.readouterr()  # drop the seed's printed summary from test output


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def login(client):
    """login("maya@bloombakery.com", "Pixel & Co") -> Authorization headers for that
    person acting inside that agency, obtained through the real auth endpoints."""

    def _login(email: str, agency_name: str) -> dict:
        r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        body = r.json()
        agency_id = next(m["agency_id"] for m in body["memberships"] if m["agency_name"] == agency_name)
        r = client.post(
            "/auth/select-agency",
            json={"agency_id": agency_id},
            headers={"Authorization": f"Bearer {body['login_token']}"},
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login


class Lookup:
    """Find seeded rows by their human name, straight from the DB (no scoping),
    so tests can aim requests at rows the caller should NOT be able to see."""

    def __init__(self, session):
        self.s = session

    def agency(self, name):
        return self.s.scalar(select(Agency).where(Agency.name == name))

    def project(self, name):
        return self.s.scalar(select(Project).where(Project.name == name))

    def task(self, title):
        return self.s.scalar(select(Task).where(Task.title == title))

    def user(self, email):
        return self.s.scalar(select(User).where(User.email == email))

    def attachment(self, filename):
        return self.s.scalar(select(Attachment).where(Attachment.filename == filename))


@pytest.fixture
def find(db):
    return Lookup(db)


@pytest.fixture
def simultaneously():
    """simultaneously(n, fn) runs fn(client) in n threads released at the same
    instant, each with its own client and DB connection. Used for race conditions."""

    def _run(n, fn):
        barrier = threading.Barrier(n)

        def worker(_):
            # Start each client (and its event loop) BEFORE the barrier, so all n
            # requests really leave at the same moment instead of staggered by startup.
            with TestClient(app) as own_client:
                own_client.get("/health")
                barrier.wait()
                return fn(own_client)

        with ThreadPoolExecutor(n) as pool:
            return list(pool.map(worker, range(n)))

    return _run
