import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash


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

# Resolve project root: this file lives in <root>/database/db.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "spendly.db"


# ------------------------------------------------------------------ #
# Connection helper                                                   #
# ------------------------------------------------------------------ #

def get_db():
    """Open a SQLite connection with Row access and FK enforcement."""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # FK enforcement is per-connection in SQLite; must be set every time.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ------------------------------------------------------------------ #
# User helpers                                                        #
# ------------------------------------------------------------------ #

def create_user(name, email, password):
    """Insert a new user and return the new row id.

    Raises sqlite3.IntegrityError if `email` already exists.
    Caller is responsible for catching it and surfacing a user-facing error.
    """
    db = get_db()
    cur = db.execute(
        """
        INSERT INTO users (name, email, password_hash)
        VALUES (?, ?, ?)
        """,
        (name, email, generate_password_hash(password)),
    )
    db.commit()
    return cur.lastrowid


def get_user_by_email(email):
    """Return the user row for `email`, or None if no match."""
    return get_db().execute(
        """
        SELECT id, name, email, password_hash, created_at
        FROM users
        WHERE email = ?
        """,
        (email,),
    ).fetchone()


def get_user_by_id(user_id):
    """Return the user row for `user_id`, or None if no match."""
    return get_db().execute(
        """
        SELECT id, name, email, password_hash, created_at
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()


# ------------------------------------------------------------------ #
# Schema                                                              #
# ------------------------------------------------------------------ #

def init_db():
    """Create all tables if they don't already exist."""
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
        """
    )
    db.commit()


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
    ("Food",          "Groceries",     455),
    ("Transport",     "Metro pass",    300),
    ("Bills",         "Electricity",   7520),
    ("Health",        "Pharmacy",      2200),
    ("Entertainment", "Movie ticket",  1250),
    ("Shopping",      "New shirt",     3500),
    ("Other",         "Gift",          1800),
    ("Food",          "Restaurant",    2875),
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
    conn = get_db()

    # Idempotency guard — don't duplicate data on subsequent runs.
    row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    if row["n"] > 0:
        return

    # 1. Demo user
    conn.execute(
        """
        INSERT INTO users (name, email, password_hash)
        VALUES (?, ?, ?)
        """,
        ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
    )

    user_id = conn.execute("SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)).fetchone()["id"]

    # 2. Sample expenses (linked to demo user)
    for (category, description, amount), day in zip(SAMPLE_EXPENSES, SAMPLE_DAYS):
        conn.execute(
            """
            INSERT INTO expenses (user_id, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, amount, category, _date_in_current_month(day), description),
        )

    conn.commit()
