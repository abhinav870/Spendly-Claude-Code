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
def _isolate_db(tmp_path, monkeypatch):
    """Each test gets a fresh, empty spendly.db in a tmp directory."""
    test_db = tmp_path / "spendly_test.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db()
    yield
    # tmp_path is cleaned automatically by pytest.


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
