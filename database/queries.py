from datetime import datetime

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


def get_summary_stats(user_id):
    """Return total_spent, transaction_count, top_category for a user."""
    with get_db() as conn:
        totals = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total_spent,
                   COUNT(*)                 AS transaction_count
            FROM expenses
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

        top = conn.execute(
            """
            SELECT category, SUM(amount) AS cat_total
            FROM expenses
            WHERE user_id = ?
            GROUP BY category
            ORDER BY cat_total DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

    if totals["transaction_count"] == 0:
        return {"total_spent": 0, "transaction_count": 0, "top_category": "—"}

    return {
        "total_spent": totals["total_spent"],
        "transaction_count": totals["transaction_count"],
        "top_category": top["category"],
    }


def get_recent_transactions(user_id, limit=10):
    """Return up to `limit` most recent expenses, newest-first."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT date, description, category, amount
            FROM expenses
            WHERE user_id = ?
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
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


def get_category_breakdown(user_id):
    """Return per-category totals + integer pct (summing to exactly 100),
    ordered by amount desc. Empty list if the user has no expenses."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT category, SUM(amount) AS amount
            FROM expenses
            WHERE user_id = ?
            GROUP BY category
            ORDER BY amount DESC
            """,
            (user_id,),
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
