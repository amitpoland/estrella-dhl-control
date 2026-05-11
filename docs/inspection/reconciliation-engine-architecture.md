# Retroactive Shipment Reconciliation Engine — Architecture (Stage 1: Inspection + Design)

**Branch:** `feat/reconciliation-engine-inspection` (from `main @ 07f41ad`)
**Status:** DESIGN ONLY — no implementation, no migrations, no production writes.
**Scope:** Recompute derived projections for historical Estrella batches that
predate the new lifecycle/readiness/inventory-aggregate architecture, by
re-running the **current** engines over **existing** audit evidence — never
rewriting history.

> Core mantra: **rebuild derived projections, never rewrite history.**

---

## 1. Reconciliation architecture (overview)

### Core principle

A historical batch carries two distinct classes of state:

| Class | Examples | Treatment under reconcile |
|---|---|---|
| **Source-of-truth evidence** | `audit.json` timeline events, `inventory_state_events`, `inventory_movement_events`, customs documents on disk, wFirma `wfirma_reservation_id`, `proforma_drafts.wfirma_proforma_id` | **Read-only.** Never modified. |
| **Derived projection / cache** | `inventory_state.state` (vs. its event log), `count_by_state()` outputs, batch readiness aggregates, Stage-2 buckets, `dhl_status` 7-state pipeline value, dashboard tile counts | **Re-computable** by running the current derivation function over the source-of-truth evidence. |

Reconciliation only touches the second class, and even then only when (a) a
derivation function exists today, (b) the diff against the stored projection is
mechanical (counts, enums, boolean flags), and (c) the change is reversible via
a snapshot.

### Three-stage workflow

```
┌────────────┐    ┌──────────────┐    ┌────────────┐
│ 1. INSPECT │──► │ 2. DRY-RUN   │──► │ 3. REPAIR  │
│ list scope │    │ diff report  │    │ gated write│
└────────────┘    └──────────────┘    └────────────┘
   operator           operator           operator
   confirms           reviews            confirms
                      per-batch          per-batch
```

Operator-gated between every transition. Default mode is dry-run. Repair is
explicit, per batch, with a confirmation token. There is no "fix everything"
button.

### Data flow

```
                   ┌──────────────────────────────────────────────┐
                   │              EVIDENCE BUNDLE                 │
  audit.json ────► │  timeline[], customs_declaration{},          │
                   │  wfirma_export{}, status, etc.               │  ◄── from
  inv_state_events │                                              │      disk
  inv_move_events  │  inventory event rows (append-only)          │      only
  tracking_db ───► │  tracking events                             │
  documents.db ──► │  customs_declarations, pz_documents          │
  proforma_drafts  │  proforma draft records (live state)         │
  wfirma_drafts ─► │  reservation drafts (external IDs)           │
                   └──────────────────────────────────────────────┘
                                       │
                                       ▼
                          reconcile_batch(batch_id)
                          ┌──────────────────────────┐
                          │ READ ► COMPUTE ► COMPARE │
                          └──────────────────────────┘
                                       │
                       ┌───────────────┼────────────────┐
                       ▼               ▼                ▼
                  identical        safe-rebuild    conflict
                  (no-op)          (gated write)   (operator)
```

### In scope

- Lifecycle-state aggregate counts (`count_by_state()` —
  `service/app/services/inventory_state_engine.py:177-194`).
- DHL pipeline derived state (`compute_dhl_readiness()` —
  `service/app/services/dhl_readiness.py:161-208`).
- Aggregated readiness fan-in (`get_batch_readiness()` —
  `service/app/services/batch_readiness.py:318-362`).
- Sales linkage classification (`sales_linkage._classify_one()` —
  `service/app/services/sales_linkage.py:54-62`).
- Dashboard tile counts and bucket counts when a derivation function exists.

### Out of scope (NEVER touched)

- `inventory_state_events` rows — append-only audit
  (`service/app/services/warehouse_db.py:156-168`).
- `inventory_movement_events` rows — append-only
  (`service/app/services/warehouse_db.py:114-130`).
- `audit.json["timeline"]` array entries — append-only contract per
  `dhl_readiness.py:9-16`.
- wFirma external identifiers (`wfirma_reservation_drafts.wfirma_reservation_id`
  — `service/app/services/wfirma_db.py:83-117`).
- Proforma/invoice link records once `status != 'pending'` —
  `service/app/services/proforma_invoice_link_db.py:12-29`.
- Customs document files in `C:\PZ\storage\sad_ready` / `outputs/<batch>/`.
- All financial values: CIF, duty, freight, VAT — explicitly forbidden by
  the project mandate in `CLAUDE.md` (the Python engine in `process_batch()` is
  the only calculation path).

---

## 2. Evidence map

Where each "status field" surfaced today comes from. **True evidence source** is
the row/event that the operator must trust; **derivation function** is what we
re-run during reconcile; **recompute safe?** is the gate for the safe-write
matrix in Section 9.

