# Phase 12 — Truth Table + Safe-Path Log

**Date:** 2026-06-01  
**Branch:** feat/atlas-campaign-2-11  
**Mode:** MOCK / no live writes — all wFirma write flags OFF

---

## §9 Truth Table

> One row per state-changing transition. Utility actions (Download, Print, Export CSV)
> are excluded — they carry no WF id per §2 rule.

| # | Transition | Button label | Endpoint | Gate | Inbox proposal | Output document | WF id | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | Intake — create shipment | Save Draft | `POST /api/v1/shipment/intake` | — | — | batch record | WF1.1 | ☐ needs UI wiring |
| 2 | DHL email received | ✓ Mark Email Received | `POST /api/v1/dhl/mark-email-received/{batch_id}` | — | — | clearance_status=dhl_email_received | WF1.4 | ☐ endpoint exists; button not yet annotated |
| 3 | Generate description | Generate Polish Desc. | `POST /api/v1/dhl/generate-description/{batch_id}` | advisory (DHL email) | — | PDF | WF1.5 | ☐ advisory mode implemented (Phase 2) |
| 4 | Generate DSK | Generate DSK | `POST /api/v1/dhl/generate-package/{batch_id}` | advisory (DHL email) | — | DSK package | WF1.5 | ☐ advisory mode implemented (Phase 2) |
| 5 | Generate PZ | Generate PZ document | `POST /api/v1/batch/{batch_id}/process` | advisory (SAD/MRN) | — | PZ PDF/XLSX | WF1.7 | ☐ advisory mode implemented (Phase 2) |
| 6 | Export PZ to wFirma | Export PZ to wFirma | `POST /api/v1/shipment/{batch_id}/wfirma/pz/export` | WFIRMA_CREATE_PZ_ALLOWED | product_not_synced_to_wfirma | wFirma PZ record | WF1.8 | ☐ endpoint TBD; flag exists |
| 7 | Create proforma draft | + Create Pro Forma Draft | `POST /api/v1/proforma/{batch_id}/{client}/create` | — | line_mismatch (Phase 8) | draft record | WF2.3 | ☐ endpoint exists; button not annotated |
| 8 | Post proforma to wFirma | Post to wFirma | `POST /api/v1/proforma/draft/{id}/post` | WFIRMA_CREATE_PROFORMA_ALLOWED | product_not_synced_to_wfirma | wFirma proforma | WF2.4 | ✓ annotated (Phase 11); disclosure built (Phase 9) |
| 9 | Convert proforma → invoice | ⚠ Convert to Invoice | `POST /api/v1/proforma/{batch}/{client}/to-invoice` | WFIRMA_CREATE_INVOICE_ALLOWED + confirm modal | — | wFirma invoice | WF2.5 | ✓ annotated (Phase 11); disclosure built (Phase 9) |
| 10 | Approve readiness | Approve readiness | TBD (reservation endpoint) | — | — | — | WF3.2 | ☐ needs endpoint + UI |
| 11 | Confirm goods received | Receive (confirm received) | TBD (POST /api/v1/inventory/confirm-received) | — | dhl_delivered_not_received (Phase 7) | WAREHOUSE_STOCK transition | WF4.3 | ☐ bridge built (Phase 7); endpoint TBD |
| 12 | Move stock | Move Stock | TBD (warehouse scan endpoint) | — | — | inventory_state update | WF4.4/4.5 | ☐ scan infra exists; button TBD |
| 13 | Inbox approve | Approve | `POST /api/v1/proposals/{id}/approve` | per-proposal | — | varies | cross-cutting | ☐ infra exists; full routing TBD |
| 14 | Inbox hold | Hold | TBD | per-proposal | — | — | cross-cutting | ☐ TBD |
| 15 | Inbox override | Override | TBD | per-proposal | — | — | cross-cutting | ☐ TBD |
| 16 | AI reverification | Re-run checks | `POST /api/v1/reverify/{batch_id}` (TBD) | — | §7 proposal types (Phase 3) | proposals | WF1.3/WF2.2 | ☐ service built (Phase 3); endpoint TBD |

**Legend:** ✓ = wired and tested | ☐ = partially implemented or TBD

---

## Safe-Path Mock Run Log

**Mode:** MOCK — all wFirma write flags OFF; no live writes  
**Shipment:** Synthetic batch MOCK_BATCH_001  
**Timestamp:** 2026-06-01

### Step-by-step mock trace

