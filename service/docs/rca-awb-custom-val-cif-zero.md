# RCA — DHL waybill "Custom Val" parses as 0.00 (CIF block)

**Incident:** AWB 2315714531 (Global Jewellery India Pvt Ltd → Estrella Jewels
Sp. z o.o.). Contents: SL925 silver jewellery studded with CZ/diamond/colour
stone. Invoice value USD 732.00 (inv_122.pdf). The pipeline stalled at
*Awaiting Start* with *"Routing Pending — CIF not calculated yet."* The DHL
waybill (DHL122_Global.pdf) customs value registered as **USD 0.00** instead of
**USD 732.00**.

Classification (Lesson I): **Authority chain** incident — the wrong value was
generated at the document-parsing authority (`awb_parser`). Fix target =
`awb_parser` customs-value extractor + the CIF readiness gate. Workflow class =
*document field extraction returns None and is silently coerced to 0.00, which a
downstream gate treats as a legitimate value.*

---

## 1. Root cause

`service/app/services/awb_parser.py` extracted the customs value with a single
regex:

```python
_RE_CUSTOM_VAL = re.compile(r'Custom\s+Val[:\s]+([0-9,\.]+)\s*([A-Z]{3})?', re.IGNORECASE)
```

This requires the **numeric amount to appear immediately** after the
`Custom Val:` label, i.e. it only matches the currency-**suffix** rendering:

```
Custom Val: 732.00 USD          ✅ matched
```

DHL waybills are not consistent about this. The 2315714531 waybill rendered the
field with a **leading** currency code:

```
Custom Val: USD 732.00          ❌ no match  → customs_value = None
```

After `Custom Val:` the next characters are `USD` (letters), so `([0-9,\.]+)`
fails and the regex returns no match. The same failure occurs for glued
currency (`USD732.00`), thousands separators in some locales, and the
`Customs Value` label variant.

When the regex did not match, `customs_value` stayed `None`. Two downstream
steps then erased the distinction between *"genuinely zero"* and *"could not
read"*:

- `routes_intake.py` stored it as `str(awb_fields.get("customs_value") or "")`
  → empty string.
- The CIF readiness gate in `active_shipment_monitor.py` compares
  `float(... or 0)`, so `None`/`""` becomes `0.0`. With `cif == 0.0` the gate
  **silently `return`s** (no Polish description, no routing, no alert) — the
  shipment simply never advances. That silent skip is why it looked "stuck"
  rather than "errored."

**One-sentence root cause:** the waybill customs-value regex matched only the
currency-suffix layout, so a currency-prefixed value parsed as `None`, which a
downstream gate coerced to `0.00` and treated as a real CIF — silently halting
clearance routing.

---

## 2. The fix (shipped in this change)

`awb_parser.py` now uses `_extract_customs_value(text)`, which:

1. Locates the label tolerantly — `Custom Val`, `Customs Val`, `Customs Value`,
   with an optional parenthetical (`(for customs purposes only)`).
2. Scans a short window after the label (current line + one wrapped line) for an
   amount with an **optional currency code on either side**, spaced or glued,
   with thousands separators.
3. Returns `(value, currency, source)` where `source` records provenance:
   `custom_val_label` (parsed), `label_no_value` (label seen, unreadable), or
   `no_label`.

Crucially, when no value can be read the parser **leaves `customs_value=None`
(not 0.00)**, logs a `WARNING`, and sets `customs_value_gap` so downstream can
raise a VERIFY-GAP instead of trusting a fake zero.

Verified: `service/tests/test_awb_customs_value.py` — 10 cases covering prefix,
glued, suffix, thousands separators, label variants, no-currency, full-waybill
block, and both VERIFY-GAP (None) paths. Existing `test_awb_normalization.py`
and `test_intake.py::TestAwbParser` still pass.

> Note: `DHL122_Global.pdf` / `inv_122.pdf` are not present in this repo, so the
> fix is proven against the reconstructed waybill text rather than the binary
> PDF. The regression test encodes the exact failing rendering
> (`Custom Val: USD 732.00`) so re-running it reproduces the original bug
> against the old regex.

---

## 3. System-level prevention (design)

The parser fix stops *this* rendering from failing. The following layers stop
the **class** of failure — a zero/unknown CIF silently blocking a shipment.

### 3a. Validation rule — never trust a silent 0.00
Treat CIF as a tri-state: **value / zero / unknown**.
- `customs_value is None` (or `customs_value_gap` set) → **UNKNOWN**, raise a
  `[VERIFY-GAP]` marker; do **not** coerce to 0.0.
- `customs_value == 0.0` parsed from a real amount → still implausible for a
  commercial shipment; flag against `_VALUE_PLAUSIBILITY_FLOOR_USD` (already
  defined in `active_shipment_monitor.py`).
- The CIF readiness gate (`active_shipment_monitor.py` ~L1518) should, when
  `cif == 0.0`, write an explicit audit marker (`cif_extraction_gap`) and emit
  an operator alert **instead of silently `return`ing**. Silent skip is what
  made this invisible.

### 3b. Fallback chain — multiple sources of truth for CIF
Resolve CIF by priority, recording which source won:
1. Invoice CIF total (`invoice_totals.total_cif_usd`) — primary commercial
   authority.
2. Verification snapshot (`verification.invoice_cif_total_usd`).
3. Waybill `customs_value` (this parser) — carrier-declared value.
If the primary parser yields nothing, fall back to the next source rather than
defaulting to zero. For 2315714531 the invoice (inv_122.pdf) carries USD 732.00,
so an invoice→waybill fallback would have unblocked it even without the parser
fix.

### 3c. Alerts / manual-review triggers
- On `cif_extraction_gap`, post a Cliq notice to `#PZ` (per CLAUDE.md posting
  rules) and surface a dashboard "CIF needs review" banner with the exact
  reason string and the document it came from. This is the operator catch
  before the shipment stalls.
- Distinguish UNKNOWN (parser failed — review the document) from ZERO
  (document genuinely declares 0 — likely sample/replacement, confirm intent).

### 3d. Logging / provenance
Every CIF resolution logs: parsed value, the `source`
(`custom_val_label` / invoice_totals / verification / fallback), currency, and
on failure the gap reason (`label_no_value` / `no_label`). The parser already
emits this at INFO (success) / WARNING (gap). The gate should log the chosen
source so an operator can answer "where did this CIF come from?" from logs
alone.

---

## 4. Implementation notes for the team

- **Shipped now (low blast radius, parser-only):** `awb_parser.py`
  `_extract_customs_value` + structured logging; `test_awb_customs_value.py`.
- **Recommended next (touches the readiness gate — governed):** 3a/3b/3c in
  `active_shipment_monitor.py`. This edits CIF gating logic and is financial-
  adjacent, so it must go through reviewer-challenge + the normal PR gate; it is
  **not** bundled into the parser fix.
- **Governance:** this analysis/edit was made in the retired scratch tree
  `C:\Users\Super Fashion\PZ APP`. Per CLAUDE.md the canonical tree for
  verification/PR is `C:\PZ-verify`; landing this requires a branch + PR (GATE 1)
  and, for production, the 7-agent deploy gate. No deploy was performed here.
- **Backfill:** re-run AWB parsing for any open shipment whose stored
  `customs_value` is empty/0.00 with a `Custom Val` label present in the source
  waybill — these are the same-class victims of the old regex.
