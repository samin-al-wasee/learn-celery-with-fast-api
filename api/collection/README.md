# Cardicheck Bruno collection

Test every endpoint of the Cardicheck API from Bruno.

## Setup

1. Open **Bruno**.
2. **File → Open Collection** → select this folder (`api/collection`).
3. Add an environment variable **baseUrl** = `http://localhost:8000`
   (**Collection → Environments**), or override per-run.
4. Make sure the API is running: `docker compose up -d`, then `uvicorn app.main:app --reload`.
5. Run any request. Each request carries its own asserts (status + body checks).

## Conventions

- One `.bru` file per example; folder layout mirrors the API surface
  (`Auth/`, `Health/`, ...).
- URLs use `{{baseUrl}}` so the collection is portable (local/CI/prod).
- **Dynamic data by default:** bodies use Bruno's built-in faker-backed
  dynamic variables (`{{$randomEmail}}`, `{{$randomFirstName}}`,
  `{{$randomLastName}}`, `{{$guid}}`, `{{$timestamp}}`) so every run sends a
  fresh, unique payload — no manual retyping. Override a field for a single
  run by editing the body, or force a prompt with a prompt variable
  (`{{?email}}`).
- **Rule:** no endpoint ships without its Bruno example — see `AGENTS.md`.
- The dev environment (`environments/Development.bru` with `baseUrl=http://localhost:8000`) is committed for convenience. Secrets (auth tokens, prod URLs) go in **local environments** which stay out of the repo — never commit a real token.