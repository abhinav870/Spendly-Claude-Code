import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database.db as db_module  # noqa: E402
from database import queries  # noqa: E402
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


def _data_section(body):
    """Slice out the transactions table + category breakdown, excluding the
    always-rendered category filter <select> which lists every category
    regardless of which user's data is shown."""
    start = body.index('id="transactions"')
    return body[start:]


# ------------------------------------------------------------------ #
# Unit tests — get_user_by_id                                        #
# ------------------------------------------------------------------ #


def test_get_user_by_id_returns_correct_shape(client):
    user = _seed_user(client, name="Alice", email="alice@example.com")
    result = queries.get_user_by_id(user["id"])

    assert result is not None
    assert result["name"] == "Alice"
    assert result["email"] == "alice@example.com"
    assert result["member_since"]  # non-empty "Month YYYY" string


def test_get_user_by_id_nonexistent_returns_none(client):
    assert queries.get_user_by_id(999999) is None


# ------------------------------------------------------------------ #
# Unit tests — get_summary_stats                                     #
# ------------------------------------------------------------------ #


def test_get_summary_stats_with_expenses(client):
    user = _seed_user(client)
    _insert_expense(user["id"], "Food", "2026-08-01", "Groceries", 100)
    _insert_expense(user["id"], "Bills", "2026-08-02", "Electricity", 500)
    _insert_expense(user["id"], "Bills", "2026-08-03", "Water", 200)

    stats = queries.get_summary_stats(user["id"])
    assert stats["total_spent"] == 800
    assert stats["transaction_count"] == 3
    assert stats["top_category"] == "Bills"


def test_get_summary_stats_no_expenses(client):
    user = _seed_user(client)
    stats = queries.get_summary_stats(user["id"])
    assert stats == {"total_spent": 0, "transaction_count": 0, "top_category": "—"}


# ------------------------------------------------------------------ #
# Unit tests — get_recent_transactions                                #
# ------------------------------------------------------------------ #


def test_get_recent_transactions_newest_first(client):
    user = _seed_user(client)
    _insert_expense(user["id"], "Food", "2026-08-01", "Oldest", 10)
    _insert_expense(user["id"], "Food", "2026-08-15", "Newest", 20)
    _insert_expense(user["id"], "Food", "2026-08-08", "Middle", 15)

    txs = queries.get_recent_transactions(user["id"])
    dates = [tx["date"] for tx in txs]
    assert dates == sorted(dates, reverse=True)
    assert txs[0]["description"] == "Newest"

    for tx in txs:
        assert set(tx.keys()) == {"id", "date", "description", "category", "amount"}


def test_get_recent_transactions_empty_list(client):
    user = _seed_user(client)
    assert queries.get_recent_transactions(user["id"]) == []


# ------------------------------------------------------------------ #
# Unit tests — get_category_breakdown                                #
# ------------------------------------------------------------------ #


def test_get_category_breakdown_pct_sums_to_100_and_ordered(client):
    user = _seed_user(client)
    _insert_expense(user["id"], "Bills", "2026-08-01", "a", 700)
    _insert_expense(user["id"], "Food", "2026-08-02", "b", 200)
    _insert_expense(user["id"], "Transport", "2026-08-03", "c", 100)

    breakdown = queries.get_category_breakdown(user["id"])

    assert sum(cat["pct"] for cat in breakdown) == 100
    amounts = [cat["amount"] for cat in breakdown]
    assert amounts == sorted(amounts, reverse=True)
    assert breakdown[0]["name"] == "Bills"
    for cat in breakdown:
        assert isinstance(cat["pct"], int)


def test_get_category_breakdown_empty_list(client):
    user = _seed_user(client)
    assert queries.get_category_breakdown(user["id"]) == []


# ------------------------------------------------------------------ #
# Route tests                                                         #
# ------------------------------------------------------------------ #


