# LEARNING.md

The living record of everything we learn in this repo. **If it didn't get logged, it didn't get learned.**

> This file is the whole point of the project. Code is the side-effect; understanding is the deliverable. When in doubt — write it down here.

---

## How to log an entry

Each entry MUST cover all of these:

1. **Date & milestone** — `2026-09-01 · M0`
2. **What we did** — the naive attempt + the observed problem (symptom)
3. **Lesson** — WHY it happened (mechanism, not just "it broke")
4. **Fix / best practice** — what we changed and why that is correct
5. **Interview answer** — the 2–5 sentence one-liner you'd say in an interview
6. **Trap to avoid** — the wrong answer people give

Keep it as bullets, not essays.

---

## Table of contents (per milestone)

- **M0 — Foundation** (placeholders below)
- **M1 — Auth & CRUD** (6 entries: alembic, sync-in-async, bruno, login+jwt+cpu-blocking, public/protected roots, envelope)
- **M2 — Caching with Redis** (empty)
- **M3 — Celery & async jobs** (empty)
- **M4 — Real-time chat / bidirectional comms** (empty)
- **M5 — RabbitMQ deep dive** (empty)
- **M6 — Microservices / distributed systems** (empty)
- **M7 — Voice/video calling** (empty)
- **M8 — Senior hardening** (empty)

---

## M0 — Foundation (scaffolding)

### `2026-09-01 · M0` — Project scaffolding

- **What we did:** Created `README.md`, `AGENTS.md`, `AI_WORKFLOW.md`, `ROADMAP.md`, `ARCHITECTURE.md`, `LEARNING.md`. No application code yet.
- **Observed:** none — no code to break. This milestone exists to fix the *process* before the code.
- **Lesson:** A learning project needs a **learning loop** (naive → fail → explain → fix → log) and a **commitment that documentation is not optional**. Without these, every "fix the naive bug" task silently becomes "just build it right."
- **Fix / best practice:** Locked the 5-step loop in `AI_WORKFLOW.md` and made `LEARNING.md` updates a hard rule in `AGENTS.md`.
- **Interview answer:** *"We structure the codebase to make every failure observable and every decision documented — so when I explain a design at work, I can ground it in a real failure I saw, not a slide."*
- **Trap to avoid:** "We documented everything... in our heads." Documentation that lives in memory doesn't survive the week.

### `2026-09-01 · M0/M1` — repo bootstrap, docker stack, app skeleton

- **What we did:** `git init`, `.gitignore`, `docker-compose.yml` (postgres 16 / redis 7 / rabbitmq 3-management, each with healthchecks + named volumes), `requirements.txt`, and a FastAPI skeleton: `app/core/config.py` (pydantic-settings), `app/core/database.py` (async engine + `async_sessionmaker` + `DeclarativeBase`), `/api/v1/health` route.
- **Observed:** N/A — infra milestone. Notably, nothing here *can* fail yet, which is deliberate: so future failures are attributable to our code, not the environment.
- **Lesson:** infra hygiene is a pre-requisite for learning. If secrets live in files, if containers are rebuilt from guesses, every later lesson gets polluted with "did my setup break it?"
- **Fix / best practice:** branch-per-feature + small commits (AGENTS §7); `.env` gitignored + `.env.example` committed; compose pins sane images with healthchecks so "is the dependency up?" is a checkable fact, not a guess.
- **Interview answer:** *"I set up the repo so that environment failures are impossible to confuse with application failures: versioned deps, validated compose healthchecks, env-config from `.env`, and linear git history via rebase + `--ff-only` merges — each commit is one reviewable unit."*
- **Trap to avoid:** committing `.env` with real credentials "just for now" — the mistake that leaks secrets forever.

### `2026-09-01 · M1` — User model + Alembic (schema versioning)

