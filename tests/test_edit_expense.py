"""Tests for Step 8: Edit Expense (`GET`/`POST /expenses/<id>/edit`).

Written entirely from `.claude/specs/08-edit-expense.md`. No assertions are
derived from reading app.py's or database/queries.py's implementation logic —
only route names, the `CATEGORIES` constant (database/db.py), and the
existing test fixture conventions (`tests/conftest.py`, `test_add_expense.py`)
were confirmed structurally.

Spec highlights under test:
- `GET /expenses/<id>/edit` and `POST /expenses/<id>/edit` share one view,
  logged-in only (redirect to /login when anonymous).
- Ownership is enforced: a user editing another user's expense (or a
  nonexistent id) gets a 404, not a redirect or leaked data.
- GET renders a form pre-filled with the expense's current amount, category,
  date, and description.
- POST validates server-side using the same rules as add expense:
    * amount must be a positive number (reject negative, zero, non-numeric)
    * category must be one of CATEGORIES
    * date must be a valid YYYY-MM-DD string (reject malformed/blank)
    * description is optional
- On validation failure: re-render edit_expense.html with an `error` message,
  HTTP 400, and the just-submitted values preserved (not the original DB
  values).
- On success: UPDATE the existing row (not insert a new one), redirect to
  /profile (302). The updated expense must show up in profile's recent
  transactions.
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
from database.db import CATEGORIES, get_user_by_email  # noqa: E402

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


def _valid_payload(**overrides):
    payload = {
        "amount": "250.50",
        "category": "Food",
        "date": date.today().isoformat(),
        "description": "Groceries",
    }
    payload.update(overrides)
    return payload


def _fetch_expenses_for_user(user_id):
    with db_module.get_db() as db:
        return db.execute(
            "SELECT * FROM expenses WHERE user_id = ?",
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
# Auth guard                                                          #
# ------------------------------------------------------------------ #


def test_get_edit_expense_redirects_when_logged_out(client):
    """Anonymous GET /expenses/<id>/edit is redirected to /login."""
    resp = client.get("/expenses/1/edit", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_post_edit_expense_redirects_when_logged_out(client):
    """Anonymous POST /expenses/<id>/edit is redirected to /login and changes nothing."""
    resp = client.post(
        "/expenses/1/edit", data=_valid_payload(), follow_redirects=False
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    with db_module.get_db() as db:
        count = db.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]
    assert (
        count == 0
    ), "No expense should exist or be modified for an unauthenticated request"


# ------------------------------------------------------------------ #
# Ownership / 404                                                     #
# ------------------------------------------------------------------ #


def test_get_edit_expense_nonexistent_id_404s(client):
    """Logged-in GET for an id that doesn't exist returns 404."""
    _register_and_login(client)

    resp = client.get("/expenses/999999/edit")
    assert resp.status_code == 404


def test_get_edit_expense_other_users_expense_404s(client):
    """User B GETting user A's expense id gets 404, and A's data must not leak."""
    user_a = _register_and_login(client, name="Alice", email="alice@example.com")
    expense_id = _create_expense_for(user_a["id"], description="Alice's secret expense")

    client.get("/logout")
    _register_and_login(
        client, name="Bob", email="bob@example.com", password="supersecret"
    )

    resp = client.get(f"/expenses/{expense_id}/edit")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "Alice's secret expense" not in body


def test_post_edit_expense_other_users_expense_404s_and_does_not_modify(client):
    """User B POSTing to user A's expense id gets 404, and A's row is unchanged."""
    user_a = _register_and_login(client, name="Alice", email="alice@example.com")
    expense_id = _create_expense_for(
        user_a["id"], amount=100.0, category="Food", description="Original"
    )

    client.get("/logout")
    _register_and_login(
        client, name="Bob", email="bob@example.com", password="supersecret"
    )

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data=_valid_payload(amount="999", category="Shopping", description="Hacked"),
    )
    assert resp.status_code == 404

    rows = _fetch_expenses_for_user(user_a["id"])
    assert len(rows) == 1
    assert rows[0]["amount"] == pytest.approx(100.0)
    assert rows[0]["category"] == "Food"
    assert rows[0]["description"] == "Original"


# ------------------------------------------------------------------ #
# GET /expenses/<id>/edit — form rendering                            #
# ------------------------------------------------------------------ #


def test_get_edit_expense_renders_form_when_logged_in(client):
    """Logged-in GET for an owned expense returns 200 and shows form fields."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"])

    resp = client.get(f"/expenses/{expense_id}/edit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="amount"' in body
    assert 'name="category"' in body
    assert 'name="date"' in body
    assert 'name="description"' in body


def test_get_edit_expense_prefills_existing_values(client):
    """The form must be pre-filled with the expense's current values, not blank."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(
        user["id"],
        amount=123.45,
        category="Health",
        expense_date="2026-03-14",
        description="Distinctive pre-fill marker",
    )

    body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)
    assert "123.45" in body
    assert "2026-03-14" in body
    assert "Distinctive pre-fill marker" in body
    assert (
        'value="Health" selected' in body
        or "selected>Health" in body
        or ">Health</option>" in body
    )


def test_get_edit_expense_lists_all_fixed_categories(client):
    """The category select must offer every entry in CATEGORIES."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"])

    body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)
    for category in CATEGORIES:
        assert category in body, f"Expected category '{category}' in edit-expense form"


def test_get_edit_expense_uses_url_for_action_no_raw_jinja(client):
    """Form action must be resolved via url_for, not leaked as raw Jinja syntax."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"])

    body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)
    assert 'action="{{ url_for(' not in body


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — happy path                                #
# ------------------------------------------------------------------ #


