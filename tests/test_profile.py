import re
from pathlib import Path

from database.db import get_user_by_email


def _seed_user(client, name="Alice", email="alice@example.com", password="supersecret"):
    """Insert a user row with a hashed password via the test client."""
    resp = client.post(
        "/register",
        data={"name": name, "email": email, "password": password},
    )
    assert resp.status_code == 302, f"seed failed: {resp.status_code}"
    with client.session_transaction() as sess:
        sess.clear()
    return get_user_by_email(email)


def test_get_profile_redirects_when_logged_out(client):
    """Anonymous visitors are redirected to /login."""
    resp = client.get("/profile", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_get_profile_shows_user_details_when_logged_in(client):
    """Logged-in users see their name and email on a 200 response."""
    _seed_user(client, name="Alice", email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Alice" in body
    assert "alice@example.com" in body


def test_get_profile_shows_transactions_and_categories(client):
    """With real expenses in the DB, the page renders a transaction row per
    expense and a category-breakdown row per distinct category."""
    from database import db as db_module

    user = _seed_user(client, email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    expenses = [
        ("Food", "2026-08-01", "Groceries", 455),
        ("Transport", "2026-08-05", "Metro pass", 300),
        ("Bills", "2026-08-08", "Electricity", 7520),
    ]
    with db_module.get_db() as db:
        for category, tx_date, description, amount in expenses:
            db.execute(
                """
                INSERT INTO expenses (user_id, amount, category, date, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user["id"], amount, category, tx_date, description),
            )

    body = client.get("/profile").get_data(as_text=True)
    assert body.count("category-badge") >= 3
    assert body.count("stat-bar-row") >= 3


def test_get_profile_never_leaks_password_hash(client):
    """The rendered page must never contain the stored password hash."""
    user = _seed_user(client, email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    body = client.get("/profile").get_data(as_text=True)
    assert user["password_hash"] not in body
    assert "password_hash" not in body
    assert "pbkdf2" not in body
    assert "scrypt" not in body


def test_get_profile_uses_url_for_links_no_raw_jinja(client):
    """Links must be resolved via url_for, not leaked as raw Jinja syntax."""
    _seed_user(client, email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    body = client.get("/profile").get_data(as_text=True)
    assert 'href="{{ url_for(' not in body


def test_get_profile_404s_if_user_row_missing(client):
    """Edge case: a valid session pointing at a deleted user 404s."""
    from database import db as db_module

    _seed_user(client, email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    with client.session_transaction() as sess:
        user_id = sess["user_id"]

    with db_module.get_db() as db:
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    resp = client.get("/profile")
    assert resp.status_code == 404


def test_profile_template_has_no_hardcoded_hex_colors():
    """Spec requires CSS variables only — no hex colour values in profile.html."""
    template_path = Path(__file__).resolve().parent.parent / "templates" / "profile.html"
    content = template_path.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", content)
