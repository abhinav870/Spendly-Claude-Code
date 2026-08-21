import os
import sqlite3

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database.db import EMAIL_RE, MIN_PASSWORD_LEN, create_user, get_user_by_email, get_user_by_id, init_db, seed_db
from database import queries

app = Flask(__name__)

# Sessions are signed with this key. Read from env in production; fall
# back to a clearly-flagged dev value so the app boots out of the box.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    # Already logged in? Send them to their profile instead of the marketing page.
    if session.get("user_id"):
        return redirect(url_for("profile"))
    return render_template("landing.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    # Already logged in? Don't show another registration form.
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        # Validate cheapest first so the user sees the most relevant error.
        if not name:
            return render_template("register.html", error="Name is required."), 400
        if not email or not EMAIL_RE.fullmatch(email):
            return (
                render_template("register.html", error="Please enter a valid email address."),
                400,
            )
        if len(password) < MIN_PASSWORD_LEN:
            return (
                render_template(
                    "register.html",
                    error=f"Password must be at least {MIN_PASSWORD_LEN} characters.",
                ),
                400,
            )

        # The UNIQUE constraint on users.email is the duplicate check;
        # let it surface as an IntegrityError we map to a friendly error.
        try:
            user_id = create_user(name, email, password)
        except sqlite3.IntegrityError:
            return (
                render_template("register.html", error="That email is already registered."),
                400,
            )

        session["user_id"] = user_id
        return redirect(url_for("profile"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    # Already logged in? Skip the login form entirely.
    if session.get("user_id"):
        return redirect(url_for("profile"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        # Use the same generic message for "no such user" and "wrong
        # password" so we don't leak which email addresses exist.
        user = get_user_by_email(email) if email else None

        if user is None or not check_password_hash(user["password_hash"], password):
            return (
                render_template(
                    "login.html",
                    error="Invalid email or password.",
                ),
                400,
            )

        session["user_id"] = user["id"]
        return redirect(url_for("profile"))

    return render_template("login.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.clear()
    return redirect(url_for("landing"))

@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if get_user_by_id(user_id) is None:
        abort(404)

    user = queries.get_user_by_id(user_id)
    summary = queries.get_summary_stats(user_id)
    transactions = queries.get_recent_transactions(user_id)
    categories = queries.get_category_breakdown(user_id)

    return render_template(
        "profile.html",
        user=user,
        summary=summary,
        transactions=transactions,
        categories=categories,
    )

# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"

@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"

@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"

if __name__ == "__main__":
    # with app.app_context():
    init_db()
    seed_db()
    app.run(debug=True, port=5001)
