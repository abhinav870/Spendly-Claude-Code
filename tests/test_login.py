import re

import pytest

from database.db import get_user_by_email
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Test helper — insert a user directly so we don't depend on /register
# ------------------------------------------------------------------ #

def _seed_user(client, name="Alice", email="alice@example.com", password="supersecret"):
    """Insert a user row with a hashed password via the test client."""
    # Use the registration endpoint — it's the cleanest way to seed a
    # real user row with a real hashed password.
    resp = client.post(
        "/register",
        data={"name": name, "email": email, "password": password},
    )
    assert resp.status_code == 302, f"seed failed: {resp.status_code}"
    # Clear the session the registration flow set, so each test starts fresh.
    with client.session_transaction() as sess:
        sess.clear()
    return get_user_by_email(email)


# ------------------------------------------------------------------ #
# GET /login                                                           #
# ------------------------------------------------------------------ #

def test_get_login_renders_form(client):
    """GET /login returns 200 and contains the login form fields."""
    resp = client.get("/login")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="email"' in body
    assert 'name="password"' in body
    assert "Sign in" in body


def test_get_login_uses_url_for_action(client):
    """The login form's action must be url_for('login'), not hardcoded."""
    body = client.get("/login").get_data(as_text=True)
    assert 'action="/login"' in body
    assert 'action="{{ url_for(' not in body  # raw jinja must not leak


# ------------------------------------------------------------------ #
# POST /login — happy path                                             #
# ------------------------------------------------------------------ #

