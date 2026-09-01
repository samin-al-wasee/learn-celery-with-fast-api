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
- **M1 — Auth & CRUD** (empty — add entries)
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

---

## M4 — Real-time chat — INTERVIEW FILE (placeholder to be filled when we reach it)

*(Filled during M4. When we get there, ensure we cover: WebSocket vs HTTP long-polling tradeoffs, connection scaling, redis pub/sub as a cross-worker bus, at-least-once delivery of chat events, and message ordering.)*

---

> Appends: each of the six topics will get its own section below as we reach it. All future entries should maintain this format so the file stays grep-able.