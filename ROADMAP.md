# ROADMAP.md

Where we are in the plan — each milestone is one learning loop. We update this file every time we finish an increment.

**Status legend:** ⬜ planned · 🔄 in progress · ✅ done · 🚧 deferred

---

## Current status

> Phase **1 — M1 complete; M2 caching complete; M3: thread-per-request → Celery (acks_late + retries) done. M3 complete. M4 complete. M5: consumer (acks/prefetch/DLX) and publisher (confirms/mandatory/persistent, topic routing) done.** Next up: M5 backpressure + queue length limits.

---

## Milestone 0 — Foundation (scaffolding)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Author all core MD docs | ✅ | README, AGENTS, AI_WORKFLOW, LEARNING, ROADMAP, ARCHITECTURE |
| 2 | Decide learning topics + milestone mapping | ✅ | See `ARCHITECTURE.md` |
| 3 | `docker-compose.yml` (postgres, redis, rabbitmq) | ✅ | Stack: postgres:16 + redis:7 + rabbitmq:3-management, healthchecks + volumes |
| 4 | Python env / deps (`pyproject.toml` or `requirements`) | ✅ | `requirements.txt` + `.venv` |
| 5 | git init + `.gitignore` (secrets, `.env`, `__pycache__`) | ✅ | Repo git-initialized; branch/commit conventions in AGENTS §7 |
| 6 | Loop Engineer: gated agent loop + verify script (`LOOP.md`, `scripts/verify.ps1`) | ✅ | Any agent via AGENTS.md; Claude Code via `/loop-engineer` |

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
- [x] Cache stampede / thundering herd: why it happens — observed 20 concurrent misses → 20 datastore calls; fixed with single-flight `read_through` → 1 call (process-local; cross-worker lock deferred to M5/M8) ✅
- [x] TTL strategy: fixed TTL → synchronized expiry (200 keys, 1s window, 200 misses in busiest second) → ±10% jitter (13s window, busiest second 30) ✅
- [x] Serialization choices & memory limits: JSON `model_dump(mode="json")` + `decode_responses=True`; full Redis (`noeviction`) / Redis down → 500 → fail-open helpers + `maxmemory 128mb` `allkeys-lru` → 200 ✅ (circuit breaker + cross-worker lock deferred to M5/M8)
- [x] LEARNING.md log + interview section (stampede, invalidation, Redis as cache vs store vs broker, full/down cache)
- **M2 scope complete.**

---

## Milestone 3 — Celery & asynchronous jobs

**Learning 2:** Celery. **Learning 3 (partial):** Message queues via the broker. **Learning 4:** Asynchronous jobs.

- [x] **Naive:** ad-hoc `threading.Thread` per request for background work — welcome email on signup
- [x] **Observations:** API killed mid-send → 0/10 delivered; 50% SMTP failure → 3/10, no retries, only stderr tracebacks
- [x] Celery app + worker + RabbitMQ broker: `acks_late` + retries → worker killed mid-send 10/10, flaky 10/10 ✅ (result backend deferred: separate Redis, see ARCHITECTURE)
- [x] Idempotency: worker killed after send, before ack → 9 duplicate emails → provider-side idempotency key `welcome-{user_id}` → 0 duplicates (9 dedup hits) ✅
- [x] Chore: Bruno collection runs headless — field-level asserts, 4 malformed JSON bodies fixed, confirm→cancel order; 15/15 requests, 49/49 asserts; `verify.ps1 -Bruno` ✅
- [x] Async no-blocking flows: notifications (welcome email) ✅, reminders ✅, records CSV export (202 + job status + download) ✅
- [x] Task modeling: retries + backoff ✅, idempotency ✅, ETA/countdown ✅ — long-ETA reminders crashed the worker (consumer_timeout) and reminded a cancelled appointment → beat DB scan
- [x] `beat` = scheduled jobs: `send_due_reminders` scan (SKIP LOCKED, `reminder_sent_at`, key includes `scheduled_at`) ✅
- [x] Task state: naive `AsyncResult` over the cache Redis (unknown id → PENDING, IDOR, eviction → PENDING) → `export_jobs` table, owner-only 404s ✅
- [x] Observability: Flower with defaults saw 0/5 tasks and (API flag flipped) was open → task events on, `flowerconfig.py` basic auth from `.env`, broker_api queue depth → 5/5 tasks, 401 unauth ✅
- [x] LEARNING.md log + interview section (Celery architecture, broker vs backend, retries, idempotency, ETA, observability) ✅
- **M3 scope complete.** (Result backend deliberately unused: app state lives in Postgres; revisit if a loop needs chords.)

---

## Milestone 4 — Real-time chat (bidirectional communication)

**Learning 3 (deep):** Bidirectional communication over WebSockets + pub/sub across workers.

- [x] **Naive:** in-process WebSocket registry → cross-process delivery 0/10 (doctor on :8001, patient on :8002)
- [x] **Observations:** two processes = two registries; same-process 10/10, cross-process 0/10
- [x] Redis pub/sub as cross-process bus (subscribe confirmed before join) → cross-process 10/10 ✅
- [x] Auth + connection lifecycle over WebSockets; reconnect handling: first-frame auth, participant check → 1008, short-lived DB session, reconnect replay via `last_seen_id` (0/5 → 5/5) ✅
- [x] Chat history via Postgres (`chat_messages`, keyset-paged `GET /appointments/{id}/messages`) ✅ — 🚧 caching recent history deferred until M8 load tests show it's hot
- [x] Error handling: retried send 2× → 1× (unique sender+client_msg_id), ordering by DB id (strictly increasing), subscribe-then-replay overlap deduped by id ✅
- [x] LEARNING.md log + interview section (WebSocket vs SSE vs long-polling, horizontal scaling of sockets, redis pub/sub guarantees — what it does NOT give you) ✅
- **M4 scope complete** (history caching deferred).

