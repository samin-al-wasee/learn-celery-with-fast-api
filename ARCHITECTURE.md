# ARCHITECTURE.md

Current stack, data flow, and the reasoning behind every architectural decision. This file deliberately evolves with us: each milestone rewrites it as we refactor (monolith → microservices).

---

## Stack (declared, not yet running)

| Layer | Choice | Why |
|-------|--------|-----|
| API framework | **FastAPI** (Python 3.11+) | Async-first, auto OpenAPI docs, Pydantic validation |
| ORM | **SQLAlchemy 2.x (async)** | Standard async ORM; migrations with Alembic |
| Migrations | **Alembic** | Versioned schema changes; never `create_all` in prod path |
| Validation/schemas | **Pydantic v2** | FastAPI-native; runtime validation in and out |
| Primary DB | **PostgreSQL** | Strong consistency for healthcare-ish data, JSONB, mature operations |
| Cache / result backend | **Redis** | In-memory key-value; also used for pub/sub (chat bus) |
| Message broker | **RabbitMQ** | AMQP features Celery needs (acks, routing, DLQs); also our own event bus |
| Background tasks | **Celery** (+ Flower for observability) | Distributed task queue on a real broker |
| Realtime messaging | **WebSockets (FastAPI)** → Redis pub/sub across workers | Bidirectional, low-latency chat (M4) |
| Calls (future) | **WebRTC** + SFU (mediasoup/LiveKit) | P2P first, SFU when scaling (M7) |
| Infra | **Docker Compose** (all services containerized) | Parity with production topology on one machine |

### Planned Docker services
```
┌───────────────────────────────────────────────────────────────────────┐
│                         docker compose                               │
│                                                                       │
│   ┌─────────────┐        ┌──────────────┐        ┌───────────────┐   │
│   │   api        │  ───▶ │  postgres    │        │   redis       │   │
│   │ (FastAPI)    │  ───▶ │   :5432      │        │   :6379       │   │
│   └──────┬───────┘  ws   └──────────────┘        └──────┬────────┘   │
│          │       (M4+)                                  │ pub/sub    │
│          ▼                                               ▼           │
│   ┌─────────────┐        ┌───────────────────────────────────────┐   │
│   │  celery     │  ───▶  │  rabbitmq      :5672                  │   │
│   │  worker(s)  │  ◀───  │  (AMQP broker + event bus, > M3)     │   │
│   └─────────────┘        └───────────────────────────────────────┘   │
│                                                                       │
│   (services: api, worker, postgres, redis, rabbitmq — at minimum)    │
└───────────────────────────────────────────────────────────────────────┘
```

---

## Evolution of the architecture (the learning journey)

### Phase 0 — Foundation (current) ✅
No code. Docs + process only.

### Phase 1 — Monolith, naive (planned M1/M2)
Single FastAPI app talking to Postgres + Redis. This is where we deliberately make the first mistakes:
- sync DB session in an async endpoint
- process-local "cache" dict
- ad-hoc background thread for jobs

**Diagram:**
```
Client ──▶ FastAPI (one process) ──▶ Postgres
                                └──▶ ("cache": process dict)
                                └──▶ ("background": threading.Thread)
```

### Phase 2 — Async-first monolith (M3, done)
Introduce Celery worker + RabbitMQ broker + Redis result backend.

**Current (M3):** `POST /auth/signup` enqueues `send_welcome_email` (`app/worker/tasks.py`) on RabbitMQ; workers run with `acks_late` + `reject_on_worker_lost` + prefetch 1 (at-least-once), autoretry with exponential backoff + jitter. No result backend yet (`task_ignore_result`). User-facing job status lives in Postgres (`export_jobs`: owner, `queued → running → succeeded | failed`), never in Celery's result backend. Reminders are **not** ETA tasks: celery **beat** runs `send_due_reminders` every `REMINDER_SCAN_SECONDS`, which reads due appointments from Postgres (`reminder_sent_at IS NULL`, `FOR UPDATE SKIP LOCKED`), sends with key `reminder-{id}-{scheduled_at}`, and marks them; reschedule clears the marker. Side effects carry an idempotency key from the business event (`welcome-{user_id}`) that the provider enforces, so redelivery can't double-send. Known gap: publish happens after the DB commit, so a broker outage loses the job (logged, not retried) → transactional outbox in M6.
```
                  ┌────────────────────────────┐
                  │  FastAPI  (request path)   │  ──▶ Postgres, Redis
                  └────────────┬───────────────┘
                               │  task (JSON payload)
                               ▼
                  RabbitMQ ──▶ Celery worker(s) ──▶ Postgres/Redis/API calls
                  (broker)     (retries, ETA, beat schedule)
```

