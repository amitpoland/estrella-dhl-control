# Phase 4B Wave 4 — product_local Soft-Delete Design Note

**Status:** DESIGN (pre-implementation). No code changed by this note.
**Date:** 2026-05-28
**Author:** Master Data soft-delete campaign
**Decision owner:** operator (Amit) — sign off before Wave 4 implementation.

`product_local` is the last hard-delete-only master entity. Unlike the other
14 soft-deletable entities, it is **not an authority** — it is a thin local
**overlay** on wFirma-owned products. Soft-deleting an overlay therefore does
not mean "remove a record"; it means "stop augmenting". This note fixes the
semantics, the forbidden behaviors, the API contract, the consumer changes,
the test plan, and rollback — so Wave 4 implementation is mechanical.

---

## 1. Current authority map

| Concern | Authority | product_local's role |
|---|---|---|
| Product existence | **wFirma** (product master) | none — product_local never creates/owns a product |
| Product code | wFirma | overlay is keyed by `product_code` (soft FK-by-value into wFirma) |
| HS classification | Customs / invoice / operator | **overlay** supplies `hs_code_override` as a *fallback filler* |
| Unit of measure | wFirma native | **overlay** supplies `unit_override` as a fallback |
| Country of origin | Customs reality | **overlay** supplies `origin_country` (seeded `'IN'` for all jewellery) |
| Design linkage | designs master | overlay supplies `design_code_link` (soft ref) |

`product_local` is an **augmentation layer**. Removing/deactivating it must
never imply the underlying wFirma product is gone.

ProductLocal dataclass (today): `product_code` (PK), `hs_code_override`,
`unit_override`, `design_code_link`, `notes`, `origin_country` (default `'IN'`),
`created_at`, `updated_at`. **No `active` / `deleted_at` column yet** — Wave 4
adds both, exactly as customers/suppliers gained them.

---

## 2. Current product_local consumers (inspected)

| Consumer | File:line | How it reads product_local | Has non-overlay fallback? |
|---|---|---|---|
| Proforma HS resolver | `service/app/services/proforma_draft_sync.py:208–213` | `get_product_local()` → uses `pl.hs_code_override` as **Level 1** | **Yes** — Level 2 = `invoice_lines.hs_code`, Level 3 = unchanged |
| Proforma line enrichment | `service/app/api/routes_proforma.py:6092–6101` | `get_product_local()` → fills `origin_country` and (only `if not hs`) `hs_code_override` | **Yes** — `hs` already defaults from line; origin defaults `"IN"` |
| Proforma intelligence HS lookup | `service/app/services/proforma_intelligence.py:199–242` | raw SQL `SELECT product_code, hs_code_override FROM product_local WHERE hs_code_override IS NOT NULL` | **Yes** — advisory only; absence just removes a suggestion |
| Master-data intelligence coverage | `service/app/services/master_data_intelligence.py:36,417–558` | `list_product_local()` → computes "% designs with overlay" | **Yes** — advisory metric only |
| Master-data CRUD | `routes_master_data.py` `pl_router` | full CRUD | n/a (owner) |
| RI checks | `master_reference_checks.py` | comment reference only; does **not** read product_local rows | n/a |

**Critical finding:** none of the live consumers currently filter on `active`
(the column does not exist yet). All three functional consumers
(`proforma_draft_sync`, `routes_proforma`, `proforma_intelligence`) already
have a clean fallback path when the overlay is absent. This is what makes the
recommended semantics safe and cheap.

**PZ / customs engine:** the repo-root PZ engine (`pz_import_processor.py`,
`pz_calculator.py`) does **not** import `product_local` (grep returned no
matches outside `service/app`). The overlay influences proforma-side HS/origin
enrichment only. PZ landed-cost remains driven by invoice + ZC429 authority.

---

## 3. Chosen inactive-overlay semantics (DECISION)

**An inactive `product_local` row means "stop applying the local overlay."**

Concretely:
1. Downstream consumers must behave **as if no local overlay exists** for that
   `product_code`.
2. They must **fall back to existing non-overlay behavior**:
   - HS code → next resolution level (`invoice_lines.hs_code`, then unchanged).
   - `origin_country` → the existing default (`"IN"`).
   - `unit_override` → wFirma native unit (overlay simply not applied).
