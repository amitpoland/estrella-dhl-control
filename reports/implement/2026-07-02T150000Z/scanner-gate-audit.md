# Scanner-Gate Audit — 2026-07-02 (read-only sweep @ b934ca91/37807e4d)

**Question:** does any code path treat warehouse scanning as a MANDATORY gate on
commerce/fiscal workflows, contrary to the rule "scan is an optional helper,
never a mandatory gate (unless serial_controlled)"?

**VERDICT: rule already enforced everywhere. No demotion slice needed.**
Lesson N is implemented in backend + UI and pinned by two dedicated regression
tests. The only mandatory-scan path is the sanctioned serial_controlled case.

---

## Backend — every scan-related rejection, classified

| Finding | file:line | Verdict |
|---|---|---|
| MoveStockError("scan_code is required") | service/app/services/inventory_location_writer.py:80 | OPTIONAL-helper — input validation on a piece-op (operation's subject IS a piece id) |
| SampleOutError, same shape | service/app/services/inventory_sample_writer.py:72 | OPTIONAL-helper |
| ReturnsError, same shape | service/app/services/inventory_returns_writer.py:89 | OPTIONAL-helper |
| ValueError("scan_code is required") | service/app/services/inventory_state_engine.py:501; warehouse_db.py:777, :939 | OPTIONAL-helper |
| 400 "scan_codes is empty" on POST /inventory-state/mark-direct-dispatch | service/app/api/routes_lifecycle.py:499 | OPTIONAL-helper — the endpoint's input payload IS a scan-code list; empty = malformed input. Per docstring, per-line failures do not abort the batch |
| Scan completeness required when serial_controlled | service/app/services/warehouse_receipt.py:9, :70-82, :168 (read from audit.json, default False) | MANDATORY-BY-DESIGN — the one sanctioned case (Lesson N) |

## Workflow gates — scan signals routed as advisories

| Finding | file:line | Verdict |
|---|---|---|
| Invalid scan flows appended to batch_advisories | service/app/services/wfirma_reservation.py:283 | ADVISORY |
| "Batch-level blockers (infrastructure only now). Warehouse scan signals are surfaced separately via batch_advisories" | service/app/services/wfirma_reservation.py:495-497 | ADVISORY (explicit in code comment) |
| Stock states incl. no_scan_codes / missing_state routed to stock_advisories; business rule in-code: "Proforma can be created without stock... surfaced as an ADVISORY, never a blocker"; over-bill remains the fiscal gate | service/app/api/routes_proforma.py:1020-1040 | ADVISORY (Lesson N verbatim in code) |

## UI layer

| Finding | file:line | Verdict |
|---|---|---|
| Scan advisories rendered in distinct amber panel; "do NOT gate reservationReady" | service/app/static/v2/proforma-detail.jsx:1981-1985 | ADVISORY |
| "SERIAL-CONTROLLED · scan required" badge | service/app/static/v2/proforma-detail.jsx:3868 (pre-fix numbering) | Correctly labels the one mandatory case |
| "Scan code is required." form validation | service/app/static/warehouse.html:306 | OPTIONAL-helper — scanner UI's own submit validation |
| Lookup button disabled until scan code typed | service/app/static/v2/inventory-page.jsx:424 | OPTIONAL-helper — piece-lookup input |
| STALE COMMENT claiming batch blockers = "warehouse + wFirma config" | service/app/static/v2/proforma-detail.jsx:1972-1978 | Comment-only defect — code below it was already correct. FIXED in this commit (comment now states scan signals arrive as batch_advisories, advisory never blocker). Zero behavior change |

## Schema

- packing_lines.scan_code = TEXT DEFAULT NULL (packing_db.py:140) — nullable,
  with explicit legacy-NULL fallback paths (packing_db.py:1001, :1022-1032;
  warehouse_db.py:229-240).
- NOT NULL scan_code columns exist only in warehouse_db's scan-event tables
  (warehouse_db.py:101, :117, :138, :158) — rows there ARE scans; correctly
  non-null.

## Regression pins (already exist — the demotion is test-enforced since 2026-06-22)

- service/tests/test_authority_separation.py:108
  test_sales_linkage_missing_scan_is_advisory_not_blocker
- service/tests/test_authority_separation.py:137
  test_reservation_ready_not_gated_by_missing_scans

## End-to-end check

A batch can flow receive -> proforma -> reservation with ZERO scan events today:
receipt = quantity confirmation (no scan unless serial_controlled); proforma
issuable with no scans (advisory); reservation-ready not gated by missing scans
(test-pinned).

## DO-NOT-TOUCH list — features that genuinely depend on scan (by nature, not by gate)

These are scan-keyed traceability features; scan_code is their subject, the way
an email needs an address. Their input validation must stay:

- Piece timeline (GET /api/v1/inventory/pieces/{scan_code} unified timeline)
- Direct-dispatch marking (routes_lifecycle mark-direct-dispatch)
- Sample-out / sample-return writers (inventory_sample_writer.py)
- Returns writers (inventory_returns_writer.py)
- Stock-move writer (inventory_location_writer.py)
- Warehouse audit gap detection (warehouse_audit.py:54-76 — compares expected
  vs seen scan codes)
- Stage-2 aggregates (inventory_state_engine.count_by_state)
- serial_controlled receipt completeness (warehouse_receipt.py)

## Recommended actions

1. NO demotion slice — nothing to demote.
2. Comment fix at proforma-detail.jsx:1972-1978 — DONE in this commit.
