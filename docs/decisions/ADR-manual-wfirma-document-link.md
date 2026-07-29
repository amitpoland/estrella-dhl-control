# ADR — Manual wFirma Document Linking (Campaign 2B)

**Status:** Proposed (operator-approved campaign; 4 decisions ratified in the 2B prep)
**Date:** 2026-07-19
**Scope:** proforma-derived drafts only; extends A2 reconciliation. No new table, no new comparison/link authority, no remote wFirma write.
**Builds on:** ADR-invoice-comparison-authority (A1), A2 reconciliation report (#949).

---

## Context
A proforma draft can be converted to a wFirma invoice out-of-band (issued in wFirma but the local
projection never recorded the `wfirma_invoice_id`), leaving the draft "posted" locally with no linked
invoice and no reconciliation possible (A2 returns `no_local_authority`). Operators need to **link an
existing wFirma invoice** to such a draft — after seeing a read-only comparison — so the canonical
projection is restored. This must not create a document, must not write to wFirma, and must not become
a second link/comparison authority.

## Decision
Add a two-step, authority-preserving flow on the existing proforma draft aggregate:

1. **`POST /api/v1/proforma/draft/{id}/resolve-wfirma-document`** — READ-ONLY (`_auth`). Resolves the
   operator-supplied remote id (direct `wfirma_id`, or `full_number` → `find_invoices_by_fullnumber`
   → exactly one, else refused), rebuilds the EXPECTED invoice plan from the draft's source proforma,
   fetches the actual remote XML read-only, and compares via the **A1** `compare_invoice_plan` reusing
   the **A2** reconciler view-model. Returns a comparison view-model + an opaque `preview_hash`.
   **Zero writes, no audit-on-read.** Not flag-gated (it cannot mutate anything).
2. **`POST /api/v1/proforma/draft/{id}/confirm-wfirma-link`** — WRITE (`_auth_write`, privileged),
   flag-gated by `wfirma_manual_document_link_enabled` (default **False** → 503). Re-fetches remote,
   rebuilds the expected plan, recomputes `preview_hash`, **refuses on any drift (409)**, enforces the
   conflict + billing gates, persists the remote-document identity onto `proforma_drafts` via the
   existing writer, appends **one** typed audit event, returns an idempotent result. **No remote
   wFirma write, ever.**

### Authority reuse (no new authority)
- **RemoteDocumentReference owner** = existing `proforma_drafts` columns (`wfirma_invoice_id` /
  `wfirma_invoice_number`), written **only** through `conversion_persistence.persist_invoice_to_draft`
  (the single post-conversion draft writer). No new table; no direct SQL in routes.
- **Comparison** = `document_comparator.compare_invoice_plan` (A1) — the sole comparison authority.
  2B adds `document_reconciler.build_manual_link_preview`, a **sibling** of `build_reconciliation`
  that targets an operator-specified remote id; it reuses the same comparator + view-model helpers and
  contains **no** comparison logic of its own.
- **Expected plan** = route-owned `_manual_link_expected_plan` (mirrors `_reconciliation_expected_plan`)
  injected into the service — the service never imports the api layer (preserves service←route direction).
- **Conflict lineage read** = `proforma_invoice_link_db.get_link_by_invoice` (issued-elsewhere check).
- **Read-only wFirma** = `wfirma_client.fetch_invoice_xml`, `find_invoices_by_fullnumber` only.
- **Privileged auth** = `require_api_key_privileged` (`_auth_write`). **Audit** = existing
  `proforma_invoice_link_db._record_draft_event` (primary) + `audit_persist` typed event (secondary,
  best-effort).

### Operator-approved decisions (2B prep, ratified)
1. **Persistence owner** = `proforma_drafts` aggregate (not a new table).
2. **Replacement policy** = replacement NOT implemented: same id → noop; different id already on draft
   → blocked; issued conversion link elsewhere → blocked.
3. **Scope** = proforma-derived drafts only (the draft must carry `wfirma_proforma_id`). Standalone /
   ownerless documents are out of scope (external-catalog, deferred).
4. **Dependency sequence** = A2 (#949) merged first — satisfied.

## Security model (resolves the pre-implementation security review — all 8 must-fixes)
- **W-1 (Lesson N true-blocker #3/#8):** confirm requires `wfirma_proforma_id` present AND
  `wfirma_invoice_id` absent, AND runs the existing product-code billing analysis; an **over-bill**
  (billed qty > available/import authority) is a hard block (409). `draft_state` alone is not the gate
  (its column default is `posted`). Only the true fiscal blocker blocks — advisory signals do not
  (Lesson N).
- **W-2 (conflict / idempotency):** confirm reads `draft.wfirma_invoice_id` **before** any persist —
  same id → noop (no write, no event); different id → blocked (409); `persist_invoice_to_draft` is an
  unconditional UPDATE, so the guard lives in the route, before the call.
- **W-3 (no internal-ID / raw-XML exposure):** responses carry only a human-readable candidate summary
  (currency, total, line count), gap **messages**, and the opaque `preview_hash`. Never `series_id`,
  `company_account_id`, `contractor_id`, `contractor_receiver_id`, `good_id`, db ids, raw XML, or
  debug metadata.
- **W-4 (document_type allowlist):** this release supports **`document_type="invoice"`** only. A1
  compares an invoice plan vs invoice XML; linking a *proforma* document would require a second
  comparison authority (proforma-vs-proforma) — **deferred** to a separate approved slice rather than
  adding a duplicate authority. Unknown/other types → 422.
- **W-5 (drift-hash integrity):** `preview_hash` = SHA-256 over a deterministic serialization of the
  **entire** expected plan (type, contractor_id, currency, series_id, company_account_id,
  contractor_receiver_id, expected_total, and every line's name/good_id/unit/unit_count/price/vat) +
  `document_type` + `comparison_version` + `remote_document_id` + `remote_snapshot_hash`. Any change to
  the local plan or the remote document between resolve and confirm changes the hash → 409.
- **W-6/W-7 (input validation):** exactly one of `wfirma_id` | `full_number`; `wfirma_id` must be
  numeric (path-injection defense); `full_number` 0/many → refused (404/409); draft-missing → 404;
  ineligible draft → 422/409 (distinct from 404); never 500 on upstream failure → 502.
- **W-8:** "NO wFirma write" is stated in the service + confirm docstrings as a review contract.

## Consequences
Idempotent audited reruns; read-only preview safe under `_auth` even with the flag off; write path
inert until the operator sets `WFIRMA_MANUAL_DOCUMENT_LINK_ENABLED=1`. A manual link sets
`draft_state='converted'` (correct — the draft now has a known remote invoice identity); there is no
self-service undo in this release (replacement is a separate approved slice).

## Rollback
Flag first (`wfirma_manual_document_link_enabled=False` → confirm 503). Never delete/mutate the remote
wFirma document. The persisted reference + audit event are preserved as immutable evidence.

## Alternatives rejected
- New `document_link` table / service → duplicate authority (Zero-Duplicate rule). Rejected.
- Proforma-vs-proforma comparison in this release → a second comparison authority. Deferred.
- Writing the link via `record_invoice_identity` unconditionally → it requires a pre-existing link row
  (KeyError otherwise) that a "posted" draft need not have. The draft aggregate is the correct owner.