| # | Status field (dashboard surface) | Where shown (file:line) | True evidence source | Derivation function (file:line) | Recompute safe? |
|---|---|---|---|---|---|
| 1 | `inventory_state.state` (per scan_code) | `dashboard.html:1719` (`warehouse-operations-attention-lifecycle-pill`) | `inventory_state_events` append log (`warehouse_db.py:156-168`) | `inventory_state_engine.transition()` validates; `get_state()` reads (`inventory_state_engine.py:134-143`) | DANGEROUS-history (current `state` row is the projection of the event log; can be rebuilt from events but is also written by `transition()` — see §10) |
| 2 | Lifecycle bucket counts (PURCHASE_TRANSIT / WAREHOUSE_STOCK / DIRECT_DISPATCH_READY / CLIENT_DISPATCHED / SALES_TRANSIT / CLOSED) | `dashboard.html:1622` (`warehouse-operations-card`) | `inventory_state` rows | `count_by_state()` (`inventory_state_engine.py:177-194`) | SAFE-recompute (pure aggregate of `inventory_state`) |
| 3 | Warehouse domain `status` (clean/partial/empty/n/a) | `dashboard.html:1622` (warehouse card readiness banner) | `inventory_current_location` + packing rows | `batch_readiness._warehouse_domain()` (`batch_readiness.py:38-96`) → `warehouse_audit.get_batch_completion()` (`warehouse_audit.py:228`) | SAFE-recompute |
| 4 | Missing scan count | `dashboard.html:2188` (`dhl-customs-operations-attention-tracking-pill` etc.) | `inventory_current_location` rows for batch | `warehouse_audit.get_missing_scans()` (`warehouse_audit.py:50`) | SAFE-recompute |
| 5 | Invalid flow count | warehouse card | events vs. expected ordering | `warehouse_audit.get_invalid_flows()` (`warehouse_audit.py:132`) | SAFE-recompute |
| 6 | Orphan inventory count | warehouse card | scan_codes with no packing match | `warehouse_audit.get_orphan_inventory()` (`warehouse_audit.py:197`) | SAFE-recompute |
| 7 | Sales domain status (ready / warnings / missing / none) | `dashboard.html:1828` (`sales-accounting-operations-card`) | `documents.invoice_lines` + `inventory_current_location` | `batch_readiness._sales_domain()` (`batch_readiness.py:99-149`) → `sales_linkage.get_sales_linkage()` | SAFE-recompute |
| 8 | Sales item classification (ready/pending_dispatch/not_ready/missing_scan) | sales card pill | `inventory_current_location.current_status` | `sales_linkage._classify_one()` (`sales_linkage.py:54-62`) | SAFE-recompute |
| 9 | wFirma domain status (ready/blocked/not_configured/created/none) | `dashboard.html:1936` (`sales-accounting-operations-attention-wfirma-pill`) | `wfirma_reservation_drafts` rows | `batch_readiness._wfirma_domain()` (`batch_readiness.py:152-217`) | SAFE-recompute (READS draft state; never recomputes external IDs) |
| 10 | wFirma reservation ID | wfirma pill / sales card | `wfirma_reservation_drafts.wfirma_reservation_id` (`wfirma_db.py:119-`) | none — external system value | IMMUTABLE-external |
| 11 | wFirma PZ doc id | dashboard PZ badge (`dashboard.html:1944` `sales-accounting-operations-attention-pz-pill`) | `audit.wfirma_export.wfirma_pz_doc_id` | populated by app; reconciled by `audit_persist.reconcile_from_timeline()` (`audit_persist.py:536-583`) | SAFE-recompute (only when timeline carries `wfirma_pz_created` event AND field is empty — see §10) |
| 12 | DHL pipeline state (7-stage) | `dashboard.html:2171` (`dhl-customs-operations-attention-dhl-pill`) | `audit.timeline` events (see `_EVENT_STATE_MAP` `dhl_readiness.py:45-68`) | `compute_dhl_readiness()` (`dhl_readiness.py:161-208`) | SAFE-recompute (pure function over timeline) |
| 13 | SAD received flag | `dhl-customs-operations-attention-sad-pill` (`dashboard.html:2179`) | timeline `zc429_received`/`pzc_received`/`sad_uploaded`/`duty_note_received` events OR `audit.customs_declaration.received` (`dhl_readiness.py:191-201`) | `get_dhl_readiness()` (`dhl_readiness.py:211-412`) | SAFE-recompute |
| 14 | DHL SLA breach | dhl card warning | timeline outbound/inbound events (`dhl_readiness.py:72-93`) | `get_dhl_readiness()` SLA block (`dhl_readiness.py:312-332`) | SAFE-recompute |
| 15 | DHL `days_since_last_outbound` | dhl card | timeline outbound events | `dhl_readiness.py:317-323` | SAFE-recompute |
| 16 | `next_required_action` | dhl card next-step | derived from `best_state` | `dhl_readiness._NEXT_ACTION` map (`dhl_readiness.py:99-107`) | SAFE-recompute |
| 17 | `pz_generated` flag | dhl card | `audit.wfirma_export.wfirma_pz_doc_id` OR `wfirma_pz_fullnumber` | `dhl_readiness.py:366-369` | SAFE-recompute (reads only) |
| 18 | Overall `ready_for_closure` | top of dashboard batch row | fan-in of 4 domains | `batch_readiness.get_batch_readiness()` (`batch_readiness.py:318-362`) | SAFE-recompute |
| 19 | `next_step` (priority) | dashboard active table | fan-in priority logic | `batch_readiness._next_step()` (`batch_readiness.py:269-313`) | SAFE-recompute |
| 20 | Tracking events per AWB | `dhl-customs-operations-attention-tracking-pill` | `shipment_tracking_events` rows (`tracking_db.py:31-58`) | `tracking_db.get_events_for_batch()` | IMMUTABLE-evidence (rows are evidence, not projection) |
| 21 | AWB / carrier on batch | dhl card | `shipment_tracking_events.awb` (fallback to timeline detail) | `get_dhl_readiness()` lines 226-238 | SAFE-recompute (only the *display* — never overwrite original AWB) |
| 22 | Proforma draft status | broker followup panel `dashboard.html:2653` | `proforma_drafts` rows (`proforma_links.db`) | proforma_drafts table — direct read | DANGEROUS-business (status reflects external commitment) |
| 23 | Proforma → invoice link (PROF → FV) | sales tab | `proforma_invoice_links.status` (`proforma_invoice_link_db.py:12-29`) | n/a — direct read | IMMUTABLE-external once status != 'pending' |
| 24 | Reservation queue status (pending/ready/created/blocked) | reservations panel | `reservation_queue.status` (`reservation_db.py:89-119`) | populated by `reservation_worker.py`; status field | DANGEROUS-business (drives external POST) |
| 25 | wFirma customer match_status | wfirma panel | `wfirma_customer_mapping.match_status` (`reservation_db.py:76-87`) | external sync results | IMMUTABLE-external |
| 26 | wFirma product sync_status | wfirma panel | `wfirma_product_mapping.sync_status` (`reservation_db.py:60-74`) | external sync results | IMMUTABLE-external |
| 27 | Customs declarations / MRN | shipment detail | `documents.customs_declarations` row | direct read; MRN is parsed customs evidence | IMMUTABLE-evidence |
| 28 | `audit.timeline[]` events | timeline view per batch | `audit.json["timeline"]` array | append-only contract | IMMUTABLE-history |
| 29 | Email evidence ingestion | email evidence panel `dashboard.html:1793` | `email_evidence/` files + audit pointers | `email_evidence_ingestor` | IMMUTABLE-evidence |
| 30 | Broker-followup CIF gap | `broker-followup-cif-gap` (`dashboard.html:2709`) | computed delta between SAD CIF and invoice total | broker_followup_detector module | SAFE-recompute |
| 31 | DSK received timestamp | dhl card | first `cesja_received`/`dsk_received` event | `dhl_readiness.py:277-279` | SAFE-recompute |
| 32 | Agency forwarded timestamp | dhl card | first `agency_email_sent` event | `dhl_readiness.py:281-282` | SAFE-recompute |
| 33 | Customs cleared timestamp | dhl card | first `ganther_pzc_sent`/`payment_confirmed`/`ganther_invoice_received` event | `dhl_readiness.py:289-292` | SAFE-recompute |
| 34 | Missing documents list | dhl card | derived per-state from `best_state` | `dhl_readiness.py:385-389` | SAFE-recompute |
| 35 | Sales-accounting bucket counts | `sales-accounting-operations-buckets` (`dashboard.html:1842`) | aggregate over `inventory_state` + sales linkage results | aggregated in routes/dashboard layer (no single named fn on this branch) | SAFE-recompute |
| 36 | DHL-customs bucket counts | `dhl-customs-operations-buckets` (`dashboard.html:2076`) | aggregate over `dhl_status` per batch | aggregated in routes/dashboard layer | SAFE-recompute |
| 37 | Warehouse operations bucket counts | `warehouse-operations-buckets` (`dashboard.html:1636`) | aggregate over warehouse domain | aggregated in routes/dashboard layer | SAFE-recompute |
| 38 | Sales pill (per batch) | `sales-accounting-operations-attention-sales-pill` (`dashboard.html:1928`) | sales_linkage result | `sales_linkage.get_sales_linkage()` | SAFE-recompute |
| 39 | Action diagnostics | `routes_dashboard.py:1578` `/batches/{batch_id}/action-diagnostics` | composite of multiple readiness inputs | route handler | SAFE-recompute |
| 40 | Email-evidence rescan signal | `routes_dashboard.py:2220` POST endpoint | re-classifies attachments | rescan endpoint | DANGEROUS-history (this is itself a write; reconcile would not call it) |
| 41 | Proforma readiness | `routes_dashboard.py:2333` | composite over packing + inventory_state | proforma-readiness route handler | SAFE-recompute |
| 42 | ZC429 lineage | `routes_dashboard.py:2583` | lineage panel | route handler | SAFE-recompute |
| 43 | CN/HSN classification | `routes_dashboard.py:2820` | classifier output | classifier | SAFE-recompute (classifier output; not an external commitment) |
| 44 | Archive status | `routes_dashboard.py:3194` `/archive` | `audit.json` status flag | direct read | IMMUTABLE-history |
| 45 | Active shipment monitor | `active_shipment_monitor.py` | aggregate of batch states | monitor service | SAFE-recompute |
| 46 | PZ document id (local) | sales card | `documents.pz_documents` row | direct read | IMMUTABLE-history |
| 47 | Invoice lines | sales card | `documents.invoice_lines` rows | direct read | IMMUTABLE-evidence (parsed from invoice) |
| 48 | `audit.wfirma_export.pz_source` | derived | derived in `reconcile_from_timeline()` (`audit_persist.py:565-567`) | SAFE-recompute (only fills empty) |
| 49 | Audit `status` field (e.g. failed/partial) | dashboard status pill | `restamp_pz_status_if_done()` (`audit_persist.py:68-124`) | SAFE-recompute (idempotent restamp) |
| 50 | Dashboard active table empty state | `active-table-empty-state` (`dashboard.html:2355`) | computed UI projection | n/a (UI only) | SAFE-recompute |

