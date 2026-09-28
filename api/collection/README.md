# Cardicheck Bruno collection

Test every endpoint of the Cardicheck API from Bruno.

## Setup

1. Open **Bruno**.
2. **File → Open Collection** → select this folder (`api/collection`).
3. Add an environment variable **baseUrl** = `http://localhost:8000`
   (**Collection → Environments**), or override per-run.
4. Make sure the API is running: `docker compose up -d`, then `uvicorn app.main:app --reload`.
   `Protected/Exports/*` also needs a Celery worker: `celery -A app.worker.celery_app worker -P threads`.
   Headless run of the whole flow: `..\..\scripts\verify.ps1 -Bruno` (or `npx @usebruno/cli run --env Development`).
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
  1. `Public/Auth/Signup Patient` and `Signup Doctor` → on **201** both set
     `signup_email` (last run wins — the appointments flow expects the doctor
     last) plus their own id (`signup_patient_id` / `signup_doctor_id`).
  2. `Public/Auth/Login` (no auth) → on **200** its post-response sets
     `access_token` and **clears `signup_email`** (the account now exists —
     the email was consumed). Variable lifecycle: each signup captures the
     email only on success, and login empties it again on success.
  3. Any `Protected/...` request inherits the bearer token and just works.
     `Protected/Appointments/*` additionally needs the captured participant
     ids: `Signup Patient` sets `signup_patient_id` (and `Signup Doctor` sets
     `signup_doctor_id`), which `Create Appointment` uses. Create captures
     `appt_id`, consumed by `Cancel Appointment` (idempotent — repeat returns
     200 no-op). `Confirm Appointment` (doctor-only) flips it to `confirmed`;
     the sequence is Signup Patient → Signup Doctor → Login → Create → List →
     Cancel → Confirm.
   - `Protected/Users/*`: `Get My Profile` → `Update My Profile`
     (`PATCH /users/me` — phone must be E.164 `+…`, specialty is doctor-only).
  Run `Login` again whenever the token expires (the demo JWT lives 60 min).
- URLs use `{{baseUrl}}` so the collection is portable (local/CI/prod).
- **Dynamic data by default:** bodies use Bruno's built-in faker-backed
  dynamic variables (`{{$randomEmail}}`, `{{$randomFirstName}}`,
  `{{$randomLastName}}`, `{{$guid}}`, `{{$timestamp}}`) so every run sends a
  fresh, unique payload — no manual retyping. Override a field for a single
  run by editing the body, or force a prompt with a prompt variable
  (`{{?email}}`).
- **Rule:** no endpoint ships without its Bruno example — see `AGENTS.md`.
- **Response envelope (every endpoint):** success is `{"data": ..., "meta": {}, "error": null}`;
  failure is `{"data": null, "meta": {}, "error": {"code": ..., "message": ..., "details": {}}}`.
  Asserts in this collection verify the envelope keys alongside the payload
- The dev environment (`environments/Development.bru` with `baseUrl=http://localhost:8000`) is committed for convenience. Secrets (auth tokens, prod URLs) go in **local environments** which stay out of the repo — never commit a real token.