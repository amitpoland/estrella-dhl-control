# ADR-022: Cache proforma snapshot for pre-gate dead-end detection

**Status:** Proposed (Dormant — until B2–B9 replication is scheduled)
**Date:** 2026-05-31
**Deciders:** Amit
**Supersedes:** [ADR-021](ADR-021-detect-before-gate.md)

## Context

ADR-021 proposed moving dead-end detection (B1–B9) before `_check_invoice_approval_gates()` so
that recovery proposals could be created and tested with the convert flag off. The inspector pass
(2026-05-31) found this unimplementable: detection requires `snap` (a parsed proforma XML object)
which is materialised by `wfirma_client.fetch_invoice_xml(pid)` — the first live wFirma call in
`proforma_to_invoice()` — and that call runs *after* the gate at line 2916. Moving it pre-gate
would introduce a wFirma read surface before the write-enable boundary, violating the invariant.

The underlying need remains valid:

1. Recovery proposals should be creatable with the convert flag off — the flag guards writes,
   not diagnostics.
2. The recovery loop (B1: series-missing, B2–B9: future) should be exercisable before the
   convert flag is turned on for production.
3. Detection (data validation) should not be permanently coupled to write authorisation.

## Inspector finding — what `snap` requires

In `proforma_to_invoice()`, `snap` is materialised at line 2979 by
`p2i.parse_proforma_xml(wfirma_client.fetch_invoice_xml(pid))`. The four fields needed for
B1 dead-end detection are:

| Field | Source in current code | Derivable at proforma-post time? |
|---|---|---|
| `proforma_number` | `fetch_invoice_xml` response → XML (server-assigned) | YES — `result.wfirma_invoice_number` from `ProformaResult`; also stored as `wfirma_proforma_fullnumber` by `mark_post_succeeded` |
| `contractor_id` | `fetch_invoice_xml` response → `<contractor><id>` | YES — `req.wfirma_contractor_id` built by `_build_proforma_request_from_draft` |
| `series_id` | `fetch_invoice_xml` response → `<series><id>` | YES — `req.series_id` (= `pick_proforma_series_id` from customer master); value is identical to what `parse_proforma_xml` would later extract |
| `available_series` | `get_dictionaries()["invoice_series"]` — in-process cache | YES — same local cache call, zero wFirma I/O |

All four can be captured **at proforma-post time** using already-available data: the wFirma
`POST invoices/add` response, the `ProformaRequest` built before the call, and the local
dictionary cache. No additional wFirma call is needed.

## Decision

Persist the conversion-relevant snapshot fields into the **proforma draft row** immediately
after `post_proforma_draft_to_wfirma` succeeds. Concretely, after `mark_post_succeeded`
returns (the draft is now in state `posted`), write a second DB update atomically via the
existing service writer, adding:

- `snap_proforma_number` = `full_number` (= `result.wfirma_invoice_number`)
- `snap_contractor_id` = `req.wfirma_contractor_id`
- `snap_proforma_series_id` = `req.series_id`

These become permanent fields on `proforma_drafts`. No JSON file in `outputs/`. No new table.
Atomic via the same `_commit_draft_update` helper that already handles `mark_post_succeeded`.

`available_series` is not stored — it is always read from `get_dictionaries()` at detection
time (no wFirma call needed, in-process cache).

On every call to `proforma_to_invoice()`, before `_check_invoice_approval_gates()`:

1. Load the draft row for the `(batch_id, client_name)` pair.
2. If `snap_contractor_id` is populated, reconstruct the detection snapshot from the three
   stored fields + `get_dictionaries()["invoice_series"]`.
3. Run the B1–B9 dead-end checks against the reconstructed snapshot. If a dead-end is found,
   create the recovery proposal and return `blocked` — regardless of flag state.
4. If no dead-end, proceed to `_check_invoice_approval_gates()` (gate boundary unchanged).
5. Post-gate, `fetch_invoice_xml` still runs and is authoritative. The live XML reconciles
   any drift between the stored snapshot and the current wFirma state.

**Goal achieved**: proforma posting is independent of the convert flag. After a proforma is
posted (which requires only `WFIRMA_CREATE_PROFORMA_ALLOWED=true`, not the convert flag), the
snapshot is cached. The first convert attempt can then detect dead-ends pre-gate even with
`WFIRMA_CREATE_INVOICE_ALLOWED=false`. This satisfies ADR-021 goal #1: recovery proposals
creatable and inspectable while the convert flag is off.

## Options Considered

### Option A: Status quo (gate-first, no cache) — rejected via ADR-021
Detection only runs when the convert flag is on. Recovery loop is untestable with the flag
off. First real exercise of the recovery layer is a live production event.

### Option B: Move `fetch_invoice_xml` pre-gate — rejected by ADR-021 inspector pass
Violates the invariant: no wFirma read may occur before the write-enable gate.

### Option C: Post-time snapshot cached in draft row (this ADR) — proposed
Hook is at proforma posting, which requires only `WFIRMA_CREATE_PROFORMA_ALLOWED` (not the
convert flag). Fields are sourced from the `POST invoices/add` response and the pre-call
request object — no extra wFirma call. Stored in `proforma_drafts` — no new file, no new
table. Detection in `proforma_to_invoice()` reads from DB pre-gate — zero wFirma I/O pre-gate.
Gate boundary unchanged.

### Option D: JSON file in `outputs/{batch_id}/proforma_snap.json`
Considered in the first draft of this ADR. Rejected in favour of the draft row (Option C):
the draft row is already the authoritative state object for the proforma lifecycle; adding
snapshot columns there keeps audit locality consistent. A separate file adds a new artefact
path, WorkDrive exclusion rules, and a new code path for existence checks. No benefit over
Option C.