Note on row 1 (`inventory_state.state`): the table row is a **projection** of
the append-only `inventory_state_events` log; in principle it is rebuildable.
But because `transition()` (`inventory_state_engine.py:207-310`) is the only
sanctioned writer and enforces evidence gates (e.g. RECEIVE-event requirement
for `DIRECT_DISPATCH_READY`, `inventory_state_engine.py:254-268`), reconcile
should **not** bypass that path. Treat as DANGEROUS-history — re-derivation is
acceptable only by replaying events through `transition()` (out of scope for
Stage 1).

---

## 3. Stale-cache risks

Each projection that could drift from its source of truth, ranked by how the
drift can occur and whether `reconcile_batch()` heals it.

| Cache / projection | How drift happens | Detection today | Reconcile heals? |
|---|---|---|---|
| `inventory_state.state` vs. `inventory_state_events` | A concurrent write into events without updating the state row, or a crash between INSERT-event and UPDATE-state (`transition()` is single-txn under `_lock`, `inventory_state_engine.py:235`) | None — invariant assumed | Partial — could flag mismatch in COMPARE phase; would not rewrite (DANGEROUS) |
| Lifecycle bucket counts (Stage 1 / Stage 2) | Counts cached anywhere they're served from outside `count_by_state()` (live SELECT used today, `inventory_state_engine.py:180-190`) | Tests | YES — re-running `count_by_state()` is the cure |
| DHL `dhl_status` value (if cached on dashboard) | Operator updates audit.json while dashboard hold stale value | None | YES — `compute_dhl_readiness()` is pure |
| `audit.wfirma_export.wfirma_pz_doc_id` | wFirma PZ created but audit was not stamped (legacy batches, see comment `audit_persist.py:537-547`) | None automated | YES — `reconcile_from_timeline()` exists today (`audit_persist.py:536-583`) |
| `audit.status` field | Status was set to "failed" before recovery event arrived | None | YES — `restamp_pz_status_if_done()` exists (`audit_persist.py:68`) |
| `batch_readiness.overall.next_step` | Any input domain changed since last fetch (always live read, no cache layer on this branch) | n/a | YES (no cache to fix; recompute is the call) |
| Sales linkage `status` | `inventory_current_location.current_status` updated by a scan after sales card was loaded | n/a | YES — pure function |
| `dhl_readiness.sla_breach` time-derived | Time moves forward → breach develops without any event | Tests | YES — recompute reads `now()` each call |
| `warehouse_audit.get_orphan_inventory()` | New packing import resolves an orphan | Tests | YES |
| Lifecycle transitions silently failed | `EV_INVENTORY_TRANSITION_FAILED` event (`timeline.py:40`) recorded but UI may not surface | Manual audit | NO — operator action required |
| Reservation queue `status='blocked'` | external system became available; local row stale | Tests via worker re-run | NO — handled by `reservation_worker.py`, not reconcile |
| wFirma `wfirma_reservation_id` missing locally | wFirma created it; webhook missed | None | NO — operator must re-pull |

