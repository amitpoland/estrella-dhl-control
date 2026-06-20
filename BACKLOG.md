# BACKLOG.md

Side-discoveries captured during task execution that are out of scope for the current task.
Each entry must receive a SCHEDULED / ISSUE / REJECTED disposition (GATE 4) before the
next task closes.

---

## Entries

| # | Discovery | Found during | Disposition | Notes |
|---|---|---|---|---|
| B-001 | PR #661 (`ci/auto-merge-approved`) is non-draft and unreviewed — appears stale since 2026-06-20 | /feature DISCOVERY | SCHEDULED — review before next merge sprint | Verify it doesn't conflict with governance gates before approving |
| B-002 | `store_sales_document` uses `INSERT OR REPLACE` with a fresh-UUID PK and no `UNIQUE(batch_id, document_id)` — repeat calls create duplicate sales_documents rows (PRE-EXISTING; not introduced by PR-2). | PR-2 backend-safety review (F1) | SCHEDULED — sales-doc identity hardening PR | Canonical path is `ensure_sales_document_id` (id==document_id). PR-2 populates contractor on every insert, so no contractor value is lost; the dup-row design wart is orthogonal. |
| B-003 | `replace_sales_packing_lines` returns the pre-DELETE count as `deleted` rather than actual rows removed (`SELECT changes()`); a failed DELETE reports a non-zero count (PRE-EXISTING). | PR-2 backend-safety review (F4) | SCHEDULED — honesty fix on next document_db touch | Low impact; DELETE rarely fails. |
| B-004 | `auto_create_draft_from_sales_packing` writes the `created_from_sales_packing` event on a second connection outside the draft INSERT txn; a crash between leaves a draft with no creation event (PRE-EXISTING). | PR-2 backend-safety review (F5) | SCHEDULED — wrap event in the draft txn | Comment claims they commit together; they do not. |
| B-005 | No end-to-end test asserts `get_reservation_preview` output carries `client_contractor_id` / `contractor_resolved`. Needs a full batch fixture (audit.json + packing.db + stock). | PR-2 test-coverage review (#5) | SCHEDULED — reservation-preview field test PR | Reference verified at the `upsert_reservation_draft`/`get_reservation_draft` DB layer (PR-2 tests) + field wiring confirmed by integration-boundary review. |
| B-006 | Broad single-process `pytest -k` run (4800+ tests) trips pre-existing failures + STORAGE-LEAK guard cascade in a fresh worktree (e.g. `test_reservation_queue` 404 reproduces on clean origin/main 5242417). | PR-2 VERIFY | SCHEDULED — CI harness/isolation investigation (not PR-2) | Authoritative signal is isolated/smoke suites; broad combined run is unreliable in a bare worktree. |
| B-007 | `enrich_lines_from_product_descriptions` unconditionally overwrites `name_pl` from the product-descriptions authority even when a line carries an operator-confirmed non-blank `name_pl` (the `_birth_resolve_name_pl` guard is not replicated). PRE-EXISTING; PR-2 does not add new `enrich_draft_lines` call sites. | PR-2 final challenge (F1) | SCHEDULED — name_pl enrichment guard PR | Mirror the non-blank guard from `_birth_resolve_name_pl`. |
| B-008 | `contractor_conflict` draft-birth blocks are advisory and persist (open) while the ambiguity stands; a `list_draft_birth_blocks` code filter / `include_advisory=false` would let operators separate advisory conflicts from true non-creation blocks. | PR-2 final challenge (F4) | SCHEDULED — blocks-API filter PR | By design: conflict persists until operator reconciles the contractor assignment; it auto-resolves when the conflict is gone. |
| B-009 | The backfill log message conflates a rename-path charge collision (`canonical_already_has_charge_type`) with a canonical-wins drop (`canonical_wins_collision`) under one "DROPPED" WARNING. The per-entry `reason` field distinguishes them; the summary log does not. | PR-3 final challenge (F4) | SCHEDULED — split log severity by reason | Cosmetic; both are surfaced in the response `dropped_charges` with distinct reason codes. |
| B-010 | No isolated unit test for `set_sales_client_name` multi-client non-clobber (two distinct client_names on one sales_document, assert only the old-name lines are renamed). Covered indirectly via the forward-sync integration test. | PR-3 final consistency review | SCHEDULED — add focused unit test | Code is scoped by `client_name=?`; an explicit isolated test would pin the contract. |
| B-011 | `migrate_draft_to_canonical_name` is not listed in `proforma_invoice_link_db.__all__` (nor are the PR-2 `record_/resolve_/list_draft_birth_block` helpers). Imported by name so no runtime break; invisible to static export checks. | PR-3 final consistency review | SCHEDULED — add to __all__ | Cosmetic; matches the existing PR-2 omission pattern in the same module. |

---

_Maintained per TASK_EXECUTION_PROTOCOL.md §Standing Rules — BACKLOG rule._
