# LOOP.md — the Loop Engineer

The **execution loop** every coding agent (Claude Code, Codex, Cursor, Copilot, a human) runs for every increment in this repo:

```
PLAN ──► IMPLEMENT ──► TEST ──► VERIFY ──► DOCUMENT ──► REPEAT
  ▲                      │         │                       │
  └──────── fail ────────┴─────────┘                       │
  └──────────────────── next increment ◄───────────────────┘
```

`AI_WORKFLOW.md` says **what** we learn (naive → fail → explain → fix → log). This file says **how an agent executes it** without drifting: each phase has an entry condition, actions, and an **exit gate**. You may not leave a phase until its gate is green.

---

## How the two loops map

| Loop phase | Learning-loop step (`AI_WORKFLOW.md`) | Output |
|------------|---------------------------------------|--------|
| PLAN | "Plan-first" (7-label plan) | Plan in chat, user confirms |
| IMPLEMENT (pass 1) | 1. Naive version | Naive code, marked as deliberate |
| TEST (pass 1) | 2. Run / observe / fail | Captured symptom (numbers, output) |
| — | 3. Explain the problem | PROBLEMS + BECAUSE in chat |
| IMPLEMENT (pass 2) | 4. Refactor to best practice | Fixed code, `file:line` refs |
| TEST + VERIFY (pass 2) | proves the fix | Before/after numbers, green gate |
| DOCUMENT | 5. Log it | `LEARNING.md` + `ROADMAP.md` (+ `ARCHITECTURE.md`, Bruno) |
| REPEAT | next topic / next increment | New loop, or stop |

So one learning topic = **two passes** through IMPLEMENT → TEST (naive, then fixed) and one pass through everything else.

---

## Phase contracts

### 1. PLAN
- **Enter:** a task from the user or the next ⬜/🔄 item in `ROADMAP.md`.
- **Do:** read `README.md`, `AI_WORKFLOW.md`, `LEARNING.md`, `ROADMAP.md`, `ARCHITECTURE.md`, `AGENTS.md`. Check `LEARNING.md` for a mistake we are about to repeat. Write the 7-label plan (WE_NEED … TRADEOFFS) and add:
  - **Scope:** one concept, the files it touches (keep each commit under 10 files).
  - **Observe:** how we will make the failure visible (`scripts/observe_<topic>.py`, Bruno request, load burst).
  - **Done when:** the measurable before/after, e.g. "20 misses → 1 loader call".
  - **Branch + commit plan:** `<type>/<short-desc>`, `[<type>] Title` commits.
- **Exit gate:** the user confirms the plan. **No code before confirmation.**

### 2. IMPLEMENT
- **Enter:** confirmed plan (pass 1) or explained failure (pass 2).
- **Do:** pass 1 = the naive version, stated out loud: *"we are now deliberately writing a mistake to observe it."* Pass 2 = best practice. Follow `AGENTS.md §5` (type hints, async DB, envelope, no hardcoded secrets, Bruno example per endpoint, comments only for learning insights).
- **Exit gate:** code imports cleanly (`scripts/verify.ps1 -Quick`).

### 3. TEST
- **Enter:** code written.
- **Do:** run the observe script / Bruno examples / `pytest` (once tests exist) against the real stack (`docker compose up -d`, `alembic upgrade head`, `uvicorn …`). Capture **real numbers**, never predicted ones.
- **Exit gate:**
  - pass 1: the failure **reproduced** and captured. If it didn't reproduce, say so honestly and explain why (see the M2 stampede entry), then find a deterministic way to show it.
  - pass 2: the fix measured against the pass-1 numbers.

### 4. VERIFY
- **Enter:** tests ran.
- **Do:** run `scripts/verify.ps1` (the full gate; add `-Bruno` whenever an endpoint or `.bru` changed) and re-read the diff against the plan's **Done when**.
- **Exit gate:** `verify.ps1` exits 0, **and** every **Done when** item is met, **and** no edits are left over that the plan didn't mention.

### 5. DOCUMENT
- **Enter:** verify green.
- **Do:** dated `LEARNING.md` entry (what / observed / lesson / fix / interview answer / trap), `ROADMAP.md` status + increment log, `ARCHITECTURE.md` if the design changed, Bruno `.bru` updated in the same increment, Interview File when a topic closes (`AGENTS.md §9`).
- **Exit gate:** `scripts/verify.ps1 -RequireDocs` passes (docs are in the diff).

### 6. REPEAT
- **Gate the commit on the exit code, not on reading the output:** `.\scripts\verify.ps1 -RequireDocs; if ($LASTEXITCODE) { throw }` before any `git commit`/merge in the same chain. (2026-09-28: a docs script failed mid-way, verify printed RED, and a blindly chained commit + merge still landed partial docs on `main`.)
- **Do:** report the iteration (template below), propose the commit(s). **Never commit, branch, or merge unless the user asks** (`AGENTS.md §8`).
- Then either start the next PLAN (next roadmap item) or **stop**.

---

## Failure routing (where to go when a gate is red)

| Red gate | Go back to | Rule |
|----------|-----------|------|
| Import/compile error | IMPLEMENT | fix, re-run gate |
| Test fails unexpectedly (pass 2) | IMPLEMENT | root-cause first; never weaken the assert to pass |
| Failure won't reproduce (pass 1) | PLAN | change the observe method, tell the user |
| Verify: diff exceeds scope / >10 files | PLAN | split into more commits or more increments |
| Docs missing | DOCUMENT | no log = not done |

## Stop conditions (an agent must halt and ask)

- The **same gate fails 3 times** in a row → stop, show the output, ask.
- The fix needs a **decision the plan didn't cover** (new dependency, schema change, API contract change).
- Anything **hard to reverse**: migrations on shared data, deleting files, force-push, commits/merges.
- The plan's **Done when** turns out to be wrong or impossible to measure.

---

## Iteration report (print at the end of every loop)

```
LOOP #<n> · <milestone> · <increment>
PLAN      ✅ confirmed <date>
IMPLEMENT ✅ naive: <file:line>   fixed: <file:line>
TEST      ✅ naive: <symptom + number>   fixed: <number>
VERIFY    ✅ scripts/verify.ps1 exit 0 (<n> files changed)
DOCUMENT  ✅ LEARNING.md · ROADMAP.md · <others>
NEXT      <next roadmap item>  |  STOP: <reason>
Proposed: branch <type>/<desc> · commits: [<type>] <title> …
```

---

## Running it

- **Claude Code:** `/loop-engineer <task>` (skill in `.claude/skills/loop-engineer/`). No task given → it takes the next roadmap item.
- **Any other agent:** point it at this file: *"Follow LOOP.md for: <task>."* `AGENTS.md` already links here, so agents that load `AGENTS.md` automatically (Codex, Cursor, Copilot) get it too.
- **Verify gate by hand:** `.\scripts\verify.ps1` · `-Quick` (imports only) · `-RequireDocs` · `-Observe observe_stampede.py` · `-Bruno`.