---

## 4. `reconcile_batch(batch_id)` design

### Signature

```python
def reconcile_batch(
    batch_id: str,
    *,
    mode: Literal["dry_run", "repair"] = "dry_run",
    operator: str = "",
    confirmation_token: Optional[str] = None,
) -> ReconcileResult:
    ...
```

- `mode="dry_run"` → COMPARE only, no writes; returns the diff.
- `mode="repair"` → requires `operator` and `confirmation_token`; performs
  gated writes only on `safe-rebuild` rows.

### Phases

**1. READ phase.** Pure file/DB reads; no locks beyond per-connection. Loads:

- `audit.json` at `settings.storage_root / "outputs" / batch_id / "audit.json"`
  (`dhl_readiness.py:114`).
- `inventory_state_events` for batch_id via existing `get_history()`
  (`inventory_state_engine.py:146-156`); aggregate across all scan_codes that
  carry the `batch_id` (use index `idx_invstate_batch`,
  `warehouse_db.py:150-151`).
- `inventory_movement_events` for batch_id via index `idx_ime_batch`
  (`warehouse_db.py:129-130`).
- `shipment_tracking_events` via `tracking_db.get_events_for_batch()`
  (`tracking_db.py`).
- `documents.customs_declarations` for the batch's MRN/declaration row.
- `wfirma_reservation_drafts` rows (`wfirma_db.py:83-117`) — **read-only**.
- `proforma_drafts` rows — read-only.

Build a `BatchEvidenceBundle` typed object holding all of the above. Bundle is
the **only** input to COMPUTE.

**2. COMPUTE phase.** Pure-function calls into existing derivers:

- `inventory_state_engine.count_by_state(batch_id)` (`:177-194`).
- `dhl_readiness.compute_dhl_readiness(audit)` (`:161-208`) — pure-from-audit
  variant.
- `batch_readiness.get_batch_readiness(batch_id)` (`:318-362`).
- `sales_linkage.get_sales_linkage(batch_id)`.
- `audit_persist.reconcile_from_timeline()` semantics replicated in dry-run
  (`:536-583`) — but **never write** in this phase; only stage the proposed
  diff.

Produces a `ComputedProjection` snapshot.

**3. COMPARE phase.** Field-by-field diff between `ComputedProjection` and the
currently-served projection (which for live functions is the same — making the
comparison degenerate; for cached projections, the comparison surfaces drift).

Each diff classified as:

- **identical** — no action.
- **safe-rebuild** — covered by the matrix in §9 with class `SAFE-recompute`.
- **conflict-needs-operator** — stored value is a `DANGEROUS-*` or
  `IMMUTABLE-*` class, OR the recompute disagrees with a value already
  committed to an external system.

**4. WRITE phase.** Only `safe-rebuild` rows are written. Each write is
preceded by a snapshot row in `reconciliation_snapshots` (§8). Conflicts are
surfaced in the response payload; never auto-resolved.

### Idempotency

- Running `reconcile_batch(b, mode="dry_run")` twice produces identical output.
- Running `reconcile_batch(b, mode="repair")` once and then again with no new
  events between calls produces zero writes the second time — every diff
  classifies as `identical`. This is the core test invariant.
- Idempotency relies on derivers being pure: `count_by_state()`,
  `compute_dhl_readiness()`, and `_warehouse_domain()` are all pure functions
  over their inputs.

### Read-only default

`mode="dry_run"` is the default. Callers must opt into `mode="repair"` with
both an operator identity and a confirmation token issued by the dry-run report
(token = SHA256 of the diff payload; operator UX in §11).

---

## 5. `reconcile_all_batches()` design

```python
def reconcile_all_batches(
    *,
    mode: Literal["dry_run", "repair"] = "dry_run",
    operator: str = "",
    since: Optional[str] = None,
    limit: Optional[int] = None,
    checkpoint_path: Path = settings.storage_root / "reconcile.ckpt",
) -> ReconcileAllReport:
    ...
```

### Iteration order

By `audit.json["timestamp"]` ASC — oldest batches first. Rationale: oldest
batches predate the most engines and carry the most drift; surfacing them first
lets the operator triage the worst legacy state before touching anything live.

Batch enumeration: list `settings.storage_root / "outputs"` (directories like
`SHIPMENT_1012178215_2026-05_da47e465` observed in `C:\PZ\storage\outputs`),
read each `audit.json["timestamp"]`, sort ASC.

### Streaming + checkpointing

- Process one batch at a time. Stream results to `ReconcileAllReport.batches[]`
  via a generator; callers can write to disk as they consume.
- After each batch completes (or fails) write a `{batch_id, status, last_ts}`
  line to `checkpoint_path` (JSONL). On resume, skip batch_ids already in the
  checkpoint with a terminal status.
- A crash mid-batch leaves that batch in `in_progress`; resume re-runs it.
  Because `reconcile_batch` is idempotent, re-running is safe.

### Per-batch failure isolation

Each batch is wrapped in `try/except`. On exception: record `status="failed"`,
the exception message, and continue to the next batch. The single failure does
not halt the run. This is the same pattern as `batch_readiness.py:95` and
`:148` — every domain helper catches `Exception` and returns a fallback dict.

### Summary report

```
{
  "total":      <int>,
  "identical":  <int>,    # batches with zero diffs
  "repaired":   <int>,    # batches where safe-rebuild writes occurred (repair mode only)
  "conflict":   <int>,    # batches with at least one conflict
  "failed":     <int>,    # batches that threw
  "batches":    [...]     # per-batch detail (see §7)
}
```

---

## 6. Dry-run mode

`mode="dry_run"` is the **default**. Operator workflow:

1. Operator triggers `reconcile_all_batches(mode="dry_run", since=...)`.
2. Engine writes a markdown report to
   `C:\PZ\storage\reconciliation\reports\<run_id>.md` (suggested path —
   subject to operator review; for now, the path is not created — design only).
3. Operator opens the report, greps for `conflict:` and `safe-rebuild:`
   sections, picks batches to repair.
4. Operator invokes `reconcile_batch(batch_id, mode="repair", ...)` per batch,
   using the per-batch confirmation token printed in the dry-run report.

No writes occur in dry-run. No `reconciliation_snapshots` rows are created.

---

## 7. Audit report format

