---
name: loop-engineer
description: Run one Plan -> Implement -> Test -> Verify -> Document -> Repeat iteration for this learning repo, following LOOP.md and the naive-first workflow. Use when the user says "/loop-engineer <task>", "run the loop", "next increment", or asks to build a roadmap item end to end.
---

# Loop Engineer

You are running the execution loop in `LOOP.md`. That file is the contract; this skill is how Claude Code starts it.

**Task:** `$ARGUMENTS` — if empty, take the first 🔄 or ⬜ item in `ROADMAP.md` and say which one you picked.

## Run it

1. **PLAN** — Read `README.md`, `AI_WORKFLOW.md`, `LEARNING.md`, `ROADMAP.md`, `ARCHITECTURE.md`, `AGENTS.md`, `LOOP.md`. Say whether `LEARNING.md` already logs the mistake you're about to make. Write the 7-label plan plus **Scope / Observe / Done when / Branch + commit plan**. **Stop and wait for confirmation.** Write no code yet.
2. **IMPLEMENT (naive)** — Say "we are now deliberately writing a mistake to observe it." Build the naive version. Gate: `pwsh -File scripts/verify.ps1 -Quick`.
3. **TEST (naive)** — Bring up the stack if needed and run the observe script or Bruno examples. Capture the real symptom and its numbers. If it doesn't reproduce, say so and change how you observe it.
4. **Explain** — PROBLEMS + BECAUSE, interview-quality.
5. **IMPLEMENT (fix)** — Refactor to best practice and cite `file:line`. Gate: `-Quick`.
6. **TEST + VERIFY (fix)** — Re-run the same observation and compare numbers. Gate: `pwsh -File scripts/verify.ps1 -Observe <script>` must exit 0, and every **Done when** must be met.
7. **DOCUMENT** — Update `LEARNING.md`, `ROADMAP.md`, `ARCHITECTURE.md` (if the design changed), and Bruno `.bru` files. Gate: `pwsh -File scripts/verify.ps1 -RequireDocs`.
8. **REPEAT** — Print the iteration report from `LOOP.md`, then propose the branch and commits. Do **not** commit, branch, or merge unless the user asks. Offer the next roadmap item, or stop.

## Rules

- A red gate sends you back along the failure routing in `LOOP.md`. Never weaken an assert or skip a gate to go green.
- If the same gate fails 3 times, or you hit a decision the plan didn't cover, stop and ask.
- Every chat response uses the WE_NEED / INITIAL / PROBLEMS / AVOID / BEST_PRACTICE / BECAUSE / TRADEOFFS labels (`AGENTS.md §4`).
- Report only numbers you actually measured.
