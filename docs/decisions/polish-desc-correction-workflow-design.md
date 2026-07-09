# Design: Operator Polish-Description Correction Workflow (slice A/B)

Status: DESIGN LOCKED — implement slice A/B in a fresh GATE-1 session. C/D require new authority (STOP).
Origin: `SHIPMENT_8341809162_2026-07_3d940f75`, guard `polish_desc_forbidden_tokens`. Related: #859.

## Root cause (recorded)
Document-registry staleness, NOT a description-authority failure at generation. Invoice re-upload
appends `invoice_lines` (`store_invoice_lines` = `INSERT OR IGNORE`, `document_db.py:1352`) and never
supersedes the prior document's lines. The original sparse upload's placeholder line survived
(`invoice_lines.description = "(placeholder — PZ engine will populate)"`, doc `dd1adaae`) and classified
to the generic fallback `"Wyrób jubilerski"` at `customs_description_engine.py:296`, which the
post-generation validator (`routes_dhl_clearance.py:3214-3249`) forbids. The single offending row was
deleted for this shipment; generation now reproduces clean.

## Authority map
- Per-line validation / forbidden flag: `customs_desc_checker` → `customs_description_mismatch`
  proposals; read `GET /api/v1/action-proposals/{batch_id}`. EXISTS.
- Save correction: `POST /api/v1/action-proposals/{proposal_id}/approve` with
  `{correction: DescriptionCorrection, scope: "shipment"|"global_mapping"}` →
  `audit["description_corrections"][product_code]` (`routes_action_proposals.py:982`). EXISTS (reuse).
- Correction applied at generation: `apply_description_corrections(audit)` (`customs_desc_checker.py:280`)
  overrides `row["material"]`, `row["description_pl"]`. EXISTS.
- Guards (keep active): reconcile `_reconcile_rows_with_audit_totals`; forbidden-token read-back.
- List documents: `GET /shipment/{batch_id}/documents` (`routes_upload.py:1208`). EXISTS.
- Product Master description: `reservation_db.get_product_master()` read fn only; NO per-product route.
- Product exception table: DOES NOT EXIST (do not invent).

## Slice A/B — REUSE-ONLY (build this)
Canonical page: `service/app/static/v2/shipment-detail-page.jsx` (route `/v2/shipment_detail?batch_id=`).
V1 `shipment-detail.html` is FROZEN (Lesson F). Do not add feature work to V1.

**Panel A — Product Description Correction** (insert in `DhlTab` after the DHL Clearance PanelCard, ~line 1113):
- Rows = projected description lines. Read via `GET /shipment/{batch_id}/documents` (invoice_lines) +
  `GET /api/v1/action-proposals/{batch_id}` (per-product_code `customs_description_mismatch` status).
- Columns: product_code | invoice | original extracted desc | Product Master desc | generated PL desc |
  validation status | forbidden-token reason. Row-level error badge on forbidden/empty.
- Correct: free-text or "use Product Master" → save via `POST /api/v1/action-proposals/{id}/approve`
  (scope `shipment`). Manual free-text must flow through the same `DescriptionCorrection` body (no bypass route).

**Panel B — Recheck / Regenerate** (same tab, action strip ~line 1106):
- Wire "Recheck" → existing recheck-all endpoint; "Generate Polish Description" →
  `POST /api/v1/dhl/generate-description/{batch_id}` (replace the `PendingAction` placeholder + remove
  `BackendPendingBanner` for these two actions only). Guards stay server-side; surface 422
  `rows_audit_reconciliation_failed` / `polish_desc_forbidden_tokens` as row-level operator errors.

Reuse primitives: `Btn, Badge, Card, Sel, Toast` (dashboard-shared.js) / `components.jsx`; CSS vars only;
`data-testid` kebab-case; api via `v2/pz-api.js` (add DHL methods there — it currently has none).

Small NEW read route (needed for "use Product Master" source):
`GET /api/v1/reservations/product-master/{product_code}/description` → `{description_pl, description_en}`
(thin wrapper over `reservation_db.get_product_master` + `description_engine.build_description_block`).

## STOP — new WRITE authority required (do NOT build silently; render "Backend Pending / Authority Gap")
- **C. Disable/archive a document**: add `shipment_documents.active` (+ `superseded_by`) column and
  `POST /shipment/{batch_id}/documents/{document_id}/deactivate` (soft, audited). None exists today.
- **D. Supersede invoice_lines on re-upload**: `store_invoice_lines` must delete/deactivate prior
  `(batch_id, invoice_no)` (or add `invoice_lines.active` + filter in the injector). This is the #859 fix.
- Until these exist, Panel C renders read-only list + disabled actions labelled "Backend Pending".

## PERMANENT BACKEND FIX — canonical customs description resolver (single authority for V1+V2)

Decided 2026-07-09: V1 and V2 both call the SAME route `POST /api/v1/dhl/generate-description/{batch_id}`
(V1 wired at `shipment-detail.html:7932/7940` `doAction('genDesc')`; V2 is a placeholder). Fixing the
backend fixes both — do NOT write separate V1/V2 logic.

