# 07 — Business Operability Gate (MANDATORY)

This gate is the reason the OS exists: a package that compiles and passes unit tests is **not**
shipped. A capability is operable only when a real operator can trigger it, see it, and
understand its state. This gate is mandatory on **both** Fast and Deep paths (`06`) and is
enforced by `reviewer-challenge` + `frontend-flow-reviewer` (Business Feature Completeness
Standard, CLAUDE.md).

---

## 1. Completeness authority — the seven requirements (defined in CLAUDE.md)

**The single authoritative definition of feature completeness is the Business Feature
Completeness Standard in `CLAUDE.md`** — seven requirements (1 Automation · 2 Shared Service ·
3 Business API · 4 Business UI · 5 Observability · 6 Browser Verification · 7 Business
Verification with a named Business Owner) plus the seven-stage lifecycle (Design →
Implementation → Technical Complete → Deployed → Browser Verified → Business Verified →
Production Complete) and the Business Owner registry. This file does not restate that text —
it is the **gate procedure** that enforces it.

Supersession note (v1.3): the former "four mandatory layers" model (Automation, Business API,
Business UI, Observability) that this file originally defined maps onto requirements 1–5 of
the CLAUDE.md standard — the ratified model additionally names the **Shared Service**
(`run_<capability>()`) explicitly and adds the two acceptance gates the four-layer model
lacked (Browser Verification, Business Verification). No canonical four-layer definition
remains; where older records say "four layers," read the seven-requirement standard.

The core invariants are unchanged: scheduler/webhook, `POST /api/v1/.../action`, and the
Run-Now button all call the **same** `run_<capability>()` — never "Logic A" and "Logic B". A
scheduler-only or endpoint-only implementation is a **draft** (at most Technical Complete),
not a shipped feature. An exception requires an ADR in `docs/decisions/` — "not built yet" is
not an exception.

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

- [ ] A single `run_<capability>()` is the shared authority (no A/B divergence) — requirement 2
- [ ] Automation caller exists (or manual-only justified) — requirement 1
- [ ] `POST /api/v1/.../action` exists and calls the shared function — requirement 3
- [ ] Business UI Run-Now control exists, labeled exactly what it writes, `data-testid` present — requirement 4
- [ ] Status endpoint + panel answer all four questions — requirement 5
- [ ] No capability suppression without a cancellation record (Lesson M)
- [ ] Every blocker maps to a named true-fiscal risk; every soft signal is advisory (Lesson N)
- [ ] Read-back / history visible where the operator needs to confirm an action took effect

**BLOCK** the package if any box is unchecked. This is not a Deep-Path-only gate — a Fast-Path
button that writes but shows no state fails operability just the same.

Lifecycle note: this gate covers **requirements 1–5** and runs pre-PR. A PASS here makes the
package at most **Technical Complete**. Requirements **6 (Browser Verification)** and
**7 (Business Verification — named Business Owner sign-off)** are acceptance gates that close
after deploy, per the CLAUDE.md lifecycle ladder — only then may a feature claim
**Production Complete**.