Markdown report produced by dry-run. One file per run.

### Aggregate header

```
# Reconcile run <run_id> — <ts>

Mode:       dry_run
Operator:   <op>
Batches:    20 total
Identical:  12
Safe-rebuild candidates: 5
Conflicts:  2
Failed:     1
```

### Per-batch section

```
## SHIPMENT_1012178215_2026-05_da47e465

audit.json timestamp: 2026-04-12T...

| field                            | stored value      | recomputed value  | classification    | recommended action                |
|----------------------------------|-------------------|-------------------|-------------------|-----------------------------------|
| dhl_status                       | "agency_forwarded"| "sad_received"    | safe-rebuild      | repair: update dashboard projection |
| audit.wfirma_export.wfirma_pz_doc_id | ""           | "PZ-12345"        | safe-rebuild      | repair: copy from timeline event  |
| inventory_state_counts.WAREHOUSE_STOCK | 8           | 8                 | identical         | none                              |
| wfirma_reservation_drafts.status | "created"         | (no recompute)    | identical         | none                              |
| proforma_drafts[42].status       | "issued"          | (no recompute)    | identical         | none                              |
| inventory_state[scan=X].state    | "WAREHOUSE_STOCK" | "PURCHASE_TRANSIT" via event replay | conflict-needs-operator | operator decision required — replay history? |

Confirmation token: sha256:abc123...
Repair command:    reconcile_batch("SHIPMENT_1012178215_...", mode="repair", confirmation_token="sha256:abc123...")
```

---

## 8. Rollback strategy

### Snapshot table (DESIGN — not created)

Proposed schema:

```sql
CREATE TABLE reconciliation_snapshots (
    id                  TEXT PRIMARY KEY,                        -- uuid
    run_id              TEXT NOT NULL,                           -- groups one reconcile_all run
    batch_id            TEXT NOT NULL,
    field_path          TEXT NOT NULL,                           -- e.g. "audit.wfirma_export.wfirma_pz_doc_id"
    prior_value_json    TEXT NOT NULL,                           -- JSON-encoded prior value
    new_value_json      TEXT NOT NULL,
    classification      TEXT NOT NULL,                           -- safe-rebuild | ...
    operator            TEXT NOT NULL,
    confirmation_token  TEXT NOT NULL,                           -- token operator used
    written_at          TEXT NOT NULL,
    reverted_at         TEXT DEFAULT NULL,                       -- set on reverse-reconcile
    revert_operator     TEXT DEFAULT NULL
);

CREATE INDEX idx_recon_snap_batch  ON reconciliation_snapshots (batch_id);
CREATE INDEX idx_recon_snap_run    ON reconciliation_snapshots (run_id);
CREATE INDEX idx_recon_snap_active ON reconciliation_snapshots (reverted_at) WHERE reverted_at IS NULL;
```

### Reverse-reconcile

```python
def revert_reconcile(run_id: str, *, operator: str, confirmation_token: str) -> RevertReport:
    ...
```

Reads all rows in `reconciliation_snapshots WHERE run_id=? AND reverted_at IS NULL`,
restores `prior_value_json` to the original field. Stamps `reverted_at` and
`revert_operator`.

Operator-gated. Cannot revert a snapshot whose target field has been *further
mutated since the reconcile write* — in that case, surface a hard conflict and
require operator decision.

---

## 9. Safe-write matrix

The most important deliverable. **Anything not on this table as "YES" must be
treated as NO.** Default is no.

| # | Operation | Class | Allowed in reconcile? | Why |
|---|---|---|---|---|
| 1 | recompute `count_by_state(batch_id)` | SAFE-recompute | YES | pure aggregate of `inventory_state`; no storage layer to update on this branch — value is live (`inventory_state_engine.py:177-194`) |
| 2 | recompute `compute_dhl_readiness(audit)` output | SAFE-recompute | YES | pure function over audit (`dhl_readiness.py:161-208`); no separate storage |
| 3 | recompute Stage-2 aggregate bucket counts | SAFE-recompute | YES | aggregates served live from `inventory_state` |
| 4 | recompute warehouse domain status | SAFE-recompute | YES | pure read of completion / orphans (`batch_readiness.py:38-96`) |
| 5 | recompute sales domain status | SAFE-recompute | YES | pure read of linkage (`batch_readiness.py:99-149`) |
| 6 | recompute wFirma domain *display label* | SAFE-recompute | YES | reads draft rows only; never writes them (`batch_readiness.py:152-217`) |
| 7 | recompute `next_step` priority | SAFE-recompute | YES | pure function over 4 domain dicts (`batch_readiness.py:269-313`) |
| 8 | fill `audit.wfirma_export.wfirma_pz_doc_id` from timeline event when empty | SAFE-recompute (existing) | YES | guarded by `if not (wfirma_export.get("wfirma_pz_doc_id") or "").strip()` (`audit_persist.py:558`); existing function |
| 9 | `restamp_pz_status_if_done` | SAFE-recompute (existing) | YES | idempotent — only restamps stale `failed` → `partial` when evidence supports it (`audit_persist.py:68-124`) |
| 10 | UPDATE `inventory_state.state` directly | DANGEROUS-history | **NO** | mutates lifecycle audit projection without replaying events — bypasses `transition()` evidence gates (`inventory_state_engine.py:254-268`) |
| 11 | INSERT into `inventory_state_events` | DANGEROUS-history | **NO** | append-only audit log (`warehouse_db.py:156-168`) |
| 12 | INSERT into `inventory_movement_events` | DANGEROUS-history | **NO** | append-only (`warehouse_db.py:114-130`) |
| 13 | Modify any `audit.json["timeline"]` entry | DANGEROUS-history | **NO** | timeline is append-only contract (`dhl_readiness.py:9-16`) |
| 14 | UPDATE `proforma_drafts.status` | DANGEROUS-business | **NO** | external commitment — status reflects a wFirma proforma issuance |
| 15 | UPDATE `proforma_invoice_links` once `status != 'pending'` | DANGEROUS-business | **NO** | `proforma_invoice_link_db.py:12-29` — unique-by-proforma_id with status state machine; reconcile must not collapse states |
| 16 | UPDATE `wfirma_reservation_drafts` | IMMUTABLE-external | **NO** | external commitment lives in this table once submitted (`wfirma_db.py:83-117`) |
| 17 | UPDATE `wfirma_reservation_drafts.wfirma_reservation_id` | IMMUTABLE-external | **NO** | external system identifier — operator-only via wFirma resync |
| 18 | UPDATE `wfirma_customer_mapping` / `wfirma_product_mapping` | IMMUTABLE-external | **NO** | populated by external sync flow (`reservation_db.py:60-87`) |
| 19 | UPDATE `reservation_queue.status` | DANGEROUS-business | **NO** | drives external POST in `reservation_worker.py` |
| 20 | INSERT into `shipment_tracking_events` | IMMUTABLE-evidence | **NO** | evidence rows from carriers / email (`tracking_db.py:31-58`) |
| 21 | UPDATE `documents.customs_declarations` | IMMUTABLE-evidence | **NO** | parsed customs evidence |
| 22 | UPDATE `documents.pz_documents` | IMMUTABLE-history | **NO** | issued PZ records |
| 23 | UPDATE `documents.invoice_lines` | IMMUTABLE-evidence | **NO** | parsed from supplier invoice |
| 24 | DELETE any row from any DB | DANGEROUS-history | **NO** | reconcile never deletes |
| 25 | "Blanket UPDATE inventory_state SET state='CLOSED' WHERE..." | DANGEROUS-history | **NEVER. EXPLICITLY FORBIDDEN.** | this is the exact anti-pattern reconcile exists to prevent |
| 26 | "Auto-close all batches older than X days" | DANGEROUS-business | **NEVER. EXPLICITLY FORBIDDEN.** | closure is a deliberate operator action |
| 27 | "Mark complete" any batch | DANGEROUS-business | **NEVER. EXPLICITLY FORBIDDEN.** | same reason |
| 28 | Write into `reconciliation_snapshots` (precede a real write) | SAFE-meta | YES | by design — see §8 |