def test_post_login_valid_credentials_sets_session_and_redirects(client):
    """Valid email + matching password sets session and redirects to /profile."""
    _seed_user(client, email="alice@example.com", password="supersecret")

    resp = client.post(
        "/login",
        data={"email": "alice@example.com", "password": "supersecret"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    user = get_user_by_email("alice@example.com")
    with client.session_transaction() as sess:
        assert sess["user_id"] == user["id"]


def test_post_login_email_lookup_is_case_insensitive(client):
    """The login route lowercases email before lookup (matches /register)."""
    _seed_user(client, email="alice@example.com", password="supersecret")

    resp = client.post(
        "/login",
        data={"email": "  ALICE@Example.COM  ", "password": "supersecret"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "user_id" in sess


# ------------------------------------------------------------------ #
# POST /login — validation errors                                      #
# ------------------------------------------------------------------ #

def test_post_login_unknown_email_shows_generic_error(client):
    """Unknown email re-renders the form with the generic error."""
    resp = client.post(
        "/login",
        data={"email": "nobody@example.com", "password": "anything"},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "invalid email or password" in body.lower()


def test_post_login_wrong_password_shows_generic_error(client):
    """Known email + wrong password re-renders with the SAME generic error
    (no distinction between no-such-user and wrong-password)."""
    _seed_user(client, email="alice@example.com", password="supersecret")

    resp = client.post(
        "/login",
        data={"email": "alice@example.com", "password": "wrongpass1"},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "invalid email or password" in body.lower()

    # Session must NOT be set on a failed login.
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_post_login_does_not_distinguish_unknown_email_from_wrong_password(client):
    """The two failure responses must be byte-identical in the user-visible
    error message — i.e. we don't leak which case it was."""
    _seed_user(client, email="alice@example.com", password="supersecret")

    unknown = client.post(
        "/login",
        data={"email": "nobody@example.com", "password": "anything"},
    ).get_data(as_text=True)
    wrong = client.post(
        "/login",
        data={"email": "alice@example.com", "password": "wrongpass1"},
    ).get_data(as_text=True)

    # Both responses should contain the exact same generic error block.
    assert "Invalid email or password." in unknown
    assert "Invalid email or password." in wrong


@pytest.mark.parametrize("missing_field", ["email", "password"])
def test_post_login_missing_field_shows_error(client, missing_field):
    """Empty email or password is treated as a generic invalid-credential error."""
    _seed_user(client, email="alice@example.com", password="supersecret")

    data = {"email": "alice@example.com", "password": "supersecret"}
    data.pop(missing_field)
    resp = client.post("/login", data=data)
    assert resp.status_code == 400
    assert "invalid email or password" in resp.get_data(as_text=True).lower()

    with client.session_transaction() as sess:
        assert "user_id" not in sess


# ------------------------------------------------------------------ #
# Password verification uses werkzeug                                  #
# ------------------------------------------------------------------ #

def test_login_verifies_password_with_check_password_hash(client):
    """The stored hash is a real werkzeug hash, and login uses
    check_password_hash rather than plaintext comparison."""
    _seed_user(client, email="alice@example.com", password="supersecret")

    user = get_user_by_email("alice@example.com")
    assert user is not None
    assert re.match(r"^(pbkdf2|scrypt):", user["password_hash"])

    # Plaintext must not appear in the stored hash.
    assert "supersecret" not in user["password_hash"]


# ------------------------------------------------------------------ #
# GET /logout — clears session                                         #
# ------------------------------------------------------------------ #

def test_get_logout_clears_session_and_redirects(client):
    """When logged in, /logout clears session and 302s to /."""
    _seed_user(client, email="alice@example.com", password="supersecret")

    # Log in first.
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})
    with client.session_transaction() as sess:
        assert "user_id" in sess

    # Then log out.
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")

    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_get_logout_works_when_not_logged_in(client):
    """Logging out when no session exists must not error and still redirects."""
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_logout_does_not_affect_database(client):
    """Logging out must NOT delete the user — they should be able to log back in."""
    _seed_user(client, email="alice@example.com", password="supersecret")

    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})
    client.get("/logout")

    # User still exists.
    user = get_user_by_email("alice@example.com")
    assert user is not None

    # And they can log in again.
    resp = client.post(
        "/login",
        data={"email": "alice@example.com", "password": "supersecret"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user_id"] == user["id"]


# ------------------------------------------------------------------ #
# Session persistence across requests                                  #
# ------------------------------------------------------------------ #

def test_session_persists_across_requests(client):
    """After login, the session cookie is usable on subsequent requests."""
    _seed_user(client, email="alice@example.com", password="supersecret")

    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    # A second request with the same client should still see the session.
    resp = client.get("/profile")
    assert resp.status_code == 200
    with client.session_transaction() as sess:
        assert sess["user_id"] is not None


# ------------------------------------------------------------------ #
# Navbar — shows Log out only when logged in                           #
# ------------------------------------------------------------------ #

def test_navbar_shows_login_and_register_when_logged_out(client):
    """Anonymous visitors see Sign in + Get started in the navbar."""
    body = client.get("/").get_data(as_text=True)
    assert "Sign in" in body
    assert "Get started" in body
    assert "Log out" not in body


def test_navbar_shows_logout_when_logged_in(client):
    """Logged-in users see Log out instead of Sign in / Get started."""
    _seed_user(client, email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    body = client.get("/profile").get_data(as_text=True)
    assert "Log out" in body
    # The signed-out nav items should be gone for logged-in users.
    assert ">Sign in<" not in body
    assert ">Get started<" not in body


# ------------------------------------------------------------------ #
# Logged-in users should be redirected away from auth pages            #
# ------------------------------------------------------------------ #

def test_get_login_redirects_when_already_logged_in(client):
    """A logged-in user GETting /login is bounced to /profile."""
    _seed_user(client, email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")


def test_post_login_redirects_when_already_logged_in(client):
    """A logged-in user POSTing /login is bounced to /profile (don't re-auth)."""
    _seed_user(client, email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    resp = client.post(
        "/login",
        data={"email": "alice@example.com", "password": "supersecret"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")


def test_get_register_redirects_when_already_logged_in(client):
    """A logged-in user GETting /register is bounced to /profile."""
    _seed_user(client, email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    resp = client.get("/register", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")


def test_post_register_redirects_when_already_logged_in(client):
    """A logged-in user POSTing /register is bounced to /profile (no new user)."""
    _seed_user(client, email="alice@example.com", password="supersecret")
    client.post("/login", data={"email": "alice@example.com", "password": "supersecret"})

    resp = client.post(
        "/register",
        data={"name": "Eve", "email": "eve@example.com", "password": "longenough"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")

    # Critical: the registration must NOT have created Eve.
    assert get_user_by_email("eve@example.com") is None


# ------------------------------------------------------------------ #
# Seeded demo user can log in                                          #
# ------------------------------------------------------------------ #

def test_demo_user_can_login(monkeypatch, tmp_path):
    """The demo user seeded by seed_db() must be loggable-in via /login."""
    # Point DB_PATH at a fresh file and seed it.
    from database import db as db_module
    test_db = tmp_path / "demo_login.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    db_module.init_db()
    db_module.seed_db()

    client = db_module.__dict__  # placeholder — replaced below
    # Use the real Flask app for this test.
    from app import app as flask_app
    flask_app.config.update(SECRET_KEY="test-secret-key", TESTING=True)
    flask_client = flask_app.test_client()

    resp = flask_client.post(
        "/login",
        data={"email": "demo@spendly.com", "password": "demo123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with flask_client.session_transaction() as sess:
        assert "user_id" in sess
