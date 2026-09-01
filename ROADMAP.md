# ROADMAP.md

Where we are in the plan — each milestone is one learning loop. We update this file every time we finish an increment.

**Status legend:** ⬜ planned · 🔄 in progress · ✅ done · 🚧 deferred

---

## Current status

> Phase **0 — Foundation**: docs scaffolded. No application code yet. **Next up: M1.**

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
- [ ] Signup (✅ done) / **Login + JWT** — next increment
- [x] **Naive:** sync `Session` in async endpoint → observe event-loop blocking — probe blocked ~1085ms
- [x] **Fix:** `AsyncSession` dependency injection — probe ~24ms, loop free
- [ ] CRUD for profiles / appointments / medical records (fictional data only)
- [ ] Pydantic validation, consistent response envelope, error handling
- [x] LEARNING.md log + interview section for "sync-in-async pitfall" — ✔ entry added

---

## Milestone 2 — Caching with Redis

**Learning 1:** Caching. Popular caveats: cache stampede, invalidation, TTL vs event-driven invalidation, serialization.

- [ ] **Naive:** "caching" = dictionary in process memory → lost on deploy, no sharing across workers
- [ ] **Observations:** multi-worker divergence, stale data after writes
- [ ] Redis as cache: read-through pattern on hot queries (profile lookups, recently-viewed)
- [ ] Cache invalidation on write (delete vs update; versioned keys)
- [ ] Cache stampede / thundering herd: why it happens, single-flight / lock options
- [ ] Serialization choices & memory limits, TTL strategy
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