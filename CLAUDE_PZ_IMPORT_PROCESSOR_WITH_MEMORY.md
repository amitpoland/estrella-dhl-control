# PZ Import Processor — Claude Code Instructions (with retained corrections)

## Purpose
Given supplier invoice PDFs and one ZC429 / SAD customs PDF,
extract data, calculate landed cost, and output a final PZ document
in the same business format as the validated sample PZ.

This version includes **retained corrections learned from shipment 039–044**.
These corrections must be treated as persistent parsing rules for future batches.

---

## Retained corrections from validated batch 039–044

These are not optional hints. They are fixed rules for future runs unless the PDFs clearly prove otherwise.

### 1. Quantity parsing rule
In invoice item rows, the parser must **never** confuse:
- HSN code
- gross weight
- net weight
- quantity
- rate
- amount

Expected item row pattern in these Estrella invoices is:

`<UOM prefix>, <material/product text> <ITEM_TYPE> <gross_wt> <net_wt> <HSN> <UOM> <QTY> <RATE_USD> <AMOUNT_USD>`

Examples from the validated batch:
- `PCS, 14KT Gold, Stud Jewelry DIA&CLS PENDANT 1.060 0.796 71131919 PCS 2.0 213.50 427.00`
- `PCS, 14KT Gold, Stud With Diam Jewel RING 26.140 25.641 71131913 PCS 9.0 495.44 4,459.00`
- `PRS, 14KT Gold, Stud With Diam Jewel EARRINGS 4.310 4.123 71131913 PRS 1.5 489.33 734.00`

Therefore:
- quantity is the numeric field **after the second UOM token** (`PCS` or `PRS`)
- HSN is the numeric code immediately before that UOM token
- quantity may be decimal, especially for `PRS`

### 2. Duty parsing rule
In ZC429, the parser must **only** use:
- `A00 -> Kwota należnej opł.`

It must **never** use:
- taxable base / customs value
- `Kwota: 48987.00 PLN`
- calculated `kwota opł.`

Validated customs example:
- wrong value that must be ignored: `48987.00 PLN`
- correct A00 duty to use: `1225.00 PLN`

### 3. LRN parsing rule
The ZC429 field can appear in bracketed form:
- `Numer LRN [12 09]: 26S00Q8O0S`

Parser must support:
- `Numer LRN`
- `LRN`
- bracketed layout with `[12 09]`

### 4. Filename vs PDF-body rule
Invoice filename is not reliable metadata.
Always trust the PDF body first.

Validated example:
- filename suggests invoice 041 dated `11-04-26`
- PDF body shows `EJL/26-27/041 Date : 10-04-2026`

Use the date from the PDF text, not the filename.

### 5. Silver-item rule
If the invoice row is silver, do not force gold/karat wording.

Validated example:
- invoice 043 includes `PCS, SL925 SILVER Plain Jewellery PENDANT ... 5.00`

Silver should map to a silver-specific Polish description, not a gold-karat template.

### 6. Regression safety rule
Before final output, the script must fail loudly if:
- any quantity looks like an HSN code such as `71131919`
- duty percentage is implausible, for example > 20%
- parsed A00 duty is greater than total purchase PLN
- item quantity is missing while amount is present

---

## Required parsing validations

### Quantity sanity checks
```python
def is_suspicious_quantity(q):
    if q is None:
        return True
    if q > 1000:
        return True
    if int(q) in {71131911, 71131913, 71131914, 71131919, 71131141}:
        return True
    return False
```

If `is_suspicious_quantity(quantity)` is true:
- stop and re-parse the item row with a stricter regex
- do not continue silently

### Duty sanity checks
```python
if zc429["duty_pln"] <= 0:
    raise ValueError("A00 duty not parsed correctly")

if total_purchase_pln <= 0:
    raise ValueError("Total purchase PLN invalid")

duty_rate_pct = zc429["duty_pln"] / total_purchase_pln

if duty_rate_pct > 0.20:
    raise ValueError(
        f"Implausible duty rate {duty_rate_pct:.2%} - likely parsed the customs base instead of A00 duty"
    )
```

