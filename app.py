import calendar
import math
import os
import sqlite3
from datetime import date, datetime

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from database.db import (
    CATEGORIES,
    EMAIL_RE,
    MIN_PASSWORD_LEN,
    create_user,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
)
from database import queries

app = Flask(__name__)

# Sessions are signed with this key. Read from env in production; fall
# back to a clearly-flagged dev value so the app boots out of the box.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# ------------------------------------------------------------------ #
# Date filter helpers                                                 #
# ------------------------------------------------------------------ #


def _parse_iso_date(value):
    """Parse a "YYYY-MM-DD" string into a date, or None if absent/malformed."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _months_ago_start(today, n):
    """First day of the month n months before (inclusive) today's month.
    e.g. n=3 on 2026-08-22 -> 2026-06-01 (Jun, Jul, Aug = 3 months)."""
    month_index = today.month - 1 - (n - 1)
    year = today.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


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
                render_template(
                    "register.html", error="Please enter a valid email address."
                ),
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
                render_template(
                    "register.html", error="That email is already registered."
                ),
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

    selected_category = request.args.get("category") or None

    raw_from = _parse_iso_date(request.args.get("date_from"))
    raw_to = _parse_iso_date(request.args.get("date_to"))

    if raw_from and raw_to and raw_from > raw_to:
        flash("Start date must be before end date.", "error")
        date_from = date_to = None
    else:
        date_from, date_to = raw_from, raw_to

    date_from_str = date_from.isoformat() if date_from else None
    date_to_str = date_to.isoformat() if date_to else None

    today = date.today()
    month_end = date(
        today.year, today.month, calendar.monthrange(today.year, today.month)[1]
    )
    presets = {
        "this_month": {
            "date_from": date(today.year, today.month, 1).isoformat(),
            "date_to": month_end.isoformat(),
        },
        "last_3_months": {
            "date_from": _months_ago_start(today, 3).isoformat(),
            "date_to": today.isoformat(),
        },
        "last_6_months": {
            "date_from": _months_ago_start(today, 6).isoformat(),
            "date_to": today.isoformat(),
        },
        "all_time": {"date_from": None, "date_to": None},
    }

    if date_from_str is None and date_to_str is None:
        active_preset = "all_time"
    else:
        active_preset = next(
            (
                name
                for name, r in presets.items()
                if r["date_from"] == date_from_str and r["date_to"] == date_to_str
            ),
            None,
        )

    user = queries.get_user_by_id(user_id)
    summary = queries.get_summary_stats(
        user_id,
        category=selected_category,
        date_from=date_from_str,
        date_to=date_to_str,
    )
    transactions = queries.get_recent_transactions(
        user_id,
        category=selected_category,
        date_from=date_from_str,
        date_to=date_to_str,
    )
    categories = queries.get_category_breakdown(
        user_id,
        category=selected_category,
        date_from=date_from_str,
        date_to=date_to_str,
    )

    return render_template(
        "profile.html",
        user=user,
        summary=summary,
        transactions=transactions,
        categories=categories,
        category_options=CATEGORIES,
        selected_category=selected_category or "",
        selected_date_from=date_from_str or "",
        selected_date_to=date_to_str or "",
        active_preset=active_preset,
        presets=presets,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if get_user_by_id(user_id) is None:
        abort(404)

    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]

    if request.method == "POST":
        amount_raw = (request.form.get("amount") or "").strip()
        category = (request.form.get("category") or "").strip()
        date_raw = (request.form.get("date") or "").strip()
        description = (request.form.get("description") or "").strip() or None

        form_values = {
            "amount": amount_raw,
            "category": category,
            "date": date_raw,
            "description": description or "",
        }

        # Validate cheapest first so the user sees the most relevant error.
        try:
            amount = float(amount_raw)
            if not math.isfinite(amount):
                amount = None
        except ValueError:
            amount = None

        if amount is None or amount <= 0:
            return (
                render_template(
                    "add_expense.html",
                    error="Amount must be a positive number.",
                    category_options=CATEGORIES,
                    **form_values,
                ),
                400,
            )

        if category not in CATEGORIES:
            return (
                render_template(
                    "add_expense.html",
                    error="Please choose a valid category.",
                    category_options=CATEGORIES,
                    **form_values,
                ),
                400,
            )

        expense_date = _parse_iso_date(date_raw)
        if expense_date is None:
            return (
                render_template(
                    "add_expense.html",
                    error="Please enter a valid date.",
                    category_options=CATEGORIES,
                    **form_values,
                ),
                400,
            )

        queries.create_expense(
            user_id, amount, category, expense_date.isoformat(), description
        )
        return redirect(url_for("profile"))

    return render_template(
        "add_expense.html",
        category_options=CATEGORIES,
        amount="",
        category="",
        date=date.today().isoformat(),
        description="",
    )


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]

    expense = queries.get_expense_by_id(id, user_id)
    if expense is None:
        abort(404)

    if request.method == "POST":
        amount_raw = (request.form.get("amount") or "").strip()
        category = (request.form.get("category") or "").strip()
        date_raw = (request.form.get("date") or "").strip()
        description = (request.form.get("description") or "").strip() or None

        form_values = {
            "amount": amount_raw,
            "category": category,
            "date": date_raw,
            "description": description or "",
        }

        # Validate cheapest first so the user sees the most relevant error.
        try:
            amount = float(amount_raw)
            if not math.isfinite(amount):
                amount = None
        except ValueError:
            amount = None

        if amount is None or amount <= 0:
            return (
                render_template(
                    "edit_expense.html",
                    expense=expense,
                    error="Amount must be a positive number.",
                    category_options=CATEGORIES,
                    **form_values,
                ),
                400,
            )

        if category not in CATEGORIES:
            return (
                render_template(
                    "edit_expense.html",
                    expense=expense,
                    error="Please choose a valid category.",
                    category_options=CATEGORIES,
                    **form_values,
                ),
                400,
            )

        expense_date = _parse_iso_date(date_raw)
        if expense_date is None:
            return (
                render_template(
                    "edit_expense.html",
                    expense=expense,
                    error="Please enter a valid date.",
                    category_options=CATEGORIES,
                    **form_values,
                ),
                400,
            )

        queries.update_expense(
            id, user_id, amount, category, expense_date.isoformat(), description
        )
        return redirect(url_for("profile"))

    return render_template(
        "edit_expense.html",
        expense=expense,
        category_options=CATEGORIES,
        amount=expense["amount"],
        category=expense["category"],
        date=expense["date"],
        description=expense["description"] or "",
    )


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    # with app.app_context():
    init_db()
    seed_db()
    app.run(debug=True, port=5001)
