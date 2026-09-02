# ROADMAP.md

Where we are in the plan — each milestone is one learning loop. We update this file every time we finish an increment.

**Status legend:** ⬜ planned · 🔄 in progress · ✅ done · 🚧 deferred

---

## Current status

> Phase **1 — M1 complete, M2 in progress (first caching increment done: naive in-process dict → Redis read-through + write-invalidation on profile reads).** Next up: stampede/single-flight + serialization/TTL refinement.

---

## Milestone 0 — Foundation (scaffolding)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Author all core MD docs | ✅ | README, AGENTS, AI_WORKFLOW, LEARNING, ROADMAP, ARCHITECTURE |
| 2 | Decide learning topics + milestone mapping | ✅ | See `ARCHITECTURE.md` |
| 3 | `docker-compose.yml` (postgres, redis, rabbitmq) | ✅ | Stack: postgres:16 + redis:7 + rabbitmq:3-management, healthchecks + volumes |
| 4 | Python env / deps (`pyproject.toml` or `requirements`) | ✅ | `requirements.txt` + `.venv` |
| 5 | git init + `.gitignore` (secrets, `.env`, `__pycache__`) | ✅ | Repo git-initialized; branch/commit conventions in AGENTS §7 |

---

## Milestone 1 — Auth & basic CRUD (FastAPI fundamentals)

**Learning 0:** sync vs async in one app; sync DB call inside async endpoint = first deliberate mistake.

- [x] Project skeleton: `app/` package, settings, routers, database module
- [x] Docker stack up: postgres + redis (+ rabbitmq later) — all healthy
- [x] SQLAlchemy async + Alembic migrations wired — User model, first migration applied
- [ ] Signup (✅ done) / **Login + JWT** (✅ done — increment `feat/login-jwt`)
- [x] **Naive:** sync `Session` in async endpoint → observe event-loop blocking — probe blocked ~1085ms
- [x] **Fix:** `AsyncSession` dependency injection — probe ~24ms, loop free
- [x] Bruno collection: directory + health/signup examples; next endpoints add theirs
- [x] **Naive:** `verify_password` (argon2 ≈31ms CPU) directly in async handler → observe CPU-blocking — 8×login burst ~413ms, logins serialized
- [x] **Fix:** `run_in_threadpool` for hash/verify — loop free during burst (probe ~23ms), honest: argon2 still ~1.4x parallel
- [x] JWT: minimal claims (`sub`/`iat`/`exp`, HS256), env secret, `get_current_user` re-reads user from DB, protected `GET /users/me`
- [x] Bruno flow: signup → login → me (chained vars) — verified live
- [x] **Envelope + error handling:** one response shape (data/meta/error + stable codes 409/401/422/404/500) via `ApiResponse[T]` + centralized handlers; all endpoints + Bruno asserts updated — verified live
- [ ] CRUD for profiles / appointments / medical records (fictional data only)
- [x] **Appointments CRUD slice:** migration `e30a4c8a53e0` + `POST /appointments` (role-based booking) + naive `GET` (1+N) observed **601 execs/388ms → fixed** pagination + `selectinload` (~4 execs/7ms) + `meta.pagination` — verified live
- [x] **Appointment cancel slice:** naive (no authz/transitions) → fixed: participant-only 403, COMPLETED 409, idempotent 200 no-op, + status filter — verified live
- [x] **Medical records CRUD slice:** naive (leaky GET, wiping PATCH, ungated DELETE) → fixed: ownership reads (403 RECORD_ACCESS_DENIED), creator-only writes, PATCH `exclude_unset` partial semantics, 204 DELETE + silent-500 logging fix — verified live
- [x] **Appointment update/confirm + profiles CRUD slice:** naive (patient confirm, past reschedule, terminal edits, patient specialty) → fixed: doctor-only 403 confirm, future-only 400, terminal 409, role-aware profile 403; `users.phone` migration; `PATCH /users/me` — verified live
- [x] **Validation slice:** static shape rules (strip whitespace, blank-text 422, doctor-specialty required via model_validator) in schemas; temporal rule (15-min lead → 400) in handler; bonus fix — envelope sanitizes Pydantic `ctx` (was crashing its own 422 into a 500) — verified live
- **M1 scope complete — every planned feature shipped, Bruno-covered, and logged.**
- [x] LEARNING.md log + interview section for "cancel state machine / idempotency" — ✔ entry added
- [x] LEARNING.md log + interview section for "sync-in-async pitfall" — ✔ entry added
- [x] LEARNING.md log + interview section for "cpu-bound work off the loop (argon2 + threadpool)" — ✔ entry added