### LRN sanity check
```python
if not zc429["lrn"]:
    raise ValueError("LRN missing - ZC429 parser must support 'Numer LRN [12 09]' format")
```

---

## Invoice extraction model

```python
invoice = {
    "invoice_no": "",
    "invoice_date": "",
    "fob_usd": 0.0,
    "freight_usd": 0.0,
    "insurance_usd": 0.0,
    "cif_usd": 0.0,
    "carrier": "DHL",
    "consignee_name": "",
    "items": [
        {
            "description_header": "",
            "raw_item_line": "",
            "item_type": "",
            "karat": "",
            "diamond_type": "",
            "uom": "",
            "quantity": 0.0,
            "unit_price_usd": 0.0,
            "amount_usd": 0.0,
            "hsn_code": "",
        }
    ]
}
```

---

## Robust item-row regex

Use a regex that captures the tail of the line explicitly.

Suggested strategy:
1. detect only lines starting with `PCS,` or `PRS,`
2. capture from the end backwards:
   - amount
   - rate
   - quantity
   - UOM
   - HSN
   - net wt
   - gross wt
3. everything before gross wt is description text

Example pattern:
```python
ITEM_RE = re.compile(
    r'^(PCS,|PRS,)\s+'
    r'(?P<desc>.+?)\s+'
    r'(?P<item_type>PENDANT|RING|EARRINGS|BRACELET|NECKLACE)\s+'
    r'(?P<gross>\d+(?:\.\d+)?)\s+'
    r'(?P<net>\d+(?:\.\d+)?)\s+'
    r'(?P<hsn>\d{8})\s+'
    r'(?P<uom>PCS|PRS)\s+'
    r'(?P<qty>\d+(?:\.\d+)?)\s+'
    r'(?P<rate>[\d,]+(?:\.\d+)?)\s+'
    r'(?P<amount>[\d,]+(?:\.\d+)?)$'
)
```

Normalization:
```python
def parse_money(s: str) -> float:
    return float(s.replace(",", "").strip())
```

---

## ZC429 parsing rules

Extract:
- MRN
- LRN
- acceptance date
- release date if present
- A00 duty paid
- B00 VAT paid
- invoice value USD
- agent

### Duty extraction rule
For A00 and B00 blocks:
- ignore `Kwota:`
- ignore `kwota opł.:`
- use only the separate right-column value under:
  `Kwota należnej opł. [14 03 042]`

Example logic:
```python
A00_RE = re.compile(
    r'A00.*?Kwota należnej opł\.\s*\[14 03 042\].*?(\d[\d\s,.]*)\s*PLN',
    re.S
)
```

If table parsing is messy, use a block-based parser:
1. isolate A00 section
2. find the last PLN figure in the rightmost duty column
3. normalize to float

---

## Exchange rate rule

Use NBP Table A from one working day before the invoice date extracted from the PDF body.

If invoices have different dates:
- compute by date group

If all invoice dates are the same:
- use one shared table

---

## Cost logic

### Shipping allocation
Allocate freight+insurance proportionally within each invoice:

```python
invoice_ship_usd = invoice["freight_usd"] + invoice["insurance_usd"]
row_share = row["amount_usd"] / invoice["fob_usd"]
row["allocated_ship_usd"] = invoice_ship_usd * row_share
row["allocated_ship_pln"] = row["allocated_ship_usd"] * row["usd_rate"]
```

### Duty allocation
Allocate A00 duty proportionally over all rows by pre-duty PLN value:

```python
row["purchase_value_pln"] = row["amount_usd"] * row["usd_rate"]
row["value_before_duty_pln"] = row["purchase_value_pln"] + row["allocated_ship_pln"]

total_purchase_pln = sum(r["value_before_duty_pln"] for r in all_rows)
duty_rate_pct = zc429["duty_pln"] / total_purchase_pln

row["allocated_duty_pln"] = row["value_before_duty_pln"] * duty_rate_pct
row["total_cost_pln"] = row["value_before_duty_pln"] + row["allocated_duty_pln"]
row["gross_cost_pln"] = row["total_cost_pln"] * 1.23
row["unit_net_price_pln"] = row["total_cost_pln"] / row["quantity"]
```

