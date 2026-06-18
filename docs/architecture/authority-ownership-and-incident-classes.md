# Architecture Brief — Authority Ownership & Incident-Class Registry

**Date:** 2026-06-18
**Origin incident:** AWB 2315714531
**Status:** Reference document. Permanent. Shareable with the full technical team.
**Companion:** `docs/post-incident/2026-06-18-awb-2315714531-landed-cost-and-authority-references.md`
**Evidence:** PR #648 (`8024c50`), PR #652 (`03ffce9`), PR #653 (docs), scorecard `.claude/memory/scorecards/2026-06-18-pr652-deploy-gate.md`.

This document names which component owns which data state, registers the incident classes the
system now defends against, and positions the next architecture work as the missing reconciliation
authority — not a new project. Use it when triaging a similar incident: find the authority owner
first, then the incident class, then the protection mechanism.

---

## 1. Incident Classes Identified

### Incident Class A — Incomplete landed cost on a degraded ingestion path

- **Observed symptom.** Image-only invoices produced PZ landed cost that omitted Freight and
  Insurance, and customs value (CIF) could surface as `0.00`. Downstream, shipments showed false
  `blocked` / false `ready` states and an under-stated goods-receipt value. No error was raised.
- **Root cause chain.** Image-only invoice reaches `vision_extractor` → engine ingestion path for
  image-only invoices did not allocate Freight + Insurance into PZ net → customs value resolved to
  a silent `0.00` instead of an honest `UNKNOWN` → action gates (`routes_dhl_clearance`,
  `routes_dsk`, `routes_action_proposals`, `routes_dashboard`) read the fabricated zero → false
  customs blocks and under-valued PZ.
- **Permanent rule.** **Rule 1 — Landed cost is complete and computed by one engine across every
  ingestion path.** `process_batch()` is the only calculation path. Freight + Insurance + Duty
  allocate into PZ net for text-parsed and image-only invoices alike. CIF is tri-state
  (`RESOLVED` / `DECLARED_ZERO` / `UNKNOWN`); extraction failure never becomes a silent `0.00`.
- **How it's protected.** Ticket: **PR #648** (`8024c50`). Tests: `test_cif_authority.py`,
  `test_routes_upload_cif_e2e.py`, vision extraction suites; PZ baseline 221, carrier 420. Gate:
  7-agent deploy gate (canonical `deploy-security-reviewer`); CIF authority enforced backend-side by
  `require_resolved_cif()`. Architecture: Rule 1 in the post-incident brief; ADR-030
  (single resolved-CIF authority), ADR-031 (invoice-extraction authority separation).

### Incident Class B — External-reference authority lost on audit regeneration

- **Observed symptom.** After a Run PZ on AWB 2315714531, `audit.wfirma_export` was `null` — the
  link from the shipment to its booked wFirma PZ (document 189364835) had disappeared. The booked
  document still existed in wFirma; the local pointer to it was gone.
- **Root cause chain.** Run PZ rebuilds `audit.json` from engine-only output → `merge_regenerated_audit()`
  overlays only keys in `PRESERVED_KEYS` → `wfirma_export` was written post-engine by `global_pz_push`
  and named in neither `PRESERVED_KEYS` nor the engine output → each regeneration set it to `null` →
  the reference survived only in the append-only `timeline`, with no automatic read-path recovery.
- **Permanent rule.** **Rule 2 — External-reference authority is explicitly preserved across audit
  regeneration.** Any audit block holding a reference to an external system's document
  (`wfirma_export`, DHL labels, customs/SAD/MRN/ZC429 references, WorkDrive resource IDs) must be
  engine-written or listed in `audit_merge.PRESERVED_KEYS`. The merge is asymmetric: the preserved
  overlay wins only when the regenerated value is not meaningful, so preservation never blocks a
  legitimate update.
- **How it's protected.** Ticket: **PR #652** (`03ffce9`). Tests: `test_audit_merge.py` — 27 cases
  incl. `test_cleared_pointer_is_not_resurrected_by_regen` and the preserved-keys contract. Gate:
  7-agent deploy gate; post-deploy verification confirmed `wfirma_export in PRESERVED_KEYS == True`
  with no stale-`.pyc` shadow. Architecture: Rule 2 in the post-incident brief; memory rule
  `project_preserve_external_reference_authority`. Recovery: `audit_persist.reconcile_from_timeline()`.

---

## 2. Authority Ownership Map

Every data state has exactly one owner. The owner produces truth; all other components reflect it.

### 2.1 PZ value calculation and its components

| Authority | Owner | Rule |
|---|---|---|
| Landed cost (the composite) | `process_batch()` — the engine (`pz_import_processor.py`) | Only calculation path. Never recompute landed cost, freight, duty, totals, or notes anywhere else. |
| FOB | Invoice parse, or operator-confirmed `vision_invoice` for image-only | Advisory until `operator_confirmed == true`; only then does it drive accounting (ADR-031). |
| Freight + Insurance | Engine allocation | Proportional **by value** within each invoice. Never by piece count. Allocated on every ingestion path (Rule 1). |
| Duty | Engine, from ZC429 / A00 | Proportional by before-duty value. Never a fixed %. B00 VAT is reference-only, excluded from landed cost. |
| Customs value (CIF) | `cif_resolver.py` → `cif_authority.py` | Tri-state `RESOLVED` / `DECLARED_ZERO` / `UNKNOWN`. Raw invoice CIF is evidence only. `require_resolved_cif()` gates customs/PZ actions. |
| Notes / UWAGI | Engine | From the engine only. Never reconstructed independently. |

