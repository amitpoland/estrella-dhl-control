# Post-Incident Architecture Brief — AWB 2315714531

**Date:** 2026-06-18
**Incident class:** Landed-cost completeness + external-reference authority loss
**Status:** Fixes live and verified in production (`C:\PZ`). One business decision open.
**Authority owner of this document:** Engineering / Architecture
**Evidence chain:** PR [#648] (`8024c50`), PR [#652] (`03ffce9`), PR #653 (docs), scorecard `.claude/memory/scorecards/2026-06-18-pr652-deploy-gate.md`, `PROJECT_STATE.md` FACTS (2026-06-18).

This brief records the two architectural rules the incident exposed, maps every fix to its
implementation, defines the one decision that remains, and ranks the follow-up work. It is
written to be enforced. A future change that violates Rule 1 or Rule 2 is a regression, not a
design choice.

---

## Architectural Rules (what's now protected and how)

### Rule 1 — Landed cost is complete and computed by one engine across every ingestion path

**Statement.** `process_batch()` is the only calculation path for landed cost. Freight,
insurance, and duty are allocated into PZ net on **every** invoice ingestion path — text-parsed
and image-only alike. Customs value (CIF) is tri-state: `RESOLVED`, `DECLARED_ZERO`, or
`UNKNOWN`. An extraction failure never becomes a silent `0.00`.

**What it protects.** The correctness of PZ net, the declared customs value, and the goods-receipt
value booked downstream. Freight and insurance allocate proportionally by value within each
invoice; duty derives from ZC429 / A00 only. An image-only invoice that skipped F+I allocation
understated landed cost and mis-stated the customs basis.

**Why it matters.** Landed cost feeds customs declarations, the wFirma PZ (goods receipt), and
accounting. An undervalued landed cost is a compliance exposure (under-declared customs value) and
an accounting defect (wrong inventory cost). A fabricated `CIF = 0` produced false customs blocks
and false readiness states.

**Systems that depend on it.**
- `pz_import_processor.py` — the engine; root-level file, deploys to `C:\PZ\engine\`.
- `service/app/services/cif_resolver.py` — tri-state CIF resolver (RESOLVED / DECLARED_ZERO / UNKNOWN).
- `service/app/services/cif_authority.py` — `get_cif_authority()` / `require_resolved_cif()` backend gate.
- `service/app/services/vision_extractor.py` — image-only invoice extraction (advisory; operator-confirmed before it drives accounting).
- Action gates: `routes_dhl_clearance.py`, `routes_dsk.py`, `routes_agency.py`, `routes_action_proposals.py`, `routes_dashboard.py`.

**What happens if it breaks.** Image-only or extraction-degraded shipments receive understated
landed cost and mis-stated CIF. Customs documents declare the wrong value. The wFirma PZ books the
wrong inventory cost. Operators see false `ready` or false `blocked` states driven by a fabricated
zero. The defect is silent — no error is raised — which is why it reached production undetected.

### Rule 2 — External-reference authority is explicitly preserved across audit regeneration

**Statement.** The PZ engine rebuilds `audit.json` from engine-only output on every Run PZ.
`merge_regenerated_audit()` overlays only the keys named in `audit_merge.PRESERVED_KEYS`. Any audit
block that holds a reference to an **external system's document** must be engine-written or listed
in `PRESERVED_KEYS`. If it is neither, regeneration drops it to null.

**What it protects.** The canonical link between the local audit and external systems of record:
the wFirma booked PZ (`wfirma_export.wfirma_pz_doc_id`), DHL labels, customs/SAD/MRN/ZC429
references, and WorkDrive resource IDs. These references are created by post-engine workflow steps;
the engine has no knowledge of them and will not re-emit them.

**Why it matters.** A booked wFirma PZ is a real accounting document. The pointer in `audit.json`
is the only automatic link from the shipment to that document. When regeneration wiped
`wfirma_export`, the link survived only in the append-only `timeline` — recoverable, but by a
manual one-shot, not by any read path. Operators lose the ability to see, from the shipment, which
booked document corresponds to it.

**Systems that depend on it.**
- `service/app/services/audit_merge.py` — `merge_regenerated_audit()` + `PRESERVED_KEYS`.
- `service/app/services/export_service.py` — `_write_audit()`, called on every PZ run.
- `service/app/tools/regenerate_stale_batches.py` — CLI regenerate path.
- `service/app/services/audit_persist.py` — `reconcile_from_timeline()`, the recovery path.
- The merge rule is **asymmetric**: the preserved overlay wins only when the regenerated value is
  not meaningful. A flow that legitimately resets the field still wins. Preservation never blocks a
  real update.

**What happens if it breaks.** Every Run PZ silently nulls the external pointer. The audit loses
its link to the booked document, the DHL label, or the customs reference. Reconciliation,
readiness, and audit-evidence consumers degrade to "no link" without any error. This is the
#570 / #652 incident class. It recurs whenever a new external-reference key is added to the audit
without registering it in `PRESERVED_KEYS`.

---

## Current Production State (map each fix to its implementation)

Source of truth: the incident status table. All items below are deployed to `C:\PZ` and verified.

| Fix | What was broken | What the fix does | Where it lives | Audit / PR |
|---|---|---|---|---|
| **#648** | Image-only invoices skipped Freight + Insurance allocation; landed cost understated; CIF could fabricate `0.00`. | Allocates F+I into PZ net for image-only landed cost; routes customs value through the tri-state CIF authority. | `pz_import_processor.py` (engine → `C:\PZ\engine\`); `cif_resolver.py`, `cif_authority.py`, `vision_extractor.py` (→ `C:\PZ\app\`). | PR #648, commit `8024c50`. On-disk verified: engine carries the image-only F+I code. |
| **#652** | `audit.wfirma_export` (booked-PZ pointer) was in neither `PRESERVED_KEYS` nor engine output; every Run PZ wiped it to null (#570-class). | Adds `wfirma_export` to `audit_merge.PRESERVED_KEYS`; the booked-PZ pointer now survives regeneration. | `service/app/services/audit_merge.py`; tests in `service/tests/test_audit_merge.py`. | PR #652, commit `03ffce9`. Deployed via scoped single-file sync; verified `wfirma_export in PRESERVED_KEYS == True`, no stale-`.pyc` shadow. |
| **Pointer restore** | `audit.wfirma_export` for AWB 2315714531 was already null from prior regenerations. | `reconcile_from_timeline()` copied `wfirma_pz_doc_id = 189364835` from the `wfirma_pz_created` timeline event back into `wfirma_export`. Now durable post-#652. | `service/app/services/audit_persist.py`; data at `storage/outputs/SHIPMENT_2315714531_2026-06_ffe086f3/audit.json`. | Idempotent one-shot; timeline authority event retained; recorded in PR #653 + scorecard. |
| **Regression coverage** | No test pinned external-reference preservation or the F+I/CIF path. | `test_audit_merge.py` (27 cases incl. `test_cleared_pointer_is_not_resurrected_by_regen`); `test_cif_authority.py`, `test_routes_upload_cif_e2e.py`, vision suites. | `service/tests/`. | PZ `tests/test_pz_*.py` 221 passed; carrier 420 passed; focused 27/27. |
| **Production verified** | — | 7-agent deploy gate (read-only) returned READY after full suites; post-deploy verification confirmed the file landed and is active. | `C:\PZ\app\services\audit_merge.py`; PZService (NSSM, port 47213). | Scorecard `.claude/memory/scorecards/2026-06-18-pr652-deploy-gate.md` (6 EXEMPLARY, 1 ACCEPTABLE). |

**Gate notes recorded for audit.** The deploy gate BLOCKED on first pass because the full baseline
suites had not been run, then cleared after PZ 221 / carrier 420 completed. Two GATE-4 SCHEDULED
process fixes were logged: (1) `deploy-qa-reviewer` must treat the PZ-221 / carrier-412 baseline as
unconditional; (2) `deploy-release-manager`'s checklist must include the mandatory `__pycache__`
clear before restart. The "last verified prod SHA = `e4d96b5`" record was stale; an on-disk probe
proved production was at `8024c50` (#648 and prior already deployed), which reduced the deploy from
a tree-wide sync to a single-file sync.

---

## Open Business Decision (context and ownership)

**The decision.** wFirma PZ **4/6/2026** (document id **189364835**) holds stale line prices:
booked net **2,280.14 PLN** against the corrected local authority **2,736.87 PLN** — a gap of
**+456.73 PLN (+20.0%)**. Whether and how to correct the booked document is an open decision.

**Why this is not a software defect.** The engine and the local audit are now correct. The corrected
line authority (`pz_rows.json`, total 2,736.87) is in place. The divergence exists only in a wFirma
document that was booked before the correction. wFirma's API exposes no validated edit, update, or
delete for `warehouse_document_p_z` — the client supports `create_warehouse_pz`, `fetch_warehouse_pz`
(read), and `find_warehouse_pz_by_number` only, and `global_pz_push.py` is create-only by design
("CANCEL_AND_RECREATE is out of scope"; "wFirma documents cannot be deleted via API"). A booked PZ
is locked. There is no code path to "fix" it, and the team has ruled that none will be built until a
wFirma sandbox proves safe API editing of a posted PZ.

**Who owns it.** The operator / accounting function. This is a wFirma accounting action; all wFirma
writes require explicit operator approval. Engineering's role is closed: the defects are fixed, the
pointer is restored, and the corrected data is ready.

**What the owner needs to decide.**
- The gap and target: booked 2,280.14 → corrected 2,736.87 PLN (unit prices 36.55 / 81.16; doc 189364835).
- The two governed correction paths: (a) manual line-price correction in the wFirma UI, or
  (b) cancel/delete the document in wFirma, then recreate through the gated `global_pz_push` create
  path from the corrected `pz_rows.json`.
- The linkage requirement: any correction must record the old → new document linkage in the
  timeline / audit.

---

## Future Development Roadmap (three priorities with rationale)

### Priority 1 — Global PZ ↔ wFirma reconciliation (mismatch detector)

**What it solves.** The PZ engine recalculates; wFirma already holds a booked document; the values
diverge; no one notices. This incident surfaced that exact class. A detector compares the resolved
PZ result against the booked wFirma document for every shipment and flags divergence.

**How it reduces risk.** It converts a silent, per-shipment failure into a surfaced, all-shipments
signal. It prevents the next AWB 2315714531 — a booked document drifting from corrected local truth
without an operator ever seeing it. It is the highest-leverage item because it is detection across
the entire portfolio, not a fix for one shipment.

**Dependencies and safety gates.**
- Read-only. It reads the `process_batch()` result and calls `fetch_warehouse_pz` (read). It
  performs no wFirma write.
- It compares against the **resolved** CIF / landed-cost authority (`cif_authority.py`), not raw
  invoice fields.
- It surfaces as a **comparison workflow** (the recorded DECISION), not an auto-correction.
- Values must be authority-honest and normalized before comparison; flag, never mutate.

### Priority 2 — Booked-PZ correction workflow (manual or recreate)

**What it solves.** It operationalizes the two governed correction paths so an operator can correct
a booked PZ without hand-assembling the recreate.

**How it reduces manual work.** A guided cancel/recreate drives `global_pz_push` from the corrected
`pz_rows.json` and writes the old → new document linkage into the timeline automatically, removing
the manual linkage step and the risk of an unlinked replacement.

**Dependencies and safety gates.**
- Depends on Priority 1 to identify which documents need correction.
- Every wFirma write is operator-approved. The five background-automation safety properties apply:
  execution-time validation, idempotency, terminal-state suppression, replay safety, environment
  isolation.
- `CANCEL_AND_RECREATE` is currently out of scope in `global_pz_push.py`. Adding it requires a new
  capability behind a feature flag (`WFIRMA_CORRECTION_PUSH_ALLOWED`, default OFF) and must preserve
  old → new linkage.

### Priority 3 — wFirma API-edit research (sandbox-gated)

**What it solves.** A potential path to automated price correction of a posted PZ, eliminating the
manual UI step — if and only if it is provably safe.

**How it reduces work.** It would remove the manual correction entirely. It is ranked last because
its value is conditional on a safety proof that does not yet exist.

**Dependencies and safety gates.**
- Hard gate: a wFirma **sandbox** must prove safe API editing of a **posted** PZ before any design
  work begins. Until then, no production API price-edit path exists.
- If the sandbox does not prove it safe, this item stays closed and correction remains manual or
  recreate (Priority 2).

---

## Architectural Maturity Progression

This incident advanced the platform's audit/authority posture by two capability stages. Read the
stages as the operations the platform reliably performs on a PZ's authority state:

| Stage | Capabilities | What it means |
|---|---|---|
| **Before incident** | Calculate → Store → Export | The engine computed landed cost (Calculate), wrote `audit.json` (Store), and pushed a booked PZ to wFirma (Export). There was no contract that authority survived regeneration and no recovery path — a regenerate silently dropped external references, and a degraded ingestion path silently produced incomplete input. |
| **After incident** | Calculate → **Preserve** → **Recover** → **Govern** | **Preserve** = Rule 2 / `PRESERVED_KEYS` keeps external-reference authority across regeneration. **Recover** = `reconcile_from_timeline()` restores a lost pointer from append-only timeline authority. **Govern** = no-API-price-edit policy, operator-gated wFirma writes, deploy-guard, 7-agent gate. Calculate is now complete on every ingestion path (Rule 1). |
| **Future state** | Calculate → Preserve → Recover → Govern → **Reconcile** | **Reconcile** = the Global PZ ↔ wFirma comparison layer (Rule 3) that surfaces divergence between the recalculated PZ and the booked wFirma document before a period closes. This is the only stage still missing, and it is the one that would have caught AWB 2315714531 without a human. |

The progression is cumulative: each stage is a permanent capability the platform did not previously
guarantee. Preserve and Recover and Govern are live. Reconcile is the next strategic project (§4),
not a separate initiative — it completes the same authority lifecycle.

---

**Production posture.** The system is in a good, verified state. No further production changes are
scheduled. Items 1–3 are future development; item 1 begins with a design spec / ADR (authority
owner, comparison rule, surfacing point) before any code.

[#648]: https://github.com/amitpoland/estrella-dhl-control/pull/648
[#652]: https://github.com/amitpoland/estrella-dhl-control/pull/652