---

## Milestone 5 — RabbitMQ deep dive (message queue masterclass)

**Learning 3 (complete).** Now we own RabbitMQ, not just use it through Celery.

- [x] RabbitMQ concepts: topic exchange `cardicheck.events` with notifications (`appointment.*`) + audit (`appointment.#`, `user.#`) bindings; fanout DLX; direct/headers explained ✅
- [x] Publisher side: naive per-publish connection (102 ms), silent drop on typo, 0/20 after broker restart → confirms + mandatory (UnroutableError) + persistent (20/20) ✅
- [x] Manual publish/consume (pika): auto-ack + no prefetch lost 86/99 on kill and 49/99 on poison → manual ack, prefetch 10, reject → DLX/DLQ → 99/99, poison dead-lettered ✅
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
| 2026-09-28 | M0 | Loop Engineer: `LOOP.md` gated loop (Plan→Implement→Test→Verify→Document→Repeat) + `scripts/verify.ps1` + `/loop-engineer` skill; linked from AGENTS.md | ✅ |
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
| 2026-09-02 | M2 | Caching (2nd increment): cache stampede/thundering herd — observed 20 concurrent misses → 20 datastore calls (in-process, deterministic) → single-flight `read_through` (cache.py) → 1 call; process-local scope + cross-worker lock deferred | ✅ |
| 2026-09-28 | M2 | TTL strategy: fixed TTL → synchronized expiry (200 keys in 1s) → ±10% jitter in `cache_set` (13s window, peak 200 → 30) | ✅ |
| 2026-09-28 | M2 | Memory limits + fail-open: full Redis (`noeviction`) and Redis down → `GET /users/me` 500 → fail-open cache helpers (0.5s timeouts) + `maxmemory 128mb allkeys-lru` → 200 in all three cases | ✅ |
| 2026-09-28 | M3 | Welcome email: naive thread-per-request (crash 0/10, flaky 3/10) → Celery task on RabbitMQ with acks_late + retries (crash 10/10, flaky 10/10, 0 dupes); found kombu localhost→127.0.0.1 + silent publish-after-commit loss, competing consumers, thread-unsafe outbox | ✅ |
| 2026-09-28 | M3 | Idempotency: worker killed between provider accept and ack → 9/10 duplicate emails → provider-enforced key `welcome-{user_id}` (exclusive create) → 0 duplicates, 9 dedup hits | ✅ |
| 2026-09-28 | M1 | Bruno collection as contract: CLI run exposed substring asserts invalid in CLI 4.2.0, 4 malformed JSON bodies (422), cancel-before-confirm order → field asserts, fixed bodies/order (15/15, 49/49) + `verify.ps1 -Bruno` | ✅ |
| 2026-09-28 | M3 | Reminders: naive long-ETA tasks (worker crashed on consumer_timeout, 0/3 sent; with 30 min timeout the cancelled appointment was reminded and the rescheduled one got the stale time) → `reminder_sent_at` migration + beat scan with SKIP LOCKED + scheduled_at-keyed idempotency (A/B/C all correct) + reschedule Bruno example | ✅ |
| 2026-09-28 | M3 | Export jobs: naive AsyncResult status on the cache Redis (unknown id → 200 PENDING, other user read result, eviction → PENDING) → `export_jobs` table (migration `cdac0e353a2c`, enum downgrade fixed) + 202/Location + owner-only 404 + download; Bruno 20/20 | ✅ |
| 2026-09-28 | M3 | Observability: Flower defaults saw 0/5 tasks, no queue depth, and with the API flag flipped UI+API were open → task events, `flowerconfig.py` (basic auth + broker_api from settings) → 5/5 tasks with runtimes, queue depth, 401 unauth. **M3 complete** | ✅ |
| 2026-09-28 | M4 | WS chat: naive in-process registry (cross-process 0/10) → Redis pub/sub hub (10/10); first-frame auth (no JWT in logs), 1008 for outsiders; Bruno ws example (GUI-only, CLI excluded by tag); export Bruno example now polls (3/3 cold) | ✅ |
| 2026-09-28 | M4 | Chat history: pub/sub only (reconnect catch-up 0/5, retried send 2×, no ids) → `chat_messages` log (migration `620d4cee556c`) + subscribe-then-replay `last_seen_id` (5/5) + unique sender+client_msg_id (1×) + keyset history endpoint; Bruno 21/21. **M4 complete** | ✅ |
| 2026-09-28 | M5 | pika consumer: naive auto-ack + unbounded prefetch (kill → 86/99 lost; poison → crash, 49 lost) → manual ack + prefetch 10 + reject→DLX (99/99, DLQ 1, 0 crashes); queue-arg redeclare PRECONDITION_FAILED observed | ✅ |
| 2026-09-28 | M5 | Event publisher: naive per-publish connection (102 ms, typo silently dropped, 0/20 after broker restart) → long-lived confirmed channel, mandatory, persistent (56 ms, UnroutableError, 20/20); API emits appointment.booked/cancelled end to end; latency breakdown (confirm round-trip ~48 ms) | ✅ |
