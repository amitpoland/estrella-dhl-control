# 06 — Package Lifecycle

Every work package runs the same lifecycle, on one of two declared paths. The Executive
Coordinator (`01`) sequences it. No stage is skipped; on Fast Path some stages collapse but
none are removed.

---

## Fast Path vs Deep Path

The Coordinator **declares the path at Intake** and states why.

| | **Fast Path** | **Deep Path** |
|---|---|---|
| **When** | small, single-authority, low blast radius; no schema change; no protected-domain edit; ≤ ~2 files | multi-authority, schema change, protected domain, fiscal write, new capability surface, or cross-layer |
| **Manifest** | load the one capability manifest | load manifest + confirm authority map in PROJECT_STATE |
| **Skills** | 1 skill (minimum) | up to the domain minimum (design pair / fullstack+clean-code) |
| **Agents** | 1 lead + 1 targeted reviewer | full relevant council in parallel (`02`) |
| **Councils** | one domain council + Security if any write | all relevant councils |
| **Verification** | targeted `pytest -k` / smoke | `make verify` (+ `make verify-full` before PR) + browser GATE 6 |
| **Operability gate** | mandatory (never skipped) | mandatory |
| **Deploy** | 7-agent gate | 7-agent gate |
| **Example** | fix a stale subtitle string; add a testid; repoint one route | Returns QC authority; a new schema table; a fiscal-write path |

Fast Path is a **speed optimization, not a governance discount** — the Operability gate (`07`)
and the deploy gate (`08`) are mandatory on both paths. When in doubt, choose Deep Path.

### Discussion budget (hard cap per path)

Planning is capped as a fraction of total effort. The budget is a ceiling, not a target — spend
less when the answer is obvious.

| Path | Planning | Execution |
|---|---|---|
| **Fast Path** | **5%** | **95%** |
| **Deep Path** | **15%** | **85%** |

**If planning exceeds its budget, stop planning and execute.** More discussion past the cap does
not improve the outcome — it burns tokens and delays the work. A package that cannot be planned
within budget is either mis-pathed (bump Fast→Deep once) or blocked on a real HOLD condition
(`01 §4`) — it is never a reason to keep deliberating.

## Default execution mode

If sufficient information exists, **implement** — do not ask, do not re-summarize, do not restate
known rules (`01 §1.3`). Councils run internally; report only decisions, findings, blockers,
implementation, verification (`01 §1.2`).

---

## Lifecycle stages

```
1 Intake        → one-line objective; declare Fast/Deep path
2 Load Manifest → capabilities/<name>/manifest.md; prove authority/page/API/DB/service (STOP if unnamable)
3 Classify      → one category (ej-dashboard-master §2)
4 Route         → minimum skills (04) + agents (03)
5 Plan          → route→service→model chain, every arrow named; state files to touch
6 Implement     → agents execute within skill contracts, on a branch, on named files only
7 Verify        → repo-real tests with counts; browser GATE 6 if UI (webapp-testing)
8 Operability   → mandatory 4-layer gate (07) — BLOCK if any layer missing
9 Review        → councils return verdict blocks (02); resolve/escalate HIGH+CRITICAL (GATE 1)
10 Deploy       → hand to 7-agent gate (08); operator + gate own the sync
11 Close        → verify prod; record state (10); release skills (04 §4)
```

Stages 7–9 iterate: a council/verification finding sends work back to stage 6.

---

## Gate checklist (before PR-open — GATE 1)

- [ ] Capability manifest loaded; authority/page/API/DB/service named
- [ ] Path declared (Fast/Deep) with reason
- [ ] Minimum skills + agents routed; write-capable agents given negative scope (Lesson K)
- [ ] route→service→model chain written; every arrow named
- [ ] Regression run with **counts** stated (`make verify` / targeted `pytest`)
- [ ] Browser GATE 6 complete if UI (console + network reviewed)
- [ ] **Business Operability gate PASS** (`07`)
- [ ] Every HIGH/CRITICAL council finding resolved inline or escalated
- [ ] Forbidden-files check: no out-of-scope edits; no engine-file surprise (Lesson J)
- [ ] Rollback stated (incl. the separate `C:\PZ\engine\` sync if an engine file changed)
- [ ] Open-PR count ≤ 3 implementation (GATE 2)

---

## HOLD conditions (valid stops — from `01 §4`)

Destructive production action · missing credentials · legal/financial approval · unclear
business decision · unnamable authority · protected-domain edit. Record a one-line HOLD reason
in `.claude/memory/TASK_STATE.md` so the next session resumes without re-deriving context.

## Completion discipline

A package is done only when its checklist passes **and** it is deployed + production-verified +
recorded (`10`). Do not begin a second package while one is `IN_PROGRESS` in `TASK_STATE.md`
unless the operator redirects.
