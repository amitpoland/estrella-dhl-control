# ADR-022: Cache proforma snapshot for pre-gate dead-end detection

**Status:** Proposed
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

1. Recovery proposals should be creatable and inspectable while the convert flag is off.
2. The recovery loop (B1: series-missing) should be exercisable in a staging or pre-production
   environment before the flag is turned on for production.
3. Detection (data validation) should not be permanently coupled to write authorisation.

## Decision

On any conversion attempt that successfully passes the gate and reaches `fetch_invoice_xml()`,
persist the relevant snapshot fields to a local cache file:

```
<storage_root>/outputs/<batch_id>/proforma_snap.json
```

The cache records the fields needed for dead-end detection: at minimum `proforma_number`,
`contractor_id`, `series_id`, and the available-series list resolved from the wFirma dictionary
cache. No wFirma-derived bytes may be stored; only the structured fields extracted by
`p2i.parse_proforma_xml()`.

On every subsequent call to `proforma_to_invoice()` for the same `batch_id`, if
`proforma_snap.json` exists, **use it for dead-end detection before the gate check**. The
detection path reads exclusively from the local cache — zero wFirma calls. The gate continues
to guard every actual wFirma write path unchanged.

The result:

- **First conversion attempt** (flag must be ON to pass the gate): snap is fetched from wFirma,
  dead-end proposals are created post-gate (current behaviour), and the snap is written to cache.
- **Subsequent attempts** (flag ON or OFF): dead-end detection runs pre-gate from the local
  cache; proposals are created before the flag is checked; if the flag is off, the function
  returns `blocked` after creating proposals; if the flag is on, the gate passes and the live
  wFirma write proceeds using the cached snap fields where possible.

## Options Considered

### Option A: Status quo (gate-first, no cache) — rejected via ADR-021
Detection only runs when the flag is on. Recovery loop is untestable with the flag off. First
real exercise of the recovery layer is a live production event.

### Option B: Move fetch_invoice_xml pre-gate — rejected by ADR-021 inspector pass
Violates the invariant: no wFirma read may occur before the write-enable gate.

### Option C: Snapshot cache (this ADR) — proposed
Caches the structured snapshot from the first gate-passing attempt. Zero extra wFirma calls on
retries. Gate boundary is unchanged. Recovery loop becomes testable with the flag off after one
initial flag-on attempt. Detection is decoupled from write-authorisation for all subsequent
invocations.

### Option D: Separate lightweight pre-check endpoint
A dedicated `GET /proforma/{batch_id}/conversion-preflight` endpoint could call
`fetch_invoice_xml` independently and populate the cache. This extends the surface area (new
route, new wFirma read outside the conversion context) and is unnecessary if Option C is
implemented — the cache is naturally populated by the first conversion attempt.

## Trade-off Analysis

Option C costs one write to disk on the first gate-passing attempt and a cache-file read on
every subsequent attempt. Both are negligible. The benefit is a fully testable, pre-loadable
recovery layer that requires no changes to the gate boundary or to the invariant.

Constraint: the cache is populated only after the first flag-ON attempt. Before that first
attempt there is no local snapshot and detection cannot run pre-gate. This is acceptable: a
conversion attempt with the flag on is the natural first step in any operator workflow, and the
cache persists across retries.

Cache invalidation: if the proforma is edited in wFirma between attempts, the cached snap may
be stale. Mitigation: the live `fetch_invoice_xml` result always supersedes the cache on
gate-passing attempts. The cache is used only when `WFIRMA_CREATE_INVOICE_ALLOWED` is off.

## Invariant Preservation

The write-enable gate (`_check_invoice_approval_gates()`) continues to guard every code path
that may call `wfirma_client._http_request("invoices/add")` or any other wFirma mutating
call. The cache-read path contains no wFirma calls and no wFirma state mutations. A new test
must assert: with flag off and a pre-populated cache, calling `proforma_to_invoice()` creates a
B1 proposal and returns `blocked` without making any wFirma HTTP call.

## Consequences

- **Enabled:** recovery proposals can be created and inspected with the flag off (after one
  initial flag-on attempt); the B1 recovery loop is fully testable in staging; dead-end
  detection is logically separated from write authorisation for retry calls.
- **New artefact:** `proforma_snap.json` per batch in the outputs directory. Must be excluded
  from WorkDrive uploads and treated as internal scratch state.
- **New test required:** no-wFirma-call assertion for the cache-read path with the flag off.
- **Migration:** no schema changes, no env-var changes, no deploy gate changes.

## Action Items

1. [ ] Define `proforma_snap.json` schema (fields: `proforma_number`, `contractor_id`,
       `series_id`, `available_series`, `cached_at`).
2. [ ] Write `proforma_snap.json` immediately after `snap = p2i.parse_proforma_xml(proforma_xml)`
       succeeds on any gate-passing attempt.
3. [ ] On entry to `proforma_to_invoice()`, if `proforma_snap.json` exists, load it as
       `cached_snap` and run dead-end detection (series resolution + B1–B9 checks) before
       `_check_invoice_approval_gates()`.
4. [ ] Gate check remains in its current position; if flag is off, return `blocked` (with
       proposals already created from the cache).
5. [ ] Add regression test: flag off + pre-populated cache → B1 proposal created, zero wFirma
       calls, return `blocked`.
6. [ ] Add regression test: flag on + pre-populated cache → cache snap used for detection,
       live `fetch_invoice_xml` result supersedes cache fields at write time.
