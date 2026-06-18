# Final Closure Record — AWB-2315714531-2026-06

**Date:** 2026-06-18
**Prepared for:** Engineering leadership and governance reviewers
**Validation basis:** 11-agent validation review of the 5-document closure package — 0 confirmed closure-blockers after adversarial verification; 4 documentation/consistency issues resolved (commit `912ed40`).
**Disposition:** Software-closed. One business decision open. Approved for merge.

---

## 1. Incident Classification and Defect Resolution Status

```
INCIDENT ID         : AWB-2315714531-2026-06
SUBJECT             : wFirma PZ 4/6/2026, document 189364835
SEVERITY            : Architectural (workflow-class, not shipment-specific)

DEFECT CLASS A      : Landed-cost incompleteness on a degraded ingestion path
  Status            : CLOSED
  Failure mode      : Image-only ingestion path did not supply Freight + Insurance
                      to process_batch(); engine computed incomplete landed cost;
                      customs value fabricated as CIF = 0.00 (not honest UNKNOWN).
  Note              : Engine authority was intact. The input PATH was incomplete —
                      this is incompleteness, not loss of the authority itself.
  Fix               : PR #648 (8024c50)

DEFECT CLASS B      : External-reference authority loss on audit regeneration
  Status            : CLOSED
  Failure mode      : wfirma_export absent from audit_merge.PRESERVED_KEYS; every
                      Run PZ rebuilt audit.json from engine output and nulled the
                      booked-PZ pointer. Link survived only in the append-only timeline.
  Fix               : PR #652 (03ffce9)

RULE ESTABLISHMENT
  Rule 1 (Calculate): Landed cost is complete and computed by one engine across
                      every ingestion path. CIF is tri-state, never silent 0.00.   ESTABLISHED
  Rule 2 (Preserve) : External-reference authority is preserved across regeneration
                      (PRESERVED_KEYS or engine-written).                            ESTABLISHED
  Rule 3 (Reconcile): Reconciliation authority between engine and wFirma.            NOT BUILT — roadmap

DEPLOYMENT STATUS
  #648              : DEPLOYED (production functionally at 8024c50 before this gate)
  #652              : DEPLOYED — origin/main 03ffce9; scoped single-file robocopy of
                      service/app/services/audit_merge.py; operator-executed.
  Production HEAD   : 03ffce9

VERIFICATION OUTCOMES
  7-agent gate      : BLOCKED (full baseline suites not yet run) -> READY after suites
  Tests             : PZ tests/test_pz_*.py 221 passed (+1 pre-existing #613 failure);
                      carrier tests/test_carrier_*.py 420 passed (>=412 baseline);
                      focused test_audit_merge.py 27/27; golden regression 160/160
  Runtime check     : wfirma_export in PRESERVED_KEYS == True; no stale-.pyc shadow
  Authority restore : wfirma_export.wfirma_pz_doc_id = 189364835 restored via
                      reconcile_from_timeline; durable post-#652
  Scorecard         : .claude/memory/scorecards/2026-06-18-pr652-deploy-gate.md
                      (6 EXEMPLARY, 1 ACCEPTABLE; 0 NEEDS-TUNING/UNRELIABLE)
```

---

## 2. What Changed and What Did Not

### What changed — two independent defect classes, two fixes

