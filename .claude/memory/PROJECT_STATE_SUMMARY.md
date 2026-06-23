# PROJECT_STATE_SUMMARY.md

Compact snapshot for session startup. Full history in `.claude/memory/PROJECT_STATE.md`.
Last synced from PROJECT_STATE.md: 2026-06-22. Update via `/update-state`.

---

## Current Session

- **Branch:** `feat/carrier-phase-d-live-awb`
- **Main HEAD:** `282fbaf` — `fix(wfirma): harden pz_quantity_validator (#731)` (2026-06-22)
- **Active task:** Carrier Phase D live AWB integration (current branch, see TASK_STATE.md)

---

## Open PRs (GATE 2: 2 impl PRs open — 1 slot remains)

| PR | What | Status | Action needed |
|---|---|---|---|
| #726 | Import PZ sales authority split | OPEN — GATE 1 satisfied | Operator merge + 7-agent deploy |
| #708 | Freight authority blocker deep-link | OPEN — GATE 1 satisfied | Operator merge + 7-agent deploy (after #726) |
| #695 | Docs overbill-tolerance comment | OPEN — zero blast radius | Operator merge only (no deploy gate) |
| #687 | Proforma readiness V2 tab | DRAFT — GATE 6 pending | Browser verify before converting to ready |

**GATE 2 ruling:** #726 + #708 = 2 impl PRs open (docs-only PR #695 doesn't count). Must merge ≥1 impl PR before opening a 3rd from current branch.

---

## Undeployed Merged PRs

| PR | SHA | What | Blocker |
|---|---|---|---|
| PR #677 | `308145d` | Proforma authority UI (V1 customer-auth summary + description + blocked-birth) | 7-agent deploy gate + GATE-6 browser verify pending (operator-run) |
| PR #720 | (merged) | `is_due()` safety hardening | **CRITICAL:** Must deploy BEFORE arming `DHL_ORCH_AUTO_SEND_DSK_CHASE` flag |

---

## Test Baselines

- PZ regression: **221/221** | Golden: **160/160** | Carrier: **420/420**
- PR #726 adds: 12 new tests (all green against baselines)

---

## Last 10 Architectural Decisions

1. **Six separate authorities (2026-06-22):** PRODUCT / PROFORMA / IMPORT_PZ / WAREHOUSE / SALES are independent. Purchase-domain scan counts and sales SKU linkage MUST NOT gate import PZ or product creation. Lesson N binding. PR `fix/authority-model-separation`.

2. **Tri-State CIF authority (2026-06-16):** Missing CIF = `UNKNOWN`, never fabricated `0.0`. `cif_usd=None` when UNKNOWN. Invoice authority outranks carrier-declared AWB Custom Val. ADR-030. PR #627.

3. **Single resolved-CIF backend guard (2026-06-17):** `require_resolved_cif()` is the binding gate. No `float(... or 0)` coercions anywhere. Routes dashboard DSK button-state fixed in-PR (#633).

4. **Contractor-at-Birth authority (2026-06-20/21):** `client_contractor_id` propagates through sales → draft → reservation. Contractor-id-first resolution; `bill_to_name` overrides parsed `client_name` when contractor_id present. PRs #673 + #675 merged and deployed.

5. **Proforma product description = `description_engine` (2026-06-21):** Canonical per-line description authority. Display-only in V1 proforma panel. Posted line name in wFirma not yet changed (BACKLOG B-013). PR #677 merged, undeployed.

6. **/feature command tier: WRITE-CAPABLE (2026-06-20):** Every `/feature` fires reviewer-challenge. `BACKLOG.md` is the canonical side-discovery capture point (GATE 4 disposition required on every entry). PR #669.

7. **Skill routing authority (2026-06-20):** `SKILL_ROUTING.md` is the single keyword→skill mapping source. No duplication of routing table in other files.

8. **Observation period policy (2026-06-20):** Informational only — not a gate. Development continues normally. Record completed `/feature` runs in `FEATURE_SCORECARD.md`.

9. **PR-2 Stage A/B separation (2026-06-17):** Stage A = confirmation workflow (PR #647 scope). Stage B = engine injection gated on separate Issues #638/#639. `logistics` role permitted to attest vision-invoice confirmation.

10. **Next 3 priority actions (2026-06-22):** (1) Operator merge PR #726; (2) Combined 7-agent deploy for PR #726 + #708; (3) Execute agent-tuning Issues #709 + #694 (frontend-flow + backend-safety reviewer hardening).

---

## Current Blockers / Open Questions

- **OQ-PR726-MERGE** — PR #726 awaiting operator review + squash-merge. GATE 2 slot available.
- **OQ-PR708-MERGE** — PR #708 awaiting merge (after #726 merges).
- **OQ-PR726-DEPLOY** — Combined 7-agent deploy gate + GATE-6 browser verify pending after both PRs merge.
- **OQ-PR726-FRONTEND-FLOW-REPEATED-WEAK** — 4th consecutive ACCEPTABLE on frontend-flow-reviewer (evidence anchoring gap). GATE 4 ISSUE → GitHub Issue #709. Prompt hardening required.
- **OQ-PR677-DEPLOY** — PR #677 (proforma authority UI) merged but undeployed. Requires 7-agent gate.
- **OQ-PR694-ISSUE-EXECUTE** — backend-safety-reviewer REPEATED-WEAK; GitHub Issue #694 unactioned.
- **GATE 2** — 2 impl PRs open. Merge ≥1 before opening a 3rd from current branch work.

---

## Production State

- Service: `PZService` (NSSM, port 47213) at `C:\PZ`; public: `https://pz.estrellajewels.eu`
- Auth: X-API-Key header
- wFirma flags: all-ON standing posture; `DHL_ORCH_AUTO_SEND_DSK_CHASE=false` (PR #720 not yet deployed)
- Deployed SHA: pre-`282fbaf` (exact deployed SHA: verify via `Select-String` in `C:\PZ\app`)

---

*Full FACTS / DECISIONS / ASSUMPTIONS / OPEN QUESTIONS: `.claude/memory/PROJECT_STATE.md`*
*Startup protocol: read this file; read full PROJECT_STATE.md only when explicitly needed.*
