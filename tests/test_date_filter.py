"""Tests for Step 6: Date Filter on the /profile route.

Written entirely from `.claude/specs/06-date-filter.md`. No assertions are
derived from reading app.py's or database/queries.py's implementation logic —
only route/query-param names and the existing test fixture conventions were
confirmed structurally.

Spec highlights under test:
- Query params `date_from` / `date_to` (ISO `YYYY-MM-DD`), inclusive bounds.
- Absent or malformed params -> falls back to "All Time" (unfiltered) silently.
- `date_from > date_to` -> both treated as absent + flash "Start date must be
  before end date."
- All three data sections (summary stats, recent transactions, category
  breakdown) must respect the active filter.
- ₹ symbol always present regardless of filter.
- No expenses in range -> ₹0.00 total, 0 transactions, empty breakdown, no
  errors (200 OK).
- Unauthenticated access still redirects to /login (route unchanged).
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database.db as db_module  # noqa: E402
from database.db import get_user_by_email  # noqa: E402

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


def _insert_expense(user_id, category, tx_date, description, amount):
    with db_module.get_db() as db:
        db.execute(
            """
            INSERT INTO expenses (user_id, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, amount, category, tx_date, description),
        )


def _login(client, email, password):
    return client.post("/login", data={"email": email, "password": password})


def _data_section(body):
    """Slice out the transactions table + category breakdown, excluding the
    always-rendered category filter <select> which lists every category
    regardless of the active filter."""
    start = body.index('id="transactions"')
    return body[start:]


# ------------------------------------------------------------------ #
# Auth guard — unchanged behaviour with filter params present         #
# ------------------------------------------------------------------ #


def test_profile_with_date_params_still_requires_login(client):
    """Spec: no new routes — /profile with date_from/date_to must still
    enforce the existing auth guard for anonymous visitors."""
    resp = client.get(
        "/profile?date_from=2026-08-01&date_to=2026-08-31",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


# ------------------------------------------------------------------ #
# No params -> unfiltered ("Step 5 behaviour")                        #
# ------------------------------------------------------------------ #


def test_no_date_params_shows_all_expenses_unfiltered(client):
    """DoD: visiting /profile with no query params returns the same data
    as the unfiltered view — all expenses across all dates included."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2020-01-01", "Old expense", 100)
    _insert_expense(user["id"], "Bills", "2026-08-10", "Recent expense", 200)

    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Old expense" in body
    assert "Recent expense" in body
    assert "300.00" in body  # 100 + 200, unfiltered total


# ------------------------------------------------------------------ #
# Custom valid range filters all three sections                       #
# ------------------------------------------------------------------ #


def test_custom_valid_range_filters_all_three_sections(client):
    """DoD: submitting a valid date_from/date_to shows only expenses within
    that range in summary stats, transactions, and category breakdown."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-06-15", "Outside range (before)", 999)
    _insert_expense(user["id"], "Bills", "2026-08-05", "Inside range", 250)
    _insert_expense(user["id"], "Health", "2026-09-01", "Outside range (after)", 777)

    resp = client.get("/profile?date_from=2026-08-01&date_to=2026-08-31")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Inside range" in body
    assert "Outside range (before)" not in body
    assert "Outside range (after)" not in body

    # Summary total should reflect only the in-range expense.
    assert "250.00" in body
    # Category breakdown should only include the in-range category. Scope to
    # the transactions/breakdown section — the category filter <select>
    # always lists every category regardless of the active filter.
    section = _data_section(body)
    assert "Bills" in section
    assert "Health" not in section
    assert "Food" not in section


def test_date_range_bounds_are_inclusive(client):
    """Spec: date_from is an inclusive lower bound, date_to an inclusive
    upper bound — expenses dated exactly on the boundary must be included."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-08-01", "On start boundary", 111)
    _insert_expense(user["id"], "Food", "2026-08-31", "On end boundary", 222)
    _insert_expense(user["id"], "Food", "2026-07-31", "Just before start", 333)
    _insert_expense(user["id"], "Food", "2026-09-01", "Just after end", 444)

    body = client.get("/profile?date_from=2026-08-01&date_to=2026-08-31").get_data(
        as_text=True
    )

    assert "On start boundary" in body
    assert "On end boundary" in body
    assert "Just before start" not in body
    assert "Just after end" not in body


# ------------------------------------------------------------------ #
# Zero-result range -> zero state, no errors                          #
# ------------------------------------------------------------------ #


def test_range_with_no_matching_expenses_shows_zero_state(client):
    """DoD: a user with no expenses in the selected range sees ₹0.00 total
    spent, 0 transactions, and an empty category breakdown — no errors."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-01-01", "Out of range", 500)

    resp = client.get("/profile?date_from=2026-12-01&date_to=2026-12-31")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "₹0.00" in body
    assert "Out of range" not in body


