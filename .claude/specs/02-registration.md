# Spec: Registration

## Overview
This feature implements the full registration flow for Spendly. The existing `/register` route only renders a static form; this step turns it into a real, working endpoint that accepts form submissions, validates input, hashes passwords with `werkzeug`, persists new users to the `users` table, signs them in immediately, and redirects them into the app. It is the first step in the authentication story and unlocks login (Step 3), profile (Step 4), and all expense routes that require a logged-in user.

## Depends on
- **Step 1 — Database setup**: the `users` table, `get_db()`, `init_db()`, and `werkzeug.security.generate_password_hash` must already be in place.

## Routes
- `POST /register` — accepts form data (name, email, password), validates and inserts a new user, signs the user in via session, then redirects to `/`. Public.
- `GET /register` — already exists; update to surface server-side error messages (e.g. duplicate email) on re-render. Public.

If no new routes: N/A (the existing GET route is updated, and the POST is added.)

## Database changes
No database changes. The `users` table is already defined in `database/db.py` with `email` (UNIQUE), `password_hash`, `name`, and `created_at` columns — this step only writes to it.

## Templates
- **Modify:** `templates/register.html`
  - Replace the hardcoded `action="/register"` with `url_for('register')` (or keep it since it is identical, but prefer `url_for`).
  - Read the flashed/error message from the context instead of relying on a hard-coded `error` variable if Flask's `flash` is used; otherwise pass an `error` string from the route.

## Files to change
- `app.py` — convert `/register` to accept both `GET` and `POST`; on POST, validate input, hash the password, insert into `users`, log the user in, and redirect to `/`. Add a new helper or session key (e.g. `session["user_id"]`) for "logged in" state.

## Files to create
- None.

## New dependencies
No new dependencies. Uses `werkzeug.security.generate_password_hash` and `flask.session` (both already available via Flask and the existing `requirements.txt`).

## Rules for implementation
- No SQLAlchemy or ORMs — keep raw `sqlite3` via `database/db.py`.
- All DB logic goes in `database/db.py`; route stays single-responsibility (collect input, call helper, render/redirect).
- Use **parameterized queries only** (the `?` placeholder) when inserting into `users`.
- Hash passwords with `werkzeug.security.generate_password_hash` — never store plaintext.
- Use CSS variables for any styling tweaks — never hardcode hex values in templates or new CSS.
- All templates extend `base.html`.
- Use `url_for()` for every internal link.
- Use `abort()` for HTTP errors, not bare string returns.
- Validate server-side: name not empty, email matches a basic pattern and is not already registered, password length >= 8.
- On successful registration, set `session["user_id"]` to the new user's id and redirect to `url_for("landing")` (or `/dashboard` once it exists — for now, `landing` is fine).
- On duplicate email, re-render `register.html` with a clear error message rather than crashing.
- Do not implement `/login` or `/logout` here — that is Step 3. Only the registration flow.

## Definition of done
- [ ] `GET /register` still renders `register.html` with no errors.
- [ ] `POST /register` with valid name, unique email, and password >= 8 chars creates a row in `users` with a hashed password.
- [ ] After successful registration, the user is redirected to `/` (landing) and `session["user_id"]` is set.
- [ ] `POST /register` with an already-used email re-renders the form with an error message and does **not** create a row.
- [ ] `POST /register` with a password shorter than 8 chars re-renders the form with a validation error.
- [ ] `POST /register` with an empty name re-renders the form with a validation error.
- [ ] Passwords are stored as `werkzeug` hashes — no plaintext appears in `spendly.db`.
- [ ] All SQL uses `?` placeholders — no f-strings in queries.
- [ ] DB logic lives in `database/db.py`, not in the route function.
- [ ] App still starts cleanly on port 5001 with no unhandled exceptions.
- [ ] No new pip packages were added.
