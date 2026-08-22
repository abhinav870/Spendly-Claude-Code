"""Tests for Step 7: Add Expense (`GET`/`POST /expenses/add`).

Written entirely from `.claude/specs/07-add-expense.md`. No assertions are
derived from reading app.py's or database/queries.py's implementation logic —
only route names, the `CATEGORIES` constant (database/db.py), and the
existing test fixture conventions (`tests/conftest.py`, `test_login.py`,
`test_profile.py`, `test_06-date-filter.py`) were confirmed structurally.

Spec highlights under test:
- `GET /expenses/add` and `POST /expenses/add` share one view, logged-in only
  (redirect to /login when anonymous, matching profile()'s guard).
- GET renders a form: amount, category (select from CATEGORIES), date
  (defaulted to today), description (optional).
- POST validates server-side:
    * amount must be a positive number (reject negative, zero, non-numeric)
    * category must be one of CATEGORIES
    * date must be a valid YYYY-MM-DD string (reject malformed/blank)
    * description is optional
- On validation failure: re-render add_expense.html with an `error` message,
  HTTP 400, and the submitted values preserved.
- On success: INSERT a row into `expenses` for the current user, redirect to
  /profile (302). The new expense must show up in profile's recent
  transactions, summary stats, and category breakdown.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database.db as db_module  # noqa: E402
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


def _register_and_login(client, name="Alice", email="alice@example.com", password="supersecret"):
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


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

def test_get_add_expense_redirects_when_logged_out(client):
    """Anonymous GET /expenses/add is redirected to /login."""
    resp = client.get("/expenses/add", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_post_add_expense_redirects_when_logged_out(client):
    """Anonymous POST /expenses/add is redirected to /login and inserts nothing."""
    resp = client.post("/expenses/add", data=_valid_payload(), follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")

    with db_module.get_db() as db:
        count = db.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]
    assert count == 0, "No expense should be inserted for an unauthenticated request"


# ------------------------------------------------------------------ #
# GET /expenses/add — form rendering                                  #
# ------------------------------------------------------------------ #

def test_get_add_expense_renders_form_when_logged_in(client):
    """Logged-in GET returns 200 and shows amount/category/date/description fields."""
    _register_and_login(client)

    resp = client.get("/expenses/add")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="amount"' in body
    assert 'name="category"' in body
    assert 'name="date"' in body
    assert 'name="description"' in body


def test_get_add_expense_lists_all_fixed_categories(client):
    """The category select must offer every entry in CATEGORIES."""
    _register_and_login(client)

    body = client.get("/expenses/add").get_data(as_text=True)
    for category in CATEGORIES:
        assert category in body, f"Expected category '{category}' in add-expense form"


def test_get_add_expense_date_defaults_to_today(client):
    """Spec: the date field defaults to today's date."""
    _register_and_login(client)

    body = client.get("/expenses/add").get_data(as_text=True)
    today = date.today().isoformat()
    assert today in body, "Expected today's date to be pre-filled in the date field"


def test_get_add_expense_uses_url_for_action_no_raw_jinja(client):
    """Form action must be resolved via url_for, not leaked as raw Jinja syntax."""
    _register_and_login(client)

    body = client.get("/expenses/add").get_data(as_text=True)
    assert 'action="{{ url_for(' not in body


# ------------------------------------------------------------------ #
# POST /expenses/add — happy path                                     #
# ------------------------------------------------------------------ #