- **What we did:** `alembic init --template async`, wired `env.py` to our settings + `Base.metadata`, added `User` model (role enum doctor/patient), `autogenerate` first migration, applied with `upgrade head`, verified with `psql \d users`.
- **Observed (naive setup):** `Base.metadata.create_all()` is the beginner path — it creates missing tables but is **blind to existing schemas**: no versioning, no downgrade, no audit trail. We did not take that path; we documented it instead.
- **Lesson 1 — Alembic = schema history as code:** `alembic_version` table stores the current revision; migrations are replayable, ordered, reviewable diffs. Same discipline as app code versioning.
- **Lesson 2 — autogenerate ≠ trusted output:** Alembic detected table + indexes correctly, but review each file — it can miss renames/constraint details. We read `c3726ca5d8b0` before applying.
- **Lesson 3 — sync vs async drivers:** Alembic runs *sync* by default; the `async` template + `async_engine_from_config` keeps us on one driver (asyncpg) with `asyncio.run`.
- **Lesson 4 — `str`-enum stores by NAME:** `Enum(UserRole)` wrote PG labels `DOCTOR/PATIENT` (the enum member *names*), not values `doctor/patient`. Consistent round-trip (Python `UserRole.DOCTOR` <-> PG `'DOCTOR'`), but if you expect lowercase in the DB you need `values_callable=lambda e: [m.value for m in e]`.
- **Interview answer:** *"Schema changes are code. I version them with Alembic — each revision is a reversible diff, the DB records where it is, and deployments run `upgrade head` from version A to D deterministically. Never `create_all` in production because it can't evolve a live schema."*
- **Trap to avoid:** "Autogenerate wrote it, so it must be right." It's a starting draft — the base/`downgrade`/indexes need a human eye.

### `2026-09-01 · M1` — sync-in-async: the blocking event loop

- **What we did:** Built signup the **naive** way (deliberate): a sync psycopg session + `time.sleep(2)` inside the `async def` handler (see git history `44d0dc6`). Observed the damage with `scripts/observe_blocking.py`, then refactored to `AsyncSession` via DI (`1fcf0ac`).
- **Observed (naive):** a **health probe issued at t=1s completed at t+2085ms — blocked ~1085ms** behind the signup's `sleep(2)`; a second signup request was serialized too (t+4214ms). One slow request stalled unrelated traffic.
- **Observed (fixed):** same script → signup t+107ms, probe at t=1s completes t+1024ms (~24ms — the loop stayed free), dup → clean 409.
- **Lesson:** `async def` gives **concurrency, not parallelism**. All coroutines share ONE event-loop thread; any blocking call (`time.sleep`, sync DB driver, `requests.get`, heavy CPU) stalls **every** in-flight request — not just this one. Concurrency is cooperative: you must `await` to yield.
- **Fix / best practice:** async driver (asyncpg) + `AsyncSession` provided by `Depends(get_db_session)` (`app/core/database.py:22`); every I/O `await`ed. `expire_on_commit=False` keeps attributes usable after commit.
- **Why this matters later:** this exact failure is why heavy work gets moved to workers/tasks (M3 Celery) — a task *never* holds the request path hostage.
- **Interview answer:** *"In FastAPI/uvicorn an async endpoint is one task on one event-loop thread. Blocking I/O inside it freezes the whole server — a `time.sleep` or sync driver call doesn't just slow one request, it serializes all of them. So we use async drivers (asyncpg) and `await` every DB call; truly expensive or fire-and-forget work goes to a background task worker, not the request thread."*
- **Trap to avoid:** "'It's an async endpoint, so it's fine.'" — async signature ≠ non-blocking body. Also `run_in_threadpool` as a reflex: it hides blocking in the default threadpool, which *also* saturates under load.

### `2026-09-01 · M1` — Bruno API collection (endpoint testing convention)

- **What we did:** Added a git-friendly **Bruno** collection under `api/collection/` (bruno.json + `{{baseUrl}}`-based `.bru` examples for `/health` and `/auth/signup` with asserts). Made the rule explicit in `AGENTS.md` §5: **every endpoint — HTTP, WebSocket, SSE — ships with its Bruno example before merging to `main`.** Then switched signup bodies to Bruno's faker-backed **dynamic variables** (`{{$randomEmail}}`, `{{$randomFirstName}}`, `{{$randomLastName}}`, `{{$guid}}`) so re-runs send unique data instead of colliding on a fixed email.
- **Observed:** not a failure — a tooling gap. Before this, examples lived in chat history and died with the session.
- **Lesson:** an API is only as testable as its examples. If the only way to hit an endpoint is to re-derive the payload, the API is undocumented regardless of Swagger.
- **Fix / best practice:** one `.bru` file per example, folder mirrors the API surface, `{{baseUrl}}` keeps it portable, asserts encode the contract (status + body).
- **Interview answer:** *"Every endpoint I ship has a runnable example in the repo's API collection — versioned, diffable, with asserts. Onboarding or debugging becomes 'open Bruno, press send', not 'read the code and reconstruct the request'."*
- **Trap to avoid:** "Swagger docs are enough." Swagger shows the shape; a collection proves the happy path works and keeps exercising it.