**Operator note:** all rows in the "**NO**" rows above remain NO even in `mode="repair"`. The mode gate only unlocks SAFE-recompute writes.

---

## 10. States that should NEVER be overwritten

Each entry: field, why, file:line.

| Field | Why it must never be overwritten | Citation |
|---|---|---|
| `inventory_state_events.*` rows | append-only audit; rebuilding the projection from the log is fine, but altering the log destroys the audit chain | `warehouse_db.py:156-168` |
| `inventory_movement_events.*` rows | append-only audit of physical movement | `warehouse_db.py:114-130` |
| `inventory_state.state` (when stored value matches latest event) | the latest event IS the source of truth; the row is a cache OF that — divergence indicates a write-bug that reconcile must NOT paper over | `inventory_state_engine.py:207-310` |
| `audit.json["timeline"][i]` for any i | append-only — the entire DHL readiness machine and audit chain rely on this | `dhl_readiness.py:9-16`, `audit_persist.py:559-570` (reconcile reads, never edits) |
| `audit.wfirma_export.wfirma_pz_doc_id` once non-empty | external commitment; only fillable when empty | `audit_persist.py:558` (guarded) |
| `wfirma_reservation_drafts.wfirma_reservation_id` | external identifier — wFirma owns it | `wfirma_db.py:83-117` |
| `wfirma_reservation_drafts.status` once `'created'` | the row records a successful POST to wFirma | `batch_readiness.py:190-198` |
| `proforma_drafts.wfirma_proforma_id` | external commitment | `proforma_invoice_link_db.py:30-39` |
| `proforma_invoice_links.invoice_id` once set | external invoice issued via wFirma | `proforma_invoice_link_db.py:12-29` |
| `shipment_tracking_events.*` | evidence captured from carrier / email | `tracking_db.py:31-58` |
| `documents.customs_declarations.mrn` | parsed customs evidence | `dhl_readiness.py:191-201` (reads, never writes) |
| Any row in `inventory_state_events` even from older schema migrations | history is history; schema drift in older rows is acceptable, mutation is not | `warehouse_db.py:156-168` |
| CIF / duty / freight / VAT anywhere | engine mandate — `process_batch()` is the only calculation path | `CLAUDE.md` financial-rules block (project mandate) |

---

## 11. Batch repair flow (operator UX)

### Steps

1. **Pick a batch.** Operator opens the dry-run report (markdown), scans the
   "Conflicts: 0" header line at the top to find batches with only
   safe-rebuild diffs, picks one.
2. **Review the diff inline.** Each row in the per-batch table includes:
   field, stored, recomputed, classification, recommended action.
3. **Authorize.** Operator copies the per-batch `Confirmation token`
   (`sha256:...`) and pastes it into either the admin CLI or the admin-UI
   confirmation box.
4. **Execute.** The reconcile runs in `mode="repair"`. For each safe-rebuild
   row:
   1. INSERT a `reconciliation_snapshots` row with `prior_value_json`.
   2. Write the new value.
   3. Stamp `written_at`.
5. **Receive rollback handle.** Response includes the `run_id` and the list
   of `snapshot_id`s. Operator can revert with
   `revert_reconcile(run_id, operator=..., confirmation_token=...)`.

### CLI sketch (text only)

```
$ pz-reconcile dry-run --since 2026-01-01 --out reports/2026-05-12.md
Wrote report: reports/2026-05-12.md
Total: 20  Identical: 12  Safe: 5  Conflict: 2  Failed: 1

$ pz-reconcile repair --batch SHIPMENT_1012178215_2026-05_da47e465 \
                        --token sha256:abc123... \
                        --operator amit
Wrote 3 safe-rebuild rows. run_id=2026-05-12T10-14-22.
Rollback: pz-reconcile revert --run 2026-05-12T10-14-22 --operator amit
```

### Admin UI sketch (text only)

- Dashboard `Admin → Reconciliation` panel.
- Tab 1 "Dry-run": shows last 5 runs with summary counts; "Open report" button.
- Tab 2 "Per-batch": one row per batch with a `Repair` button. Clicking opens
  a modal that shows the diff table, requires the operator to paste the
  confirmation token, then a `Confirm repair` button. The modal cannot be
  bypassed.
- Tab 3 "Snapshots": list of `reconciliation_snapshots` rows grouped by
  `run_id`, each with a `Revert` button (gated again by a confirmation token).

---

## 12. Implementation phases (Stage-3 plan)

Each phase ends with operator decision points and explicit test requirements.
**Stage 1 (this doc) ends with this section** — no code in Stages 1 or 2.

### Phase 1 — Dry-run `reconcile_batch()` (read-only)

