# Description Authority Audit Report
**Date:** 2026-06-25  
**Trigger:** Post-PR #741 (f117086) — wFirma gate now enforces `validate_description_line()`  
**DB audited:** `C:\PZ\storage\documents.db` — `product_descriptions` table  
**Script:** `C:\PZ-verify\scripts\_audit_descriptions.py`

---

## Summary

| Category | Count |
|---|---|
| Total rows audited | 575 |
| **BLOCKED** — will fail wFirma gate | **102** |
| WARNINGS — advisory (not blocked) | 329 |
| OK — pass validation | 144 |

### BLOCKED breakdown by cause

| Cause | Count | source=auto | source=manual |
|---|---|---|---|
| Shorthand tokens in description_en (PCS/PRS/LGD/Jewell/DIA&CLS) | 97 | 79 | 18 |
| Missing required PL legal words (karat/próba/metal) — no shorthand | 5 | 5 | 0 |
| **Total blocked** | **102** | **84** | **18** |

### Warning breakdown (not blocked)
329 rows have `description_en` present but missing stone-type word (`Diamond/Ruby/Sapphire/Emerald`).
These pass the gate — the wording is advisory only. These are silver/CZ jewellery products where
the stone type is legitimately absent from the required EN word list. No action required.

---

## Category A — source='auto' shorthand rows (79 rows) — REPAIR REQUIRED

**Rule:** `source='auto'` rows may be repaired without operator confirmation per-row, but the
repair action must be reviewed and approved as a batch before writing.

**Proposed repair action:** Clear `description_en` to blank string.

Rationale:
- PL-only render (`description_pl` only, no EN) is fully valid — wFirma accepts it.
- The existing `description_pl` for most rows is correct Polish customs text.
- The blocked EN values are EJL/Ethos invoice column abbreviations (PCS = Pieces, PRS = Pairs, etc.).
  They were auto-populated from invoice column headers — never customs-grade English.
- Clearing EN unblocks the wFirma gate immediately with zero risk to the Polish description.

**Repair script (DO NOT RUN — awaiting operator approval):**  
`C:\PZ-verify\scripts\correct_ejl_auto_shorthand_en.py`  
(Written below — contents shown for review)

### Full list of 79 auto-shorthand codes

```
EJL/26-27/098-1   EJL/26-27/098-2   EJL/26-27/099-1   EJL/26-27/100-1
EJL/26-27/100-2   EJL/26-27/100-3   EJL/26-27/101-1   EJL/26-27/101-2
EJL/26-27/101-3   EJL/26-27/102-1   EJL/26-27/102-2   EJL/26-27/177-1
EJL/26-27/177-2   EJL/26-27/177-3   EJL/26-27/177-4   EJL/26-27/177-5
EJL/26-27/178-1   EJL/26-27/179-1   EJL/26-27/179-2   EJL/26-27/180-1
EJL/26-27/180-2   EJL/26-27/180-3   EJL/26-27/180-4   EJL/26-27/187-1
EJL/26-27/188-1   EJL/26-27/188-2   EJL/26-27/188-3   EJL/26-27/207-1
EJL/26-27/207-2   EJL/26-27/207-3   EJL/26-27/233-1   EJL/26-27/234-1
EJL/26-27/235-1   EJL/26-27/235-2   EJL/26-27/235-3   EJL/26-27/236-1
EJL/26-27/236-2   EJL/26-27/244-1   EJL/26-27/244-2   EJL/26-27/244-3
EJL/26-27/244-4   EJL/26-27/244-5   EJL/26-27/256-4   EJL/26-27/257-2
EJL/26-27/257-4   EJL/26-27/258-4   EJL/26-27/290-1   EJL/26-27/290-2
EJL/26-27/291-1   EJL/26-27/291-2   EJL/26-27/291-3   EJL/26-27/291-4
EJL/26-27/291-5   EJL/26-27/292-1   EJL/26-27/292-2   EJL/26-27/292-3
EJL/26-27/293-1   EJL/26-27/294-1   EJL/26-27/295-1   EJL/26-27/296-1
EJL/26-27/297-1   EJL/26-27/297-2   EJL/26-27/298-1   EJL/26-27/298-2
EJL/26-27/298-3   EJL/26-27/299-2   EJL/26-27/299-3   EJL/26-27/299-4
EJL/26-27/299-5   EJL/26-27/299-6   EJL/26-27/299-7   EJL/26-27/299-8
EJL/26-27/299-9   EJL/26-27/299-10  EJL/26-27/299-11  EJL/26-27/300-1
EJL/26-27/331-1
GLOBAL Invoice-AGG-PCS
GLOBAL Invoice-AGG-PRS
```

---

## Category B — source='auto' non-shorthand blocked rows (5 rows) — OPERATOR DECISION REQUIRED