**Canonical Product Description Authority (exists — reuse, do not create a new table):**
`product_descriptions` table, owned by `service/app/services/description_engine.py`
(`get_description_block()` L267, `build_description_block()` L51); fields `description_pl`/`description_en`;
approval marker = `source='manual'` (manual rows protected at `document_db.py:2616`).

**Root architectural defect**: the customs path `process_batch_items → normalize_item_description`
(`customs_description_engine.py:581`) is an INDEPENDENT classifier that never consults the authority;
it fabricates a generic fallback instead of stopping. `description_corrections` only patch `audit["rows"]`,
not the classifier; `get_description_block()` is only used later at PDF-block render (L1234).

**Generic fallback sites to REMOVE/redirect (never emit these):**
`customs_description_engine.py` L296 `or "Wyrób jubilerski"`; L389 `material_pl="metal szlachetny"`;
L408 `"… — wyrób jubilerski do noszenia."`; L477 `noun='Wyrób jubilerski'`; L492 `"… — wyrób jubilerski"`;
L1735 `item_type or "UNKNOWN"`. Each must yield an UNRESOLVED marker, not fabricated text.

**New function `resolve_product_description_for_customs(product_code, invoice_row, product_master, corrections)`**
(place in an existing service — description_engine.py — reusing existing authorities; NO new table):
returns `{description_pl, description_en, source, status, reason, forbidden_token_check}`.
Source priority (STOP, never fabricate):
1. `audit["description_corrections"][product_code]` (operator, shipment scope)
2. `product_descriptions` row with `source='manual'` (approved Product Master customs description)
3. `description_engine.get_description_block()` / `normalize_item_description` result **only if non-generic**
   (reject if it equals any forbidden/generic token)
4. else `status="missing_description"` with `reason` — NO fallback text.

**Wire it into `process_batch_items`** so BOTH SAD JSON and the PDF use the resolver output. Add a
**pre-generation guard** in the route (before PDF write, mirroring `lines_missing_for_description` at
`routes_dhl_clearance.py:3119`): collect rows with `status="missing_description"` (or generic-token) and
raise `422 {guard:"descriptions_missing_for_customs", rows:[{product_code, invoice, reason}]}`. Keep the
post-generation forbidden-token read-back (`routes_dhl_clearance.py:3214`) as the backstop — do not remove.

**V1 surfacing**: V1 `doAction('genDesc')` already shows the 422 detail; enhance the error render to list
per-row `product_code + reason` and offer "Use Product Master description" / "Save correction" (approve
route) / "Recheck" / "Generate". V2 wires the same route + panel later; no separate logic.

**Golden-safe**: rows that classify today are unchanged (resolver step 3 returns the same non-generic text);
only previously-fabricated rows change from fake-text → blocked. Still run `make verify-full` (golden PDF)
+ Lesson J (engine file deploys separately to C:\PZ\engine).

## Gates for the build session
GATE 1 (subagent review before PR) · GATE 6 (browser verify with console+network on this shipment) ·
FRONTEND AUTHORITY pre-check (one page/URL/authority) · Business Feature Completeness (Run-Now + status) ·
Lesson M (no capability suppression). Regression tests required:
1. forbidden placeholder blocks generation (guard stays 422),
2. approved shipment-scope correction → apply_description_corrections → generation passes,
3. (C/D, after authority) deactivated doc's invoice_lines excluded from projection,
4. (C/D) re-upload + recheck cannot silently reuse superseded rows.

## Implementation note — strategy actually built (reconciliation, GATE-1 2026-07-09)

The "Generic fallback sites to REMOVE/redirect" mandate above described ONE way to guarantee
"generic text must never reach PDF/SAD/audit": rewrite each fallback site (L296/L389/L408/L477/L492)
to emit an UNRESOLVED marker. The implementation instead achieves the same guarantee with a
**guard-based strategy**, which is the chosen, GATE-1-reviewed design:

- The resolver (`resolve_product_description_for_customs` / `resolve_and_stamp_customs_descriptions`)
  is the **generation source**: it STAMPs the approved, non-generic description onto the exact render
  items (`_extract_invoices`), and `process_batch_items` consumes `_resolved_description_pl` verbatim.
- **Guard #1 (pre-generation, engine-internal, fail-closed):** if any line lacks an approved
  non-generic description → BLOCK (`descriptions_missing_for_customs`); if the resolver itself raises →
  BLOCK (`customs_description_guard_error`). No file is written. This covers ALL callers (routes AND
  automation/CLI), not just the HTTP route.
- **Guard #2 (post-generation read-back):** scans the rendered PDF + SAD JSON for forbidden tokens;
  on any hit, unlinks both files and BLOCKs (`polish_desc_forbidden_tokens`). Backstop only.

The legacy fallback strings at L296/L389/L408/L477/L492 remain in the classifier as its internal
"suggestion" text, but they are unreachable as FINAL customs output: a stamped row overrides them, and
an unstamped/unresolved row is blocked by Guard #1 before generation (or Guard #2 after). L477/L492 are
on the PZ/proforma `render_product_description_pl` path, not the customs description path. Redirecting
the sites in place is deferred (would touch shared PZ/proforma rendering); the guard strategy is the
authority for the customs path. Follow-up hardening tracked in the PR (endpoint-2 route-level read-back
parity, forbidden-token single-source de-duplication, resolver-cache lock symmetry).
