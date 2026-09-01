# AGENTS.md

Rules for **any AI agent (or collaborator)** working in this repository.

## 1. This is a LEARNING project, not a normal app

The product features exist to force us through the learning topics. Do not "just build it correctly." Follow the workflow in [`AI_WORKFLOW.md`](AI_WORKFLOW.md):

1. **Naive version first** — build the simplest thing that works.
2. **Run / observe / fail** — verify and document the failure mode.
3. **Explain the problem** — WHY does this break at scale / under load / in production?
4. **Refactor to best practice** — with rationale (BECAUSE ...).
5. **Log it** — every step goes into [`LEARNING.md`](LEARNING.md).

## 2. Always read the docs before acting

Before starting any task, read:

- `README.md` — overview
- `AI_WORKFLOW.md` — the learning loop you must follow
- `LEARNING.md` — existing mistakes and lessons (so we do not repeat them)
- `ROADMAP.md` — where we are in the plan
- `ARCHITECTURE.md` — current stack and decisions
- `AGENTS.md` — you are here

If you are about to repeat a mistake already logged in `LEARNING.md`, stop and say so.

## 3. Every task must include a LEARNING.md update

"If it didn't get logged, it didn't get learned." When you finish any meaningful task:

- Add a dated entry to the **per-milestone log** in `LEARNING.md`.
- It must cover: what we did, naïve attempt + observed problem, lesson, fix / best practice, "interview answer" one-liner.
- Keep entries concise — bullets, not essays.

## 4. Teaching style when explaining

**Every single response about anything we do — code, concept, tool, setup, a yes/no question — must use the message format below. Do not answer outside it.** The labels must be explicit every time, never implied. If a label doesn't apply, state the ones that do; never answer without the format.

Follow the message framing from `AI_WORKFLOW.md`:

- **WE_NEED** → what the goal is and why
- **INITIAL** → the naive approach we'll try / what a beginner would do
- **PROBLEMS** → what breaks and why
- **AVOID** → the trap / anti-pattern
- **BEST_PRACTICE** → the right way
- **BECAUSE** → the reasoning
- **TRADEOFFS** → when we can still do the simple thing and what it costs

Be explicit, concise, concrete. Give the `file:line` references.

## 5. Coding conventions (once we write code)

- **Python 3.11+**, type hints everywhere.
- **FastAPI** for the API. **Celery** for background tasks. **SQLAlchemy (async) + Alembic** for DB access/migrations. **Pydantic** for schemas/validation.
- Use `AsyncSession` against PostgreSQL; never run blocking DB calls in the async event loop.
- API responses: consistent envelope; HTTP status codes from `httpx`/Starlette constants.
- Secrets/config: **never hardcode**. Use env vars / `.env` (gitignored).
- Never log passwords, tokens, or patient health data.
- Run migrations via Alembic; avoid `Base.metadata.create_all` in production paths.
- Follow existing file structure; mimic surrounding code style for new files.
- **Every endpoint (HTTP, WebSocket, SSE, anything) ships with a Bruno example** under `api/collection/`, mirroring the route — filename matches the action, URL uses `{{baseUrl}}`, realistic JSON body, and asserts. No endpoint merges to `main` without its collection example.
- Wire tasks through Celery app instance; do not create ad-hoc threads inside FastAPI for background work (that's the naive mistake we document first).
- **No code comments unless they capture a learning insight** — we prefer explanations live in `LEARNING.md`.

## 6. Commands we use (verify with the roadmap / architecture before running)

```powershell
docker compose up -d                       # infra: postgres, redis, rabbitmq
docker compose down                        # stop
docker compose ps                          # status
uvicorn app.main:app --reload              # API (from project root)
celery -A app.worker.celery_app worker --loglevel=info
alembic upgrade head                       # apply migrations
pytest                                     # run tests (once tests exist)
```

Prefer PowerShell for this repo. Do not `cd` inside commands — use the `workdir` parameter.

## 7. Git workflow

- **Never work on `main`.** Every feature/change gets its own branch, created off an up-to-date `main`.
- **One branch per feature.** Branch names: `<type>/<short-desc>` (e.g. `feat/celery-worker`, `fix/ws-conn-leak`, `docs/learning-log`).
- **Small, meaningful commits only.** Each commit is one unit of work and touches **fewer than 10 files**. No huge/"catch-all" commits. If a change grows past that, split it into multiple commits.
- **Commit message format:** `[<type>] Title` on the first line, then an optional description body (what/why), e.g.:
  ```
  [feat] Add Celery worker with RabbitMQ broker

  - wire celery app + worker entrypoint
  - configure broker/backend from env
  - add Flower for observability
  ```
- **Merge back with fast-forward to `main`.** After finishing the branch (tested + logged in `LEARNING.md`), update it against `main` (rebase so history stays linear) then merge with `--ff-only`. `main` always ends up on an exact branch tip; we never merge-commit.
- Keep feature branches short-lived; merge them as soon as the increment is done, then delete the branch.
- Suggested `<type>` values: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `infra`.

## 8. Warnings / guardrails

- **Do not commit / push / open PRs** unless the user explicitly asks.
- **Never merge or branch on your own** unless the user asks — propose the branch + commit plan and get confirmation.
- Keep patient-data scenarios fictional. Real medical data never enters this repo.
- When a task says "plan first," produce the AI_WORKFLOW plan and get confirmation before writing code.
- Prefer small, reviewable increments. Each increment updates `ROADMAP.md` status and `LEARNING.md`.

## 9. Interview-prep duty

Every learning topic must end with an **Interview File** section (even a short one) in `LEARNING.md` containing:

- The 2–3 questions you'd realistically be asked.
- A crisp 2–5 sentence answer in your own words.
- One "trap" answer to avoid.