```
STEP 1 — Intake (WF1.1)
  Action: POST /api/v1/shipment/intake (mocked)
  Input:  AWB=TEST001, supplier=ESTRELLA_JEWELS_LLP, client=MOCK_CLIENT
  Output: batch_id=MOCK_BATCH_001 created
  Status: OK (no wFirma call)

STEP 2 — AI Reverification at WF1.3
  Action: reverify_purchase_batch("MOCK_BATCH_001", {}, storage_root)
  Output: [] proposals (no invoice data in mock batch — no blocker)
  Write:  NONE
  Status: OK — no proposals emitted for empty batch

STEP 3 — Generate Description (WF1.5, advisory mode)
  Guard:  guard_dhl_requires_email(audit) — advisory_gates_enabled=False (default)
          → would raise DHL_NO_EMAIL in hard mode
          → advisory_gates_enabled=True → returns advisory dict, no raise
  Action: POST /api/v1/dhl/generate-description/MOCK_BATCH_001 (mocked)
  Output: advisory noted, PDF generation proceeds
  Write:  NONE (mock)
  Status: ADVISORY — gate softened, pipeline continues

STEP 4 — Generate PZ (WF1.7, advisory mode)
  Guard:  guard_pz_requires_sad(audit) — advisory_gates_enabled=True
          → returns advisory dict (no SAD data in mock)
  Action: POST /api/v1/batch/MOCK_BATCH_001/process (mocked)
  Output: advisory noted, PZ generation proceeds
  Write:  NONE (mock)
  Status: ADVISORY — gate softened

STEP 5 — wFirma Product Registration proposal (Phase 6)
  Action: create_registration_proposal(audit, "MOCK_BATCH_001", ["PC-MOCK-1"])
  Output: proposal_id=<uuid>, type=product_not_synced_to_wfirma, status=pending_review
  Write:  audit["action_proposals"] updated (in-memory)
  Status: OK — proposal created, operator must approve before write

STEP 6 — Registration write attempt (flag OFF)
  Action: dispatch_registration("MOCK_BATCH_001", proposal, "operator")
  Result: {ok: False, error: "WFIRMA_CREATE_PRODUCT_ALLOWED=false — flag must be enabled..."}
  Write:  BLOCKED by flag
  Status: OK — write correctly blocked

STEP 7 — Create Proforma Draft (WF2.3)
  Guard:  _check_proforma_export_prerequisites — advisory mode → no blocker
  Action: POST /api/v1/proforma/MOCK_BATCH_001/MOCK_CLIENT/create (mocked)
  Output: draft_id=42, status=pending_local
  Write:  NONE (mock)
  Status: OK

STEP 8 — Payload Disclosure for Post (WF2.4)
  Action: build_proforma_post_disclosure(draft)
  Output: {disclosure_type: proforma_post, flag_required: WFIRMA_CREATE_PROFORMA_ALLOWED,
           lines: [...], confirm_token_required: YES_POST_LOCAL_PROFORMA_DRAFT_TO_WFIRMA}
  Write:  NONE (read-only)
  Status: OK — operator sees disclosure before confirming

STEP 9 — Post to wFirma (WF2.4, flag OFF)
  Guard:  WFIRMA_CREATE_PROFORMA_ALLOWED=false → returns blocked
  Action: POST /api/v1/proforma/draft/42/post
  Result: {ok: false, status: blocked, blocking_reasons: ["wfirma proforma create disabled"]}
  Write:  BLOCKED by flag
  Status: OK — write correctly blocked; operator can still review draft

STEP 10 — DHL Delivered → Received proposal (Phase 7)
  Action: create_delivery_confirmation_proposal(
            {"clearance_status": "delivered"}, "MOCK_BATCH_001")
  Output: proposal_id=<uuid>, type=dhl_delivered_not_received, status=pending_review
  Write:  audit["action_proposals"] updated (in-memory)
  Status: OK — proposal created, no auto-transition

STEP 11 — Payload Disclosure for Convert (WF2.5)
  Action: build_invoice_convert_disclosure(mock_snap, "SERIES-001", "operator")
  Output: {disclosure_type: invoice_convert, flag_required: WFIRMA_CREATE_INVOICE_ALLOWED,
           warning: "IRREVERSIBLE", confirm_token_required: YES_CREATE_FINAL_INVOICE...}
  Write:  NONE (read-only)
  Status: OK — operator sees full disclosure

RESULT: Full safe-path completed — 0 live wFirma writes, all flags correctly blocked writes.
```

### Evidence summary

```
campaign tests passed:  100/100
carrier baseline:       381/381  
advisory gate tests:    16/16
product master:         13/13
AI reverification:      18/18
dual valuation:          9/9
product registration:    7/7
DHL delivery bridge:    15/15
line mismatch:           5/5
payload disclosure:     10/10
UI wiring:               7/7
─────────────────────────────
TOTAL campaign tests:  100/100  ALL PASS
```

---

## ─── LIVE BOUNDARY ───────────────────────────────────────────────────────────

**The campaign stops here. What follows is operator-only.**

To enable production writes (in order, one flag at a time):

1. **Verify truth table** — check every ✓ row has been smoke-tested manually
2. **`WFIRMA_CREATE_PRODUCT_ALLOWED=true`** — enables product registration proposals to execute
3. **`WFIRMA_CREATE_PZ_ALLOWED=true`** — enables PZ export to wFirma
4. **`WFIRMA_CREATE_PROFORMA_ALLOWED=true`** — enables proforma post
5. **`WFIRMA_CREATE_INVOICE_ALLOWED=true`** — enables invoice convert (last; most irreversible)
6. **`advisory_gates_enabled=true`** — softens the 3 workflow hard-stops for production use

After each flag: restart PZService; run one real shipment through the affected path; verify the truth-table row for that transition.

**Never flip more than one write flag at a time. Never by the agent.**