def test_post_edit_expense_valid_data_updates_row_and_redirects(client):
    """Valid submission updates the existing row and redirects to /profile."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(
        user["id"], amount=100.0, category="Food", description="Original"
    )

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data=_valid_payload(
            amount="500.25", category="Shopping", description="Updated"
        ),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == expense_id
    assert row["amount"] == pytest.approx(500.25)
    assert row["category"] == "Shopping"
    assert row["description"] == "Updated"
    assert row["user_id"] == user["id"]


def test_post_edit_expense_description_can_be_cleared(client):
    """Submitting without a description clears it (nullable, matches add-expense behavior)."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"], description="Will be cleared")

    payload = _valid_payload()
    payload.pop("description")

    resp = client.post(
        f"/expenses/{expense_id}/edit", data=payload, follow_redirects=False
    )
    assert resp.status_code == 302

    rows = _fetch_expenses_for_user(user["id"])
    assert rows[0]["description"] in (None, "")


def test_post_edit_expense_updated_expense_reflects_on_profile(client):
    """DoD: the updated expense's new values appear on profile, old ones don't."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(
        user["id"], amount=100.0, category="Food", description="Old Description Marker"
    )

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data=_valid_payload(
            amount="777", category="Entertainment", description="New Description Marker"
        ),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "New Description Marker" in body
    assert "Old Description Marker" not in body
    assert "Entertainment" in body
    assert "777.00" in body


def test_post_edit_expense_does_not_create_a_new_row(client):
    """A successful edit must UPDATE the row, not INSERT a second one."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"])

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data=_valid_payload(amount="42.00"),
        follow_redirects=False,
    )
    assert resp.status_code == 302

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — amount validation                        #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("bad_amount", ["-50", "-0.01", "0", "0.00"])
def test_post_edit_expense_non_positive_amount_rejected(client, bad_amount):
    """Zero and negative amounts are rejected with a 400 + error, row unchanged."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"], amount=100.0)

    resp = client.post(
        f"/expenses/{expense_id}/edit", data=_valid_payload(amount=bad_amount)
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "error" in body.lower()

    rows = _fetch_expenses_for_user(user["id"])
    assert rows[0]["amount"] == pytest.approx(100.0)


@pytest.mark.parametrize("bad_amount", ["abc", "", "twenty", "12.5.3", "NaN"])
def test_post_edit_expense_non_numeric_amount_rejected(client, bad_amount):
    """Non-numeric amount values are rejected with 400 + error, row unchanged."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"], amount=100.0)

    resp = client.post(
        f"/expenses/{expense_id}/edit", data=_valid_payload(amount=bad_amount)
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "error" in body.lower()

    rows = _fetch_expenses_for_user(user["id"])
    assert rows[0]["amount"] == pytest.approx(100.0)


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — category validation                      #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("bad_category", ["Vacation", "food", "", "Not-A-Category"])
def test_post_edit_expense_invalid_category_rejected(client, bad_category):
    """Any category outside the fixed CATEGORIES list is rejected with 400."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"], category="Food")

    resp = client.post(
        f"/expenses/{expense_id}/edit", data=_valid_payload(category=bad_category)
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "error" in body.lower()

    rows = _fetch_expenses_for_user(user["id"])
    assert rows[0]["category"] == "Food"


@pytest.mark.parametrize("category", CATEGORIES)
def test_post_edit_expense_accepts_every_fixed_category(client, category):
    """Every value in CATEGORIES must be an accepted, successful edit."""
    user = _register_and_login(client, email=f"user-{category.lower()}@example.com")
    expense_id = _create_expense_for(user["id"], category="Food")

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data=_valid_payload(category=category),
        follow_redirects=False,
    )
    assert resp.status_code == 302

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1
    assert rows[0]["category"] == category


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — date validation                          #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "bad_date",
    ["not-a-date", "2026-13-45", "99-99-9999", "08/22/2026", "2026/08/22"],
)
def test_post_edit_expense_malformed_date_rejected(client, bad_date):
    """Malformed date strings are rejected with 400 + error, row unchanged."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"], expense_date="2026-01-01")

    resp = client.post(
        f"/expenses/{expense_id}/edit", data=_valid_payload(date=bad_date)
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "error" in body.lower()

    rows = _fetch_expenses_for_user(user["id"])
    assert rows[0]["date"] == "2026-01-01"


def test_post_edit_expense_blank_date_rejected(client):
    """An empty date string is rejected with 400 + error, row unchanged."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"], expense_date="2026-01-01")

    resp = client.post(f"/expenses/{expense_id}/edit", data=_valid_payload(date=""))
    assert resp.status_code == 400

    rows = _fetch_expenses_for_user(user["id"])
    assert rows[0]["date"] == "2026-01-01"


# ------------------------------------------------------------------ #
# Preserve submitted values on failure                                #
# ------------------------------------------------------------------ #


def test_post_edit_expense_validation_failure_preserves_submitted_values(client):
    """On failure, the just-submitted values (not stale DB values) must be
    preserved in the re-rendered form."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"], description="Original DB value")

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data=_valid_payload(
            amount="-99", category="Health", description="Failed submission marker"
        ),
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "Failed submission marker" in body
    assert "-99" in body or 'value="-99"' in body
    assert "Original DB value" not in body


# ------------------------------------------------------------------ #
# No crash / no traceback leak on invalid input                       #
# ------------------------------------------------------------------ #


def test_post_edit_expense_invalid_input_does_not_leak_traceback(client):
    """Safety net: bad input must never surface a raw 500 / traceback text."""
    user = _register_and_login(client)
    expense_id = _create_expense_for(user["id"])

    resp = client.post(
        f"/expenses/{expense_id}/edit",
        data=_valid_payload(amount="not-a-number", category="Nope", date="garbage"),
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "Traceback" not in body
    assert "ValueError" not in body