def test_post_add_expense_valid_data_inserts_row_and_redirects(client):
    """Valid submission inserts a row for the current user and redirects to /profile."""
    user = _register_and_login(client)

    resp = client.post("/expenses/add", data=_valid_payload(), follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1
    row = rows[0]
    assert row["amount"] == pytest.approx(250.50)
    assert row["category"] == "Food"
    assert row["date"] == date.today().isoformat()
    assert row["description"] == "Groceries"
    assert row["user_id"] == user["id"]


def test_post_add_expense_description_is_optional(client):
    """Submitting without a description still succeeds and inserts the row."""
    user = _register_and_login(client)

    payload = _valid_payload()
    payload.pop("description")

    resp = client.post("/expenses/add", data=payload, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1
    assert rows[0]["description"] in (None, ""), "Description should be nullable when omitted"


def test_post_add_expense_empty_description_string_succeeds(client):
    """An explicitly empty description string is also accepted (optional field)."""
    user = _register_and_login(client)

    payload = _valid_payload(description="")
    resp = client.post("/expenses/add", data=payload, follow_redirects=False)
    assert resp.status_code == 302

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1


def test_post_add_expense_new_expense_appears_on_profile(client):
    """DoD: the new expense reflects immediately in profile's transactions,
    summary stats, and category breakdown."""
    _register_and_login(client)

    resp = client.post(
        "/expenses/add",
        data=_valid_payload(amount="500", category="Shopping", description="New Shoes"),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "New Shoes" in body, "Expected new expense in recent transactions"
    assert "Shopping" in body, "Expected new expense's category in category breakdown"
    assert "500.00" in body, "Expected new expense reflected in summary stats total"


def test_post_add_expense_only_affects_current_user(client):
    """The inserted expense must belong to the submitting user, not leak to others."""
    user_a = _register_and_login(client, name="Alice", email="alice@example.com")

    resp = client.post("/expenses/add", data=_valid_payload(), follow_redirects=False)
    assert resp.status_code == 302

    # Log out and register/login a second user.
    client.get("/logout")
    user_b = _register_and_login(client, name="Bob", email="bob@example.com", password="supersecret")

    assert len(_fetch_expenses_for_user(user_a["id"])) == 1
    assert len(_fetch_expenses_for_user(user_b["id"])) == 0

    body = client.get("/profile").get_data(as_text=True)
    assert "Groceries" not in body, "Bob must not see Alice's newly added expense"


# ------------------------------------------------------------------ #
# POST /expenses/add — amount validation                              #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("bad_amount", ["-50", "-0.01", "0", "0.00"])
def test_post_add_expense_non_positive_amount_rejected(client, bad_amount):
    """Zero and negative amounts are rejected with a 400 + error, no row inserted."""
    user = _register_and_login(client)

    resp = client.post("/expenses/add", data=_valid_payload(amount=bad_amount))
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "error" in body.lower()

    assert len(_fetch_expenses_for_user(user["id"])) == 0


@pytest.mark.parametrize("bad_amount", ["abc", "", "twenty", "12.5.3", "NaN"])
def test_post_add_expense_non_numeric_amount_rejected(client, bad_amount):
    """Non-numeric amount values are rejected with 400 + error, no row inserted."""
    user = _register_and_login(client)

    resp = client.post("/expenses/add", data=_valid_payload(amount=bad_amount))
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "error" in body.lower()

    assert len(_fetch_expenses_for_user(user["id"])) == 0


def test_post_add_expense_missing_amount_rejected(client):
    """Missing amount field entirely is rejected with 400 + error."""
    user = _register_and_login(client)

    payload = _valid_payload()
    payload.pop("amount")

    resp = client.post("/expenses/add", data=payload)
    assert resp.status_code == 400
    assert len(_fetch_expenses_for_user(user["id"])) == 0


def test_post_add_expense_negative_amount_preserves_submitted_values(client):
    """On failure, the submitted category/date/description must be preserved
    in the re-rendered form (same pattern as register/login)."""
    _register_and_login(client)

    resp = client.post(
        "/expenses/add",
        data=_valid_payload(amount="-99", category="Health", description="Failed submission marker"),
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "Failed submission marker" in body
    assert "-99" in body or 'value="-99"' in body


# ------------------------------------------------------------------ #
# POST /expenses/add — category validation                            #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("bad_category", ["Vacation", "food", "", "Not-A-Category"])
def test_post_add_expense_invalid_category_rejected(client, bad_category):
    """Any category outside the fixed CATEGORIES list is rejected with 400."""
    user = _register_and_login(client)

    resp = client.post("/expenses/add", data=_valid_payload(category=bad_category))
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "error" in body.lower()

    assert len(_fetch_expenses_for_user(user["id"])) == 0


def test_post_add_expense_missing_category_rejected(client):
    """Missing category field entirely is rejected with 400 + error."""
    user = _register_and_login(client)

    payload = _valid_payload()
    payload.pop("category")

    resp = client.post("/expenses/add", data=payload)
    assert resp.status_code == 400
    assert len(_fetch_expenses_for_user(user["id"])) == 0


@pytest.mark.parametrize("category", CATEGORIES)
def test_post_add_expense_accepts_every_fixed_category(client, category):
    """Every value in CATEGORIES must be an accepted, successful submission."""
    user = _register_and_login(client, email=f"user-{category.lower()}@example.com")

    resp = client.post("/expenses/add", data=_valid_payload(category=category), follow_redirects=False)
    assert resp.status_code == 302

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1
    assert rows[0]["category"] == category


# ------------------------------------------------------------------ #
# POST /expenses/add — date validation                                #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "bad_date",
    ["not-a-date", "2026-13-45", "99-99-9999", "08/22/2026", "2026/08/22"],
)
def test_post_add_expense_malformed_date_rejected(client, bad_date):
    """Malformed date strings are rejected with 400 + error, no row inserted."""
    user = _register_and_login(client)

    resp = client.post("/expenses/add", data=_valid_payload(date=bad_date))
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "error" in body.lower()

    assert len(_fetch_expenses_for_user(user["id"])) == 0


def test_post_add_expense_blank_date_rejected(client):
    """An empty date string is rejected with 400 + error, no row inserted."""
    user = _register_and_login(client)

    resp = client.post("/expenses/add", data=_valid_payload(date=""))
    assert resp.status_code == 400
    assert len(_fetch_expenses_for_user(user["id"])) == 0


def test_post_add_expense_missing_date_rejected(client):
    """Missing date field entirely is rejected with 400 + error."""
    user = _register_and_login(client)

    payload = _valid_payload()
    payload.pop("date")

    resp = client.post("/expenses/add", data=payload)
    assert resp.status_code == 400
    assert len(_fetch_expenses_for_user(user["id"])) == 0


def test_post_add_expense_valid_date_formats_accepted(client):
    """Sanity check: a normal valid YYYY-MM-DD date is accepted (contrast to malformed cases)."""
    user = _register_and_login(client)

    resp = client.post("/expenses/add", data=_valid_payload(date="2026-02-14"), follow_redirects=False)
    assert resp.status_code == 302

    rows = _fetch_expenses_for_user(user["id"])
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-02-14"


# ------------------------------------------------------------------ #
# No crash / no traceback leak on invalid input                       #
# ------------------------------------------------------------------ #

def test_post_add_expense_invalid_input_does_not_leak_traceback(client):
    """Safety net: bad input must never surface a raw 500 / traceback text."""
    _register_and_login(client)

    resp = client.post(
        "/expenses/add",
        data=_valid_payload(amount="not-a-number", category="Nope", date="garbage"),
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "Traceback" not in body
    assert "ValueError" not in body