After rounding, force final reconciliation:
```python
residual = zc429["duty_pln"] - round(sum(r["allocated_duty_pln"] for r in all_rows), 2)
all_rows[-1]["allocated_duty_pln"] += residual
all_rows[-1]["total_cost_pln"] += residual
all_rows[-1]["gross_cost_pln"] = all_rows[-1]["total_cost_pln"] * 1.23
all_rows[-1]["unit_net_price_pln"] = all_rows[-1]["total_cost_pln"] / all_rows[-1]["quantity"]
```

---

## Description normalization

Map invoice row wording to stable business families:

```python
def normalize_family(desc_header: str, raw_desc: str) -> str:
    text = f"{desc_header} {raw_desc}".upper()

    if "SL925" in text or "SILVER" in text:
        return "Silver Plain"
    if "LGD" in text or "LAB GROWN" in text:
        return "Lab Grown Diamond"
    if "DIA&CLS" in text or "COLOUR STONE" in text:
        return "Diamond / Colour Stone Studded"
    if "STUD WITH DIAM" in text or "DIAMOND STUDDED" in text:
        return "Diamond Studded"
    if "PLAIN" in text:
        return "Plain"
    return "Unknown"
```

Silver translation must be separate:
```python
TRANSLATIONS = {
    ("Silver Plain", "PENDANT"): "WISIOREK SREBRNY PRÓBY 925",
    ("Silver Plain", "EARRINGS"): "KOLCZYKI SREBRNE PRÓBY 925",
    ("Silver Plain", "RING"): "PIERŚCIONEK SREBRNY PRÓBY 925",
    ("Silver Plain", "BRACELET"): "BRANSOLETKA SREBRNA PRÓBY 925",
}
```

---

## Auto-correction behavior

When a known mistake pattern appears, the script should auto-correct before final output.

### Auto-correct cases
1. **Quantity equals HSN code**
   - re-run item parser with strict regex
   - do not keep first parse

2. **Duty rate > 20%**
   - assume parser captured customs base instead of A00 duty
   - re-run A00 extraction from right-column amount

3. **LRN empty**
   - retry using bracket-aware regex

4. **Filename date differs from PDF-body date**
   - keep PDF-body date
   - log a warning

5. **Silver item matched to gold template**
   - switch to silver translation family

### Technical log
The script should produce a log like:
```python
corrections_log = [
    "Reparsed invoice items due to suspicious quantity matching HSN code",
    "Reparsed ZC429 A00 duty using right-column Kwota należnej opł.",
    "Recovered LRN from 'Numer LRN [12 09]' pattern",
    "Ignored filename date for invoice 041 and used PDF body date 10-04-2026",
]
```

---

## Final output model

```python
pz_document = {
    "document_no": "",
    "issue_date": "",
    "warehouse": "Główny",
    "recipient": {
        "name": "ESTRELLA JEWELS Sp. z o. o. SPÓŁKA KOMANDYTOWA",
        "address": "ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa",
        "nip": "5252812119",
    },
    "supplier": {
        "name": "ESTRELLA JEWELS LLP.",
        "address": "312, OPTIONS PRIMO PREMISES CHSL, MAROL INDUSTRIAL ESTATE, MIDC, 400093 ANDHERI EAST, MUMBAI",
    },
    "items": [],
    "notes": [],
    "total_net": 0.0,
    "total_gross": 0.0,
    "corrections_log": [],
}
```

---

## Final instruction to Claude Code

When the user uploads the next batch:
1. parse invoices
2. parse ZC429
3. run quantity and duty sanity checks
4. auto-correct known parsing failures
5. keep a corrections log
6. output final PZ document
7. preserve these learned corrections for future runs of the same invoice family and customs format

Do not silently continue with implausible values.
If values look wrong, reparse and correct first.