- **Deliverables:** function signature §4; READ phase wired to existing
  loaders; COMPUTE wired to existing derivers; COMPARE produces typed
  `ReconcileDiff` objects; no writes anywhere.
- **Tests required:**
  - Round-trip on a batch with no drift → all `identical`.
  - Manually plant a drift case (empty `wfirma_pz_doc_id` with timeline
    `wfirma_pz_created` event) → produces one safe-rebuild diff.
  - Idempotency: two consecutive runs produce byte-identical output.
- **Security review:** N (read-only).
- **Operator decision points:** none.
- **Estimate:** ~3 days.

### Phase 2 — `reconcile_all_batches()` iterator + checkpoint

- **Deliverables:** generator over batches; JSONL checkpoint at
  `settings.storage_root / "reconcile.ckpt"`; resume-from-checkpoint;
  per-batch try/except.
- **Tests required:**
  - Crash mid-run (raise in middle batch) → checkpoint survives, resume
    completes remainder.
  - 20 batches in order → output is sorted ASC by `audit["timestamp"]`.
- **Security review:** N (read-only).
- **Operator decision points:** none.
- **Estimate:** ~2 days.

### Phase 3 — Pilot on 1 historical shipment

- **Deliverables:** dry-run output for one operator-picked shipment;
  hand-review with operator.
- **Tests required:** none new (uses Phase 1 tests).
- **Security review:** Y (operator and security_governor review the diff
  before any future repair).
- **Operator decision points:** **GO/NO-GO on repair semantics** — does the
  operator agree with the classification of each diff as safe-rebuild vs.
  conflict?

### Phase 4 — Pilot on 5 batches

- **Deliverables:** dry-run report covering 5 batches; per-batch operator
  sign-off.
- **Tests required:** same.
- **Security review:** Y.
- **Operator decision points:** any pattern of false positives must be fixed
  in derivers BEFORE Phase 5.

### Phase 5 — 20-batch dry-run

- **Deliverables:** full dry-run over historical inventory at
  `C:\PZ\storage\outputs\*` (observed: 21 shipment folders).
- **Tests required:** end-to-end harness that compares JSON output across
  runs for idempotency.
- **Security review:** Y.
- **Operator decision points:** approve `mode="repair"` capability for
  Phase 6.

### Phase 6 — Admin UI button + report viewer

- **Deliverables:** dashboard `Admin → Reconciliation` panel (§11); markdown
  report renderer; per-batch repair modal; snapshot list.
- **Tests required:** UI smoke tests; token-gate cannot be bypassed;
  cross-tab refresh.
- **Security review:** Y (security_governor must sign off on operator-gating
  and confirmation token flow).
- **Operator decision points:** Y — final UX sign-off.

### Phase 7 — Production rollout

- **Deliverables:** deploy via the 7-agent gate (`CLAUDE.md` production
  deployment rule); release notes; rollback command documented.
- **Tests required:** full QA gate (PZ + carrier).
- **Security review:** Y.
- **Operator decision points:** Y — go/no-go.

---

## 13. Risk table

| # | Risk | Severity | Mitigation | Detection |
|---|---|---|---|---|
| 1 | Reconcile runs during a concurrent write (e.g. an operator scan flips `inventory_state` mid-recompute) | **CRITICAL** | Per-batch lock acquired via existing `_lock` in `inventory_state_engine.py:117` or a file-based per-batch lock (`service/app/utils/batch_lock.py` exists per inventory). Reconcile retries on lock contention up to N times. | Lock-acquisition timeout in logs. |
| 2 | `audit.json` schema drift across historical batches (e.g. missing `wfirma_export` block on very old batches) | **HIGH** | All readers use `.get(...) or {}` chains; reconcile must do the same (mirrors `dhl_readiness.py:170-174`). Add a schema-version detection step in READ phase. | Test fixture covering 3+ schema generations. |
| 3 | External system (wFirma) state ahead of local cache — reservation posted but local says `'pending'` | **HIGH** | Reconcile **never** writes to wFirma-owned fields (see §9 rows 16-18). Surfaces as `conflict-needs-operator`; operator action is to run the wFirma resync flow, not reconcile. | Diff classification |
| 4 | Idempotency-key collision between repair-write and a live operator write happening simultaneously | **HIGH** | Snapshot-then-write within a single sqlite transaction. If transaction fails, snapshot is rolled back. | sqlite atomicity guarantees |
| 5 | `customs_declaration.received=True` but no `zc429_received` event in timeline (legacy compat path `dhl_readiness.py:191-201`) | MED | Already handled by the deriver itself; reconcile uses the same compat path. | Test covering both paths. |
| 6 | Reconciliation snapshot table grows unbounded | MED | Soft retention: snapshots older than 90 days and already `reverted_at` set can be archived (separate operator-gated routine, not part of reconcile). | Disk usage monitoring. |
| 7 | A batch's audit.json has been hand-edited (legacy operator intervention) and disagrees with event tables | **HIGH — OPERATOR DECISION FLAGGED** | Surface as `conflict-needs-operator`. The audit file is the timeline source of truth (`dhl_readiness.py:114`); diverging event tables must be operator-reviewed. | Diff in COMPARE phase. |
| 8 | Re-running over a partially-completed batch (still in active processing) | **HIGH** | Reconcile detects "active processing" via the most-recent timeline event timestamp; if event within the last N hours, skip with `status="active_skipped"`. | Timestamp-window check. |
| 9 | Operator-supplied confirmation token forgery | MED | Token = SHA256 of the dry-run diff payload + run_id + batch_id; verified server-side before any write. | Token-mismatch logged as security event. |
| 10 | Drift in CIF / duty / freight values | **CRITICAL** | Reconcile **must refuse** to touch any financial field. Hard-coded denylist of field paths in COMPARE phase. Failure to refuse blocks deploy via the 7-agent gate (`CLAUDE.md`). | Test fixture with planted CIF drift → reconcile classifies as `conflict-needs-operator` and never writes. |
| 11 | Customs document missing on disk but `audit.customs_declaration.received=True` | MED | Surface as `conflict-needs-operator` (the operator must locate the document, not reconcile). | Path existence check in READ phase. |
| 12 | Schema migration adds a new column to `inventory_state` after the snapshot was taken | LOW | Snapshot stores prior values per field-path; columns added later are simply not snapshotted (defaults apply). Reverting cannot undo a new-column DEFAULT. | Migration tracked separately. |
| 13 | Timeline event order corruption (`EV_INVENTORY_TRANSITION_FAILED` event without resolution) | MED | Surface in diff as `transition_failures: N`; do not auto-resolve. | Count of failed-transition events per batch. |
| 14 | wFirma PZ doc id present in two places that disagree (timeline event vs. `wfirma_export` block) | MED | The existing `reconcile_from_timeline()` only copies when target is empty (`audit_persist.py:558`); we extend the same rule. Disagreement → `conflict-needs-operator`. | Direct comparison. |
| 15 | Operator runs `mode="repair"` on the wrong batch_id by accident | MED | The confirmation token is bound to `(run_id, batch_id, diff_hash)`; the wrong batch fails token verification. | Server-side token check. |