These rows have no shorthand tokens, but their `description_pl` is missing required legal words
(karat grade, próba, or specific metal/stone type). The description is too generic for customs.

| product_code | description_pl | description_en | Decision needed |
|---|---|---|---|
| `BRACELET` | `Bransoletka — wyrób jubilerski do noszenia.` | `Gold Jewellery BRACELET` | Generic type stub — no karat/próba. Operator: delete row or provide correct PL |
| `EARRINGS` | `Kolczyki — wyrób jubilerski do noszenia.` | `Gold Jewellery EARRINGS` | Same — generic stub |
| `PENDANT` | `Wisiorek — wyrób jubilerski do noszenia.` | `Gold Jewellery PENDANT` | Same — generic stub |
| `RING` | `Pierścionek — wyrób jubilerski do noszenia.` | `Gold Jewellery RING` | Same — generic stub |
| `EJL/26-27/255-1` | `pierścionek z kamieniami` | `ring with stones` | Skeleton entry — no metal/karat. Re-run description engine or operator provides correct PL |

**Note:** The BRACELET/EARRINGS/PENDANT/RING codes are generic type-level placeholders with no
karat/próba information in description_pl. These cannot be automatically repaired — the correct
material data is not present. If any product uses these codes, the product_code should be updated
to a specific EJL/PRODUCT_CODE that carries proper material information.

**No action taken — awaiting operator decision.**

---

## Category C — source='manual' shorthand rows (18 rows) — OPERATOR REVIEW ONLY

These rows were manually set. No auto-overwrite under any circumstance.

Operator must review each row and decide whether to:
1. Replace with a correct English customs sentence (e.g. "14KT Gold Ring With Laboratory Grown Diamonds. Jewellery.")
2. Clear description_en to blank (PL-only render)

| product_code | current description_en |
|---|---|
| EJL/26-27/328-1 | `PCS, 14KT Gold, Stud With Diam Jewel Pendant` |
| EJL/26-27/328-2 | `PRS, 14KT Gold, Stud Jewelry DIA&CLS; Earrings` |
| EJL/26-27/329-1 | `PCS, 18KT Gold, Stud Jewelry DIA&CLS; Pendant` |
| EJL/26-27/329-2 | `PCS, 18KT Gold, Stud Jewelry DIA&CLS; Ring` |
| EJL/26-27/329-3 | `PRS, 18KT Gold, Stud Jewelry DIA&CLS; Earrings` |
| EJL/26-27/330-1 | `PCS, 18KT Gold, Stud With Diam Jewel Ring` |
| EJL/26-27/332-1 | `PCS, 18KT Gold, LGD Gold Stud Jewell Ring` |
| EJL/26-27/333-1 | `PCS, 18KT Gold, LGD Gold Stud Jewell Bracelet` |
| EJL/26-27/334-1 | `PCS, 14KT Gold, LGD Gold Stud Jewell Bracelet` |
| EJL/26-27/335-1 | `PCS, 14KT Gold, Stud With Diam Jewel Pendant` |
| EJL/26-27/335-2 | `PRS, 14KT Gold, Stud With Diam Jewel Earrings` |
| EJL/26-27/336-1 | `PCS, 18KT Gold, Studed Jewellery CLS Ring` |
| EJL/26-27/337-1 | `PCS, SL925 SILVER LGD Std Jewel PENDANT` |
| EJL/26-27/337-2 | `PCS, 14KT Gold, LGD Gold Stud Jewell PENDANT` |
| EJL/26-27/337-3 | `PCS, 14KT Gold, LGD Gold Stud Jewell RING` |
| EJL/26-27/337-4 | `PCS, 14KT Gold, Plain Jewellery PENDANT` |
| EJL/26-27/337-5 | `PCS, SL925 SILVER Plain Jewellery PENDANT` |
| EJL/26-27/337-6 | `PRS, SL925 SILVER LGD Std Jewel EARRINGS` |

---

## UI change (completed this session)

Added historical description advisory badge to `service/app/static/proforma-detail-v2.html`.
Shown when `draft_state ∈ {'posted', 'adopted_from_audit'}` AND any line has `name_pl_source === 'operator'`.
Advisory text: "This posted proforma contains legacy or operator description text that differs from
current product description authority. No automatic change will be made."
Non-blocking — no gate, no block.

---

## Repair plan status

| Action | Status |
|---|---|
| Audit script run | DONE |
| UI advisory badge | DONE |
| Category A (79 auto-shorthand rows) — clear EN | AWAITING OPERATOR APPROVAL |
| Category B (5 generic stubs) | AWAITING OPERATOR DECISION |
| Category C (18 manual rows) | AWAITING OPERATOR REVIEW |
| EJL/26-27/292-1 specifically (known open row) | Included in Category A |
