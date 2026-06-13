# fix(authority): consolidate name normalization into a single authority module (Campaign 02.5/02.75 — B5)

## What & why
Seven different name-normalization implementations were scattered across the codebase, each a private `_normalize_name`/`normalise_name`/`_norm`. Divergent normalization is a direct cause of duplicate contractors and failed wFirma contractor matches. This PR extracts **one authority module** — `service/app/services/name_normalization.py` (7 public functions) — and converts the 7 host files to thin delegates. **Behavior is preserved, not changed** (parity-pinned).

## Authority → delegate mapping (1:1, verified)
| Authority function | Delegate host |
|---|---|
| `customer_resolution_normalize_name` | `customer_resolution_authority.py` |
| `proforma_normalize_client_name` | `routes_proforma.py` |
| `suppliers_db_normalize_name` | `suppliers_db.py` |
| `wfirma_auto_resolve_normalize_name` | `wfirma_customer_auto_resolve.py` |
| `master_data_norm` | `master_data_intelligence.py` |
| `packing_contractor_normalise_name` | `packing_contractor_resolver.py` |
| `wfirma_sync_normalise_client_name` | `wfirma_customer_sync.py` |

`master_data_norm` is intentionally the only function emitting NFD-decomposed output; the other six emit NFC. This asymmetry is pinned by the C1 contract test (audit-drift branch).

## Test evidence (independently re-run, orchestrator)
- PZ regression `tests/test_pz_*.py`: **221 passed, 1 pre-existing failure** (`test_save_json_csv_ui_round_trip` — known, baseline).
- `tests/test_name_normalization_parity.py`: green (asserts against real frozen implementations — no stubs, Lesson A compliant).

## GATE 1 reviewer verdicts (pre-open)
- reviewer-challenge: **PASS** — real delegates, real-function parity tests, import-cycle guard present.
- backend-safety-reviewer: **PASS** — authority module is a pure leaf (`re`, `unicodedata`, `typing`); None-handling preserved; no unsafe writes.
- integration-boundary: **PASS** — 7→7 mapping 1:1; no orphan/shadow normalizers remain in tree.

## Lesson J (files outside service/app)
- `service/scripts/extract_name_corpus.py` — **dev-only corpus extraction script, NOT imported by `service/app`, NOT deployed.** No additional robocopy sync required.

## Risk / rollback
- Risk: pure-function refactor; residual risk is parity-table transcription. Monitor the first production customer-resolution run.
- Rollback: revert this squash commit; no schema change, no flag, no data migration.

## Merge-train position
B5 is **step 1 of 4** (B5 → B6 → Tracking → AWB). No conflict with origin/main at this step. Downstream `config.py` union-merge applies to B6/Tracking/AWB, not B5.