### `2026-09-01 · M1` — login + JWT (CPU-bound crypto: argon2 in the loop)

- **What we did:** Added `POST /auth/login` (naive first: `verify_password` straight in the async handler), JWT helpers (`create/decode_access_token`, minimal claims `sub=user_id`/`iat`/`exp`, HS256), a `get_current_user` dependency that **loads the user fresh from the DB each request**, and protected `GET /users/me`. Observed the failure with `scripts/observe_cpu_blocking.py`, then moved hash/verify to a threadpool. Bruno flow: signup captures `signup_email` → login captures `access_token` → me authenticates with it.
- **Observed (naive):** 8 wrong-password logins + health probe issued together → total wall **~413ms**, later logins finishing at ~370–410ms — serialized behind each other's argon2. Measured cost: `PasswordHash.recommended()` (argon2id) ≈ **31ms/call** of pure CPU.
- **Observed (fixed):** logins off the loop → probe reliably fast (~23ms vs ~46ms naive), and the loop is free to serve unrelated traffic during the burst. Honest nuance: 8 concurrent verifies took 179ms threaded vs 245ms sequential — argon2 only ~1.4x parallelizes because hashing saturates cores/GIL; **the fix wins on loop responsiveness, not login wall-time.**
- **Lesson:** crypto is deliberately slow (argon2id ≈ 30ms+). Doing it *on* the loop stalls every request under a login storm; `run_in_threadpool` moves the CPU to the anyio default threadpool. The key distinction — I/O and CPU concurrency: async gives I/O concurrency by `await`, but there is ONE thread for Python bytecode; CPU work needs a real thread. Leave the refine-to-boundary design (concurrency → parallelism mapping) for M3.
- **Fix / best practice:** `await run_in_threadpool(verify_password, ...)` and `run_in_threadpool(hash_password, ...)` in `app/api/routes/auth.py`; note `starlette.concurrency.run_in_threadpool` == `anyio.to_thread`. DB fetch stays async; only the CPU step leaves the loop. Passing the AsyncSession across threads is avoided — only pure data crosses the boundary.
- **Why this matters later (M3):** the default threadpool is finite and shared. Under real load, dedicated workers (Celery) take the CPU-heavy + retryable work; the loop keeps doing I/O. This is the naive-fix that becomes the seed of the workers milestone.
- **JWT design rationale:** `sub` = `user_id` (int as string), no email/role in the token — the dependency re-reads the user from the DB, so role revocation/deactivation applies immediately (token can't outlive a DB-level demotion). `exp`+`iat` standard claims; HS256 with a dev-only fallback secret from env (`JWT_SECRET`, `.env.example`).
- **Interview answer:** *"Passwords are hashed with argon2id, which is intentionally slow — ~30ms per verify. In an async server that CPU work must never run on the event loop or it freezes every concurrent request, so I delegate it to a threadpool. Tokens are short-lived JWTs with just `sub`, `iat`, and `exp`; I re-load the user from the DB on every request so authz reflects current state, and rotation/revocation stays simple."*
- **Trap to avoid:** "I'll put the whole user object in the JWT so I don't need a DB round-trip." That's a caching tank that can hand out expired roles; and adding `run_in_threadpool` everywhere as a reflex without thinking about which call actually blocks.

### `2026-09-01 · M1` — Bruno collection: Public vs Protected auth roots

- **What we did:** Restructured the collection into two top-level roots. `Public/folder.bru` pins `auth mode: none`. `Protected/folder.bru` declares `auth mode: bearer` with `token: {{access_token}}`; every nested request uses `auth: inherit` and gets the token from the folder root — **no per-request auth blocks**. The public `Login` example's post-response script auto-sets `access_token` (`bru.setVar`), so exactly one request (login) culminates in auth for the entire protected tree. Removed a stale `vars:pre-request` override that was hardcoding a dead email in login.
- **Observed (naive structure):** originally every request carried its own `auth` block — auth duplicated N times, easy to miss on new endpoints, and signup/login living in a plain `Auth/` folder gave no hint about which requests needed a token. Doubling: two requests to update (real token value + URL) whenever auth changed.
- **Lesson:** an API collection is a contract too, so it needs the same DRY that code needs — auth is a *cascading concern*: collection → folder → request. Bruno models it with `collection.bru` / `folder.bru`, and `auth: inherit` at the request level. Form follows the API's security boundary: public endpoints *cannot* accidentally inherit credentials.
- **Fix / best practice:** two roots — `Public/` (folder-level `none`) and `Protected/` (folder-level bearer); nested request files under `Protected/` declare only what's theirs; one auth-mutation point (login) writes the collection variable every other request reads. Rule codified in `AGENTS.md` §5 so future endpoints follow it automatically.
- **Interview answer:** *"I treat the API test collection as a reproducible contract: auth is configured once at the folder root and inherited by every nested request — public and protected endpoints are physically separated. One login example sets the token variable that the whole protected tree consumes, so onboarding a new endpoint is 'drop a file in the folder, it's already authenticated'."*
- **Trap to avoid:** duplicating `Authorization` headers/tokens per request — it rots fast (stale token values, forgotten audits) and gives reviewers the illusion that auth is per-route instead of per-boundary.
- **Amendments:** chain vars follow an explicit lifecycle — `access_token` is cleared pre-login and populated only on a 200; `signup_email` is captured on a 201 signup and **cleared again when login succeeds (it's consumed)**. Exactly one "writer" and one "consumer" per variable → no stale fixtures across runs; Bruno kept re-pinning `vars:pre-request { signup_email }` (its request-variable panel) which must not come back.

### `2026-09-01 · M1` — response envelope + centralized error handling

- **What we did:** Introduced a single contract: success `{"data": ..., "meta": {}, "error": null}`, failure `{"data": null, "error": {"code", "message", "details"}, "meta": {}}`. Added `ApiResponse[T]` (Pydantic generic), `CardicheckError` domain exception, and one handler per class registered once in `app/core/errors.register_exception_handlers`: domain errors, Starlette `HTTPException` (covers 401/404/405), FastAPI's `RequestValidationError` (422), and a catch-all `Exception` (500, detail only when `settings.debug`). Migrated health/signup/login/users/me; Bruno asserts now check envelope keys.
- **Observed (before — 5 shapes on one API):** dup signup → `{"detail": ...}`; bad login → 401 `detail`; validation → FastAPI's `{"detail": [{type,loc,msg,ctx}]}`; unknown route → `{"detail":"Not Found"}`; unhandled → plain text `500`. No machine-readable code anywhere; clients had to special-case every route.
- **Observed (after — one shape):** all six probes now `{data,error,meta}`; `EMAIL_ALREADY_REGISTERED`, `INVALID_CREDENTIALS`, `VALIDATION_ERROR`, `NOT_FOUND` carry stable codes; 500 is sanitized (no stack/HTML leak in prod).
- **Lesson:** responses ARE the API's public surface — if each endpoint invents its own shape, the "API" is really N micro-APIs. Errors are a contract too: a `code` (stable, machine-parseable) + `message` (human) + `details` (structured context) beats freeform text. Centralize via exception handlers so routes return happy-path values and *raise* honestly.
- **Fix / best practice:** one generic `ApiResponse[T]`; domain code raises `CardicheckError(status, code, message, details)`; `register_exception_handlers` in `main.py` maps every failure path to the same envelope, including foreign classes (FastAPI 422, Starlette 404). `settings.debug` decides how much of a 500 leaks.
- **Interview answer:** *"I define one response envelope — success data plus an error object with a stable code, human message, and structured details — and enforce it at the edges with FastAPI exception handlers, so route handlers stay clean and every failure path (validation, not-found, domain conflicts, crashes) serializes identically. Codes, not freeform 'detail' strings, are the machine contract; messages are for humans."*
- **Trap to avoid:** "Errors are fine as `{'detail': '...'}`" — with that, upgrading any client or adding an SDK means touching every endpoint; and leaking raw `str(exc)` to clients in prod is a security hole, not a convenience.

---

## M4 — Real-time chat — INTERVIEW FILE (placeholder to be filled when we reach it)

*(Filled during M4. When we get there, ensure we cover: WebSocket vs HTTP long-polling tradeoffs, connection scaling, redis pub/sub as a cross-worker bus, at-least-once delivery of chat events, and message ordering.)*

---

> Appends: each of the six topics will get its own section below as we reach it. All future entries should maintain this format so the file stays grep-able.