---

## 14. Estimated runtime

### Measured row counts in `C:\PZ\storage\` (dev environment, READ-ONLY check via Python `sqlite3` module)

| DB | Table | Rows |
|---|---|---|
| warehouse.db | inventory_current_location | 0 |
| warehouse.db | inventory_movement_events | 0 |
| warehouse.db | inventory_state | 0 |
| warehouse.db | inventory_state_events | 0 |
| warehouse.db | warehouse_locations | 0 |
| proforma_links.db | proforma_drafts | 4 |
| proforma_links.db | proforma_draft_events | 8 |
| proforma_links.db | proforma_service_charges | 0 |
| wfirma.db | wfirma_customers / wfirma_products / wfirma_reservation_drafts / wfirma_reservation_lines | 0 each |
| packing.db | packing_documents / packing_lines | 0 each |
| documents.db | customs_declarations | 1 |
| documents.db | invoice_lines | 11 |
| documents.db | pz_documents | 1 |
| documents.db | shipment_documents | 10 |
| documents.db | (others) | 0 |
| pz_main.db | (zero tables) | n/a |
| correction_registry.db | corrections | 0 |
| intake_lineage.db | intake_attachments / events / processing_history | 0 each |

Plus **21 shipment folders** observed in `C:\PZ\storage\outputs\` (e.g.
`SHIPMENT_1012178215_2026-05_da47e465`). The audit.json files in those
folders are not present in the dev environment (sampled folder was empty), so
audit.json per-batch size **cannot be measured here**.

### Runtime estimates

Estimates are based on the structure of READ-phase calls, not measured timings.
Every estimate is marked with its basis.

- **READ phase per batch:** approximately
  - 1 file read (`audit.json`, typically <1 MB based on the timeline-event
    count typical for a full DHL cycle: ~50 events at ~500 bytes = ~25 KB).
    **needs measurement** in production (`C:\PZ\storage\outputs\<batch>/audit.json`).
  - 4-6 sqlite SELECTs over indexed columns (`idx_invstate_batch`,
    `idx_ime_batch`, `idx_te_batch_id`, etc. — all defined in
    `warehouse_db.py:108-130` and `tracking_db.py:53-58`). Indexed lookups on
    a sub-million-row table are ~1 ms each.
- **COMPUTE phase per batch:** pure-Python over a small in-memory bundle —
  sub-millisecond.
- **COMPARE phase per batch:** dictionary diff — sub-millisecond.

**For 20 batches:** Based on N=20 batches at ~10 ms/batch (4-6 indexed SELECTs
+ one ~25 KB JSON parse) = ~200 ms total in dry-run. **Needs measurement** —
the dev DB has zero rows so disk-resident sqlite scan cost cannot be observed
here. In production, with the actual `inventory_state_events` and
`shipment_tracking_events` row counts, expect 10-50 ms/batch.

**For 200 batches:** Linear extrapolation: 2-10 seconds total.

**For 2000 batches:** Linear extrapolation: 20-100 seconds total. At this
scale the cost is dominated by file I/O on `audit.json` reads (one open() +
json.load() per batch), NOT by sqlite query cost. wFirma API rate limits do
**not** apply because reconcile never calls wFirma (we never revalidate
against the live system; see §9 row 16).

**Repair-mode writes:** add one `reconciliation_snapshots` INSERT and one
field UPDATE per safe-rebuild diff. Typical batches have 0-3 safe-rebuild
diffs; cost is negligible compared to READ phase.

**Operator wall-clock:** the dry-run finishes in under a minute for the full
production set. Most of the time goes to operator review, not engine time.

---

## Appendix A — Files inspected with citations

- `service/app/services/inventory_state_engine.py` (lines 8-310, full)
- `service/app/services/warehouse_db.py` (lines 1-220)
- `service/app/services/batch_readiness.py` (full)
- `service/app/services/dhl_readiness.py` (full)
- `service/app/services/wfirma_db.py` (lines 1-120)
- `service/app/services/proforma_invoice_link_db.py` (lines 1-100)
- `service/app/services/tracking_db.py` (lines 1-80)
- `service/app/services/sales_linkage.py` (lines 1-62)
- `service/app/services/reservation_db.py` (lines 1-130)
- `service/app/services/audit_persist.py` (lines 536-583 + grep of all `def`)
- `service/app/services/warehouse_audit.py` (function index lines 50-228)
- `service/app/core/timeline.py` (event constants lines 25-92)
- `service/app/api/routes_dashboard.py` (route index, head 30 routes)
- `service/app/api/routes_lifecycle.py` (route index)
- `service/app/api/routes_batch_readiness.py` (route index)
- `service/app/static/dashboard.html` (data-testid grep — confirmed UI surface IDs cited in §2)

## Appendix B — Files NOT present on this branch / could not access

- `service/app/services/inventory_stage2_aggregator.py` — does not exist on
  this branch (Glob returned no match).
- `service/app/services/inventory_batch_state.py` — does not exist on this
  branch (confirmed per the task prompt note that it lives on
  `feat/inventory-state-batch-read`).
- `service/app/services/pz_engine*.py` — no files match this pattern;
  reconcile does NOT need them (the engine is `process_batch()` per CLAUDE.md,
  separate from reconcile).
- Per-batch `audit.json` payload bodies — directories under
  `C:\PZ\storage\outputs\SHIPMENT_*` are empty in this dev environment, so
  the audit.json schema could only be verified via reads in the source code
  (`dhl_readiness.py:114`, `audit_persist.py:536`), not by sampling a real
  file. Production has 21 shipment folders; sizes need measurement.