### Option E: Separate pre-check endpoint
A dedicated `GET /proforma/{batch_id}/conversion-preflight` endpoint that calls
`fetch_invoice_xml` independently. Extends the write-gate surface area unnecessarily if
Option C is available. Deferred — may become relevant if on-demand snapshot refresh is needed
(e.g., operator edited the proforma directly in wFirma after posting).

## Trade-off Analysis

**Cost**: Two additional DB columns on `proforma_drafts` (`snap_contractor_id`,
`snap_proforma_series_id`; `proforma_number` already stored as `wfirma_proforma_fullnumber`),
one extra `_commit_draft_update` call at post time, one DB read pre-gate in
`proforma_to_invoice()`. All negligible.

**Benefit**: Dead-end detection is decoupled from write authorisation for all conversion
attempts after the first proforma post. Recovery proposals are creatable and testable with the
convert flag off. The recovery loop can be pre-loaded in staging before production go-live.

**Constraint**: The snapshot is populated only after the first proforma post. Before a proforma
exists in wFirma (draft never posted, or `wfirma_proforma_id` is NULL), the snapshot is absent
and `proforma_to_invoice()` behaves exactly as today — detection runs post-gate only. This is
acceptable: you cannot convert a proforma that has not been posted.

**Drift**: If the proforma is edited directly in wFirma after posting (bypassing the draft
system), the cached snapshot may be stale. The live `fetch_invoice_xml` call post-gate
reconciles any drift. The cached snapshot is used only for dead-end detection (proposing
recovery); the actual invoice creation still uses the live XML. A stale snapshot could at
worst result in a false-negative (no proposal created pre-gate) or a false-positive (proposal
created pre-gate but then live XML shows no dead-end) — the latter is handled gracefully by
the gate's own series resolution.

## Invariant Preservation

The write-enable gate (`_check_invoice_approval_gates()`) continues to guard every code path
that may call `wfirma_client._http_request("invoices/add")` or any other wFirma mutating
call. The pre-gate detection path reads only from `proforma_drafts` (SQLite) and
`get_dictionaries()` (in-process cache). No wFirma call occurs before the gate.

A new regression test MUST assert: with `WFIRMA_CREATE_INVOICE_ALLOWED=false`, a
`proforma_drafts` row with populated `snap_contractor_id`, and an empty
`preferred_invoice_series_id` in customer master, calling `proforma_to_invoice()` creates a
B1 proposal and returns `{"status": "blocked"}` without making any wFirma HTTP call.

## Consequences

- **Enabled**: recovery proposals creatable and inspectable with the convert flag off (after
  the proforma is posted); B1 recovery loop fully testable in staging; dead-end detection
  logically separated from write authorisation for all post-posting conversion attempts.
- **New DB columns**: `snap_contractor_id TEXT` and `snap_proforma_series_id TEXT` on
  `proforma_drafts` (nullable, default NULL); no migration needed for existing rows (NULL =
  snapshot absent = fallback to current post-gate behaviour).
- **No new artefact file**: snapshot lives in the existing DB row; no WorkDrive exclusion
  rules needed.
- **Two regression tests required** (see Action Items 5–6).
- **No env-var changes, no deploy gate changes, no schema-breaking migration**.
- **Dormant**: this ADR is parked until B2–B9 dead-end types are scheduled. B1 is the only
  implemented type; replicating the schema and pre-gate check for B1 alone before the full
  type set is designed is premature. Activate when B2–B9 replication is scheduled.

## Action Items

1. [ ] Add two nullable columns to `proforma_drafts`: `snap_contractor_id TEXT DEFAULT NULL`
       and `snap_proforma_series_id TEXT DEFAULT NULL`. Use `_safe_add_column` migration
       helper; existing rows get NULL (= snapshot absent, fallback to current behaviour).
2. [ ] In `post_proforma_draft_to_wfirma`, after `mark_post_succeeded` returns, call
       `pildb.write_draft_snapshot(db, draft_id, contractor_id=req.wfirma_contractor_id, series_id=req.series_id)`
       (new helper). `proforma_number` is already stored as `wfirma_proforma_fullnumber`.
3. [ ] In `proforma_to_invoice()`, before `_check_invoice_approval_gates()`: load the draft
       row; if `snap_contractor_id` is populated, reconstruct a `ProformaSnapshot`-compatible
       dict from `{proforma_number: wfirma_proforma_fullnumber, contractor_id: snap_contractor_id, series_id: snap_proforma_series_id}` + `get_dictionaries()["invoice_series"]`
       as `available_series`; run B1–B9 dead-end checks; create proposals on any dead-end;
       if any dead-end found, return `blocked` before reaching the gate.
4. [ ] Post-gate flow is unchanged: `fetch_invoice_xml` runs, live XML is authoritative,
       `snap` is re-derived from the live XML (no change to existing post-gate path).
5. [ ] Add regression test: convert-flag off + draft row with `snap_contractor_id` populated
       + no invoice series in customer master → B1 proposal created, zero wFirma HTTP calls,
       response `{status: "blocked"}`.
6. [ ] Add regression test: convert-flag on + draft row with `snap_contractor_id` populated
       + no invoice series → B1 proposal created pre-gate (same as above), gate then passes,
       live `fetch_invoice_xml` runs, live `series_id` reconciles, invoice write proceeds if
       caller supplied `final_series_id` in the resolve body.