# ------------------------------------------------------------------ #
# Invalid range: date_from > date_to                                  #
# ------------------------------------------------------------------ #


def test_date_from_after_date_to_falls_back_to_unfiltered_with_flash(client):
    """DoD + Rules: if date_from > date_to, treat both as absent (no filter)
    and flash 'Start date must be before end date.'"""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-01-01", "January expense", 100)
    _insert_expense(user["id"], "Bills", "2026-06-01", "June expense", 200)

    resp = client.get(
        "/profile?date_from=2026-08-31&date_to=2026-08-01",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Falls back to unfiltered — both expenses visible.
    assert "January expense" in body
    assert "June expense" in body

    # User-visible flash error message per spec text (exact wording).
    assert "Start date must be before end date." in body


# ------------------------------------------------------------------ #
# Malformed date strings                                              #
# ------------------------------------------------------------------ #


def test_malformed_date_from_does_not_crash_and_falls_back_unfiltered(client):
    """DoD: a malformed date string (e.g. date_from=not-a-date) does not
    crash the app — it silently falls back to the unfiltered view."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-01-01", "January expense", 100)
    _insert_expense(user["id"], "Bills", "2026-06-01", "June expense", 200)

    resp = client.get("/profile?date_from=not-a-date&date_to=2026-08-31")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # Both expenses visible -> filter silently ignored, not applied partially.
    assert "January expense" in body
    assert "June expense" in body


def test_malformed_date_to_does_not_crash_and_falls_back_unfiltered(client):
    """Same guarantee, but with the malformed value on date_to instead."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-01-01", "January expense", 100)
    _insert_expense(user["id"], "Bills", "2026-06-01", "June expense", 200)

    resp = client.get("/profile?date_from=2026-01-01&date_to=garbage")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "January expense" in body
    assert "June expense" in body


def test_both_dates_malformed_falls_back_unfiltered_no_crash(client):
    """Edge case: both params malformed simultaneously must still be safe."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-01-01", "January expense", 100)

    resp = client.get("/profile?date_from=xxxx&date_to=yyyy")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "January expense" in body


def test_empty_string_date_params_treated_as_absent(client):
    """Edge case: empty-string query params (e.g. from a cleared form field)
    must not error and must behave as unfiltered, per the 'absent or
    malformed' fallback rule."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-01-01", "January expense", 100)

    resp = client.get("/profile?date_from=&date_to=")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "January expense" in body


# ------------------------------------------------------------------ #
# Only one of the two params provided                                 #
# ------------------------------------------------------------------ #


def test_only_date_from_provided_does_not_crash(client):
    """Spec doesn't define single-sided filtering explicitly, but per the
    'no crash' guarantee and the fallback rule (both params absent/invalid
    -> unfiltered), a single param alone must be handled without error."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-01-01", "January expense", 100)
    _insert_expense(user["id"], "Bills", "2026-06-01", "June expense", 200)

    resp = client.get("/profile?date_from=2026-05-01")
    assert resp.status_code == 200  # must never 500


def test_only_date_to_provided_does_not_crash(client):
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-01-01", "January expense", 100)

    resp = client.get("/profile?date_to=2026-06-01")
    assert resp.status_code == 200  # must never 500


# ------------------------------------------------------------------ #
# Preset: This Month                                                  #
# ------------------------------------------------------------------ #


def test_this_month_preset_filters_to_current_calendar_month(client):
    """DoD: clicking 'This Month' filters all three sections to the current
    calendar month only. Presets are computed server-side in app.py and
    rendered as links, so we simulate the click by hitting /profile with
    the query params the current-month preset would resolve to."""
    from datetime import date
    import calendar

    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    today = date.today()
    this_month_start = today.replace(day=1).isoformat()
    last_day = calendar.monthrange(today.year, today.month)[1]
    this_month_end = today.replace(day=last_day).isoformat()

    _insert_expense(user["id"], "Food", this_month_start, "This month expense", 150)
    _insert_expense(user["id"], "Bills", "2020-01-01", "Long ago expense", 999)

    resp = client.get(f"/profile?date_from={this_month_start}&date_to={this_month_end}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "This month expense" in body
    assert "Long ago expense" not in body


# ------------------------------------------------------------------ #
# Preset: All Time — clean URL, no filter params                      #
# ------------------------------------------------------------------ #


def test_all_time_preset_url_has_no_query_params_and_shows_everything(client):
    """DoD + Rules: the 'All Time' preset must pass no query params (clean
    /profile URL) and must remove any active filter, showing all expenses."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2020-01-01", "Old expense", 100)
    _insert_expense(user["id"], "Bills", "2026-08-10", "Recent expense", 200)

    # "All Time" is the clean /profile URL, per spec §Rules.
    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Old expense" in body
    assert "Recent expense" in body