---

## Milestone 2 — Caching with Redis

**Learning 1:** Caching. Popular caveats: cache stampede, invalidation, TTL vs event-driven invalidation, serialization.

- [x] **Naive:** "caching" = dictionary in process memory → lost on deploy, no sharing across workers — observed stale-after-write (`GET /users/me` served old name after PATCH)
- [x] **Observations:** stale data after writes (same-process, reproduced deterministically); cache lost on restart / not shared across workers (reasoned, by-design lookup)
- [x] Redis as cache: read-through pattern on hot queries (profile lookups) — `GET /users/me`, key `profile:{user_id}` — observe script: miss ~26ms vs hit ~5ms
- [x] Cache invalidation on write: `PATCH /users/me` deletes the key (delete-over-update), read-through re-fetches fresh on next read — verified key gone after PATCH
- [ ] Cache stampede / thundering herd: why it happens, single-flight / lock options (documented in LEARNING.md; implementation deferred — see increment)
- [ ] Serialization choices & memory limits, TTL strategy (partly covered: JSON `model_dump(mode="json")`, `decode_responses=True`, config TTL; stampede/single-flight + keyset TTL refinement deferred)
- [ ] LEARNING.md log + interview section (stampede, invalidation, Redis as cache vs store vs broker)

---

## Milestone 3 — Celery & asynchronous jobs

**Learning 2:** Celery. **Learning 3 (partial):** Message queues via the broker. **Learning 4:** Asynchronous jobs.

- [ ] **Naive:** ad-hoc `threading.Thread` per request for background work (e.g. "send email confirmation")
- [ ] **Observations:** jobs lost when process dies, no retries, can't scale, unobservable
- [ ] Celery app, worker process, broker (rabbitmq) + result backend (redis)
- [ ] Async no-blocking flows: notifications, PDF/export generation, reminders
- [ ] Task modeling: signatures, `apply_async`, ETA/countdown, retries + backoff, idempotency
- [ ] `beat` = scheduled jobs (e.g. daily reminder)
- [ ] Observability: flower or similar; task state/tracebacks
- [ ] LEARNING.md log + interview section (Celery architecture, broker vs backend, retries, idempotency, ETA)

---

## Milestone 4 — Real-time chat (bidirectional communication)

**Learning 3 (deep):** Bidirectional communication over WebSockets + pub/sub across workers.

- [ ] **Naive:** in-process WebSocket registry in one uvicorn worker → messages "disappear" when connected to a different worker
- [ ] **Observations:** two workers = two registries; the "echo" works only on one port/worker
- [ ] Redis pub/sub as cross-process bus; message broadcast pattern
- [ ] Auth + connection lifecycle over WebSockets; reconnect handling
- [ ] Chat history via Postgres (and caching read of recent history — unifies M2)
- [ ] Error handling: disconnects mid-message, ordering, at-least-once vs duplicates
- [ ] LEARNING.md log + interview section (WebSocket vs SSE vs long-polling, horizontal scaling of sockets, redis pub/sub guarantees — what it does NOT give you)

---

## Milestone 5 — RabbitMQ deep dive (message queue masterclass)

**Learning 3 (complete).** Now we own RabbitMQ, not just use it through Celery.

- [ ] RabbitMQ concepts: exchanges, queues, bindings, routing keys; `direct`, `fanout`, `topic`, `headers`
- [ ] Manual publish/consume (pika) — message `ack`/`nack`, `reject`, dead-letter queues, prefetch
- [ ] Delivery semantics: at-least-once in practice → dedup/idempotency with Redis
- [ ] Backpressure, flow control, queue length monitoring
- [ ] Relating it back: show exactly which parts Celery abstracts and which it doesn't
- [ ] LEARNING.md log + interview section (delivery guarantees, DLQ, prefetch, when to use RabbitMQ vs Kafka vs Redis pub/sub)

---

## Milestone 6 — Microservices / distributed systems

**Learning 2 (deep).** Split the monolith; deal with facts of distributed life.

- [ ] **Naive:** "microservice" = monolith copied into more containers sharing one DB/port conflict → observation: coupling, race conditions
- [ ] Service boundaries: auth, patients/doctors (core), chat, notifications
- [ ] Each service owns its data — no shared SQL tables across services
- [ ] Inter-service communication: sync (HTTP/REST) vs async (events on RabbitMQ); the duality
- [ ] Failures that only exist in distributed systems: timeouts, retries, partial failure, idempotency, saga patterns for multi-step transactions
- [ ] Event-driven flow: "appointment booked" event → chat created, notifications sent, reminder scheduled
- [ ] API gateway + service discovery basics; observability (structured logs, tracing)
- [ ] LEARNING.md log + interview section (sync vs async comms, saga, exactly-once is impossible, 2PC vs saga)

