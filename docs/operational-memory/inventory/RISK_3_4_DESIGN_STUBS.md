# Risk-3 and Risk-4 Button Design Stubs

> **NOT FOR OVERNIGHT IMPLEMENTATION.**
>
> These five buttons are write endpoints that mutate lifecycle state and/or invoke external systems (customs, wFirma posting, carrier handoff). They require dedicated security reviews, operator-decision moments, and in some cases schema additions or new states in `inventory_state_engine.STATES`. This document is design scaffolding for the morning operator only.

## Architecture references

- Doc 1 v2 — `INVENTORY_STATE_MACHINE.md` (extend-existing architecture)
- Doc 2 — `BUTTON_REGISTRY.md` (full row for each button)
- Doc 3 — `DATA_SOURCE_MAPPING.md` (per-state data sources)
- Doc 4 — `FAILURE_MODES.md` (all 8 failure categories for write paths)
- Inspector report — `inventory-proforma-flow-map.md` §5 (double-allocation risk)

## Pre-conditions that must hold before any of these ship

1. `reservation_queue.scan_code` exists (Doc 1 v2 §1 documents the gap). Without it, double-allocation cannot be prevented at the engine level.
2. Single-writer discipline preserved — all five buttons must funnel state transitions through `inventory_state_engine.transition()`, never write `inventory_state.state` directly.
3. New states added to `STATES` if introducing flows like `SAMPLE_OUT`, `SAMPLE_RETURNED`, `CONSIGNMENT_OUT`, etc. The current set is 6 (`PURCHASE_TRANSIT, WAREHOUSE_STOCK, DIRECT_DISPATCH_READY, CLIENT_DISPATCHED, SALES_TRANSIT, CLOSED`) — every new lifecycle vertex requires both a `STATES` addition AND a `LEGAL_TRANSITIONS` row.
4. Doc 1 v2 §5 header-lines allocation table accepted as DESIGN (parent `allocation_groups` + child `allocation_pieces`) before any of these buttons writes such rows.
5. **`feat/hybrid-auth-prep` MUST be merged + `settings.api_key` set non-empty in prod** before exposing any of these. The current main-branch posture (empty api_key) means these endpoints would be open to unauthenticated callers — unacceptable for write paths.

---

## Button 5 — Sample out (Risk-3)

**Allocation type:** `SAMPLE`
**State transition:** `WAREHOUSE_STOCK → SAMPLE_OUT` (new state needed)
**Customs implication:** none (samples are domestic in current scope)

### Proposed endpoint contract

```
POST /api/v1/inventory/pieces/{piece_id}/sample-out
Auth: Depends(require_api_key)
Payload:
  { "to_client_name": <str>,
    "operator": <str>,
    "expected_return_at": <ISO8601 | null>,
    "idempotency_key": <str>,
    "note": <str> }
Errors:
  400 INVALID_INPUT
  404 PIECE_NOT_FOUND
  409 WRONG_STATE        (piece not in WAREHOUSE_STOCK)
  409 ALREADY_ALLOCATED  (active allocation_pieces row exists)
  503 DB_UNAVAILABLE
```

### Why Risk-3

- Mutates lifecycle state (`WAREHOUSE_STOCK → SAMPLE_OUT`).
- Writes a row in `allocation_groups`/`allocation_pieces` (Doc 1 v2 §5) — table doesn't exist yet.
- Adjusts what `count_by_state` returns for `WAREHOUSE_STOCK` — affects Stage 2 aggregate, proforma readiness checks, and any other reader of that state.
- Idempotency same as Move stock + transactional guarantee that the state change and the allocation row both succeed (or both rollback).

### Security concerns explicit

- Double-allocation race: two operators sample-out the same scan_code concurrently. Mitigation = UNIQUE index on `(scan_code)` in `allocation_pieces` where `line_status='CONFIRMED'`, combined with the existing `inventory_state.scan_code` UNIQUE.
- Customer-name injection in audit logs: sanitize before storing. Doc 4 §4 covers this pattern.
- Roll-forward only: once `SAMPLE_OUT` is written, the reversal path is button #6 (Sample return). No silent rollback of state.

### Operator decisions needed

