# wFirma PZ AutoFill — Chrome Console Script

Fills the wFirma.pl PZ (Przyjęcie Zewnętrzne) form from a `PZ_READY.json` file.

**Mode: Semi-automated assist** — the script fills fields and rows but **never submits**.
You review every value and click Save yourself.

The script returns a structured audit result and refuses to fill if validation fails.
Two override modes: default (strict) and `{reviewMode: true}` (allows fill with `UNKNOWN_SUPPLIER`).

---

## Prerequisites

- Google Chrome (any recent version)
- Access to your wFirma.pl company panel
- `PZ_READY.json` downloaded from the Estrella dashboard

---

## How to use

### Step 1 — Download PZ_READY.json

In the Estrella dashboard, open the shipment → **PZ / Accounting** section → click **Download PZ_READY.json**.

The file is named `PZ_READY_<batch_id>.json`.

### Step 2 — Open wFirma PZ page

1. Log into [wfirma.pl](https://wfirma.pl)
2. Navigate to **Magazyn → Przyjęcia zewnętrzne → Nowe PZ**
3. Leave the page open — do NOT click anything yet

### Step 3 — Open Chrome DevTools

Press `F12` → **Console** tab.

### Step 4 — Paste and run the loader

Copy the entire contents of `autofill_pz.js` and paste into the Console.

Press **Enter**.

You will see a prompt:

```
wFirma AutoFill loaded. Call: wfirmaFill(jsonData)
```

### Step 5 — Load your JSON

In the Console, paste:

```javascript
fetch('path/to/PZ_READY_<batch_id>.json')
  .then(r => r.json())
  .then(data => wfirmaFill(data));
```

Or if you have the JSON text already, paste it directly:

```javascript
const data = { /* paste JSON content here */ };
wfirmaFill(data);
```

### Step 6 — Review filled fields

The script will:
- Fill **Kontrahent** (supplier name)
- Fill **Magazyn** (default: Główny)
- Fill **Data dokumentu**
- Fill each line row: Nazwa towaru, Ilość, J.m., Cena netto, Uwagi

The script will print to Console:
```
[wFirma AutoFill] Filled header: <doc_no>
[wFirma AutoFill] Row 1: <nazwa_towaru> → <wartosc_netto> PLN
...
[wFirma AutoFill] DONE — review all fields, then click Save manually.
```

### Step 7 — Save manually

⚠️ **The script never clicks Save.**

Check every filled value matches your printed PZ. Then click **Zapisz** in wFirma.

---

## Validation chain (strict mode)

The script blocks fill (`status: "blocked"`, nothing typed into wFirma) if **any** of the following fail:

| Check | Reason |
|-------|--------|
| `data.rows` non-empty array | Nothing to fill |
| `data.supplier` present | Cannot identify Kontrahent |
| `data.supplier !== "UNKNOWN_SUPPLIER"` | Backend could not resolve supplier — review required |
| `data.totals` object present | Cannot verify post-fill |
| `data.document_date` present | wFirma requires Data dokumentu |
| Form is empty | Refuses to overwrite an in-progress PZ |

The script **warns** (still fills, returns `status: "warning"`) for:

| Warning | What you must do |
|---------|------------------|
| `data.doc_no` empty | Set the PZ document number in wFirma manually before clicking Save |
| Backend warnings present in `data.warnings[]` | Review each one — they were emitted by the PZ engine |
| Totals selectors not found in DOM | Compare totals against `PZ_READY.json` totals manually |
| Filled totals don't match expected | wFirma calculated something different — investigate before saving |

### Review mode (override)

```javascript
wfirmaFill(data, { reviewMode: true });
```

`reviewMode` allows fill even when `supplier === "UNKNOWN_SUPPLIER"` so you can pre-populate rows and then set Kontrahent by hand. The script still **never** clicks Save.

---

## Audit result

Every call returns and prints a structured object:

```json
{
  "status":         "filled" | "warning" | "blocked",
  "rows_expected":  8,
  "rows_filled":    8,
  "supplier":       "Estrella Jewels LLP",
  "doc_no":         "PZ 12/4/2026",
  "warnings":       [],
  "blockers":       [],
  "totals_checked": true,
  "totals_match":   true,
  "review_mode":    false
}
```

`totals_match` may be `null` (no selector match in DOM — manual check required), `true` (matched within 5-grosz tolerance), or `false` (mismatch — investigate).

---

## Safety guarantees

| Action | Status |
|--------|--------|
| Auto-submit (Zapisz) | ❌ Never |
| Delete existing PZ | ❌ Never |
| Overwrite without warning | ❌ Never (checks for empty form first) |
| Modify saved documents | ❌ Never |
| Send to any external server | ❌ Never |
| Modify input JSON | ❌ Never (data is read-only) |
| Fill with UNKNOWN_SUPPLIER (default) | ❌ Blocked unless `reviewMode: true` |
| Fill with empty rows | ❌ Always blocked |

---

## Field mapping

| wFirma field | Source in PZ_READY.json |
|---|---|
| Kontrahent | `supplier` |
| Magazyn | hardcoded "Główny" |
| Data dokumentu | `document_date` |
| Nazwa towaru | `rows[n].name` |
| Ilość | `rows[n].quantity` |
| J.m. | `rows[n].unit` |
| Cena netto | `rows[n].net_price_pln` |
| Uwagi | `rows[n].notes` |

---

## Troubleshooting

**"Cannot find field"** — wFirma may have updated their UI. Check field selectors in `autofill_pz.js` and update the `SELECTORS` object at the top.

**"Form appears to have existing data"** — The script detected non-empty fields. Clear the form manually or reload the page.

**"Kontrahent not found"** — wFirma supplier search uses async autocomplete. The script types the name and waits — but if the supplier doesn't exist in wFirma yet, you must add them manually first.

---

## Mode 3 — Direct API (not enabled)

See `wfirma_api_payload.json` in the project root for the planned API payload structure.
Direct API posting is **not enabled** — it requires endpoint verification and sandbox testing first.