### Phase 3 — Realtime chat (planned M4)
WebSockets terminate in FastAPI; Redis pub/sub carries messages across workers so any worker can reach any connected client.
```
 Client A ──ws──▶ Worker1 ──publish──▶ Redis pub/sub ──sub──▶ Worker2 ──ws──▶ Client B
```
Redis pub/sub is a *bus*, not a queue — no persistence, no acks. That limitation becomes our lesson.

**Current (M4):** `WS /api/v1/ws/appointments/{id}/chat` — first-frame auth, participants only (1008 otherwise). `app/realtime/hub.py` publishes to `chat:appointment:{id}`; each API process subscribes once per room with local sockets (subscription confirmed before join returns) and forwards to them. Messages are not persisted yet.

### Phase 4 — Microservices (planned M6)
Broken into services, each owning its data:
```
Client ──▶ API Gateway
              │
   ┌──────────┼──────────────┬──────────────┐
   ▼          ▼              ▼              ▼
 auth     core (patients/  chat          notifications
 service     doctors)      service          service
   │          │              │              │
 (own DB)  (own DB)      (own DB)      (own DB)
   └──────────┴────────── RabbitMQ event bus ─────┘
```
Events (e.g. `appointment.booked`) replace direct calls between services. Sync HTTP calls remain only where immediate response is required. Saga patterns handle multi-step writes.

### Phase 5 — Calls (planned M7)
WebRTC signaling over WebSocket inside the chat service; media flows P2P (mesh) initially, then via SFU when group calls need it.

---

## Cross-cutting decisions

### Request path vs worker path (async boundary)
- HTTP responses must be **fast** → anything slow/side-effecting goes to Celery.
- Event loop stays free; workers do the hard lifting; blocking DB calls never touch the async loop.
- Rationale/lesson: an async server's concurrency is *not* free CPU — blocking calls defeat the event loop.

