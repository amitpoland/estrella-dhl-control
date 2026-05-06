# verify-after-create-gate

**Version:** 1.0.0  
**Status:** active  
**Scope:** `wfirma_client.create_proforma_draft`

## What this gate does

After `invoices/add` returns status=OK and a valid invoice id, immediately
fetches the new proforma via `fetch_invoice_xml` and asserts two invariants:

1. **Line count** — persisted `<invoicecontent>` count == `len(req.lines)`
2. **VAT code parity** — every persisted `<invoicecontent>/<vat_code>/<id>`
   equals `req.vat_code_id`

If either check fails, raises `RuntimeError` and does **not** return
`ProformaResult(ok=True)`.  The caller (`routes_proforma.py`) catches the
exception and marks the `proforma_drafts` row as `failed`.

## Why both checks are needed

wFirma has demonstrated two distinct silent-failure modes:

| Mode | Incident | Symptom |
|------|----------|---------|
| Partial persistence | PROF 92/2026 (2026-05-06) | 12 lines submitted → 1 persisted |
| VAT rewrite | discovered by SECURITY audit | wFirma rewrites per-line VAT silently |

A count-only check passes mode 2 — the proforma has the right number of lines
but every line carries the wrong VAT code.  Adding VAT parity catches both
modes with a single second fetch (no additional HTTP call needed).

## Implementation contract

### Invariant 1 — count

```
actual_count = len(persisted_lines)
if actual_count != expected_count:
    raise RuntimeError(
        "invoices/add partial persistence: wfirma_invoice_id=... "
        "expected_count=... actual_count=... missing_good_ids=[...] — ..."
    )
```

### Invariant 2 — VAT code parity

Runs only when count check passes (reuses `persisted_lines` list, no new fetch).

```
expected_vat = (req.vat_code_id or "").strip()
vat_mismatches = [
    {"good_id": ..., "expected_vat_code_id": expected_vat, "actual_vat_code_id": ...}
    for ln in persisted_lines
    if (ln.find("vat_code").findtext("id") or "").strip() != expected_vat
]
if vat_mismatches:
    raise RuntimeError(
        "invoices/add vat_code mismatch: wfirma_invoice_id=... "
        "expected_vat_code_id=... mismatched_vat_codes=[...] — "
        "wFirma silently rewrote per-line VAT; do NOT mark as success"
    )
```

Missing `<vat_code>/<id>` element is treated as `actual_vat_code_id=""` —
a mismatch unless `req.vat_code_id` is also empty.

### Customs-value-freeze

This gate is **read-only**.  It never mutates `qty`, `unit_price`, `currency`,
freight, duty, or totals.  It only compares persisted state against the request.

## What this gate never does

- Never calls `invoices/edit`, `invoices/delete`, `goods/edit`, or any write
  endpoint
- Never writes to local DB tables
- Never flips an env flag
- Never retries `invoices/add` — a failed gate means the operator must
  investigate the wFirma state manually before any reissue attempt

## Stop conditions (raise RuntimeError)

| Condition | Error prefix |
|-----------|-------------|
| verify-fetch HTTP error | `invoices/add succeeded (id=…) but verify-fetch failed:` |
| count mismatch | `invoices/add partial persistence:` |
| VAT code mismatch on any line | `invoices/add vat_code mismatch:` |

## Test coverage

Tests in `service/tests/test_wfirma_client_contract.py`:

| Test | Assertion |
|------|-----------|
| `test_create_proforma_draft_posts_invoices_add_and_verifies` | ok=True when count and VAT both match |
| `test_create_proforma_draft_raises_on_partial_persistence` | RuntimeError on count mismatch |
| `test_create_proforma_draft_raises_when_verify_fetch_fails` | RuntimeError on fetch error |
| `test_create_proforma_draft_raises_on_vat_code_mismatch` | RuntimeError when persisted VAT ≠ req.vat_code_id |
| `test_create_proforma_draft_raises_on_vat_code_mismatch_partial_lines` | RuntimeError when only some lines have wrong VAT |
| `test_create_proforma_draft_vat_check_passes_on_correct_vat_code` | ok=True when multi-line proforma has correct VAT on all lines |