---

## Milestone 7 — Voice & video calling

**Learning 5 (final stretch).** Real-time media over WebRTC — the hardest topic, done last.

- [ ] WebRTC fundamentals: signaling, SDP, ICE/STUN/TURN; media over UDP vs TCP
- [ ] Signaling server in FastAPI (WebSocket for SDP/ICE exchange)
- [ ] 1-on-1 calls; room management; Identity on calls
- [ ] Media server options (SFU like mediasoup/livekit) — when a client-to-client P2P mesh stops working (N+1 calls)
- [ ] Why this project covers it: forces real-time, stateful, multi-peer reasoning
- [ ] LEARNING.md log + interview section (WebRTC flow, STUN vs TURN, mesh vs SFU, UDP + retransmission vs TCP)

---

## Milestone 8 — Senior hardening / review sweep

- [ ] Dedup, retries, circuit breakers, rate limiting, backpressure — revisit each topic's caveat
- [ ] Observability: structured logs, metrics, distributed tracing across services
- [ ] Seeding/load-testing the failure modes we only simulated earlier
- [ ] Revise all `LEARNING.md` interview sections into a final interview-prep cheat sheet
- [ ] Full interview drill: "walk me through your architecture" answer

---

## Topic → milestone map (for quick reference)

| Learning topic | Milestone(s) |
|----------------|--------------|
| Caching | M2 |
| Microservices / distributed systems | M6 |
| Bidirectional communication | M4 (+ M7 signaling) |
| Message queues / RabbitMQ | M3 (broker) + M5 (deep) |
| Celery | M3 |
| Asynchronous jobs | M3 |

---

## Increment log

| Date | Milestone | Increment | Status |
|------|-----------|-----------|--------|
| 2026-09-01 | M0 | Docs scaffolded | ✅ |
| 2026-09-01 | M0/M1 | git init, docker compose stack (postgres/redis/rabbitmq), FastAPI + async DB skeleton | ✅ |
| 2026-09-01 | M1 | User model + Alembic async migrations (first migration applied, psql verified) | ✅ |
| 2026-09-01 | M1 | naive signup (sync session + sleep) → observed probe blocked ~1085ms → `AsyncSession` DI | ✅ |
| 2026-09-01 | M1 | Bruno collection: health + signup (dynamic vars) | ✅ |
| 2026-09-01 | M1 | Login + JWT: naive argon2-in-loop → observed CPU burst ~413ms/8 → threadpool fix + `GET /users/me` + Bruno flow | ✅ |
| 2026-09-01 | M1 | Bruno auth roots: Public (no auth) vs Protected (inherited bearer) + var lifecycle | ✅ |
| 2026-09-01 | M1 | Response envelope + centralized exception handlers (409/401/422/404/500) — all endpoints + Bruno asserts updated | ✅ |
| 2026-09-01 | M1 | Appointments CRUD slice: migration + booking + naive 1+N list (601 execs/388ms) → pagination + selectinload (~4/7ms) + meta.pagination | ✅ |
| 2026-09-01 | M1 | Appointment cancel: naive (no authz/transitions) → participant 403 / completed 409 / idempotent 200 + status filter | ✅ |
| 2026-09-02 | M1 | Records CRUD: naive (leaky GET, wiping PATCH, ungated DELETE) → ownership 403s, PATCH exclude_unset, 204 DELETE, silent-500 logging fix | ✅ |
| 2026-09-02 | M1 | Appointment update/confirm + profiles CRUD: naive (patient confirm/past reschedule/terminal edits/patient specialty) → doctor-only 403, future 400, terminal 409, role-aware specialty; users.phone migration | ✅ |
| 2026-09-02 | M1 | Validation slicing: strip/blank 422s + doctor-specialty in schema, 15-min lead 400 in handler; envelope ctx-sanitized (validator 422 was crashing to 500) | ✅ |
| 2026-09-02 | M2 | Caching (1st increment): naive in-process dict on `GET /users/me` → observed stale-after-write (served old name after PATCH) → Redis read-through (`profile:{id}`) + write-invalidation on PATCH; observe: miss ~26ms vs hit ~5ms | ✅ |