### 2.2 External-reference lifecycle

| Lifecycle stage | Owner | Rule |
|---|---|---|
| Creation | `global_pz_push.py` (create-only) | The only governed wFirma create path. Gated on operator approval. |
| Update / Delete | **wFirma UI (operator) only** | No validated API edit/delete for `warehouse_document_p_z`. A booked PZ is locked. `CANCEL_AND_RECREATE` is out of scope in `global_pz_push`. |
| Preservation across regeneration | `audit_merge.PRESERVED_KEYS` | The pointer must be listed here or it is wiped on every Run PZ (Rule 2). |
| System of record | **wFirma** | wFirma owns the booked document. `audit.wfirma_export` is a pointer/projection, not the source. |
| Append-only authority / recovery | `timeline` events → `reconcile_from_timeline()` | The `wfirma_pz_created` event is the durable authority; reconciliation restores a lost pointer. Manual one-shot, not automatic. |

### 2.3 Other implicit authorities extracted from the rules

| Authority | Owner | Rule |
|---|---|---|
| Audit overlay vs engine output | `merge_regenerated_audit()` | Engine owns engine keys (rows, totals, verification); workflow owns overlay keys (`PRESERVED_KEYS`). Asymmetric merge; meaningful regen value always wins. |
| Valuation planes (Sales / Cost / Landed) | Three distinct authorities | Sales = `excel_symbol`; Cost = `packing_xlsx_value`; Landed = engine USD→PLN via ZC429. The PZ engine valuation math is frozen — do not change it. |
| Readiness / gate state | Backend resolvers | Frontend reflects truth; it does not produce it. Business legality stays backend-authoritative (Lesson F). |
| Customs declaration / routing | `clearance_decision` pipeline | Owns the routing decision and declared value source; reads resolved CIF, not raw invoice 0. |

---

## 3. Open Items

### 3.1 Closed technical defects — system state is now correct

- **#648** — image-only landed cost now allocates Freight + Insurance; CIF tri-state enforced. Deployed, on-disk verified.
- **#652** — `wfirma_export` preserved across regeneration. Deployed, verified active.
- **Pointer restore** — `audit.wfirma_export` for AWB 2315714531 restored to document 189364835 via `reconcile_from_timeline`; now durable.
- **Regression coverage** — preservation, no-resurrection, and CIF-path tests added. PZ 221 / carrier 420 green.

### 3.2 Open business decision — system is correct; the business must reconcile

- **wFirma PZ 4/6/2026 (document 189364835): 2,280.14 → 2,736.87 PLN (+456.73 / +20.0%).** The
  engine and local audit are correct; the booked wFirma document holds stale prices. wFirma is the
  system of record and exposes no validated API edit/delete. **Owner: operator / accounting.** The
  owner chooses (a) manual UI line-price correction, or (b) cancel + recreate via the gated
  `global_pz_push` path from the corrected `pz_rows.json`, recording old → new document linkage.
  No software change resolves this; no wFirma write occurs without operator approval.

### 3.3 Documented strategic opportunities — future architecture work

- **Global PZ ↔ wFirma reconciliation (mismatch detector)** — see §4.
- **Booked-PZ correction workflow** — operationalizes the two governed correction paths; requires
  `CANCEL_AND_RECREATE` behind `WFIRMA_CORRECTION_PUSH_ALLOWED` (default OFF) with the five
  background-automation safety properties and automatic old → new linkage.
- **wFirma API-edit research** — hard-gated on a wFirma sandbox proving safe edit of a posted PZ.
  Closed until that proof exists.

---

## 4. Next Strategic Work — Global PZ ↔ wFirma Reconciliation

This is the natural continuation of the architecture, not a separate project. Rule 1 guarantees the
engine computes the **correct** value. Rule 2 guarantees the audit retains the **link** to the
booked document. Neither rule makes the **divergence between the two systems observable**. That
missing authority — reconciliation — is the third leg, and this incident is the proof it is absent.

- **What it detects.** Value divergence between the recalculated PZ result (engine, resolved CIF
  authority) and the booked wFirma document (`fetch_warehouse_pz`). It reads both and compares;
  AWB 2315714531's +20% gap is its canonical first case.
- **When it surfaces.** Continuously across all shipments, and — critically — **before accounting
  closes a period**. A booked PZ that has drifted from corrected local truth must be flagged while
  the period is still open, not discovered in an audit afterward.
- **What it prevents.** Future 2315714531-class incidents that today depend on a human noticing.
  It removes "operator happened to look" from the control path and replaces it with a portfolio-wide
  signal.
- **Why it's architecturally strategic.** It closes the loop the two permanent rules leave open. It
  is the **reconciliation authority** between the engine (owner of computed value) and wFirma (owner
  of the booked document). Once it exists, the entire root-cause category — "PZ recalculates, wFirma
  holds a booked document, values diverge, no one notices" — stops being a class of incident and
  becomes a surfaced, dispositioned signal.

**Safety gates for implementation.** Read-only (no wFirma write). Compares against the resolved
authority (`cif_authority.py`), not raw invoice fields. Surfaces as a **comparison workflow** per the
recorded decision — it flags, it never auto-corrects. Begins with a design spec / ADR naming the
authority owner, the comparison rule, and the surfacing point before any code.

---

**Triage guidance for similar incidents.** Name the authority owner (§2). Match the symptom to an
incident class (§1). Apply the permanent rule and confirm its protection mechanism is intact. If the
divergence is between the engine and wFirma, it belongs to the reconciliation authority (§4) — build
or extend it rather than patching the single shipment.
