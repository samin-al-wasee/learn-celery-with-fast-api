# AI_WORKFLOW.md

The guided learning loop used for every task in this repo. This is the **process contract** between you and the AI agent.

> Put a beginner in the room: they ask "why?" 20 times. This file makes sure the agent always has the answer — and says it out loud before, during, and after coding.

---

## The message format

Every task starts with a plan that follows this exact framing. Use these labels explicitly so the reasoning is visible and the user can follow along (or stop you at any step):

| Label | Meaning | Example |
|-------|---------|---------|
| **WE_NEED** | What the goal is and why we care | *"We need async email confirmation so signup never blocks the request."* |
| **INITIAL** | The naive approach we'll try first | *"Let's `time.sleep(2)` inside the endpoint and call it done."* |
| **PROBLEMS** | What breaks, and why | *"The worker (uvicorn) is single but clients queue; with N requests we block N segments of the event loop → connection latency blows up under load."* |
| **AVOID** | The anti-pattern not to repeat | *"Don't spawn `threading.Thread` per request — process exits kill it, no retries, no observability."* |
| **BEST_PRACTICE** | The right way | *"Push the job to a shared queue (Celery broker) and let a worker process handle it with retries and state."* |
| **BECAUSE** | The technical reason | *"Async HTTP servers complete requests quickly; long work must leave the request path so the event loop stays free. A broker gives durability + horizontal scaling."* |
| **TRADEOFFS** | When the simple thing is still fine, and what it costs | *"For <10 users, inline work is fine — you pay in lost scale and no retry guarantees; acceptable for demos, unacceptable for production."* |

## The 5-step loop (do not skip steps)

1. **Naive version** — write the simplest possible code that "works" for the happy path. No abstractions. No over-engineering.
2. **Run / observe / fail** — actually run it. Reproduce the problem: load test, many requests, two workers, lost job, etc. Capture the symptom.
3. **Explain the problem** — a clear, technical, interview-quality explanation of WHY it breaks.
4. **Refactor to best practice** — replace the naive code with the production-grade approach. Cite file:line.
5. **Log it** — write the dated entry in `LEARNING.md` (naive attempt, observed problem, lesson, fix, interview answer). No log = task not finished.

### Hard rules on the loop

- **Never skip step 1.** Jumping straight to best practice is the biggest violation of this project. The whole point is seeing how the naive version fails.
- **Never skip step 5.** "If it didn't get logged, it didn't get learned."
- **One loop per concept.** Don't bundle three learning topics into one task.
- **Small increments.** Each PR-like increment updates `ROADMAP.md` status + `LEARNING.md`.

## Plan-first requests

When the user says *"plan first"* (or the task is non-trivial), the agent:

1. Reads the docs (`README.md`, `AI_WORKFLOW.md`, `LEARNING.md`, `ROADMAP.md`, `ARCHITECTURE.md`).
2. Produces the **WE_NEED / INITIAL / PROBLEMS / AVOID / BEST_PRACTICE / BECAUSE / TRADEOFFS** plan in chat.
3. Waits for confirmation **before writing any code**.

## How we answer questions

- **Conceptual questions** (how does Celery work, how are retries implemented, what is at-least-once): answer with the architecture doc + the relevant `LEARNING.md` entry. Frame like a senior dev explaining to a junior: analogy → mechanism → edge cases.
- **Code requests**: run the loop above — build naive, show the failure, refactor.
- **"Why is this best practice?"** → always answered with BECAUSE + TRADEOFFS, never just "it's best practice".

## Teaching-by-mistake (deliberate)

Sometimes we *deliberately* write the wrong thing (e.g., sync DB call in an async endpoint, forgetting the `result_backend`, using a thread per request). When we do:

- State clearly which commitment we're making: **"we are now deliberately writing a mistake to observe it."**
- Keep the scope contained — include a marked file/section, log it, and fix it in the same session when possible.
- The fix goes through the same 5-step loop so the lesson is complete.

## Topic map (what each learning topic must produce)

For each of the six topics, before we consider it "done" we need:

1. A working example in the codebase (naive → fixed).
2. A `LEARNING.md` entry with the failure mode we actually observed.
3. An interview section (2–3 questions, crisp answers, one trap answer).
4. An `ARCHITECTURE.md` diagram/decision showing where it fits in the system.

---

## Summary for the agent

> Demonstrate the problem first. Then explain why. Then apply the fix. Then document everything. Never teach best practice by skipping the failure.