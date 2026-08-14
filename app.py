import os
import sqlite3

from flask import Flask, abort, redirect, render_template, request, session, url_for

from database.db import (
    EMAIL_RE,
    MIN_PASSWORD_LEN,
    create_user,
    get_user_by_email,
    init_db,
    seed_db,
)

app = Flask(__name__)

# Sessions are signed with this key. Read from env in production; fall
# back to a clearly-flagged dev value so the app boots out of the box.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
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
        return redirect(url_for("landing"))

    return render_template("register.html")


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    return "Logout — coming in Step 3"


@app.route("/profile")
def profile():
    return "Profile page — coming in Step 4"


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
    with app.app_context():
        init_db()
        seed_db()
    app.run(debug=True, port=5001)
