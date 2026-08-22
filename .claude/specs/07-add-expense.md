# Spec: Add Expense

## Overview
This feature implements Step 7 of the Spendly roadmap: letting a logged-in
user record a new expense. It replaces the `GET /expenses/add` stub with a
real form page, and adds a `POST /expenses/add` route that validates the
submission, writes the row to the `expenses` table, and redirects back to
the profile page where the new transaction, summary stats, and category
breakdown all reflect it immediately.

## Depends on
- Step 1 — Database setup (`expenses` table exists)
- Step 3 — Login and logout (session-based auth)
- Step 4/5 — Profile page and backend routes (redirect target, `queries.py` pattern)

## Routes
- `GET /expenses/add` — renders the add-expense form — logged-in only
- `POST /expenses/add` — validates and inserts a new expense, redirects to `/profile` — logged-in only

Both methods share a single `add_expense` view (`methods=["GET", "POST"]`), matching the pattern used by `register` and `login` in `app.py`.

## Database changes
No database changes. The existing `expenses` table
(`database/db.py`) already has every column needed:
`user_id, amount, category, date, description`.

## Templates
- **Create:** `templates/add_expense.html` — form with fields: amount, category (select, from `CATEGORIES`), date, description. Extends `base.html`.
- **Modify:** None required. `profile.html` already links nowhere to add-expense yet; adding a nav/button link there is optional polish, not required for this spec's definition of done.

## Files to change
- `app.py` — replace the `add_expense` stub with the real `GET`/`POST` implementation
- `database/queries.py` — add a `create_expense(user_id, amount, category, date, description)` helper

## Files to create
- `templates/add_expense.html`
- `static/css/add_expense.css` (page-specific styles, linked via `{% block head %}`)

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders)
- All templates extend `base.html`
- Use CSS variables — never hardcode hex values
- DB logic (the INSERT) lives in `database/queries.py`, never inline in `app.py`
- Validate server-side: amount must be a positive number, category must be one of `CATEGORIES`, date must be a valid `YYYY-MM-DD` string, description is optional
- On validation failure, re-render `add_expense.html` with an `error` message and HTTP 400, preserving the user's entered values (same pattern as `register`/`login`)
- Route must redirect unauthenticated users to `/login`, matching `profile()`'s guard

## Definition of done
- [ ] Visiting `/expenses/add` while logged out redirects to `/login`
- [ ] Visiting `/expenses/add` while logged in shows a form with amount, category, date, and description fields
- [ ] Submitting a valid expense inserts a row into `expenses` for the current user and redirects to `/profile`
- [ ] The new expense appears in the profile page's recent transactions, summary stats, and category breakdown
- [ ] Submitting a negative or zero amount re-renders the form with an error and does not insert a row
- [ ] Submitting an invalid/missing category re-renders the form with an error and does not insert a row
- [ ] Submitting an invalid or missing date re-renders the form with an error and does not insert a row
- [ ] Description is optional — submitting without one succeeds
