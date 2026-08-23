import sys
from pathlib import Path

import pytest

# Make the project root importable so `import app` and
# `from database.db import ...` resolve under pytest.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database.db as db_module  # noqa: E402
from app import app as flask_app  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_db():
    """Each test gets a fresh, empty set of tables.

    Postgres has no per-test throwaway file like SQLite did, so instead
    we truncate the tables (and reset identity sequences) before each
    test against whatever DATABASE_URL points at.
    """
    db_module.init_db()
    with db_module.get_db() as conn:
        conn.execute("TRUNCATE TABLE expenses, users RESTART IDENTITY CASCADE")
    yield


@pytest.fixture(autouse=True)
def _app_config():
    """Force a stable SECRET_KEY so signed session cookies round-trip."""
    flask_app.config.update(
        SECRET_KEY="test-secret-key",
        TESTING=True,
    )
    yield


@pytest.fixture
def client():
    """A Flask test client."""
    return flask_app.test_client()
