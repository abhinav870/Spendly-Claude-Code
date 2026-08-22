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


def get_month_options():
    """Return filter dropdown options from the current month back through
    January of the current year, newest first, with "Overall" prepended.

    Each option is {"value": "" | "YYYY-MM", "label": "Overall" | "Mon-YY"}.
    """
    today = date.today()
    options = [{"value": "", "label": "Overall"}]
    for month in range(today.month, 0, -1):
        month_date = date(today.year, month, 1)
        options.append({
            "value": month_date.strftime("%Y-%m"),
            "label": month_date.strftime("%b-%y"),
        })
    return options


def get_summary_stats(user_id, month=None, category=None):
    """Return total_spent, transaction_count, top_category for a user,
    optionally restricted to a "YYYY-MM" month and/or a category."""
    with get_db() as conn:
        totals = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total_spent,
                   COUNT(*)                 AS transaction_count
            FROM expenses
            WHERE user_id = ?
              AND (? IS NULL OR strftime('%Y-%m', date) = ?)
              AND (? IS NULL OR category = ?)
            """,
            (user_id, month, month, category, category),
        ).fetchone()

        top = conn.execute(
            """
            SELECT category, SUM(amount) AS cat_total
            FROM expenses
            WHERE user_id = ?
              AND (? IS NULL OR strftime('%Y-%m', date) = ?)
              AND (? IS NULL OR category = ?)
            GROUP BY category
            ORDER BY cat_total DESC
            LIMIT 1
            """,
            (user_id, month, month, category, category),
        ).fetchone()

    if totals["transaction_count"] == 0:
        return {"total_spent": 0, "transaction_count": 0, "top_category": "—"}

    return {
        "total_spent": totals["total_spent"],
        "transaction_count": totals["transaction_count"],
        "top_category": top["category"],
    }


def get_recent_transactions(user_id, limit=None, month=None, category=None):
    """Return up to `limit` most recent expenses, newest-first, optionally
    restricted to a "YYYY-MM" month and/or a category. `limit=None` returns
    every matching expense."""
    sql_limit = -1 if limit is None else limit
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT date, description, category, amount
            FROM expenses
            WHERE user_id = ?
              AND (? IS NULL OR strftime('%Y-%m', date) = ?)
              AND (? IS NULL OR category = ?)
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (user_id, month, month, category, category, sql_limit),
        ).fetchall()

    return [
        {
            "date": row["date"],
            "description": row["description"],
            "category": row["category"],
            "amount": row["amount"],
        }
        for row in rows
    ]


def get_category_breakdown(user_id, month=None, category=None):
    """Return per-category totals + integer pct (summing to exactly 100),
    ordered by amount desc. Empty list if the user has no expenses.
    Optionally restricted to a "YYYY-MM" month and/or a category."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT category, SUM(amount) AS amount
            FROM expenses
            WHERE user_id = ?
              AND (? IS NULL OR strftime('%Y-%m', date) = ?)
              AND (? IS NULL OR category = ?)
            GROUP BY category
            ORDER BY amount DESC
            """,
            (user_id, month, month, category, category),
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
