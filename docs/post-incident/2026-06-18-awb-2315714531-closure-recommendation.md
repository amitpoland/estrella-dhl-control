# Closure Recommendation — AWB-2315714531-2026-06

**Date:** 2026-06-18
**Audience:** Engineering leadership and business stakeholders
**Reviewer role:** Technical architect / governance reviewer
**Subject:** PR #653 (docs-only closure package); incident AWB-2315714531-2026-06
**Bottom line:** Approve and merge PR #653. Archive the incident on the engineering side. One business decision (document 189364835) remains open and is owned by accounting. Rule 3 is a new strategic initiative, not part of this incident.

---

## 1. Closure Classification — Validated

I validated the evidence trail directly against production (`C:\PZ`) and the repository. Both closed
rules have implementation artifacts on disk, passing tests, verified deployment, and complete
governance documentation.

### Rule 1 — Calculate correctly (#648, `8024c50`) — CLOSED

| Evidence | Result |
|---|---|
| Implementation artifacts (prod) | `app/services/cif_resolver.py`, `app/services/cif_authority.py`, `app/services/vision_extractor.py` PRESENT in `C:\PZ`; engine `pz_import_processor.py` carries the image-only Freight/Insurance code |
| Tests | PZ `tests/test_pz_*.py` 221 passed; carrier 420 passed (≥412); golden regression 160/160; CIF suites green |
| Deployment | Verified live; production functionally at `8024c50` prior to the #652 gate |
| Governance | Rule 1 documented in the architecture brief, incident-closure, and authority-ownership registry; ADR-030 / ADR-031 |

### Rule 2 — Preserve external authority references (#652, `03ffce9`) — CLOSED

| Evidence | Result |
|---|---|
| Implementation artifact (prod) | `C:\PZ\app\services\audit_merge.py` contains `wfirma_export` (3 matches); running-service import confirms `PRESERVED_KEYS includes wfirma_export == True` |
| Tests | `test_audit_merge.py` 27/27 incl. `test_cleared_pointer_is_not_resurrected_by_regen` (no-resurrection contract) |
| Deployment | `03ffce9` deployed via scoped single-file sync; no stale-`.pyc` shadow; 7-agent gate BLOCKED→READY after full suites |
| Authority restore | Live `audit.wfirma_export.wfirma_pz_doc_id == 189364835` — pointer restored and durable post-#652 |
| Governance | Scorecard `.claude/memory/scorecards/2026-06-18-pr652-deploy-gate.md` on disk; PR #653 carries 7 docs-only commits |

### Gaps flagged — none material to closure

- **Two GATE-4 process items (SCHEDULED, non-blocking).** `deploy-qa-reviewer` must treat the
  PZ-221 / carrier-412 baseline as unconditional; `deploy-release-manager` checklist must include the
  mandatory `__pycache__` clear. These are agent-process improvements, not Rule 1/2 closure gaps.
- **One documentation nit (MINOR).** The authority-ownership and architecture docs name
  `audit_merge.PRESERVED_KEYS` / `merge_regenerated_audit()` without the literal file path
  (`service/app/services/audit_merge.py`). Traceable via PR #652; optional to add.