1. Should sample-out require operator-customer-allocation pairing (i.e., samples are always to a SPECIFIC client), or can they be unallocated ("display sample")? If the latter, allocation_type fans out further (PROFORMA, DIRECT_DISPATCH, SAMPLE, **DISPLAY**, etc. — already in operator's enum but worth a UI signal).
2. Auto-revert SLA on `expected_return_at`? E.g., if a sample isn't returned in 90 days, escalate to operator.
3. Should the existing `inventory_movement_events` track sample-out as `MOVE` with `to_location=<client-name>`, or introduce a new action verb? Doc 4 §3 leans toward keeping it as MOVE for audit simplicity.

---

## Button 6 — Sample return (Risk-3)

**Allocation type:** `SAMPLE` (closes the prior allocation)
**State transition:** `SAMPLE_OUT → WAREHOUSE_STOCK` (new transition needed)
**Customs implication:** none

### Proposed endpoint contract

```
POST /api/v1/inventory/pieces/{piece_id}/sample-return
Auth: Depends(require_api_key)
Payload:
  { "to_location": <str>,
    "operator": <str>,
    "idempotency_key": <str>,
    "condition": "ok" | "damaged",
    "note": <str> }
Errors:
  same as Sample out, plus:
  409 NO_OPEN_SAMPLE      (no active allocation_pieces row to close)
```

### Why Risk-3

- Mutates state back to `WAREHOUSE_STOCK` (only if the allocation row exists and is open).
- Closes the `allocation_groups` row by transitioning its `status` to `CONSUMED`.
- Adds a return audit entry: condition flag preserved across the operation.

### Security concerns explicit

- Sample-return without a prior sample-out (data drift): reject with `NO_OPEN_SAMPLE`.
- Damaged-condition flag must NOT auto-purge inventory — operator decides if a damaged sample stays in stock as `QUARANTINE` or is removed entirely.
- Replay safety: same idempotency_key strategy as Move stock + Sample out.

### Operator decisions needed

1. Damaged-condition behavior: stay in `WAREHOUSE_STOCK` with `note`, or transition to `QUARANTINE`? `QUARANTINE` would be another new state.
2. Should partial returns be possible (e.g., one piece of a set returns, others stay out)? Per-piece tracking already allows this trivially; UI affordance is the question.

---

## Button 7 — Consignment flows (Risk-3)

**Allocation type:** `CONSIGNMENT`
**State transition:** `WAREHOUSE_STOCK ↔ CONSIGNMENT_OUT` (two new states + two new transitions)
**Customs implication:** TIN ownership flag (titre retained = no customs change; titre transferred = sale)

### Proposed endpoint contracts

```
POST /api/v1/inventory/pieces/{piece_id}/consignment-out
POST /api/v1/inventory/pieces/{piece_id}/consignment-return
POST /api/v1/inventory/pieces/{piece_id}/consignment-convert-to-sale
```

Three operations to capture the consignment lifecycle. Conversion path (last one) is dangerous: it converts `CONSIGNMENT_OUT → SALES_TRANSIT` and triggers proforma/PZ generation. Title transfer is a real commercial event.

### Why Risk-3

- Same state-change + allocation pattern as Sample out.
- Conversion-to-sale invokes proforma machinery downstream (existing routes).
- Long-running state: consignment can sit out for months. Aggregate counts will skew unless surfaced clearly in Stage 2.

### Security concerns explicit

- Conversion-to-sale is the highest-stakes operation in this design. Must require explicit operator signoff via two-step confirm (Doc 4 §5 documents the pattern from proforma post-to-wFirma).
- Audit must retain consignment_id linkage so a returned consignment can be paired with the original send-out row.
- Cross-DB: consignment may need a wfirma_reservation_drafts row before conversion — bridge invariants per Doc 1 v2 §3.

### Operator decisions needed

1. **Customs implication at conversion:** if the consignment crosses borders, what does the conversion event trigger on the customs side? Hold for separate session with customs SME.
2. **Auto-aging:** should consignments older than N days flag a follow-up in the dashboard? UI question.
3. **Allocation type fan-out:** `CONSIGNMENT_OUT` vs. `CONSIGNMENT_RETURN` as separate types, or a single `CONSIGNMENT` with a status field? Operator's locked enum has just `CONSIGNMENT` — leans toward status field.

---

## Button 8 — Goods return (Risk-3)

**Allocation type:** `QUARANTINE` (typical reason for return) or new `RETURN` type
**State transition:** `CLIENT_DISPATCHED → QUARANTINE` (new state) or back to `WAREHOUSE_STOCK` if condition is fine
**Customs implication:** if cross-border, return goods may trigger import duty refund (operator decision)

### Proposed endpoint contract

```
POST /api/v1/inventory/pieces/{piece_id}/goods-return
Auth: Depends(require_api_key)
Payload:
  { "reason": "damaged" | "wrong_item" | "client_changed_mind" | "other",
    "to_location": <str>,
    "operator": <str>,
    "idempotency_key": <str>,
    "linked_pz_doc_id": <str | null>,    # wFirma PZ this return reverses
    "note": <str> }
```

### Why Risk-3

- Pieces returning from CLIENT_DISPATCHED need both a state change AND a wFirma corrective document if the original PZ already posted.
- Reason code drives downstream routing: `damaged` → `QUARANTINE`; `wrong_item` → likely `WAREHOUSE_STOCK` after inspection.
- linked_pz_doc_id ties the return to its originating PZ — out of scope to AUTO-post the reversal; just capture the linkage.

### Security concerns explicit

- Returns must NEVER auto-issue a credit note. Only capture the return state; financial reversal stays with accounting.
- linked_pz_doc_id is a foreign reference into wfirma.db — bridge invariant: validate it exists before accepting the request.
- Reason field is an enum; unknown values rejected.

### Operator decisions needed

1. What's the customs implication of a return crossing borders? Customs SME session needed before implementation.
2. Should goods-return UI cross-link to the wFirma PZ doc immediately, or is that a separate accounting step?

---

## Button 9 — Return to producer (Risk-4)

**Allocation type:** `REPAIR` (typical reason) or new `RETURN_TO_PRODUCER` type
**State transition:** `WAREHOUSE_STOCK → RETURN_TO_PRODUCER` (new terminal-ish state; piece leaves Estrella's inventory but isn't sold)
**Customs implication:** **YES — cross-border re-export likely triggers customs paperwork (CN23, SAD adjustment, possible duty refund)**

### Proposed endpoint contract

```
POST /api/v1/inventory/pieces/{piece_id}/return-to-producer
Auth: Depends(require_api_key)
Payload:
  { "producer_name": <str>,
    "reason": "warranty_repair" | "manufacturing_defect" | "wrong_spec" | "other",
    "operator": <str>,
    "customs_docs": {
      "cn23_uploaded": <bool>,
      "sad_zc429_ref": <str | null>,
      "expected_export_date": <ISO8601>
    },
    "idempotency_key": <str>,
    "note": <str> }
```

### Why Risk-4

- Highest customs-implication button. Goods physically cross the EU border outbound, which is a regulated event.
- Audit trail must satisfy customs auditors (the same gate `routes_lifecycle.py:469` enforces for `DIRECT_DISPATCH_READY`).
- Wrong handling here = real-world legal/financial exposure.

### Security concerns explicit

- Endpoint must NOT be exposed before:
  - Customs SME signs off on the audit-trail design
  - SAD/ZC429 attachment mechanism designed (does it use the existing `dhl_documents` upload path or a new one?)
  - Duty-refund eligibility logic agreed with accounting

### Customs implications explicit

- Reverse SAD generation: when goods are returned to producer, a new customs declaration is issued. Estrella's current SAD parsing (`sad_importer.py`) is read-only. A write path or external-API handoff (DHL re-export) is required.
- Duty refund path: if Estrella already paid import duty on the original entry, the return-to-producer event may trigger a refund claim. This is finance-team territory and is OUT OF SCOPE for this stub.
- CN23 attachment is REQUIRED for shipments under €1000 in some jurisdictions. The button must reject submissions where `cn23_uploaded=false` unless operator explicitly overrides.

### Operator decisions needed

1. Customs SME session — REQUIRED before any implementation. Timeline: separate task, not overnight.
2. CN23 attachment mechanism: reuse `dhl_documents` upload route, or new endpoint?
3. SAD reversal: manual operator workflow (download SAD, file at customs office, scan back in) OR automated wFirma/DHL path?
4. Operator override for `cn23_uploaded=false`: should there be a "I attest this is under €X threshold" checkbox, or hard block?
5. **This button should remain in the disabled state on dashboard.html until at least three of the four above are resolved.**

---

## Common implementation pattern for all five

Once the design decisions land:

1. New router file: `service/app/api/routes_inventory_writes_state.py` (separate from the location-metadata writer for clarity).
2. New service file per button (single-responsibility):
   - `inventory_sample_writer.py`
   - `inventory_consignment_writer.py`
   - `inventory_returns_writer.py`
   - `inventory_producer_return_writer.py`
3. All services funnel state transitions through `inventory_state_engine.transition()`. NO direct `con.execute("UPDATE inventory_state ...")` anywhere.
4. All services use the same idempotency strategy as Move stock — but **after the race fix from `feat/inventory-button-move-stock` lands**.
5. All endpoints get a security review BEFORE commit (Phase 7 model).
6. UI exposure adds matching JSX in InventoryPage; the five disabled action buttons (`move_stock` / `sample_out` / `sample_return` / `goods_return` / `return_prod` at `dashboard.html:1330-1343`) gain handlers and lose the `disabled` attribute.

## What this design does NOT cover

- Mass operations (bulk sample-out for a batch). All buttons are per-piece.
- UI mockups beyond "row click + drawer + form" pattern from Phase 4.4.
- Wire-level details for the Customs SME session (held for that meeting).
- Performance budgets at scale.
- Mobile / scanner integration — the warehouse.html scanner page handles physical scans; these buttons are operator-keyed.

---

## Recommended sequencing for morning operator

Earliest-first:

1. **Resolve `feat/inventory-button-move-stock` race condition** (option A or B per the security review). This is the foundation idempotency pattern for buttons 5–9.
2. Add `reservation_queue.scan_code` column + UNIQUE index. Doc 1 v2 §1 documents the gap.
3. Add new `STATES` entries (`SAMPLE_OUT`, `CONSIGNMENT_OUT`, `QUARANTINE`, `RETURN_TO_PRODUCER`) to `inventory_state_engine.STATES` and matching `LEGAL_TRANSITIONS`. Tests-first — single PR.
4. Implement allocation_groups + allocation_pieces tables (Doc 1 v2 §5 design becomes migration).
5. Implement buttons 5–8 ONE PER PR, each with SECURITY review.
6. Button 9 (Return to producer) — separate Customs SME session, then dedicated PR.

Estimated calendar: 4–6 weeks if customs SME availability is the long pole.