def test_get_profile_unauthenticated_redirects_to_login(client):
    resp = client.get("/profile", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_get_profile_seeded_demo_user_shows_real_data(monkeypatch, tmp_path):
    """Uses seed_db() (demo user + SAMPLE_EXPENSES) with a fresh DB, following
    the test_demo_user_can_login pattern from tests/test_login.py."""
    test_db = tmp_path / "demo_profile.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db()
    db_module.seed_db()

    from app import app as flask_app

    flask_app.config.update(SECRET_KEY="test-secret-key", TESTING=True)
    flask_client = flask_app.test_client()

    resp = flask_client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "demo123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    # Compute expected values dynamically from SAMPLE_EXPENSES — never hardcode.
    expected_total = sum(amount for _, _, amount in db_module.SAMPLE_EXPENSES)
    expected_count = len(db_module.SAMPLE_EXPENSES)

    category_totals = {}
    for category, _, amount in db_module.SAMPLE_EXPENSES:
        category_totals[category] = category_totals.get(category, 0) + amount
    expected_top_category = max(category_totals, key=category_totals.get)

    resp = flask_client.get("/profile")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Demo User" in body
    assert "demo@spendly.com" in body
    assert "₹" in body  # ₹ symbol

    assert f"{expected_total:,.2f}" in body
    assert str(expected_count) in body
    assert expected_top_category in body

    for category in category_totals:
        assert category in body
    assert len(category_totals) == 7


def test_get_profile_transactions_render_newest_first(monkeypatch, tmp_path):
    test_db = tmp_path / "demo_profile_order.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db()
    db_module.seed_db()

    from app import app as flask_app

    flask_app.config.update(SECRET_KEY="test-secret-key", TESTING=True)
    flask_client = flask_app.test_client()

    flask_client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "demo123"},
    )

    body = flask_client.get("/profile").get_data(as_text=True)

    first_expense_desc = db_module.SAMPLE_EXPENSES[0][1]
    last_expense_desc = db_module.SAMPLE_EXPENSES[-1][1]

    # SAMPLE_DAYS is ascending, so the last sample expense has the latest
    # date and must appear before the first sample expense in the newest-
    # first rendered list.
    assert body.index(last_expense_desc) < body.index(first_expense_desc)


def test_get_profile_new_user_zero_state(client):
    """A freshly registered user (no seeding) sees zero-state, no errors."""
    _seed_user(client, name="Bob", email="bob@example.com", password="supersecret")
    client.post("/login", data={"email": "bob@example.com", "password": "supersecret"})

    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "₹0.00" in body
    assert "stat-bar-row" not in body


# ------------------------------------------------------------------ #
# Two-user isolation — the critical requirement                       #
# ------------------------------------------------------------------ #


def test_profile_isolates_expenses_between_users(client):
    """A user must only ever see their own expenses — never another
    user's transactions, categories, or totals."""
    user_a = _seed_user(
        client, name="Alice", email="alice@example.com", password="supersecret"
    )
    user_b = _seed_user(
        client, name="Bob", email="bob@example.com", password="supersecret"
    )

    _insert_expense(user_a["id"], "Food", "2026-08-01", "Alice Groceries", 111)
    _insert_expense(user_a["id"], "Bills", "2026-08-02", "Alice Electricity", 222)

    _insert_expense(user_b["id"], "Health", "2026-08-01", "Bob Pharmacy", 333)
    _insert_expense(user_b["id"], "Entertainment", "2026-08-02", "Bob Movie", 444)

    # Log in as Alice and confirm Bob's data never appears.
    client.post(
        "/login", data={"email": "alice@example.com", "password": "supersecret"}
    )
    body_a = client.get("/profile").get_data(as_text=True)

    assert "Alice Groceries" in body_a
    assert "Alice Electricity" in body_a
    assert "Bob Pharmacy" not in body_a
    assert "Bob Movie" not in body_a
    # Scope to the transactions/breakdown section — the category filter
    # <select> always lists every category regardless of whose data is shown.
    section_a = _data_section(body_a)
    assert "Health" not in section_a
    assert "Entertainment" not in section_a

    # Alice's total must only reflect her own expenses (333), not the
    # combined total of both users (1110).
    assert "333.00" in body_a  # 111 + 222
    with client.session_transaction() as sess:
        sess.clear()

    # Log in as Bob and confirm Alice's data never appears.
    client.post("/login", data={"email": "bob@example.com", "password": "supersecret"})
    body_b = client.get("/profile").get_data(as_text=True)

    assert "Bob Pharmacy" in body_b
    assert "Bob Movie" in body_b
    assert "Alice Groceries" not in body_b
    assert "Alice Electricity" not in body_b
    section_b = _data_section(body_b)
    assert "Food" not in section_b
    assert "Bills" not in section_b

    assert "777.00" in body_b  # 333 + 444


def test_query_helpers_isolate_by_user_id(client):
    """Direct check on the query layer: querying user A never returns
    user B's rows, at the function level (not just via the route)."""
    user_a = _seed_user(
        client, name="Alice", email="alice@example.com", password="supersecret"
    )
    user_b = _seed_user(
        client, name="Bob", email="bob@example.com", password="supersecret"
    )

    _insert_expense(user_a["id"], "Food", "2026-08-01", "Alice item", 50)
    _insert_expense(user_b["id"], "Food", "2026-08-01", "Bob item", 9999)

    stats_a = queries.get_summary_stats(user_a["id"])
    assert stats_a["total_spent"] == 50

    txs_a = queries.get_recent_transactions(user_a["id"])
    assert all(tx["description"] == "Alice item" for tx in txs_a)

    breakdown_a = queries.get_category_breakdown(user_a["id"])
    assert all(cat["amount"] == 50 for cat in breakdown_a)