- **One pre-existing test failure (#613).** `test_save_json_csv_ui_round_trip` (Windows CRLF artifact)
  is documented, predates this work, and is not a regression.

**Conclusion:** Rules 1 and 2 are genuinely closed. The evidence trail is complete.

---

## 2. Business vs. Engineering Boundary — Document 189364835

This distinction is the most important point for business stakeholders.

**The platform has already delivered the corrected data and preserved the linkage.** Engineering's
work on this document is done:

- The engine computes the **corrected** value: net **2,736.87 PLN** (the authority in `pz_rows.json`).
- The audit retains the durable link to the booked wFirma document **189364835** (Rule 2).
- The correction is recoverable and will not be lost on regeneration.

**What remains is a business/accounting decision, not an engineering defect.** The booked wFirma PZ
4/6/2026 holds the old value, net **2,280.14 PLN** — a gap of **+456.73 PLN (+20.0%)**. wFirma is the
system of record; the document is locked once booked; wFirma exposes no validated API edit/delete for
a booked PZ. There is nothing left for engineering to fix.

**The business owner now chooses whether to accept the correction**, and by which governed path:
- Manual line-price correction in the wFirma UI, or
- Cancel/recreate the document via the gated `global_pz_push` path from the corrected `pz_rows.json`,
  recording old → new document linkage.

No wFirma write occurs without explicit operator approval. **Owner: operator / accounting.**

---

## 3. Rule 3 — Reconcile External Systems Automatically (Strategic Initiative)

**Rule 3 is a new architectural capability, not a bug fix.** No defect in the current platform requires
it. It exists because this incident revealed that the platform cannot, today, see when a recalculated
PZ value diverges from a booked wFirma value — detection depended on an operator noticing.

**Capability definition.** A read-only layer that:
1. Compares the recalculated PZ value (resolved authority) against the booked wFirma value
   (`fetch_warehouse_pz`) across all shipments.
2. Alerts on differences — before an accounting period closes.
3. Triggers a correction workflow (manual or gated recreate) when an operator chooses to act.

It flags; it never auto-corrects. It writes nothing to wFirma.

**Why it is separated from this incident.** Folding a new capability into an incident closure would
mask scope and bypass the design and governance a new capability requires. Rules 1 and 2 restored
correctness; Rule 3 adds a capability the platform never had. Closing the incident on Rules 1 and 2,
and opening Rule 3 as its own initiative, keeps both honest.

**Governance gates (own to this initiative).** Its own ADR; read-only first with feature flags default
OFF; compares the resolved authority, not raw fields; surfaces as a comparison workflow (operator-
visible per Lesson M); the correction workflow stays behind `WFIRMA_CORRECTION_PUSH_ALLOWED` (default
OFF) with the five background-automation safety properties; full 7-agent deploy gate.

---

## 4. Final Recommendation — PR #653

**Approve and merge: YES.** PR #653 is docs-only, zero blast radius (`.claude/**` and `docs/**` are not
synced to production), and the closure classification it documents is validated. Merge is operator-only
per the deploy-guard policy.

**Archive the incident: YES (engineering side).** Incident AWB-2315714531-2026-06 is software-closed:
Class A (#648) and Class B (#652) are deployed and verified; the authority pointer is restored and
durable. Archive the incident record. Track the one open business item (document 189364835 value
correction) separately under accounting — it does not block archival, because it is not an engineering
defect.

**Rationale for separating Rule 3.** Rules 1 and 2 are corrective — they restored an invariant the
platform was supposed to hold. Rule 3 is additive — it creates a reconciliation capability that never
existed. Mixing a corrective closure with a new build would understate the design work Rule 3 needs and
overstate what this incident delivered. Separation keeps the closure auditable and gives Rule 3 the
ADR, governance gates, and deployment plan a new capability deserves.

**Next steps for the Rule 3 project:**
1. **ADR** — author an ADR naming the authority owner of the comparison, the comparison rule (resolved
   PZ value vs booked wFirma value), the alert threshold/semantics, and the surfacing point. No code
   before the ADR is approved.
2. **UI design** — design where the comparison and alert surface (a comparison workflow), honoring
   Lesson M (operator-visible, authority-honest); define the operator action that hands off to the
   correction workflow.
3. **Roadmap** — sequence the three roadmap items: (1) reconciliation detector, (2) correction
   workflow, (3) sandbox-gated API-edit research. Item 2 depends on item 1; item 3 stays closed until a
   wFirma sandbox proves safe edit of a posted PZ.
4. **Deployment plan** — read-only detector first, flags default OFF, no wFirma write, full 7-agent
   gate, post-deploy verification on a known-divergent shipment (AWB 2315714531 is the canonical first
   case).

**Where focus shifts.** From incident remediation to the Rule 3 reconciliation initiative — the
highest-value architecture work this incident revealed.