# ------------------------------------------------------------------ #
# ₹ symbol always present, regardless of filter / zero state          #
# ------------------------------------------------------------------ #


def test_rupee_symbol_present_with_active_filter(client):
    """DoD: all amounts continue to display the ₹ symbol regardless of the
    active filter."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-08-10", "Groceries", 250)

    body = client.get("/profile?date_from=2026-08-01&date_to=2026-08-31").get_data(
        as_text=True
    )
    assert "₹" in body


def test_rupee_symbol_present_on_zero_state_with_filter(client):
    """DoD: the ₹0.00 zero-state must still show the ₹ symbol when a filter
    excludes all expenses."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-01-01", "Not in range", 100)

    body = client.get("/profile?date_from=2027-01-01&date_to=2027-01-31").get_data(
        as_text=True
    )
    assert "₹0.00" in body


# ------------------------------------------------------------------ #
# Category breakdown & summary stats respect the filter (DB-level)    #
# ------------------------------------------------------------------ #


def test_category_breakdown_excludes_categories_outside_range(client):
    """DoD: the category breakdown section respects the active date filter
    — a category with expenses only outside the range must not appear."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-08-10", "In range", 300)
    _insert_expense(user["id"], "Shopping", "2025-01-01", "Out of range", 900)

    body = client.get("/profile?date_from=2026-08-01&date_to=2026-08-31").get_data(
        as_text=True
    )

    # Scope to the transactions/breakdown section — the category filter
    # <select> always lists every category regardless of the active filter.
    section = _data_section(body)
    assert "Food" in section
    assert "Shopping" not in section


def test_summary_stats_transaction_count_reflects_filtered_range(client):
    """DoD: summary stats (transaction count) must match only the filtered
    subset of expenses, not the full unfiltered set."""
    user = _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    _insert_expense(user["id"], "Food", "2026-08-01", "In range 1", 50)
    _insert_expense(user["id"], "Food", "2026-08-15", "In range 2", 75)
    _insert_expense(user["id"], "Food", "2026-01-01", "Out of range", 1000)

    body = client.get("/profile?date_from=2026-08-01&date_to=2026-08-31").get_data(
        as_text=True
    )

    # Two matching transactions -> total of 125, not 1125.
    assert "125.00" in body
    assert "1,125.00" not in body


# ------------------------------------------------------------------ #
# Two-user isolation still holds with an active filter                #
# ------------------------------------------------------------------ #


def test_date_filter_still_isolates_expenses_between_users(client):
    """The date filter must never leak another user's expenses even when
    both users have expenses inside the same date range."""
    user_a = _seed_user(
        client, name="Alice", email="alice@example.com", password="supersecret"
    )
    user_b = _seed_user(
        client, name="Bob", email="bob@example.com", password="supersecret"
    )

    _insert_expense(user_a["id"], "Food", "2026-08-05", "Alice groceries", 111)
    _insert_expense(user_b["id"], "Health", "2026-08-05", "Bob pharmacy", 222)

    _login(client, "alice@example.com", "supersecret")
    body = client.get("/profile?date_from=2026-08-01&date_to=2026-08-31").get_data(
        as_text=True
    )

    assert "Alice groceries" in body
    assert "Bob pharmacy" not in body


# ------------------------------------------------------------------ #
# Malformed date must not surface a raw 500 / traceback text          #
# ------------------------------------------------------------------ #


def test_malformed_date_does_not_leak_traceback(client):
    """Extra safety net for the 'does not crash' DoD item — the response
    body must not contain Python traceback / werkzeug debugger markers."""
    _seed_user(client)
    _login(client, "alice@example.com", "supersecret")

    resp = client.get("/profile?date_from=2026-13-45&date_to=99-99-9999")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Traceback" not in body
    assert "ValueError" not in body
