# Spec: Login and Logout

## Overview
This feature completes the authentication loop for Spendly. After registration (Step 2) creates an account and signs the user in immediately, this step adds the full **login** flow — accepting an email and password, verifying the hash with `werkzeug`, and starting a session — and the **logout** flow that clears `session["user_id"]` and returns the user to the landing page. It is the foundation that every later step (profile, add/edit/delete expense) relies on to know *who* is making the request.

## Depends on
- **Step 1 — Database setup**: the `users` table, `get_db()`, and `werkzeug.security.check_password_hash` must be in place.
- **Step 2 — Registration**: the `create_user()` and `get_user_by_email()` helpers and the `session["user_id"]` convention must exist; this step reuses them.

## Routes
- `POST /login` — accepts form data (email, password), looks up the user by email, verifies the password hash, signs the user in via `session["user_id"]`, then redirects to `/`. Public.
- `GET /login` — already exists (currently a stub rendering `login.html`); keep rendering the form, and on re-render after a failed POST show the error message. Public.
- `GET /logout` — currently a stub returning a raw string; replace it with a real route that clears the session and redirects to `url_for("landing")`. Public (must work even if the user is not logged in — in that case, still clear and redirect, no error).

## Database changes
No database changes. `users` already stores `password_hash`; this step only **reads** it.

## Templates
- **Modify:** `templates/login.html`
  - Read any flashed/error message from context so server-side validation errors are surfaced on re-render.
  - Confirm the form `action` uses `url_for('login')` (or matches — prefer `url_for`).
  - Confirm `base.html` is extended and any links (e.g. "Forgot password", "Register") use `url_for`.

No template changes needed for `logout` — it is a redirect-only route.

## Files to change
- `app.py`
  - Convert `/login` to accept both `GET` and `POST`. On POST: read `email` and `password`, look up the user via `get_user_by_email()`, verify with `check_password_hash`, set `session["user_id"]` on success, re-render with a generic "Invalid email or password." error on failure. Never reveal whether the email exists vs. the password being wrong.
  - Replace the stub `/logout` route with one that pops `session["user_id"]`, calls `session.clear()` (or equivalent), and returns `redirect(url_for("landing"))`.

## Files to create
- None.

## New dependencies
No new dependencies. Uses `werkzeug.security.check_password_hash` (already in `requirements.txt`) and `flask.session` (already imported).

## Rules for implementation
- No SQLAlchemy or ORMs — keep raw `sqlite3` via `database/db.py`.
- All DB logic stays in `database/db.py`; the `/login` route is single-responsibility (collect input → call helper → render/redirect).
- Use **parameterized queries only** (`?` placeholders) when reading from `users`.
- Verify passwords with `werkzeug.security.check_password_hash` — never compare plaintext, never use `==` on the stored hash.
- Do **not** introduce a new `verify_password(email, password)` helper in `database/db.py` unless it materially helps; the existing `get_user_by_email()` + `check_password_hash` pair is enough.
- Use CSS variables for any styling tweaks — never hardcode hex values in templates or new CSS.
- All templates extend `base.html`.
- Use `url_for()` for every internal link and form action.
- Use `abort()` for HTTP errors, not bare string returns.
- On login success, set `session["user_id"]` and redirect to `url_for("landing")` (same convention as registration).
- On login failure, re-render `login.html` with a **generic** error message such as "Invalid email or password." — do not disclose whether the email exists or the password is wrong.
- On logout, clear `session` (e.g. `session.clear()` or pop `user_id`) and redirect to `url_for("landing")` with HTTP 302. Do not require the user to be logged in — if they aren't, simply clear and redirect anyway.
- Validation order on `/login` POST: trim and lower-case the email, treat empty fields as a generic invalid-credential error (don't leak which field is wrong).
- Do not implement `/profile`, `/expenses/add`, or any protected page here — those come in later steps. This step only authenticates.
- Do not add "remember me", password reset, rate limiting, or account lockout — out of scope for the tutorial.

## Definition of done
- [ ] `GET /login` renders `login.html` with no errors.
- [ ] `POST /login` with a valid email and matching password sets `session["user_id"]` and redirects to `/`.
- [ ] `POST /login` with an unknown email re-renders the form with the generic "Invalid email or password." message and does **not** set `session["user_id"]`.
- [ ] `POST /login` with a known email but a wrong password re-renders the form with the **same** generic error (no distinction between "no such user" and "wrong password").
- [ ] `POST /login` with empty email or empty password re-renders the form with the generic error.
- [ ] `GET /logout` clears `session["user_id"]` and redirects (302) to `/`.
- [ ] `GET /logout` works even when no user is logged in — it does not error and still redirects to `/`.
- [ ] After login, refreshing `/` keeps the user logged in (session persists across requests within the same browser session).
- [ ] Password verification uses `check_password_hash` — no plaintext comparison anywhere.
- [ ] All SQL uses `?` placeholders — no f-strings in queries.
- [ ] DB lookup (`get_user_by_email`) is called from the route; no inline SQL in `app.py`.
- [ ] All internal links and form actions in `login.html` use `url_for()`.
- [ ] App still starts cleanly on port 5001 with no unhandled exceptions.
- [ ] No new pip packages were added.
- [ ] The demo user `demo@spendly.com` / `demo123` (seeded in Step 1) can log in successfully via the new `/login` form.
