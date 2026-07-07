# 07 — Business Operability Gate (MANDATORY)

This gate is the reason the OS exists: a package that compiles and passes unit tests is **not**
shipped. A capability is operable only when a real operator can trigger it, see it, and
understand its state. This gate is mandatory on **both** Fast and Deep paths (`06`) and is
enforced by `reviewer-challenge` + `frontend-flow-reviewer` (Business Feature Completeness
Standard, CLAUDE.md).

---

## 1. The four mandatory layers

```
Scheduler / Webhook
        │
        ▼
run_<capability>()        ← the ONE shared function (single authority for how it executes)
        ▲
        │
POST /api/v1/.../action   ← Business API (FastAPI endpoint) — another caller of the SAME function
        ▲
        │
[ Run Now ] button        ← Business UI (operator-facing)
```

| Layer | Required | Only exception |
|---|---|---|
| **Automation** | scheduler/webhook calls `run_<capability>()` | operation is inherently manual |
| **Business API** | `POST /api/v1/.../action` calls the **same** `run_<capability>()` | none |
| **Business UI** | a Run-Now button/action calls the Business API | none |
| **Observability** | status endpoint + panel answer the four questions below | none |

Automation and API must **not** diverge into "Logic A" and "Logic B" — one
`run_<capability>()` is the authority for how the operation executes. A scheduler-only or
endpoint-only implementation is a **draft**, not a shipped feature. An exception requires an ADR
in `docs/decisions/` — "not built yet" is not an exception.

---

## 2. The four questions every screen must answer

When an operator opens the capability's screen, all four must be immediately visible:

1. **What is the current state?** (running / healthy / error)
2. **When did it last run?** (`last_completed_at`)
3. **What happened?** (processed / created / updated / skipped / errors)
4. **Can I run it now?** (Run Now button, always enabled)

Canonical status shape (`GET /api/v1/.../status`): `healthy` (bool), `running` (bool, derived
from `last_started_at > last_completed_at`), `last_started_at`, `last_completed_at`,
`duration_ms`, `processed`, `created`, `updated`, `skipped`, `errors`, `last_error`. Full
contract: `docs/patterns/status-endpoint.md`.

---

## 3. Advisory vs blocker (Lesson N — binding at this gate)

Operability includes **honest gating**. A readiness signal falls into exactly two classes, and
the class decides whether it may block a fiscal action (Approve / Post / Convert / Reservation):

- **Advisory-only — NEVER block:** sales linkage, missing warehouse scan, missing warehouse
  confirmation, placeholder-design (PND) rows. Surface them; let the action proceed.
- **True blockers — the ONLY conditions that may block:** customer unmatched/ambiguous;
  missing price; over-bill (allocated qty > authority qty); VAT/WDT fiscal failure; duplicate
  document risk; live write-gate disabled; `product_code` missing for posting.

Adding a new hard gate requires naming which fiscal/tax/duplication risk it protects against.
A gate with no fiscal-risk justification is an advisory wearing a blocker's clothes — reject it.

---

## 4. Operability review checklist (gate PASS requires all)

- [ ] A single `run_<capability>()` is the shared authority (no A/B divergence)
- [ ] Automation caller exists (or manual-only justified)
- [ ] `POST /api/v1/.../action` exists and calls the shared function
- [ ] Business UI Run-Now control exists, labeled exactly what it writes, `data-testid` present
- [ ] Status endpoint + panel answer all four questions
- [ ] No capability suppression without a cancellation record (Lesson M)
- [ ] Every blocker maps to a named true-fiscal risk; every soft signal is advisory (Lesson N)
- [ ] Read-back / history visible where the operator needs to confirm an action took effect

**BLOCK** the package if any box is unchecked. This is not a Deep-Path-only gate — a Fast-Path
button that writes but shows no state fails operability just the same.
