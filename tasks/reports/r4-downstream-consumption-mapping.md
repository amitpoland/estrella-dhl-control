# R4-readiness mapping — downstream contractor-resolution consumption

**Status:** Mapping only. No code changes proposed in this PR. No production regression observed.
**Date:** 2026-05-17
**Production SHA:** `4b03c30` (PR #163 live)
**Verification baseline:** resolution suite 63/63 + 1 skipped; PZ regression 160/160; doctor clean (re-verified at the start of this batch).

---

## 1. Current campaign state

- **B0 identity foundation complete.** Client Master + Supplier Master deep-enriched. Bulk re-sync done. wFirma series dictionary refresh live. 28 client rows, 4 supplier rows (verified via `/api/v1/customer-master/?limit=500` + `/api/v1/suppliers/?limit=500`).
- **B0.X resolver shipped through R3.**
  - R1 (PR #161): `packing_contractor_resolver.py` deterministic 6-tier classifier — read-only.
  - R2 (PR #162): `packing_resolution_db` + 3 routes under `/api/v1/packing/{batch_id}/contractor-resolution`.
  - R3 (PR #163): `ContractorResolutionPanel` UI in `BatchDetailPage` between Packing List card and Document Registry.
- **No downstream consumption yet.** Proforma + PZ flows still use their own legacy identity resolution path (see §4 below).
- **Operator browser walk pending** (no demonstrated friction → R4 polish deferred per the previous verification batch).

---

## 2. UI field/button → API mapping (verbatim from source)

| UI surface | Component / line | API call(s) | Method | Notes |
|---|---|---|---|---|
| 🧭 Contractor resolution panel | `ContractorResolutionPanel` `dashboard.html:11019` | — | — | Pure layout; renders one role card per role |
| Client / Supplier role card | `ContractorResolutionRoleCard` `dashboard.html:10753` | `GET /api/v1/packing/{batchId}/contractor-resolution/{role}` | GET | Mount-effect + after every action |
| **Resolve** button | testid `contractor-resolution-${role}-resolve-btn` `:10958` | `POST /api/v1/packing/{batchId}/contractor-resolution` | POST | Sends `X-Operator-User: dashboard` |
| **Use this match** / **Override** | testid `contractor-resolution-${role}-confirm-btn` `:10968` | `POST /api/v1/packing/{batchId}/contractor-resolution/confirm` | POST | Override branch attaches matched_master_type/id/wfirma_id from picked candidate |
| Open Client/Supplier Master | testid `contractor-resolution-${role}-open-master-btn` `:10982` | (no network call) | — | Currently a toast hint; deep-link deferred |
| **+ Create new (disabled)** | testid `contractor-resolution-${role}-create-new-btn` `:10995` | — | — | `disabled` + `cursor: not-allowed`. Tooltip directs operator to existing Client/Supplier Master CRUD endpoints |
| Unresolved-warning banner | testid `contractor-resolution-${role}-unresolved-warning` `:11006` | — | — | Rendered only when `status === 'unresolved'`; copy: *"Operator must pick a candidate (or create the master row separately) before proforma / PZ can use this client/supplier."* |
| **Proforma readiness card** | `ProformaReadinessCard` `dashboard.html:21573` | `GET /dashboard/batches/{batchId}/proforma-readiness` | GET | **Independent surface.** Already in production. Reads `wfirma_customers` (NOT `customer_master`) via its own `_resolve_customer` path inside `routes_proforma.py:186`. |
| Proforma preview / create | inside `ProformaReadinessCard` | `POST /api/v1/proforma/preview/{batch_id}/{client_name:path}` `routes_proforma.py:746` and `/create/...` `routes_proforma.py:899` | POST | Pre-existing flow. `client_name` is a free-form string the operator types or sales-list provides. |
| PZ process | dashboard PZ panel (separate from this scope) | `POST /api/v1/pz/process` `routes_pz.py:50` | POST | Pre-existing flow. Identity touchpoints are `exporter_match` (SAD parse) + `importer_match` — not the same shape as contractor-resolution. |

**Source-grep verified network surfaces inside the resolution component (lines 10753–11020):** exactly the 3 approved URLs. Zero hits on `/api/v1/customer-master/`, `/api/v1/suppliers/`, `/api/v1/wfirma/`, `/api/v1/proforma/`, `/api/v1/pz/`, `/api/v1/dhl/`, `/api/v1/finance/`.

---

## 3. API → DB/model mapping (verbatim from source)

| API | Backend handler | DB / model touched | Read or Write |
|---|---|---|---|
| `GET /api/v1/packing/{batch_id}/contractor-resolution` | `routes_packing_resolution.list_batch_resolutions` `:55` | `packing_contractor_resolution` (in `<storage_root>/packing_resolutions.sqlite`) | READ |
| `GET .../contractor-resolution/{role}` | `routes_packing_resolution.get_one_resolution` `:68` | same | READ |
| `POST .../contractor-resolution` | `routes_packing_resolution.resolve_and_persist` `:90` | calls `packing_contractor_resolver.resolve_contractor` (reads `customer_master.sqlite` + `suppliers.sqlite`) then `packing_resolution_db.upsert_resolution` (writes one row in `packing_contractor_resolution`) | READ masters + WRITE resolution |
| `POST .../contractor-resolution/confirm` | `routes_packing_resolution.confirm_or_override` `:158` | reads stored resolution; verifies `matched_master_id` against the stored candidate list; UPDATEs the resolution row only | WRITE resolution only |
| `GET /dashboard/batches/{batch_id}/proforma-readiness` | `routes_dashboard.proforma_readiness` `:2333` | `wfirma_customers`, `document_db` rows, `audit.json`, `pz_rows.json`. **Does NOT touch `packing_contractor_resolution`.** | READ |
| `POST /api/v1/proforma/preview/{batch_id}/{client_name}` | `routes_proforma._build_preview` `:327` → `_resolve_customer` `:186` | `wfirma_customers` (3-step prefix-tolerant match), `document_db.sales_to_wfirma`, `customer_master_db.get_customer` for freight/insurance defaults | READ + builds blocking_reasons |
| `POST /api/v1/proforma/create/...` | `routes_proforma` `:899` | same as preview + writes proforma_drafts; calls wFirma live (separate write-flag gate) | READ + WRITE drafts (NOT in scope of any current B0.X work) |
| `POST /api/v1/pz/process` | `routes_pz` `:50` | exporter/importer match patterns; SAD parse; pz_rows.json | READ + WRITE pz pipeline (separate from contractor-resolution) |

**Critical finding (§4 below):** the **proforma identity-gate path is COMPLETELY SEPARATE** from the B0.X resolver. The two storages (`wfirma_customers` table inside `wfirma_db.py` vs `customer_master` table inside `customer_master_db.py` vs `packing_contractor_resolution`) are three distinct identity surfaces today.

---

## 4. Existing identity gates affected by client/supplier identity

| Gate | Location | Source of truth today | Would consult contractor-resolution? |
|---|---|---|---|
| Proforma preview blocking_reasons "customer not matched in wfirma_customers" | `routes_proforma.py:384` and `:631` | `wfirma_customers` table (via `wfdb.get_customer` + `wfdb.list_customers`) | **No.** Independent legacy resolver `_resolve_customer` `:186` walks `wfirma_customers` with prefix-tolerant matching. |
| Proforma preview "multiple wfirma customer candidates" (ambiguous) | `routes_proforma.py:376` | same | No. |
| Proforma `customer_match` final readiness | `routes_proforma.py:622` | same (`customer_resolution["found"]`) | No. |
| Proforma `wfirma_create_customer_allowed` flag gate | `routes_dashboard.py:2363` (readiness) + `routes_proforma.py` (create-path) | `settings.wfirma_create_customer_allowed` env flag | No — flag-only. |
| Freight / insurance defaults applied to proforma lines | `routes_proforma.py:36-37` (`pick_freight`, `compute_insurance_suggestion`) | `customer_master.bill_to_contractor_id` → `customer_master_db.get_customer` | **Partially.** Proforma already reads `customer_master` for freight/insurance, but maps via `wfirma_customer_id` resolved from `wfirma_customers`, not from `packing_contractor_resolution.matched_wfirma_id`. |
| PZ exporter / importer match | `routes_pz.py:170-189`, pattern store, `exporter_aliases` | Local pattern store + SAD parse | No. Supplier-side resolver verdict is structurally separate from PZ exporter aliases. |
| DHL/customs shipper/consignee identity | `document_db.py:163-164` (`shipper_name`, `consignee_name`) | AWB parse | No. Different identity flow (inbound logistics, not outbound sales). |

**Conclusion:** the B0.X resolver verdict is currently an **isolated identity surface** with no automatic consumer. The legacy identity gates each maintain their own match logic — none of them call `packing_contractor_resolution`.

The R3 UI's warning copy ("Operator must pick a candidate before proforma / PZ can use this") **describes intent, not enforcement**: there is no code path today that gates proforma posting on `packing_contractor_resolution.status`. The proforma blocker is `customer_resolution["found"] = False` based on its own `_resolve_customer` walk of `wfirma_customers`.

---

## 5. Safe future integration design — advisory only by default

The minimum-risk integration is:

**Phase R4A (advisory)** — `proforma_readiness` adds a NEW read-only field that surfaces the resolver verdict to the operator, without changing any gate. The proforma flow continues to use its own `_resolve_customer`. The new field reads `packing_contractor_resolution.role='client'` and exposes:

```json
{
  "advisory_contractor_resolution": {
    "present":        true,
    "status":         "confirmed",
    "tier":           3,
    "confidence":     0.85,
    "matched_master_type": "client_master",
    "matched_master_id":   17,
    "matched_wfirma_id":   "145067816",
    "parsed_name":         "SUOKKO",
    "agrees_with_proforma_resolver": true,
    "agrees_reason":  "wfirma_id matches"
  }
}
```

**`agrees_with_proforma_resolver`** is computed locally by comparing `packing_contractor_resolution.matched_wfirma_id` against `customer_resolution["wfirma_customer_id"]` returned by `_resolve_customer`. When the two disagree, the operator sees:
- Advisory disagreement banner on the readiness card.
- No gate change. Proforma posting still gated by its own resolver. Operator can refresh proforma readiness or override one of the surfaces — that decision stays with the operator.

This design:
- Does NOT change `customer_resolution["found"]` semantics.
- Does NOT add `packing_contractor_resolution.status` to `blocking_reasons`.
- Does NOT change any wFirma posting code path.
- Is reversible with a 1-line revert (drop the new readiness field).

**Phase R4B (gate, only if explicitly approved)** — would later flip the contract so that an UNRESOLVED `packing_contractor_resolution.status === 'unresolved'` becomes a `blocking_reason` for proforma preview. **Not in scope.** Operator must explicitly authorise this gate change because it can newly block flows that work today.

**Phase R4C (single source of truth, far future)** — collapse the three identity surfaces (`wfirma_customers`, `customer_master`, `packing_contractor_resolution.matched_wfirma_id`) into one. Significant refactor. Out of scope for now.

The R4 entry point — if and when the operator approves it — is **R4A only.**

---

## 6. Files that WOULD be touched in a future R4A implementation

(Listed for the future PR's planning, not modified now.)

- `service/app/api/routes_dashboard.py:2333` — `proforma_readiness` endpoint. Add `advisory_contractor_resolution` field. **Additive only.**
- `service/app/services/packing_resolution_db.py` — already exposes `get_resolution(db_path, batch_id=..., role='client')`; reuse as-is.
- `service/app/static/dashboard.html` — `ProformaReadinessCard` `:21573` — render an "Advisory: contractor resolution" subsection. Source-grep test that the existing readiness gate behaviour is unchanged.
- `service/tests/test_proforma_readiness*.py` (new test file) — assert advisory field present, advisory disagreement detected, but NO change to existing `proforma_readiness.proforma.ready` semantics on a baseline batch.

Hard estimate: ~80 lines of code, ~6 tests. Independently deployable.

---

## 7. Files that MUST NOT be touched in R4A

- `service/app/services/packing_contractor_resolver.py` — algorithm frozen
- `service/app/services/packing_resolution_db.py` — schema frozen
- `service/app/api/routes_packing_resolution.py` — route contract frozen
- `service/app/api/routes_proforma.py` `_resolve_customer` `:186` — pre-existing identity-gate logic; advisory must be SEPARATE
- `service/app/api/routes_proforma.py` `_check_warehouse_readiness` `:88` — unrelated gate
- `service/app/services/customer_master_db.py` — no schema change
- `service/app/services/suppliers_db.py` — no schema change
- `service/app/services/wfirma_db.py` — legacy `wfirma_customers` table; do not migrate
- `service/app/api/routes_pz.py` — PZ flow stays out
- `service/app/services/document_db.py` — exporter/consignee identity is a separate channel
- Any `wfirma_create_*_allowed` flag
- `.env`
- Database schemas (no migration)

---

## 8. Required tests for a future R4A implementation

| # | Test | Form |
|---|---|---|
| 1 | `proforma_readiness` returns the new `advisory_contractor_resolution` field with `present=false` when no resolution stored for the batch | integration |
| 2 | Returns `present=true` with full verdict mirror when a resolution exists | integration |
| 3 | `agrees_with_proforma_resolver=true` when `matched_wfirma_id` matches `wfirma_customer_id` from the legacy resolver | integration with seeded `wfirma_customers` + `packing_contractor_resolution` |
| 4 | `agrees_with_proforma_resolver=false` with a `disagreement_reason` when the two resolvers disagree on wfirma_id | integration |
| 5 | Existing `proforma.ready` semantics unchanged on the same fixture (regression) | parametrised vs. baseline | 
| 6 | `blocking_reasons` shape unchanged (no new entries from advisory) | source-grep + integration |
| 7 | Resolver verdict tier/confidence/status passthrough preserved | unit |
| 8 | No call to `packing_resolution_db.upsert_*` from `proforma_readiness` (source-grep) | trip-wire |
| 9 | Source-grep test that `routes_dashboard.proforma_readiness` does NOT import wFirma write helpers | trip-wire |
| 10 | PZ regression 160/160 (unchanged) | regression |
| 11 | Existing resolution-suite 63/63 (unchanged) | regression |

---

## 9. Hard-rule checks (verified on inspection)

| Rule | Status |
|---|---|
| Do not connect contractor-resolution to proforma/PZ yet | ✓ Mapping only. No code change. |
| Do not allow resolver verdict to silently override existing identity gates | ✓ R4A design is **advisory-only**; the legacy `_resolve_customer` remains the authoritative gate. R4B (actual gate change) would require explicit operator approval. |
| Confirmed resolution may only become a future advisory/input candidate unless explicitly approved later | ✓ Encoded in the R4A/R4B split. |
| No direct unsafe POST from UI | ✓ R3 component calls only the 3 approved routes; verified by source-grep test (`test_panel_calls_only_r2_routes`). |
| No wFirma write | ✓ |
| No finance write | ✓ |
| No DHL/customs change | ✓ |
| No schema migration | ✓ R4A is read-only against existing schemas. |
| No `.env` change | ✓ |
| No master auto-create | ✓ Create-new button remains disabled. |
| No guessed file paths | ✓ Every file path in §6/§7 was opened and confirmed in this batch (line numbers cited where useful). |
| Inspect real code before naming files as affected | ✓ §4 cites verbatim line numbers; the proforma identity-gate path was verified by reading `_resolve_customer` end-to-end. |

---

## 10. Risks / open issues

- **Two parallel customer identity tables** in production (`wfirma_customers` legacy + `customer_master` operator master). The B0.X resolver reads `customer_master`; proforma still reads `wfirma_customers`. Today the two stay in sync through operator action (Client Master sync → wfirma_customers via earlier campaign work). R4A's `agrees_with_proforma_resolver` field surfaces disagreement to the operator; resolving disagreement is operator-decided, not auto-fixed.
- **R3 UI's warning copy is aspirational.** It tells the operator "proforma / PZ cannot use this client until you pick" — but today neither proforma nor PZ actually consults `packing_contractor_resolution`. The copy is HONEST about the future intent but currently has no enforcement. R4A would not change this either (still advisory). The honest path is to keep the copy as-is so the operator's mental model matches the future R4B if/when it lands.
- **`onToast` no-op from R3** — unchanged. Pre-documented R4 polish; not affected by this mapping batch.
- **No operator browser walk has been performed** since R3 ship. Recommended sequence (per previous verification batch): operator browser walk → identify concrete friction → polish (R4 toasts/prompt/deep-link) BEFORE building R4A advisory integration.

---

## 11. Decision

**STOP.** No production regression observed during this mapping batch.

The mapping doc is the deliverable. No code changes proposed.

### If the operator subsequently authorises downstream consumption, the smallest next batch is:

**Phase R4A — advisory contractor-resolution field on proforma-readiness**

- Scope: additive read-only field on `GET /dashboard/batches/{batch_id}/proforma-readiness`
- Files: `routes_dashboard.py` (1 file), `dashboard.html` `ProformaReadinessCard` (1 file), 1 new test file
- ~80 lines + 6 tests
- Independently deployable
- Reversible with 1-line revert
- Does NOT change any existing gate; does NOT call `packing_resolution_db.upsert_*`; does NOT touch proforma posting
- Requires operator approval gate: explicit confirmation that surfacing a disagreement banner is desired UX before implementation begins

### Verification rerun (this batch, no changes made)

- Resolution suite: **63/63** pass (+ 1 intentional skip)
- PZ regression: **160/160** pass
- `campaign_status doctor`: clean
- Production SHA: `4b03c30` (unchanged)
- Deployed dashboard.html bit-identical to repo (`diff -q` returned empty)

The system is stable. Awaiting operator browser walk + explicit R4A approval before any further code change.
