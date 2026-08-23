import os
import re
from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash

# ------------------------------------------------------------------ #
# Validation constants                                                #
# ------------------------------------------------------------------ #

# Lightweight email pattern — enough to catch the obvious malformed
# addresses. The DB's UNIQUE constraint is the real duplicate check.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8


# ------------------------------------------------------------------ #
# Database location                                                   #
# ------------------------------------------------------------------ #

# Render (and most Postgres hosts) inject DATABASE_URL. Fall back to a
# local dev database so the app boots out of the box.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/spendly"
)


# ------------------------------------------------------------------ #
# Connection helper                                                   #
# ------------------------------------------------------------------ #


def get_db():
    """Open a Postgres connection with dict-style row access.

    FK enforcement is on by default in Postgres (unlike SQLite), so no
    per-connection PRAGMA is needed.
    """

    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


# ------------------------------------------------------------------ #
# User helpers                                                        #
# ------------------------------------------------------------------ #


def create_user(name, email, password):
    """Insert a new user and return the new row id.

    Raises psycopg.errors.UniqueViolation if `email` already exists.
    Caller is responsible for catching it and surfacing a user-facing error.
    """
    with get_db() as db:
        cur = db.execute(
            """
            INSERT INTO users (name, email, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (name, email, generate_password_hash(password)),
        )
        return cur.fetchone()["id"]


def get_user_by_email(email):
    """Return the user row for `email`, or None if no match."""

    with get_db() as db:
        return db.execute(
            """
            SELECT id, name, email, password_hash, created_at
            FROM users
            WHERE email = %s
            """,
            (email,),
        ).fetchone()


def get_user_by_id(user_id):
    """Return the user row for `user_id`, or None if no match."""

    with get_db() as db:
        return db.execute(
            """
            SELECT id, name, email, password_hash, created_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        ).fetchone()


# ------------------------------------------------------------------ #
# Schema                                                              #
# ------------------------------------------------------------------ #


def init_db():
    """Create all tables if they don't already exist."""

    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                name          TEXT      NOT NULL,
                email         TEXT      NOT NULL UNIQUE,
                password_hash TEXT      NOT NULL,
                created_at    TIMESTAMP NOT NULL DEFAULT now()
            )
            """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER   NOT NULL REFERENCES users(id),
                amount      REAL      NOT NULL,
                category    TEXT      NOT NULL,
                date        TEXT      NOT NULL,
                description TEXT,
                created_at  TIMESTAMP NOT NULL DEFAULT now()
            )
            """)


# ------------------------------------------------------------------ #
# Seed data                                                           #
# ------------------------------------------------------------------ #

# Fixed list of categories (spec §10)
CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]

# (category, description, amount) — 8 rows covering all 7 categories,
# with an extra Food entry so Food appears twice.
SAMPLE_EXPENSES = [
    ("Food", "Groceries", 455),
    ("Transport", "Metro pass", 300),
    ("Bills", "Electricity", 7520),
    ("Health", "Pharmacy", 2200),
    ("Entertainment", "Movie ticket", 1250),
    ("Shopping", "New shirt", 3500),
    ("Other", "Gift", 1800),
    ("Food", "Restaurant", 2875),
]

# Day-of-month offsets to spread the 8 expenses across the current month.
SAMPLE_DAYS = [1, 5, 8, 12, 15, 19, 22, 26]


def _date_in_current_month(day):
    """Return YYYY-MM-DD for `day` in the current month, clamping to the
    last day if `day` exceeds the month's length (e.g. 31 in February)."""
    today = date.today()

    try:
        return today.replace(day=day).isoformat()
    except ValueError:
        # Last day of current month: jump to day 28, add a day, walk back.
        next_month_first = (today.replace(day=28) + timedelta(days=1)).replace(day=1)
        last_day = (next_month_first - timedelta(days=1)).day
        return today.replace(day=last_day).isoformat()


def seed_db():
    """Insert demo user + 8 sample expenses. Safe to call repeatedly."""
    with get_db() as conn:

        # Idempotency guard — don't duplicate data on subsequent runs.
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        if row["n"] > 0:
            return

        # 1. Demo user
        user_id = conn.execute(
            """
            INSERT INTO users (name, email, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
        ).fetchone()["id"]

        # 2. Sample expenses (linked to demo user)
        for (category, description, amount), day in zip(SAMPLE_EXPENSES, SAMPLE_DAYS):
            conn.execute(
                """
                INSERT INTO expenses (user_id, amount, category, date, description)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, amount, category, _date_in_current_month(day), description),
            )