- **Class A fix (#648 / `8024c50`).** The image-only ingestion path now allocates Freight + Insurance
  into PZ net by value, and customs value routes through the tri-state CIF authority
  (`cif_resolver.py` → `cif_authority.py`). A degraded ingestion path can no longer produce a silent
  CIF = 0.00.
- **Class B fix (#652 / `03ffce9`).** `wfirma_export` is now in `audit_merge.PRESERVED_KEYS`. A Run PZ
  that omits the key keeps the existing booked-PZ pointer; a meaningful regenerated value still wins
  (asymmetric merge). The audit→wFirma link can no longer be silently nulled by regeneration.
- **Four documentation/consistency issues resolved** (`912ed40`): chronological incident timeline added
  to the closure document; the explicit architectural-maturity progression added to the architecture
  brief; the formal classification recorded with a precise reason; two real PROJECT_STATE
  inconsistencies corrected (stale "not deployed" status; stale origin/main HEAD block → `03ffce9`).

### What did not change — deliberately held constant

- **Business decisions.** The wFirma value correction (§3) is untouched. No wFirma write was performed.
- **Deployment decisions.** No additional production change beyond #652. Production writes remain
  operator-only (deploy-guard).
- **Authority ownership.** No owner moved. `process_batch()` still owns landed-cost calculation;
  wFirma remains the system of record for booked documents; `audit.wfirma_export` remains a projection.
- **Incident classification.** Severity (Architectural) and the resolution theme (authority
  consolidation + preservation contract) are confirmed and unchanged. Only class *names* and the
  *reason* were made precise — the classification itself did not move.
- **Correction workflow.** Still manual wFirma UI correction or cancel/recreate via the gated
  `global_pz_push` create path. No automated correction path was added.
- **Governance.** No API price-edit path for posted PZ. wFirma writes require explicit operator
  approval. These policies are unchanged and reaffirmed.

---

## 3. Software Closure vs Business Decision

### Engineering resolution — CLOSED

The platform now **calculates, preserves, restores, and records correctly**:

- **Calculates** complete landed cost on every ingestion path, with honest tri-state CIF (#648, Rule 1).
- **Preserves** external-reference authority across regeneration (#652, Rule 2).
- **Restores** a lost pointer from append-only timeline authority (`reconcile_from_timeline`).
- **Records** the booked-PZ link durably in `audit.json` post-#652.

No software defect remains open for this incident. The engine and local audit are correct.

### Business decision — OPEN

One item requires accounting/business action, not engineering:

- **Business item:** wFirma PZ 4/6/2026, document **189364835** — booked net **2,280.14 PLN** vs corrected
  authority **2,736.87 PLN**, a gap of **+456.73 PLN (+20.0%)**.
- **Why it is not a software defect:** The engine and audit are correct. wFirma is the system of record
  and the document is locked; wFirma exposes no validated API edit/delete for a booked PZ.
- **Owner:** Operator / accounting.
- **Path:** Manual line-price correction in the wFirma UI, or cancel/recreate via the gated
  `global_pz_push` path from the corrected `pz_rows.json`, recording old → new document linkage.
- **Constraint:** No wFirma write without explicit operator approval.

The line is clean: **engineering has delivered correct data; the business must reconcile the booked
document.**

---

## 4. Strategic Next Step — Rule 3: Reconciliation Authority

Rule 3 is the forward architecture move, not another patch. Rules 1 and 2 guarantee the engine
computes the correct value and the audit retains the link. Neither makes the **divergence between the
engine and wFirma observable**. That is the missing authority — and it is the exact gap that let this
incident reach production unnoticed.

**Progression from manual notice to automatic comparison to operator workflow:**

1. **Manual notice (today).** An operator happened to observe the value gap and the null pointer.
   Detection depends on a human looking. This is the current, fragile control.
2. **Automatic comparison (Rule 3 — Priority 1).** A read-only Global PZ ↔ wFirma comparison layer
   compares the recalculated PZ result (resolved authority) against the booked wFirma document
   (`fetch_warehouse_pz`) across all shipments, and surfaces divergence **before a period closes**.
   It flags; it never auto-corrects. This removes "a human happened to look" from the control path.
3. **Operator workflow (Priority 2).** A guided correction workflow operationalizes the manual/recreate
   paths — recreate via `global_pz_push` behind `WFIRMA_CORRECTION_PUSH_ALLOWED` (default OFF), with the
   five background-automation safety properties and automatic old → new linkage. It depends on
   Priority 1 to identify targets.

A further item — wFirma API-edit research (Priority 3) — stays closed and sandbox-gated: no production
API price-edit path until a wFirma sandbox proves safe editing of a posted PZ.

Rule 3 completes the authority lifecycle: **Calculate → Preserve → Recover → Govern → Reconcile.**

---

## 5. Approval Recommendation and Next Actions

**Recommendation: APPROVE / MERGE.** The closure package is fit as permanent reference and audit trail.
Validation confirmed 0 closure-blockers; all surfaced gaps are resolved.

**Merge.**
- PR **#653** (docs-only) — the governance + incident closure package (7 commits). Merge is operator-only.

**Close.**
- Incident **AWB-2315714531-2026-06** — software-closed. Class A (#648) and Class B (#652) deployed and
  verified; authority pointer restored and durable.

**Hand off (do not close — owner action).**
- wFirma PZ 4/6/2026 value correction (document 189364835): operator / accounting.

**Track (process — GATE-4 SCHEDULED).**
- `deploy-qa-reviewer` prompt: PZ-221 / carrier-412 baseline is unconditional.
- `deploy-release-manager` checklist: mandatory `__pycache__` clear before restart.

**Where focus shifts.**
- To **Rule 3 — Global PZ ↔ wFirma reconciliation.** Begin with a design spec / ADR naming the authority
  owner, the comparison rule, and the surfacing point. This is the highest-value architecture work the
  incident revealed: it converts the entire root-cause category from "a human must notice" into a
  surfaced, dispositioned signal.
