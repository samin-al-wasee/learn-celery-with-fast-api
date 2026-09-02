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
- **M1 — Auth & CRUD** (12 entries: alembic, sync-in-async, bruno, login+jwt+cpu-blocking, public/protected roots, envelope, appointments-n1-pagination, collection-freshness, cancel-state-machine, records-ownership-patch, patch-transitions-rolevalidation, validation-layers)
- **M2 — Caching with Redis** (1 entry: in-process-dict vs redis read-through + invalidation; stampede note deferred)
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
- **Amendment — scripts must unwrap the envelope:** introducing the envelope silently broke the Bruno var-capture scripts — `res.getBody().email` became `undefined` because payloads moved under `.data` (asserts survived: `contains` is serialized-text matching, var extraction is structural). Every post-response script now reads `res.getBody().data.<field>`. Lesson: response-shape changes are client-contract changes — every consumer (SDK, scripts, asserts, docs) must be re-checked, and structural consumers (var capture) break first.

### `2026-09-01 · M1` — rule: Bruno collections stay in lockstep with the API

- **What we did:** Codified a standing rule in `AGENTS.md` §5 ("Collection freshness rule"): any endpoint change — response shape, status codes, payload fields, auth, pagination — ships with its `.bru` examples updated in the same increment; var-capture scripts unwrap the envelope; re-run affected examples or `scripts/observe_*.py` before merging. Triggered directly by the envelope incident above (three post-response scripts captured `undefined` while asserts still passed).
- **Observed problem:** the envelope refactor merged with stale `.bru` scripts; the failures were silent (string-based asserts can't see a missing field a script expected) and only surfaced as 401s in the Protected flow.
- **Lesson:** asserts and capture scripts are *both* consumers of the response contract, with different blind spots — asserts check serialized text, scripts do structural extraction. "Tests pass" ⇒ "API still matches the collection" is not implied. The collection IS a client SDK; treat it like one during reviews and migrations.
- **Fix / best practice:** update Bruno in the same increment as the code that changes the contract; consciously re-check BOTH asserts and post-response `res.getBody().data` extraction; run the affected examples / observe scripts as part of the merge checklist.
- **Interview answer:** *"Our API test collection is versioned and lives with the code. When a response shape changes, I update the matching Bruno examples in the same commit — because a stale example is a broken client contract, not a cosmetic doc. The tricky part is that asserts do text matching, so they can pass while variable-capture scripts silently break; I re-check both and re-run the affected requests before merging."*
- **Trap to avoid:** "The asserts still pass, so we're fine." — asserts and scripts have complementary blind spots; a change that passes all asserts can still ship a broken collection.

### `2026-09-01 · M1` — appointment cancel: authz, state transitions, idempotency

- **What we did:** Added `POST /appointments/{id}/cancel` **naive** (find → set CANCELLED → 200), observed the holes with `scripts/observe_cancel.py`, then fixed: participant-only authz (403 `NOT_PARTICIPANT`), explicit transition guard (COMPLETED → 409 `INVALID_TRANSITION`), and idempotent no-op for already-cancelled (200 returning current state). Also added a `status` filter to the list endpoint.
- **Observed (naive):** stranger with a valid token cancels the owner's appointment → **200**; cancelling a COMPLETED past visit → **200** (rewrites history); double-cancel → blind 200 with nothing that distinguishes "still cancelled" from a fresh transition.
- **Observed (fixed):** stranger → **403**; completed → **409**; owner → 200; owner again → 200 idempotent no-op (state unchanged).
- **Lesson 1 — every stateful write needs three questions answered at the edge:** Who may do it? (authz — participant check, not "is authenticated") From which states is it legal? (transition map — not any-state-any-time) What if repeated? (HTTP semantics — cancel is idempotent, so repeat = no-op success; a *different* invalid transition = 409 conflict).
- **Lesson 2 — idempotency vs conflict:** idempotency says "same request, same effect" — cancelling a cancelled appointment is the *same effect* (it stays cancelled) so 200 no-op is correct; returning 409 would break retry-safe clients. But COMPLETED→CANCELLED is a *different* target, so 409. Idempotency is about repeated requests, not about which transitions exist.
- **Fix / best practice:** order the checks deliberately — (1) not found → 404, (2) not participant → 403, (3) already-cancelled → no-op 200, (4) terminal/illegal state → 409, (5) else transition + commit. Return the eager-loaded current state so clients converge on truth.
- **Interview answer:** *"A stateful endpoint like cancel is a tiny state machine: I authorize at the boundary (only participants), guard the transition (completed records are immutable), and honor HTTP semantics (cancel is idempotent, so repeating it is a 200 no-op, while an illegal transition is a 409). The distinction matters for retry-safe clients: idempotency is about repeated requests mapping to the same effect, not about which transitions exist."*
- **Trap to avoid:** "Everyone logged in can cancel — auth middleware got them to the route." Authentication ≠ authorization; and "idempotent means always return 200" is wrong — it means repeated requests converge on one state.

### `2026-09-02 · M1` — records CRUD: ownership on sensitive data + PATCH semantics

- **What we did:** `medical_records` table (migration `4304e911c43b`) + full CRUD. **Naive**: any authenticated user GETs any record; PATCH applies `model_dump()` (missing fields → `None`) so a title-only edit wipes notes; DELETE ungated (any participant). Observed with `scripts/observe_records.py`, then fixed, then Bruno `Protected/Records/*`.
- **Observed (naive):** patient B reads patient A's record → **200 leak**; `PATCH {title}` sets `notes=None` → **NOT NULL violation → 500** (would silently erase on a nullable column); patient A's DELETE → **204** on doctor's record; patient A's PATCH → **500** (granted, then crashed).
- **Observed (fixed):** stranger read → **403** `RECORD_ACCESS_DENIED`; PATCH title-only → 200 with notes **preserved**; patient PATCH/DELETE → **403**; creator DELETE → 204; POST-delete GET → 404.
- **Lesson 1 — PATCH vs PUT:** PUT = replace the whole resource — every field must be provided, omitted means "back to default/empty". PATCH = partial modification — omitted fields mean "leave alone". `payload.model_dump(exclude_unset=True)` is the idiom: only keys that were actually in the request body survive, so defaults (our `None`s) never get written. Shipping a "PATCH" that behaves like PUT is a data-loss bug that here surfaced as a 500 only because the column was NOT NULL — on nullable columns it silently destroys data.
- **Lesson 2 — ownership, twice:** "authenticated" ≠ "entitled". Medical data is the canonical least-privilege case: reads scoped to the two parties on the record (`patient_id OR doctor_id`), writes scoped to the creator (`doctor_id == me`). Enforce at the handler (data-level), never assume the route prefix protects you. Distinct error `RECORD_ACCESS_DENIED` (403) vs `RECORD_NOT_FOUND` (404) — do not hide 404s as 403 (don't leak existence) or vice versa (must reveal intent for debugging).
- **Ops bonus discovered en route:** the envelope's unhandled-exception handler swallowed 500s with **zero server-side trace** — a silent failure in prod. Fixed: `logging.getLogger("uvicorn.error").exception(...)` before returning. Lesson: a sanitized client error is fine, but *never* let the server log be silent too.
- **Fix / best practice:** single `_load()` (404 + eager participants) reused by all handlers; `_response()` refresh after commit; 204 empty-body DELETE (REST, no envelope — body-less by definition). Creator-check before mutate; read-check before view.
- **Interview answer:** *"PATCH and PUT differ in intent: PUT replaces the whole resource, PATCH mutates only the fields the client sent. I implement the latter with model_dump(exclude_unset=True) so defaults never clobber stored data, and I scope sensitive-data endpoints by data-level ownership — reads for the parties on the record, writes for the creator — because authentication proves who you are, not what you may see."*
- **Trap to avoid:** `model_dump()` without `exclude_unset` in a PATCH handler ("looks fine, tests pass, wipes on real use"), or treating "must be logged in" as sufficient for sensitive reads.

### `2026-09-01 · M1` — appointments CRUD: N+1 queries + pagination

- **What we did:** Added `appointments` table (migration `e30a4c8a53e0`, enum `appointment_status`), `POST /appointments` with role-based participant validation (patient books a doctor / doctor books a patient, future `scheduled_at`, participant-role checks), and a **naive** `GET /appointments` that returned every row and fetched patient+doctor with a query per row. Observed the explosion with `scripts/observe_n_plus_1.py`, then fixed: `limit/offset` + `selectinload` + `meta.pagination`.
- **Observed (naive):** 100 appointments with distinct participants → **601 cursor executions / ~388ms** for everything (1 query for rows + 200 per-row lookups ×~2 due to asyncpg prepare+execute). Earlier attempt reused the same 2 users and measured only 2 queries — the load was absorbed by SQLAlchemy's **identity map** (a real-world nuance: repeated lookups are cached; N+1 bites when the entities are distinct).
- **Observed (fixed):** 1 page of 20 → **4 cursor executions / ~7ms** (~150× less volume); `meta.pagination` reports page/per_page/total/pages; names accessible after `selectinload` without triggering lazy I/O.
- **Lesson 1 — N+1:** fetching children one-at-a-time turns 1 query into 1+N; latency isn't the point, *query volume × concurrency* is. In `AsyncSession`, lazy relationship access doesn't silently N+1 — it raises `MissingGreenlet` (async can't transparently block) — the loud, honest failure. Fix with eager loading: `selectinload` (2 IN-queries) > `joinedload` (1 JOIN but row multiplication on collections) > N queries.
- **Lesson 2 — pagination:** unbounded lists grow with the table and cost nothing per user until they cost everything; `limit/offset` is the baseline. `meta.pagination` is exactly what the envelope's `meta` slot exists for. Known debt (interview note): offset pagination *drifts* when rows are inserted/deleted between pages — keyset pagination fixes that, noted for M8.
- **Fix / best practice:** `select(Appointment).options(selectinload(...)).where(owned).order_by(...).limit().offset()` + a `func.count()` for total; participants loaded in bulk and rendered from the relationship attributes; owner scoping (`patient_id=me OR doctor_id=me`) is the authz line.
- **Interview answer:** *"List endpoints get pagination and eager loading. The naive thing — fetch the page, then load the related doctor and patient per row — turns one request into 1+N round trips; with an async schema it can't even do that silently. `selectinload` fetches whole collections in bulk, and `limit/offset` bounds the result; I expose that in `meta: {pagination}`. The trap underneath is the identity map hiding the problem when participants repeat."*
- **Trap to avoid:** "It's fast in my dev DB so it's fine" — dev data is tiny; N+1 and unbounded lists are the two things that produce the p95 cliff under load. Also: fixing N+1 by loading *everything* "just in case" — paginate first, eager-load only what the page renders.

### `2026-09-02 · M1` — appointment update/confirm + profiles: transitions, role-aware profile fields

- **What we did:** `PATCH /appointments/{id}` (confirm / reschedule / edit reason) and `PATCH /users/me` (profile CRUD now complete: GET existed, this adds update). Added `users.phone` (migration `6e435f95a96a`). **Naive:** any participant confirmed/applied any transition, past reschedules accepted, terminal records editable; patients set `specialty`. Observed with `scripts/observe_update_confirm.py`, then fixed.
- **Observed (naive):** patient confirms own appointment → **200**; doctor reschedules to a past time → **200**; reason edit on a COMPLETED record → **200**; patient `PATCH /users/me {specialty}` → **200** with the field set; garbage phone → already **422** (schema-level `pattern` caught it even before the fix).
- **Observed (fixed):** patient confirm → **403** `FORBIDDEN`; past reschedule → **400** `PAST_SCHEDULED_AT`; terminal-state edit → **409** `INVALID_TRANSITION`; patient specialty → **403**; valid E.164 phone → 200.
- **Lesson 1 — the state machine generalizes:** the same three questions as cancel — *who* (participant authz, plus doctor-only for confirm), *from which states* (PENDING→CONFIRMED only; CANCELLED/COMPLETED immutable for everything — 409), *repeated?* (re-confirming a confirmed appointment is a no-op 200, mirroring cancel's idempotency). A resource with state is a tiny state machine; encode the transitions in one place, not per-endpoint improvisation.
- **Lesson 2 — validate shape at the boundary, validate *entitlement* in the handler:** `phone` format and `status ∈ {confirmed}` are data facts → Pydantic (`pattern`, `Literal`) rejects them at 422 with zero handler code. `specialty` is a *role* fact → the handler checks `current_user.role` and answers 403. Mixing the two layers is the classic bug: doing access control with 422 validation, or validating business rules in the handler with raw `if`s.
- **Fix / best practice:** `AppointmentUpdate` uses `exclude_unset` (only sent fields), `Literal` for the one legal status value; participants check first, then per-field guards (role, transition table, `future` on reschedule). Profile: `ProfileResponse` now returns `specialty`/`phone`; schema enforces E.164 pattern; role guard for specialty.
- **Interview answer:** *"An update endpoint on a stateful resource is a transition: I authorize who's allowed, restrict which states it can run from, and treat repeats as idempotent no-ops. Data-format rules (phone E.164, allowed enum values) live in the schema so they 422 at the boundary; entitlement rules (doctor-only specialty, doctor-only confirm) live in the handler as 403s — mixing the two layers causes exactly the 'why is my validation also my authz' confusion."*
- **Trap to avoid:** giving PATCH free rein on a resource that has a lifecycle — you'll rewrite history — and putting role checks into Pydantic (schema can't see who's asking).

### `2026-09-02 · M1` — validation layers: schema shape vs handler state + the envelope crash

- **What we did:** hardened payload validation across all CRUD. `str_strip_whitespace=True` + `min_length=1` on names/reasons/titles/notes (rejects `"   "`), role-aware signup (`specialty` required for doctors via `model_validator`), and a **15-minute scheduling lead time**. Observed with `scripts/observe_validation.py`.
- **Observed (naive):** doctor without specialty → **201**; blank `full_name` → **201** (stored whitespace); appointment 5 min out → **201**; blank reason → **201**.
- **Observed (hardened):** no-specialty doctor → **422**; blank name → **422**; 5-minute lead → **400** `PAST_SCHEDULED_AT`; blank reason → **422**; valid everything → 201.
- **Unexpected gold bug found mid-run:** the no-specialty 422 was at first a **500**, not 422. Pydantic's model_validator errors embed the actual `ValueError` object in `errors()[].ctx`, and our envelope handler passed `exc.errors()` straight to `json.dumps` → `TypeError: Object of type ValueError is not JSON serializable` → the **error response itself crashed**. Lesson: an error handler must be safe against arbitrary error content — sanitize non-primitive `ctx` values (`str(v)`) before render; error paths are exactly where serialization shortcuts bite.
- **Lesson — two validation layers with two status codes:** *static shape* rules (formats, presence, relationships between fields) belong in Pydantic and answer **422** (`Literal` for allowed values, `pattern` for phone, `model_validator` for doctor-needs-specialty, `strip_whitespace` for `"   "`). *State/time* rules (scheduling lead time needs "now"; transitions need the row's current status) belong in the **handler** and answer **400/409**. The schema cannot know the time or the record; the handler should not re-implement formats.
- **Fix / best practice:** `ConfigDict(str_strip_whitespace=True)` + `min_length=1` so whitespace-only fails; role conditional via `model_validator(mode="after")`; lead time as handler check (`<= now + 15 min → 400`); error serialization sanitized centrally in `errors.py`.
- **Interview answer:** *"Validation splits into two layers: static shape in Pydantic — formats, lengths, `Literal` value sets, role-conditional fields — which surfaces as 422 with zero handler code; and state/time rules in the handler — lead time, transitions, ownership — surfacing as 400/409. And I learned the hard way to sanitize Pydantic's `ctx` before rendering errors, because the error handler itself must never crash."*
- **Trap to avoid:** trusting `min_length` to catch blank strings (whitespace passes) — combine with `str_strip_whitespace`; and echoing `exc.errors()` into the response envelope without making it JSON-safe.

---

## M2 — Caching with Redis

### `2026-09-02 · M2` — caching: in-process dict vs Redis read-through + write-invalidation

- **What we did:** Added a Redis client (`app/core/redis.py`) + `REDIS_URL`/`CACHE_TTL_SECONDS` (config + `.env.example`) + `redis>=5.0`. **Naive** cache on `GET /users/me` = a module-level `dict[int, (timestamp, profile)]` with a `time.monotonic()` TTL. Observed with `scripts/observe_cache.py`, then **fixed**: Redis **read-through** on the hot read + **delete-on-write invalidation** on `PATCH /users/me` (`app/api/routes/users.py`).
- **Observed (naive, deterministic):** `GET /users/me` caches "Cache Doctor" → `PATCH` renames to "Renamed Doctor" → next `GET /users/me` **still serves "Cache Doctor"** — stale data served from the in-process dict. The TTL of 60s would have hidden it for a minute; nothing in the write path touched the dict.
- **Observed (fixed):** cold miss ~**26ms** (Redis miss → DB → serialize → cache), warm hit ~**5ms** (no DB re-read); after `PATCH`, the key is deleted (`exists=False`), so the next `GET` refetches fresh "Renamed Doctor" and read-through re-caches it.
- **Lesson 1 — a process-local cache is not a cache, it's a lie:** each uvicorn worker / each deploy owns a *private* dict. It's not shared across workers, and a restart wipes it cold. So under `--workers N` or any rolling deploy the "cache" both diverges per process *and* serves stale data written by a different process. A cache only means something when every request path — any worker — reads the same store (Redis).
- **Lesson 2 — read caching implies write invalidation, and it's your job:** the naive dict was read-write to *nothing*. A writer that doesn't purge the cache guarantees stale reads up to TTL. Best practice here is **delete-on-write** (`cache_delete` after commit): cache-aside is "write to DB, *invalidate* cache", not "write to both" — writing to both double-maintains data and risks divergence; deleting is simpler and always correct (next read lazily refetches). *Caveat:* now every read after a write is a cache miss until refilled (the "cache miss storm" morsel that becomes the stampede lesson).
- **Lesson 3 — honest cost framing:** the hit-vs-miss delta (~5ms vs ~26ms) is meaningful but *shaved down* here by design: `get_current_user` re-reads the user by PK on every request (M1 revocation design). We deliberately cache the *profile payload*, not the auth read. In a real hot-read with a heavier query (a doctor roster, chat-history cursor), the delta is far larger — the mechanism is the teachable part, the absolute numbers are fixture-specific.
- **Lesson 4 — serialization & off-loop:** store JSON (`model_dump(mode="json")`), `decode_responses=True` so we get dicts back, TTL from config. `redis-py`'s client is **sync** — every call is delegated via `run_in_threadpool` (`app/core/redis.py`), never run on the async loop, matching the M1 lesson.
- **Deferred (next M2 increment):** **cache stampede / thundering herd** — at TTL expiry, if N readers all miss simultaneously they all hit the DB, and the cache *amplifies* load instead of absorbing it. Options noted for later: single-flight request coalescing (one in-flight load, others await it) and/or a lock/`SET NX` around refill, plus TTL jitter. Documented here so we don't repeat it blind.
- **Interview answer:** *"Caching only works if it's shared — an in-process dict is a per-worker lie that serves stale data across restarts and rollouts. We use Redis with a read-through pattern: miss → load from DB → cache with TTL, hit → serve cache. Critically, every writer must invalidate the key (delete-on-write, not write-both), otherwise reads go stale until TTL. The trap is the stampede — at expiry all concurrent misses hit the DB at once, so you plan single-flight or locking around refill."*
- **Trap to avoid:** *"I'll cache every read and write through to the cache too so it stays fresh"* — double-writing the cache and DB splits your source of truth and diverges; and *"it's fine, Redis is fast"* without thinking about the stampede that a hot expiring key triggers.

---

## M2 — Caching — INTERVIEW FILE

**Q1: When would you use a cache, and when is it a trap?**
> I add a cache when a read is hot and expensive — called many times, cheap-ish to serve, and tolerable to serve slightly stale (profile hits, leaderboards, reference lookups). It's a trap when the data must be immediately consistent (account balance, appointment state) or when the read is rarely called — a cache adds a second system and two failure modes (staleness, stampede) for no win.

**Q2: How do you keep the cache consistent with the database?**
> Two halves. Writes invalidate (delete-on-write) so the next read lazily refetches — I never write both DB and cache, that diverges. Reads use read-through: hit serves, miss loads from the DB and stores with a TTL. TTL is the fallback time-bomb for paths I forgot to invalidate; it bounds staleness but also creates the stampede.

**Q3: What is a cache stampede and how do you stop it?**
> When a hot key expires, many concurrent readers all miss and each fires its own DB query — the cache turns one expected miss into N, spiking the DB exactly at the worst moment. Mitigations: single-flight (coalesce concurrent misses into one in-flight load), a lock/`SET NX` so only one refills, and TTL jitter so keys don't expire in lockstep.

**Trap answer to avoid:** *"The cache is just `if in dict: return; else: fetch; put in dict`"* — that's a per-process stale lie that ignores sharing and invalidations; and *"I'll just set a short TTL, problem solved"* — short TTL only shrinks (doesn't remove) the stale/expiry window and can *increase* stampede frequency.

---

## M4 — Real-time chat — INTERVIEW FILE (placeholder to be filled when we reach it)

*(Filled during M4. When we get there, ensure we cover: WebSocket vs HTTP long-polling tradeoffs, connection scaling, redis pub/sub as a cross-worker bus, at-least-once delivery of chat events, and message ordering.)*

---

> Appends: each of the six topics will get its own section below as we reach it. All future entries should maintain this format so the file stays grep-able.