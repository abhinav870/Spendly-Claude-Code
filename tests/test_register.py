import re

import pytest

from database.db import get_db, get_user_by_email

# ------------------------------------------------------------------ #
# GET /register                                                       #
# ------------------------------------------------------------------ #


def test_get_register_renders_form(client):
    """GET /register returns 200 and contains the registration form fields."""
    resp = client.get("/register")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="name"' in body
    assert 'name="email"' in body
    assert 'name="password"' in body
    assert "Create account" in body


# ------------------------------------------------------------------ #
# POST /register — happy path                                         #
# ------------------------------------------------------------------ #


def test_post_register_creates_user_and_redirects(client):
    """Valid POST inserts a user, sets session, redirects to /profile."""
    resp = client.post(
        "/register",
        data={
            "name": "Alice",
            "email": "alice@example.com",
            "password": "supersecret",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    # url_for("profile") resolves to "/profile"
    assert resp.headers["Location"].endswith("/profile")

    # DB row exists with hashed password.
    user = get_user_by_email("alice@example.com")
    assert user is not None
    assert user["name"] == "Alice"
    assert user["password_hash"] != "supersecret"

    # Session contains user_id.
    with client.session_transaction() as sess:
        assert sess["user_id"] == user["id"]


# ------------------------------------------------------------------ #
# POST /register — validation errors                                  #
# ------------------------------------------------------------------ #


def test_post_register_duplicate_email_shows_error(client):
    """A second registration with the same email re-renders with an error."""
    client.post(
        "/register",
        data={"name": "Bob", "email": "bob@x.com", "password": "longenough"},
    )
    # First registration logs the user in; clear the session so the second
    # POST is treated as an anonymous attempt to register a duplicate email.
    with client.session_transaction() as sess:
        sess.clear()
    resp = client.post(
        "/register",
        data={"name": "Bobby", "email": "bob@x.com", "password": "longenough"},
    )
    assert resp.status_code == 400
    assert "already" in resp.get_data(as_text=True).lower()

    # Only one row exists.
    with get_db() as db:
        n = db.execute(
            "SELECT COUNT(*) AS n FROM users WHERE email = %s", ("bob@x.com",)
        ).fetchone()["n"]
    assert n == 1


def test_post_register_short_password_shows_error(client):
    """Passwords shorter than 8 chars are rejected."""
    resp = client.post(
        "/register",
        data={"name": "C", "email": "c@x.com", "password": "short"},
    )
    assert resp.status_code == 400
    assert "8" in resp.get_data(as_text=True)
    assert get_user_by_email("c@x.com") is None


def test_post_register_empty_name_shows_error(client):
    """Empty name is rejected."""
    resp = client.post(
        "/register",
        data={"name": "", "email": "d@x.com", "password": "longenough"},
    )
    assert resp.status_code == 400
    assert "name" in resp.get_data(as_text=True).lower()
    assert get_user_by_email("d@x.com") is None


def test_post_register_whitespace_only_name_shows_error(client):
    """Whitespace-only name is rejected (server strips before validating)."""
    resp = client.post(
        "/register",
        data={"name": "   ", "email": "d2@x.com", "password": "longenough"},
    )
    assert resp.status_code == 400
    assert get_user_by_email("d2@x.com") is None


@pytest.mark.parametrize(
    "bad_email",
    ["not-an-email", "missing@tld", "@nope.com", "spaces in@x.com", "noatsign.com"],
)
def test_post_register_invalid_email_format_shows_error(client, bad_email):
    """Bad email shapes are rejected before any DB write."""
    resp = client.post(
        "/register",
        data={"name": "E", "email": bad_email, "password": "longenough"},
    )
    assert resp.status_code == 400, f"expected 400 for email={bad_email!r}"
    assert get_user_by_email(bad_email) is None


# ------------------------------------------------------------------ #
# POST /register — password is hashed, not stored plaintext           #
# ------------------------------------------------------------------ #


def test_post_register_password_is_hashed_not_plaintext(client):
    """The stored password_hash must not equal the submitted password."""
    client.post(
        "/register",
        data={"name": "F", "email": "f@x.com", "password": "plaintext-pw-1"},
    )
    user = get_user_by_email("f@x.com")
    assert user is not None
    assert "plaintext-pw-1" not in user["password_hash"]
    # Verify the hash is a real werkzeug hash by checking the prefix.
    assert re.match(r"^(pbkdf2|scrypt):", user["password_hash"])


# ------------------------------------------------------------------ #
# POST /register — missing fields                                     #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("missing_field", ["name", "email", "password"])
def test_post_register_missing_field_shows_error(client, missing_field):
    """Each of name/email/password is required server-side."""
    data = {"name": "G", "email": "g@x.com", "password": "longenough"}
    data.pop(missing_field)
    resp = client.post("/register", data=data)
    assert resp.status_code == 400
    assert get_user_by_email("g@x.com") is None
