# 09 — Token Controller

Token economy is a first-class engineering constraint, not an afterthought. The OS is designed
so that a package consumes the **minimum** context needed to run it correctly. This file defines
the economy; the Coordinator (`01`) enforces it.

---

## 1. The economy in one line

**Use minimum agents, minimum skills, minimum context — reuse previous verified conclusions,
never repeat already-closed inspections, and release everything at Close.** Everything else is
context debt.

Low token usage is a **mandatory primary objective** (`00 §0.1`), co-equal with speed and
correctness — not a nice-to-have. The discussion budget (`06 §Discussion budget`: Fast 5% /
Deep 15% planning) is the time-side expression of this same constraint.

---

## 2. Budgets by path (`06`)

| Lever | Fast Path | Deep Path |
|---|---|---|
| Capability manifest | 1 (the one in scope) | 1 + PROJECT_STATE authority map |
| Skills loaded | 1 | ≤ domain minimum (2, or 3 only for true full-stack) |
| Agents dispatched | 1 lead + 1 targeted reviewer | full council, **in parallel** (one dispatch message) |
| Whole-file reads | only the file(s) being edited | scoped; delegate broad search to `Explore` |
| Verification | targeted `pytest -k` / smoke | `make verify` (+ `verify-full` before PR) |

Fast Path exists largely to save tokens on low-risk work. Choosing Deep Path when Fast suffices
is a token-economy failure; choosing Fast when the work is protected-domain is a governance
failure — the Coordinator balances both.

---

## 3. Rules

1. **Manifest-first, not repo-wide.** Read `capabilities/<name>/manifest.md` and the named
   files. Do not re-scan the whole tree to "understand context" — the manifest *is* the context.
2. **Minimum skills (`04`).** Never load a skill "just in case." Release Active skills at Close
   (`Available→Selected→Active→Completed→Released`).
3. **Delegate broad search.** Fan-out discovery goes to the `Explore` / general-purpose agent,
   which returns the conclusion, not the file dumps. Keep the conclusion, not the transcript.
4. **Parallelize independent work.** Dispatch independent inspectors/reviewers in a single
   message so they run concurrently (latency + token economy).
5. **Reuse previous verified conclusions; never repeat a closed inspection.** If a fact, authority
   map, or inspection was verified and recorded (PROJECT_STATE, a manifest, a scorecard, a prior
   sealed package), cite it — do not re-run the inspection. Re-deriving established state is token
   waste. Read PROJECT_STATE / TASK_STATE once; don't rebuild it from chat history (it is lossy
   across sessions).
6. **Summarize, don't echo.** A subagent's final message is the deliverable — relay what
   matters, not the raw tool output.
7. **No whole-file reads to verify an edit.** The Edit/Write tools error on failure; the harness
   tracks file state — re-reading to "confirm" wastes tokens.
8. **Prefer targeted tools.** `Grep`/`Glob` over shell `find`/`cat`; `Read` a range, not a
   2000-line default, when the target is known.

---

## 4. Context-window discipline

- When context grows long it is summarized and continued — do not wrap up early or hand off
  mid-package to "save context."
- Load reference docs (status-endpoint pattern, a Lesson's full narrative) **on demand**, not
  preemptively.
- Prefer `PROJECT_STATE_SUMMARY.md` at startup; open the full `PROJECT_STATE.md` only when a
  package needs it (recorded operator feedback).

---

## 5. Anti-patterns (token waste to avoid)

- Loading all 9 skills or the full agent roster for a one-file change.
- Reading the whole capability's source when the manifest + one file suffice.
- Sequential dispatch of reviewers that could run in parallel.
- Re-reading a just-edited file "to be sure."
- Re-deriving authority state already written in PROJECT_STATE.
- Re-running an inspection that a prior package already closed and recorded.
- Printing council deliberation the user did not ask for (`01 §1.2`).
- Planning past the discussion budget instead of executing (`06`).
