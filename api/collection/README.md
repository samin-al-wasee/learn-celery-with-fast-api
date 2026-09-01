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

- **Public vs Protected roots.** The collection is split into two top-level
  folders:
  - `Public/` — no auth. The folder root (`Public/folder.bru`) pins
    `auth mode: none`, so nothing under it ever sends credentials.
  - `Protected/` — bearer JWT. The folder root (`Protected/folder.bru`)
    defines `auth mode: bearer` with `token: {{access_token}}`. All nested
    endpoints use `auth: inherit` (or none at all) and **automatically get
    the token from the parent root** — add a new protected endpoint anywhere
    under this tree and it inherits auth without a per-request auth block.
- One `.bru` file per example; folder layout mirrors the API surface
  (`Public/Health/`, `Public/Auth/`, `Protected/Users/`, ...).
- **Auth flow (auto-set token):**
  1. `Public/Auth/Signup Doctor` (or Patient) → post-response sets
     `signup_email`.
  2. `Public/Auth/Login` (no auth) → 200 + `access_token`; its post-response
     script runs `bru.setVar('access_token', data.access_token)`, so the
     variable is auto-populated for every request under `Protected/`.
  3. Any `Protected/...` request inherits the bearer token and just works.
  Run `Login` again whenever the token expires (the demo JWT lives 60 min).
- URLs use `{{baseUrl}}` so the collection is portable (local/CI/prod).
- **Dynamic data by default:** bodies use Bruno's built-in faker-backed
  dynamic variables (`{{$randomEmail}}`, `{{$randomFirstName}}`,
  `{{$randomLastName}}`, `{{$guid}}`, `{{$timestamp}}`) so every run sends a
  fresh, unique payload — no manual retyping. Override a field for a single
  run by editing the body, or force a prompt with a prompt variable
  (`{{?email}}`).
- **Rule:** no endpoint ships without its Bruno example — see `AGENTS.md`.
- The dev environment (`environments/Development.bru` with `baseUrl=http://localhost:8000`) is committed for convenience. Secrets (auth tokens, prod URLs) go in **local environments** which stay out of the repo — never commit a real token.