3. The underlying **wFirma product is NOT treated as deleted** — product
   existence is wFirma's authority and is untouched.
4. `GET /api/v1/product-local/{product_code}` **may still return** an inactive
   overlay (with `active=false`, `deleted_at` set) for operator/audit
   inspection.
5. **Default list hides inactive overlays** (`active`-only); `?active=false`
   surfaces them.
6. Re-activating (restore) **re-applies** the overlay with its prior field
   values intact.

This matches the operator's recommended default verbatim and is implementable
because every functional consumer already has a fallback.

---

## 4. Forbidden behavior

Wave 4 implementation MUST NOT:
- F1. Treat an inactive overlay as a missing/deleted **wFirma product**.
- F2. Cause any consumer to **error** when an overlay is inactive — it must
  silently fall back (consumers are already best-effort / try-except).
- F3. Change PZ landed-cost, customs ZC429, or wFirma write behavior.
- F4. Let `PUT` (upsert) silently **reactivate** a soft-deleted overlay — same
  invariant proven for customers (`upsert` must not write `active`/`deleted_at`).
- F5. Hard-delete by default — DELETE is soft unless `?hard=true` + flag +
  master_admin.
- F6. Leave any consumer reading inactive overlays as if active. Specifically
  the **three functional consumers must be updated** to skip inactive rows
  (see §5 consumer-change list) — otherwise an inactive overlay would keep
  filling HS/origin, defeating the soft-delete.
- F7. Introduce a credential or secret field (n/a here, but the campaign rule
  stands).

---

## 5. API contract for Wave 4

### Schema
- Add `active INTEGER NOT NULL DEFAULT 1` and `deleted_at TEXT` to
  `product_local` (idempotent ALTER in `init_db`, matching the
  customers/suppliers pattern). `ProductLocal` dataclass gains
  `active: bool = True`, `deleted_at: Optional[str] = None`.
- `_row_to_pl` reads both tolerantly (legacy rows → `active=True`).

### Routes (`pl_router`)
| Verb | Path | Behavior |
|---|---|---|
| GET | `/api/v1/product-local/` | default active-only; `?active=true|false` honored |
| GET | `/api/v1/product-local/{product_code}` | returns inactive rows too (active=false + deleted_at) |
| PUT | `/api/v1/product-local/{product_code}` | upsert; MUST NOT touch active/deleted_at (no reactivation) |
| DELETE | `/api/v1/product-local/{product_code}` | **soft-delete by default**; `?hard=true` → 409 if flag off / 403 if not master_admin / 204 + audit `hard_delete` |
| POST | `/api/v1/product-local/{product_code}/restore` | **new** — active=true, deleted_at=null, audit `restore` |

### Audit ops
`delete` (soft, before=row/after=null), `restore`, `hard_delete` — identical
to prior waves. Entity tag: `product_local`.

### DB helpers (master_data_db.py)
`soft_delete_product_local`, `restore_product_local`,
`hard_delete_product_local` (alias of existing `delete_product_local`), plus
`list_product_local(..., active: Optional[bool] = None)`.

### Consumer changes (the load-bearing part)
To honor "inactive = stop applying overlay", three functional consumers must
skip inactive rows:

1. `proforma_draft_sync._resolve_hs_code` — after `get_product_local`, treat
   `pl.active is False` as a Level-1 miss → fall to Level 2.
2. `routes_proforma.py` line enrichment (~6098) — only apply
   `origin_country` / `hs_code_override` when `pl_row.active` is truthy.
3. `proforma_intelligence.py` raw SQL (~201) — add `AND active = 1` to the
   `product_local` SELECT.

Advisory-only (lower priority, safe to include in the same PR):
4. `master_data_intelligence` coverage — count active overlays only (pass
   `active=True` into `list_product_local`, or filter in the function).

These are the ONLY behavior touches; each preserves the pre-existing
non-overlay path, so PZ/customs/wFirma outcomes are unchanged for products
with no overlay or an active overlay.

---

## 6. Test plan for implementation

