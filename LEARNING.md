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
- **M1 — Auth & CRUD** (2 entries: alembic, sync-in-async)
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

---

## M4 — Real-time chat — INTERVIEW FILE (placeholder to be filled when we reach it)

*(Filled during M4. When we get there, ensure we cover: WebSocket vs HTTP long-polling tradeoffs, connection scaling, redis pub/sub as a cross-worker bus, at-least-once delivery of chat events, and message ordering.)*

---

> Appends: each of the six topics will get its own section below as we reach it. All future entries should maintain this format so the file stays grep-able.