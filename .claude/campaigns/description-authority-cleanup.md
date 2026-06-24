# Description Authority Cleanup & Audit Campaign

**Created:** 2026-06-25  
**Status:** BACKLOG  
**Trigger:** Post-PR #741 investigation of PROF 137/2026 rendering "pierścionek z kamieniami"  
**Diagnosis:** Historical snapshot — correctly frozen. Not a deploy failure.

---

## Scope (7 items)

### 1 — Posted/issued proformas: DO NOT AUTO-MODIFY
- `status IN ('issued','posted','locked')` → read-only historical record
- Changing description text on a posted document silently is worse than leaving legacy wording
- PROF 137/2026 (draft id=38): leave as-is unless a legal correction/replacement document is issued

### 2 — Historical warning banner (UI)
Add a read-only advisory badge on posted proforma views when `editable_lines_json` contains lines where:
- `name_pl_source='operator'` AND
- `name_pl` or `description_pl` differs from current `product_descriptions.description_pl`

Warning text:
> "This posted proforma contains legacy or operator description text that differs from current product description authority. No automatic change will be made."

Implementation: non-blocking advisory only. No gate, no block, no auto-write.

### 3 — Repair queue for unposted/draft-only documents
For drafts with `status IN ('draft','in_progress','pending')`:
- Surface a repair suggestion when the line's `description_pl` or `description_en` does not match current `product_descriptions` authority
- Operator clicks "Sync to authority" per line (not auto)
- Preserve `name_pl_source` provenance after sync

### 4 — Audit: shorthand description_en in product_descriptions
Query all rows where `description_en` matches known shorthand patterns:
- Category code patterns: `PCS,`, `PRS,`, `LGD`, `DIA`, `CLS`, `KT Gold`, `Plain Jewellery`
- `validate_description_line(description_pl, description_en).blocked == True`

Known open row:
- `EJL/26-27/292-1` — `description_en='PCS, 18KT Gold,Plain Jewellery Ring'`, `source='auto'`

Output: audit report listing all blocked rows, their `source`, and proposed action.

### 5 — Safe repair for source='auto' rows
Rows with `source='auto'` may be repaired via:
- Option A: Re-run customs description engine (canonical authority path)
- Option B: Operator confirms a proper English customs sentence

Repair must pass `validate_description_line()` before writing. Write with `source='manual'` after operator confirmation.

### 6 — source='manual' rows: operator review required, no auto-overwrite
For rows with `source='manual'`:
- Do NOT overwrite automatically under any circumstance
- Surface in dashboard as "Authority row requires operator review"
- Operator sees current value and proposed canonical value side-by-side
- Operator explicitly confirms or rejects the replacement

### 7 — New draft gate: canonical authority + validate_description_line
Already enforced by PR #741 (f117086):
- `routes_wfirma.py` DESCRIPTION_POLICY_BLOCKED gate is live
- `build_description_line()` applies `safe_compact_description()` at render time
- `proforma_intelligence.py` surfaces ANOMALY_DESCRIPTION_LINE_POLICY advisory

Remaining gap: new drafts for products with unrepaired `source='auto'` shorthand rows will hit
the wFirma gate at posting time. Repair (items 4+5) unblocks them proactively.

---

## Known affected rows at campaign creation

| product_code | description_en (current) | source | action |
|---|---|---|---|
| EJL/26-27/292-1 | `PCS, 18KT Gold,Plain Jewellery Ring` | auto | Repair before next posting |
| (run audit — item 4 — to find remaining rows) | | | |

---

## Admin UI: Edit Canonical Description (next iteration)

Replace manual DB correction scripts with a governed UI action on the product admin page.

**Workflow:**
1. Open a product in the admin UI
2. Display read-only: `description_pl`, `description_en`, rendered `PL / EN`, validation result (PASS / BLOCKED / warnings)
3. Authorised operator edits `description_pl` and/or `description_en` inline
4. `validate_description_line()` runs immediately on each keystroke or on blur — shows live PASS / BLOCKED / warnings
5. Save button enabled only when gate = PASS
6. On save: updates `product_descriptions` with `source='manual'`, stamps `updated_at`, writes audit event
7. Future drafts pick up the new values automatically via `get_description_block()`
8. Historical posted documents (`status IN ('issued','posted','locked')`) are unaffected — their `editable_lines_json` snapshots are immutable

**Scope:** admin route only, behind `require_api_key` or operator-level auth. Not exposed to non-admin proforma UI.

**Why this matters:** Eliminates reliance on one-off database correction scripts. Every description change is operator-confirmed, gate-validated, and auditable. Preserves the single-source architecture established by PR #741.

---

## Acceptance criteria

- [ ] No posted/issued proforma is auto-modified by this campaign
- [ ] Historical warning badge renders on posted proformas with legacy description text
- [ ] Repair queue available for draft-only documents (operator-triggered, not auto)
- [ ] Audit report produced listing all `product_descriptions` rows where `validate_description_line().blocked=True`
- [ ] `source='auto'` shorthand rows repaired via canonical engine or operator confirmation
- [ ] `source='manual'` shorthand rows surfaced for operator review (no auto-write)
- [ ] `EJL/26-27/292-1` authority row repaired and `validate_description_line()` passes before next posting

---

## What NOT to do

- Do not rewrite `editable_lines_json` on issued/posted/locked drafts automatically
- Do not treat "operator set this text" as a bug — it is a valid historical record
- Do not run a blanket UPDATE on `product_descriptions` without operator confirmation per row
- Do not block Refresh/Rebuild on drafts that have legacy operator text — warn, don't block
