# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Spendly** is a lightweight personal expense tracker built with Flask and SQLite.

## Architecture

expense-tracker/
├── app.py              # All routes — single file, no blueprints
├── database/
│   └── db.py           # Postgres helpers: get_db(), init_db(), seed_db()
├── templates/
│   ├── base.html       # Shared layout — all templates must extend this
│   └── *.html          # One template per page
├── static/
│   ├── css/
│   │   ├── style.css       # Global styles
│   │   └── landing.css     # Landing-page-only styles
│   └── js/
│       └── main.js         # Vanilla JS only
├── docker/
│   ├── Dockerfile          # App image — also used for Render's Docker deploy
│   └── docker-compose.yml  # Local dev: app + Postgres (context: repo root)
└── requirements.txt

**Where things belong:**

 - New routes → app.py only, no blueprints
 - DB logic → database/db.py only, never inline in routes
 - New pages → new .html file extending base.html
 - Page-specific styles → new .css file, not inline <style> tags

## Code style
 - Python: PEP 8, snake_case for all variables and functions
 - Templates: Jinja2 with url_for() for every internal link — never hardcode URLs
 - Route functions: one responsibility only — fetch data, render template, done
 - DB queries: always use parameterized queries (%s placeholders) — never f-strings in SQL
 - Error handling: use abort() for HTTP errors, not bare return "error string"

## Tech constraints

 - Flask only — no FastAPI, no Django, no other web frameworks
 - PostgreSQL only — migrated from SQLite so data survives Render spin-downs; no SQLAlchemy ORM, connect via psycopg (psycopg[binary] in requirements.txt)
 - Vanilla JS only — no React, no jQuery, no npm packages
 - No new pip packages — work within requirements.txt as-is unless explicitly told otherwise
 - Python 3.10+ assumed — f-strings and match statements are fine

## Subagent Policy
 - Always use a builtin explore subagent for codebase exploration before implementing any new feature
 - Always use a subagent to verify test results after any implementation
 - When asked to plan, delegate codebase research to a subagent before presenting the plan
   always use a builtin plan subagent in plan mode

### Creating new subagents
 - Whenever creating a new subagent (`.claude/agents/*.md`), always ask the user for these details before writing the file — do not assume defaults: tools, model, memory access, description, system prompt content, and color
 - Only write the agent file once these are answered, or the user explicitly says to use defaults

## Commands

# Setup
python -m venv venv
MacOS: source venv/bin/activate   
Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run dev server (port 5001) — requires a reachable Postgres (see Docker below)
python app.py

# Run app + Postgres locally via Docker (recommended)
docker compose -f docker/docker-compose.yml up -d --build
# App: http://localhost:5001 — Postgres: localhost:5432 (postgres/postgres/spendly)
docker compose -f docker/docker-compose.yml down          # stop, keep data
docker compose -f docker/docker-compose.yml down -v       # stop, wipe data

# Run all tests
pytest

# Run a specific test file
pytest tests/test_foo.py

# Run a specific test by name
pytest -k "test_name"

# Run tests with output visible
pytest -s

## Implemented vs stub routes
Route	                                                                    Status
GET /	                                                        Implemented — renders landing.html
GET /register	                                                Implemented — renders register.html
GET /login	                                                  Implemented — renders login.html
GET /logout	                                                          Stub — Step 3
GET /profile	                                                        Implemented — renders profile.html
GET /expenses/add	                                                    Stub — Step 7
GET /expenses/<id>/edit	                                              Stub — Step 8
GET /expenses/<id>/delete 	                                          Stub — Step 9

Do not implement a stub route unless the active task explicitly targets that step.

## Notes

- The `Theory/` directory is gitignored — it holds tutorial material that should not be edited or committed.
- `prompts_prepared.txt` in the repo root is working notes for the tutorial prompts, not application code.
- No CLAUDE.md, `.cursorrules`, or `.github/copilot-instructions.md` exist; this file is the only project-level Claude config.

## Warnings and things to avoid
 - Never use raw string returns for stub routes once a step is implemented — always render a template
 - Never hardcode URLs in templates — always use url_for()
 - Never put DB logic in route functions — it belongs in database/db.py
 - Never install new packages mid-feature without flagging it — keep requirements.txt in sync
 - Never use JS frameworks — the frontend is intentionally vanilla
 - database/db.py is currently empty — do not assume helpers exist until the step that implements them
 - FK enforcement is automatic in Postgres — no per-connection PRAGMA needed (unlike the old SQLite setup)
 - The app runs on port 5001, not the Flask default 5000 — don't change this
 - Connect via DATABASE_URL env var (Render's Postgres convention); get_db() falls back to a local dev connection string if unset
