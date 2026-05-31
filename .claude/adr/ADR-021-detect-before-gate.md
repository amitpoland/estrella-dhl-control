# ADR-021: wFirma recovery detection should run before the convert flag gate

Status: Proposed
Date:   2026-05-30
Context: PR #409 — wFirma recovery B1 (wfirma_series_missing)

---

## Context

`proforma_to_invoice()` currently checks guards in this order:

1. `_check_invoice_approval_gates()` — includes the `wfirma_create_invoice_allowed` flag check  
2. Series fallback chain — reads proforma XML, resolves series from customer master

The B1 dead-end (series missing) lives **inside** the series fallback chain, which is only reached when `wfirma_create_invoice_allowed = True`.

This means the wFirma recovery proposal is only ever created when the convert flag is on. Consequences:

- The recovery infrastructure (proposal creation, inbox card, `/resolve` endpoint) cannot be exercised in production until the convert flag is enabled, which is itself a separate go-live event.
- The first live exercise of the B1 recovery loop (dead-end → proposal → operator resolves → retry) is inherently a production event: the moment the convert flag flips for real clients.
- End-to-end testing of the series-check branch requires the convert flag on; mocked unit tests prove the resolve handler calls `proforma_to_invoice` with the injected series, but they do not prove the series dead-end was actually reached in the real code path.

## Decision under consideration

Move the series resolution (detection) step **before** the flag gate:

```
proposed order:
  1. Validate basic inputs (batch_id, client_name, confirm token, X-Operator)
  2. Look up local proforma_drafts → wfirma_proforma_id
  3. Fetch + parse proforma XML (read-only wFirma call)
  4. Attempt series resolution (proforma XML → customer master fallback)
     → if series still missing: create wfirma_series_missing proposal (additive)
  5. wfirma_create_invoice_allowed flag check (WRITE gate — only reached if series resolved)
  6. UNIQUE(proforma_id) duplicate-conversion guard
  7. Build final-invoice plan, POST invoices/add
```

Under this ordering:
- A missing series is **detected** even when the convert flag is off.
- Proposals are created and pre-loaded in the inbox before go-live.
- Operators can resolve series assignments (a data-prep action) independently of the write gate.
- The write gate (step 5) still enforces that no wFirma invoice is created until the flag is on.

## Implications

### What changes
- `_check_invoice_approval_gates()` call moves to after the series resolution.
- Series resolution (proforma XML fetch + customer master lookup) becomes the first substantive step, before the flag check.
- This adds one wFirma read call (`fetch_invoice_xml`) even when the flag is off — acceptable because the existing preview endpoint already makes this call.

### What stays the same
- `wfirma_create_invoice_allowed = False` still prevents any invoice creation.
- All write-side guards (confirm token, UNIQUE, operator, flag) are unchanged.
- The series-missing proposal is still additive (bare error returns unchanged).
- `wfirma_recovery_enabled_types` still gates proposal creation.

### Risk surface
- The extra wFirma read call with flag off is low-risk (read-only).
- Moving `_check_invoice_approval_gates()` past the XML fetch means the flag check runs after one more network call than today — negligible performance impact.
- The token and operator checks within `_check_invoice_approval_gates()` can stay early (they are pure-local validation); only the `wfirma_create_invoice_allowed` bit needs to move.

## Status: Proposed

This ADR records the architectural option. It is **NOT implemented in PR #409**.

Implementation requires:
1. Extracting the pure-local checks (token, operator) from `_check_invoice_approval_gates()` into a new `_check_input_gates()` helper that runs early.
2. Moving only the `wfirma_create_invoice_allowed` check to step 5.
3. Adding a regression test that proves series-missing proposals are created with the flag OFF.
4. Updating the verify claim in PROJECT_STATE: "series cleared proven by unit test" becomes "series cleared proven end-to-end (flag off, no wFirma write, proposal created in inbox before go-live)."

Decision criteria: implement before the convert flag is enabled in production, or accept that the first live exercise of B1 recovery is a production event.

## References

- PR #409: wFirma recovery B1 vertical slice
- PROJECT_STATE.md PR #409 fact block: flag-gate ordering, corrected verify claim
- `service/app/api/routes_proforma.py` `proforma_to_invoice()` lines ~2885–3060
- `service/app/services/wfirma_recovery.py` `resolve_wfirma_series_missing()`