New `test_master_soft_delete_phase4b_wave4_product_local.py`:
- soft delete sets active=false + deleted_at; audit op=`delete`
- default list excludes inactive; `?active=false` includes inactive
- get-by-code returns inactive with active=false + deleted_at
- restore resets active=true / deleted_at=null; audit op=`restore`
- PUT does not reactivate a soft-deleted overlay
- hard delete: blocked flag-off (409); blocked master_editor flag-on (403);
  allowed master_admin flag-on (204 + audit `hard_delete`)

Consumer-behavior tests (the critical proof):
- **HS fallback**: overlay with `hs_code_override` active → resolver returns
  override; same overlay soft-deleted → resolver falls back to
  `invoice_lines.hs_code` (or None) — proving "stop applying overlay".
- **origin fallback**: line enrichment with active overlay → uses overlay
  origin; soft-deleted → origin reverts to `"IN"` default.
- **intelligence SELECT**: soft-deleted overlay no longer appears in the
  proforma_intelligence HS lookup.
- **wFirma product not deleted**: assert no wFirma call / no product-existence
  mutation occurs on soft-delete (source-grep + behavior).

UI tests (V2):
- 15 soft-delete entities now enabled (catalog complete; zero hard-delete-only).
- product_local rows show Deactivate/Restore.
- `HARD_DELETE_REMAINING` becomes empty set.

Isolation / source-grep:
- product_local soft-delete functions do not import wFirma/PZ/customs modules.
- PZ engine still does not import product_local (regression of the current
  invariant).

Regression: Phase 0–5 + all prior waves stay green; **PZ regression 160/160**.

---

## 7. Rollback plan

- **Schema**: `active`/`deleted_at` are additive nullable/defaulted columns —
  leaving them in place is harmless. No down-migration needed; to disable the
  feature, revert the route + consumer changes and the columns simply sit
  unused (all rows `active=1`).
- **Route layer**: revert `pl_router` DELETE to hard-delete + drop the restore
  endpoint. Pure code revert; no data change.
- **Consumer changes**: each consumer change is a single guarded branch;
  reverting restores the pre-Wave-4 behavior (overlay always applied when
  present). Because legacy rows are `active=1`, reverting is behavior-neutral
  for existing data.
- **Flag**: `master_hard_delete_enabled` already governs permanent removal; no
  new flag introduced.
- No automatic data deletion at any point.

---

## 8. Risk assessment

| Risk | Severity | Mitigation |
|---|---|---|
| A consumer is missed and keeps applying an inactive overlay | MEDIUM | §5 enumerates all three functional consumers from a full grep; consumer-behavior tests assert fallback for HS + origin + intelligence. |
| Operator soft-deletes an overlay mid-proforma and HS silently changes | LOW-MEDIUM | This is the intended semantics (stop augmenting → fall back). The proforma line `hs_source` already records provenance; a follow-up could surface "overlay inactive" in the UI. |
| PUT reactivation regression | LOW | Proven-safe pattern from customers: `upsert_product_local` never writes active/deleted_at; pin with a test (F4). |
| PZ engine coupling | LOW | PZ engine does not import product_local (verified). Overlay is proforma-enrichment-only. |
| `origin_country` default `'IN'` masks a real origin when overlay deactivated | LOW | Pre-existing default; deactivation reverts to the same default the system uses for un-augmented products. Documented, not a new behavior. |
| Intelligence coverage metric counts inactive overlays | LOW (advisory) | Update `list_product_local(active=True)` for the coverage calc; no operational impact. |

Overall risk: **MEDIUM**, driven entirely by the consumer-update step. The
mechanical soft-delete is identical to the 14 prior entities; the only novelty
is that three read-side consumers must learn to skip inactive rows. All three
already have fallbacks, so the change is additive and reversible.

---

## 9. Decision summary

**APPROVED DEFAULT** (pending operator sign-off): inactive `product_local` =
overlay not applied; consumers fall back to non-overlay behavior; wFirma
product untouched; GET-by-code still returns inactive for audit; default list
hides inactive. Wave 4 implements schema + routes + the three consumer guards +
tests, with zero change to PZ/customs/wFirma authority.