### Consistency model
- Primary store: PostgreSQL (strong consistency, ACID for core medical-ish data).
- Cache + pub/sub: Redis (best effort, TTL'd, eventual, invalidation via events where possible).
- After M5 we'll document our exact tradeoff: for latency-sensitive reads we accept stale-by-TTL; for correctness (appointments, medications) we always read-through.
- **Current (M2):** profile reads are read-through cached in Redis (`profile:{user_id}`, TTL = `CACHE_TTL_SECONDS` ± `CACHE_TTL_JITTER` random spread, default ±10%), invalidated on write (`PATCH /users/me` deletes the key). Accepts: every cached read is stale-by-TTL after a write *until* the next write invalidates — mismatch resolved by delete-on-write, so a write always forces the next read to refetch fresh. Read path runs through a **single-flight** `read_through` helper (`app/core/cache.py`) so concurrent misses for one key coalesce into a single datastore load (stampede guard). Scope: single-flight is process-local; a cross-worker stampede guard (Redis lock / `SET NX`) is deferred to M5/M8.

### Messaging model (after M3)
- **Command/job queue (Celery):** durable, acked, retried — for work the system must complete.
- **Event bus (RabbitMQ topic/fanout, M5):** fire-and-forget notifications "something happened"; consumers decide what to do.
- **Redis pub/sub (M4):** transient realtime fan-out to connected sockets only.

### Delivery semantics (to be proven in M3/M5)
- Target: **at-least-once** everywhere → every consumer that mutates state must be **idempotent**. Exactly-once is impossible in distributed systems; we prove why.
- DLQ for poison messages; dead-letter analysis as a debugging tool.

### Data ownership rule (from M6)
- A table belongs to exactly one service. Cross-service reads go through that service's API or via events. No shared-SQL-table shortcuts.

---

## Decision log (append-only)

| Date | Decision | Alternative rejected | Why (BECAUSE) |
|------|----------|----------------------|---------------|
| 2026-09-01 | Learn on a monolith first (M1–M5), split later (M6) | Microservices day one | Distributed debugging overlaps every other topic; we learn basics with a single moving part, then learn distributed failure *deliberately* when complexity belongs to the problem, not the setup |
| 2026-09-01 | RabbitMQ as Celery broker | Redis as broker | RabbitMQ gives durable queues/acks/DLQ — needed for interview-grade understanding of queue semantics; Redis broker is a dev convenience |
| 2026-09-01 | Redis as result backend | — | Results are ephemeral; Redis eviction model matches "store last N results" reality |
| 2026-09-01 | Postgres as source of truth even for chat history | Redis for history | Redis is memory-bound; history must be durable, cursor-paged; Redis cache on top (M2 merge) |
| 2026-09-01 | WebRTC (P2P→SFU) for calls in M7 | Prebuilt SDK | P2P→SFU is the classic interview narrative; forces real-time reasoning |
| 2026-09-02 | Redis as the shared cache (read-through) | In-process dict (M1/M2 naive) | A cache must be shared across workers and survive restarts to mean anything; otherwise it silently serves stale, per-process data. Sync `redis-py` calls are delegated to the threadpool (never the loop). |
| 2026-09-28 | Cache Redis: `maxmemory 128mb` + `allkeys-lru`; cache helpers fail-open (Redis error = miss, logged) with 0.5s socket timeouts | Default unbounded memory + `noeviction`; errors propagate | A cache is an optimization: bounded memory and eviction keep writes succeeding, and fail-open means a full or down Redis degrades latency instead of returning 500. **Consequence for M3:** `allkeys-lru` can evict Celery results, so the result backend must not share this instance's eviction policy (separate instance/policy). |

| 2026-09-28 | Celery tasks ack late (`acks_late`, `reject_on_worker_lost`, prefetch 1) with autoretry + backoff | Default early ack; threads in the API | A worker crash must redeliver, not drop, the job (observed 0/10 → 10/10). Cost: at-least-once, so tasks must be idempotent. |
| 2026-09-28 | Scheduled work = beat + DB state scan; ETA/countdown only for short delays | Long-ETA Celery tasks per reminder | ETA messages freeze booking-time data and sit unacked in worker RAM, tripping RabbitMQ `consumer_timeout` (observed crash); the DB is the source of truth for what's due |
| 2026-09-28 | Async job status in a DB table with owner + explicit states; no Celery result backend for app state | `AsyncResult(task_id).state` on Redis | Observed: unknown ids read as PENDING, any user could read any result, eviction turned a finished job back into PENDING. App state needs ownership and durability. |
| 2026-09-28 | Task events on + Flower behind basic auth (`flowerconfig.py`), queue depth from RabbitMQ management API | Flower with defaults | Defaults showed 0 tasks and no backlog; opened up, it exposed task args. Flower is a live, in-memory view; history lives in logs/DB. |
| 2026-09-28 | Chat fan-out via Redis pub/sub, one subscription per active room per process; WS auth in the first frame | In-process registry; `?token=` in the WS URL | Observed cross-process 0/10 with the registry; uvicorn logs the full WS path, so a query token would be written to logs |

*(Every later milestone appends here with a BECAUSE.)*

---

## Operational notes

- **Ports (compose, planned):** api:8000 · postgres:5432 · redis:6379 · rabbitmq:5672 (+ management 15672) · flower:5555
- **Secrets:** `.env` (gitignored); never in code.
- **Fictional data only.** No real patient information anywhere in this repo.
- **Migrations:** `alembic upgrade head` after each model change; `alembic revision --autogenerate -m "..."` to create.

## Origin of terms used here
If an interview answer uses a term below, it should link to the section where we learned it:
| Term | Where we learn it |
|------|-------------------|
| Celery broker vs backend | M3 |
| Idempotency / at-least-once | M3, M5, M6 |
| Redis pub/sub ≠ queue | M4 |
| Exchange/queue/binding | M5 |
| Saga / distributed transaction | M6 |
| SFU vs mesh / STUN vs TURN | M7 |