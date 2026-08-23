from datetime import date, datetime

from database.db import get_db


def get_user_by_id(user_id):
    """Return a template-shaped dict for the profile header, or None."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        return None

    created_at = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
    member_since = created_at.strftime("%B %Y")  # e.g. "January 2026"

    return {
        "name": row["name"],
        "email": row["email"],
        "member_since": member_since,
    }


def get_summary_stats(user_id, category=None, date_from=None, date_to=None):
    """Return total_spent, transaction_count, top_category for a user,
    optionally restricted to a category and/or a date range (inclusive)."""
    with get_db() as conn:
        totals = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total_spent,
                   COUNT(*)                 AS transaction_count
            FROM expenses
            WHERE user_id = ?
              AND (? IS NULL OR category = ?)
              AND (? IS NULL OR date >= ?)
              AND (? IS NULL OR date <= ?)
            """,
            (user_id, category, category, date_from, date_from, date_to, date_to),
        ).fetchone()

        top = conn.execute(
            """
            SELECT category, SUM(amount) AS cat_total
            FROM expenses
            WHERE user_id = ?
              AND (? IS NULL OR category = ?)
              AND (? IS NULL OR date >= ?)
              AND (? IS NULL OR date <= ?)
            GROUP BY category
            ORDER BY cat_total DESC
            LIMIT 1
            """,
            (user_id, category, category, date_from, date_from, date_to, date_to),
        ).fetchone()

    if totals["transaction_count"] == 0:
        return {"total_spent": 0, "transaction_count": 0, "top_category": "—"}

    return {
        "total_spent": totals["total_spent"],
        "transaction_count": totals["transaction_count"],
        "top_category": top["category"],
    }


def get_recent_transactions(
    user_id, limit=None, category=None, date_from=None, date_to=None
):
    """Return up to `limit` most recent expenses, newest-first, optionally
    restricted to a category and/or a date range (inclusive). `limit=None`
    returns every matching expense."""
    sql_limit = -1 if limit is None else limit
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, date, description, category, amount
            FROM expenses
            WHERE user_id = ?
              AND (? IS NULL OR category = ?)
              AND (? IS NULL OR date >= ?)
              AND (? IS NULL OR date <= ?)
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (
                user_id,
                category,
                category,
                date_from,
                date_from,
                date_to,
                date_to,
                sql_limit,
            ),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "date": row["date"],
            "description": row["description"],
            "category": row["category"],
            "amount": row["amount"],
        }
        for row in rows
    ]


def get_category_breakdown(user_id, category=None, date_from=None, date_to=None):
    """Return per-category totals + integer pct (summing to exactly 100),
    ordered by amount desc. Empty list if the user has no expenses.
    Optionally restricted to a category and/or a date range (inclusive)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT category, SUM(amount) AS amount
            FROM expenses
            WHERE user_id = ?
              AND (? IS NULL OR category = ?)
              AND (? IS NULL OR date >= ?)
              AND (? IS NULL OR date <= ?)
            GROUP BY category
            ORDER BY amount DESC
            """,
            (user_id, category, category, date_from, date_from, date_to, date_to),
        ).fetchall()

    if not rows:
        return []

    grand_total = sum(row["amount"] for row in rows)

    breakdown = []
    running_pct = 0
    for row in rows:
        raw_pct = (row["amount"] / grand_total) * 100
        pct = int(round(raw_pct))
        breakdown.append({"name": row["category"], "amount": row["amount"], "pct": pct})
        running_pct += pct

    remainder = 100 - running_pct
    breakdown[0]["pct"] += remainder

    return breakdown


def create_expense(user_id, amount, category, expense_date, description=None):
    """Insert a new expense and return the new row id."""
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO expenses (user_id, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, amount, category, expense_date, description),
        )
        return cur.lastrowid


def get_expense_by_id(expense_id, user_id):
    """Return a template-shaped dict for a single expense owned by user_id, or None."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id, amount, category, date, description
            FROM expenses
            WHERE id = ? AND user_id = ?
            """,
            (expense_id, user_id),
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row["id"],
        "amount": row["amount"],
        "category": row["category"],
        "date": row["date"],
        "description": row["description"],
    }


def update_expense(
    expense_id, user_id, amount, category, expense_date, description=None
):
    """Update an expense owned by user_id. Ownership is enforced in the WHERE clause."""
    with get_db() as conn:
        cur = conn.execute(
            """
            UPDATE expenses
            SET amount = ?, category = ?, date = ?, description = ?
            WHERE id = ? AND user_id = ?
            """,
            (amount, category, expense_date, description, expense_id, user_id),
        )
        return cur.rowcount > 0


def delete_expense(expense_id, user_id):
    """Delete an expense owned by user_id. Ownership is enforced in the WHERE clause."""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
        return cur.rowcount > 0
