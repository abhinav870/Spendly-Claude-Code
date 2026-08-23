"""Tests for Step 9: Delete Expense (`POST /expenses/<id>/delete`).

Written entirely from `.claude/specs/09-delete-expense.md`. No assertions are
derived from reading app.py's or database/queries.py's implementation logic —
only route names, function names/signatures, and the existing test fixture
conventions (`tests/conftest.py`, `test_add_expense.py`, `test_edit_expense.py`)
were confirmed structurally.

Spec highlights under test:
- `POST /expenses/<int:id>/delete` is logged-in only (redirect to /login when
  anonymous).
- Ownership is enforced: deleting another user's expense (or a nonexistent
  id) returns 404, not a redirect or leaked data, and leaves the DB unchanged.
- The route only accepts POST -- a bare GET must return 405 and must not
  delete anything.
- On success: the row is removed from the database (not merely hidden), and
  the response redirects to /profile (302) without rendering a template.
- `database/queries.py` gains a new `delete_expense(expense_id, user_id)`
  mutation helper, scoped by `id = ? AND user_id = ?` as an ownership guard:
    * correct owner -> row removed
    * wrong user_id -> 0 rows deleted, no error, row remains in DB
    * nonexistent expense_id -> no error, DB unchanged
"""

import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database.db as db_module  # noqa: E402
from database import queries  # noqa: E402
from database.db import create_user, get_user_by_email  # noqa: E402

# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #


def _seed_user(client, name="Alice", email="alice@example.com", password="supersecret"):
    """Insert a user row via /register and return the DB row."""
    resp = client.post(
        "/register",
        data={"name": name, "email": email, "password": password},
    )
    assert resp.status_code == 302, f"seed failed: {resp.status_code}"
    with client.session_transaction() as sess:
        sess.clear()
    return get_user_by_email(email)


def _login(client, email, password):
    return client.post("/login", data={"email": email, "password": password})


def _register_and_login(
    client, name="Alice", email="alice@example.com", password="supersecret"
):
    user = _seed_user(client, name=name, email=email, password=password)
    _login(client, email, password)
    return user


def _seed_user_direct(name="Alice", email="alice@example.com"):
    """Insert a user row directly via create_user, for unit tests with no client."""
    create_user(name, email, "supersecret")
    return get_user_by_email(email)


def _fetch_expenses_for_user(user_id):
    with db_module.get_db() as db:
        return db.execute(
            "SELECT * FROM expenses WHERE user_id = %s",
            (user_id,),
        ).fetchall()


def _create_expense_for(user_id, **overrides):
    """Insert one expense for user_id via queries.create_expense and return its id."""
    payload = {
        "amount": 100.0,
        "category": "Food",
        "expense_date": date.today().isoformat(),
        "description": "Seed expense",
    }
    payload.update(overrides)
    return queries.create_expense(
        user_id,
        payload["amount"],
        payload["category"],
        payload["expense_date"],
        payload["description"],
    )


# ------------------------------------------------------------------ #
# Unit tests: queries.delete_expense                                  #
# ------------------------------------------------------------------ #


def test_delete_expense_removes_row_for_correct_owner():
    """Spec table row 1: valid expense_id + correct user_id removes the row."""
    user = _seed_user_direct()
    expense_id = _create_expense_for(user["id"])

    queries.delete_expense(expense_id, user["id"])

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 0, "Row should be removed from the DB for the correct owner"


def test_delete_expense_wrong_user_leaves_row_in_db():
    """Spec table row 2: valid expense_id + wrong user_id deletes 0 rows, no error."""
    user_a = _seed_user_direct(name="Alice", email="alice@example.com")
    user_b = _seed_user_direct(name="Bob", email="bob@example.com")
    expense_id = _create_expense_for(user_a["id"])

    # Must not raise.
    queries.delete_expense(expense_id, user_b["id"])

    rows = _fetch_expenses_for_user(user_a["id"])
    assert len(rows) == 1, "Row must remain in the DB when user_id does not match owner"
    assert rows[0]["id"] == expense_id


def test_delete_expense_nonexistent_id_does_not_error_or_change_db():
    """Spec table row 3: non-existent expense_id raises no error, DB unchanged."""
    user = _seed_user_direct()
    _create_expense_for(user["id"])
    before = _fetch_expenses_for_user(user["id"])

    # Must not raise.
    queries.delete_expense(999999, user["id"])

    after = _fetch_expenses_for_user(user["id"])
    assert len(after) == len(before) == 1, "DB must be unchanged for a nonexistent id"


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #


def test_post_delete_expense_redirects_when_logged_out(client):
    """Anonymous POST /expenses/<id>/delete is redirected to /login and deletes nothing."""
    resp = client.post("/expenses/1/delete", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    with db_module.get_db() as db:
        count = db.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]
    assert (
        count == 0
    ), "No expense should exist or be affected for an unauthenticated request"


def test_post_delete_expense_logged_out_does_not_delete_existing_row(client):
    """An anonymous delete attempt must not remove an existing owner's row."""
    user = _seed_user_direct()
    expense_id = _create_expense_for(user["id"])

    resp = client.post(f"/expenses/{expense_id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1, "Unauthenticated request must not delete an existing expense"


# ------------------------------------------------------------------ #
# Ownership / 404                                                     #
# ------------------------------------------------------------------ #


def test_post_delete_expense_nonexistent_id_404s(client):
    """Logged-in POST for an id that doesn't exist returns 404."""
    _register_and_login(client)

    resp = client.post("/expenses/999999/delete")
    assert resp.status_code == 404


def test_post_delete_expense_other_users_expense_404s_and_does_not_delete(client):
    """User B deleting user A's expense id gets 404, and A's row is unchanged."""
    user_a = _register_and_login(client, name="Alice", email="alice@example.com")
    expense_id = _create_expense_for(user_a["id"], description="Alice's expense")

    client.get("/logout")
    _register_and_login(
        client, name="Bob", email="bob@example.com", password="supersecret"
    )

    resp = client.post(f"/expenses/{expense_id}/delete")
    assert resp.status_code == 404

    rows = _fetch_expenses_for_user(user_a["id"])
    assert len(rows) == 1, "Another user's row must survive a 404'd delete attempt"
    assert rows[0]["id"] == expense_id
    assert rows[0]["description"] == "Alice's expense"


# ------------------------------------------------------------------ #
# POST /expenses/<id>/delete — happy path                             #
# ------------------------------------------------------------------ #


def test_post_delete_expense_valid_request_removes_row_and_redirects(client):
    """A valid delete of an owned expense removes the row and redirects to /profile."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"])

    resp = client.post(f"/expenses/{expense_id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 0, "Expense row should no longer exist in the database"


def test_post_delete_expense_only_removes_targeted_row(client):
    """Deleting one expense must not affect the user's other expenses."""
    user = _register_and_login(client)
    keep_id = _create_expense_for(user["id"], description="Keep me")
    delete_id = _create_expense_for(user["id"], description="Delete me")

    resp = client.post(f"/expenses/{delete_id}/delete", follow_redirects=False)
    assert resp.status_code == 302

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == keep_id
    assert rows[0]["description"] == "Keep me"


def test_post_delete_expense_deleted_expense_no_longer_on_profile(client):
    """DoD: after deletion the expense no longer appears in the profile transaction list."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(
        user["id"], description="Distinctive delete marker"
    )

    resp = client.post(f"/expenses/{expense_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Distinctive delete marker" not in body


def test_post_delete_expense_does_not_render_a_template_directly(client):
    """Spec: on success, redirect to /profile -- do not render a template inline."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"])

    resp = client.post(f"/expenses/{expense_id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    # A redirect response body is not the rendered profile page content.
    assert resp.headers.get("Location") is not None


def test_post_delete_expense_only_affects_current_user(client):
    """Deleting one's own expense must not remove or affect another user's expenses."""
    user_a = _register_and_login(client, name="Alice", email="alice@example.com")
    expense_a = _create_expense_for(user_a["id"], description="Alice's own expense")

    client.get("/logout")
    user_b = _register_and_login(
        client, name="Bob", email="bob@example.com", password="supersecret"
    )
    expense_b = _create_expense_for(user_b["id"], description="Bob's own expense")

    resp = client.post(f"/expenses/{expense_b}/delete", follow_redirects=False)
    assert resp.status_code == 302

    assert len(_fetch_expenses_for_user(user_b["id"])) == 0
    rows_a = _fetch_expenses_for_user(user_a["id"])
    assert len(rows_a) == 1
    assert rows_a[0]["id"] == expense_a


# ------------------------------------------------------------------ #
# Method not allowed                                                  #
# ------------------------------------------------------------------ #


def test_get_delete_expense_not_allowed(client):
    """A bare GET to the delete route must return 405, not perform a delete."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"])

    resp = client.get(f"/expenses/{expense_id}/delete")
    assert resp.status_code == 405

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1, "GET must not delete the expense"


def test_get_delete_expense_not_allowed_when_logged_out(client):
    """A bare GET while logged out must still be a 405, not a login redirect,
    since Flask enforces method routing before the view's auth guard runs."""
    resp = client.get("/expenses/1/delete")
    assert resp.status_code == 405
