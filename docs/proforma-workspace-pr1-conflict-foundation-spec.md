# PR-1 — Conflict-Detection Foundation: Technical Specification

**Author:** senior technical architect pass
**Date:** 2026-06-16
**Status:** SPEC — implementation-ready contract for PR-1
**Governs:** the first PR of the Proforma Workspace Consolidation initiative (`docs/proforma-workspace-consolidation-plan.md` §13 PR-1)
**Binding ADRs:** ADR-029 (orchestration shell), ADR-025 (soft validation), ADR-022/ADR-021 (cached-snapshot / detect-before-gate), ADR-026 (DHL label), ADR-028 (V2 tracks)
**Implementation tree:** `C:\PZ-verify` (clean session). Line numbers below were read from the working tree and MUST be re-confirmed against `origin/main` at implementation time.

---

## 1. Task summary

PR-1 builds the **conflict-detection foundation**: a new `proforma_conflicts` SQLite store, a set of **pure, read-only validator functions**, three additive HTTP routes (`scan`, `list`, `resolve`), and a flag-gated inbox source — all behind feature flags that default **OFF**. With flags off the system is byte-for-byte unchanged (zero blast radius). Conflicts are **advisory**: a conflict row records a *detected divergence* between a proforma draft and an authoritative source; it is not itself an authority, it never mutates the draft or any master, and resolution records an audited operator *decision* only. **Non-goals (explicitly out of scope):** no workspace frontend consolidation, no `workflow_stage` column, no reservation endpoint activation, no AWB/DHL work, no wFirma writes, no inventory mutations, no wiring of `conflict_posting_blocker` into the post path (that is PR-3), no schema change to `proforma_drafts`, no live external calls.

---

## 2. Files to inspect (reviewed for this spec)

| File | Role confirmed |
|---|---|
| `.claude/adr/ADR-021…ADR-029` | detect-before-gate invariant (no wFirma read before write gate); cached-snapshot-in-draft-row; soft validation; DHL label scaffold; orchestration-shell amendment |
| `docs/proforma-workspace-consolidation-plan.md` | PR sequencing, conflict-layer design, validator→authority table |
| `service/app/core/audit.py` | **master_audit authority.** `write_audit(...)`, `audit_safe(entity, op, pk, *, before, after, reason, request, ...) -> int` (returns `-1` disabled / `-2` failed, never corrupts primary write). `VALID_OPS` includes `create`/`update`/`transition`. Storage `settings.storage_root/"master_audit.sqlite"`; idempotent `init_audit_db()`; `BEGIN IMMEDIATE`; `settings.master_audit_enabled` gate |
| `service/app/services/wfirma_product_compare.py` | **validator template.** `compare_product_metadata(*, wfirma_product, local_expected, product_code) -> Dict` — pure, side-effect-free, severity ladder `minor`/`material`, `recommendation` enum; helpers `_normalise_text`, `_normalise_unit` |
| `service/app/api/routes_inbox.py` | **inbox surface.** `APIRouter(prefix="/api/v1/inbox")`, `_auth = Depends(require_api_key)`; 4 read-only sources; **graceful per-source degradation** (dead source → `{ok:false,error}`, never 500); item envelope `{id,type,priority,title,detail,age,actor,primary_action,linked_batch_id,actionable,endpoint}`; Source D reads `proforma_invoice_link_db.list_attention_drafts()` |
| `service/app/services/proforma_invoice_link_db.py` | **DB idiom.** `init_db(db_path)` (115), `CREATE TABLE IF NOT EXISTS` (121/464), additive `ALTER TABLE … ADD COLUMN {col} {ddl}` loop (534), `list_attention_drafts(...)` (1461), `get_draft_by_id`, `_commit_draft_update` (1808); `with sqlite3.connect(str(db_path))`; DB at `settings.storage_root/"proforma_links.db"` |
| `service/app/api/routes_proforma.py` | `APIRouter(prefix="/api/v1/proforma")` (55), `_auth = Depends(require_api_key)` (56); post gate `settings.wfirma_create_proforma_allowed` (6861) inside `post_proforma_draft_to_wfirma` (6828) — **PR-3 blocker wiring point, not touched in PR-1**; `export_blockers` projection (1803) |
| `service/app/services/proforma_draft_sync.py` | `_resolve_designs(...)` → `{designs_resolved, designs_ambiguous, designs_unresolved}` (57–168) — read projection for SKU-ambiguity validator |
| `service/app/main.py` | router registration idiom: `from .api.routes_X import router as X_router` (12–41) + `app.include_router(...)`; startup DB inits in lifespan |
| `.claude/memory/PROJECT_STATE.md` (FACTS) | deploy baselines PZ=221 / Carrier=412; reservation infra exists; OQ-NEW-14; AWB gaps; ADR-029 authored |
| existing blocking/conflict code | `routes_proforma` `blocking_reasons`/`export_blockers` (preview gate); `wfirma_product_compare` (product drift); `wfirma_customer_sync.plan_sync` (customer conflict count); `proforma_draft_sync` design_no ambiguity; `cache_freshness.is_audit_stale`. **No general `proforma_conflicts` store exists** — this PR creates it |

---

## 3. Files allowed to edit in PR-1 (exact paths — no others)

**New files:**
1. `service/app/services/proforma_conflict_db.py` — store + CRUD
2. `service/app/services/proforma_conflict_detector.py` — pure validators + orchestrator
3. `service/app/api/routes_proforma_conflicts.py` — 3 routes (own `APIRouter`)
4. `service/tests/test_proforma_conflict_db.py`
5. `service/tests/test_proforma_conflict_detector.py`
6. `service/tests/test_proforma_conflict_routes.py`
7. `service/tests/test_proforma_conflict_audit.py`
8. `service/tests/test_proforma_conflict_inbox_source.py`

**Modified files (additive only):**
9. `service/app/core/config.py` — add 4 flags (all default OFF) — additive fields only
10. `service/app/main.py` — 2 lines: import + `include_router` + 1 startup `init_conflicts_db()` call
11. `service/app/api/routes_inbox.py` — add flag-gated Source E (returns `[]` when flag off → identical behavior)

No file outside this list of 11 may be modified in PR-1.

---

## 4. Forbidden files and paths (PR-1 must never touch)

- **Frozen authorities:** `wfirma_client.py` (and any wFirma payload builder), `vat_resolver.py`, `dual_valuation.py`, PZ valuation engine (`pz_batch_schema.py`, engine root files), `customer_master_db.py` schema, product-master description engine.
- **Post/convert path:** `post_proforma_draft_to_wfirma` and any code under the `wfirma_create_*_allowed` gates (PR-3).
- **Reservation / AWB / DHL:** `routes_reservations.py`, `wfirma_reservation*.py`, `reservation_db.py`, `carrier/**`, `routes_carrier_actions.py`, `routes_dhl_*`.
- **Inventory writes:** `inventory_state_engine.py` (read-only consumption only; never call `transition()`).
- **Schema of existing tables:** no `ALTER TABLE proforma_drafts`, no new columns on any existing table.
- **Deploy / forbidden-paths (`.claude/contracts/forbidden-paths.md`):** `*.db`, `storage/*`, `outputs/*`, `logs/*`, `.env`, `cloudflared/*` — never committed; the new `proforma_conflicts.sqlite` is a runtime artifact, never checked in.
- **Frontend:** no `proforma-v2.html`, `pz-*.js`, `dashboard-shared.js`, `/v2/` edits (PR-4).
- `wfirma_capabilities.py` — flag exposure to the frontend is deferred to PR-4.

---

## 5. Authority map

| Data | Authority owner (writes) | PR-1 access |
|---|---|---|
| Inventory availability / state | `inventory_state_engine.py` (`count_by_state`, `PROFORMA_ELIGIBLE_STATES`) | **read projection only** |
| Product SKU/HS/origin/UOM/status | Product Master (`wfirma_products`, `product_descriptions`, `product_local`) | **read only** |
| Customer VAT-EU / address / terms / currency / service-charge defaults | `customer_master_db.py` (`customer_master.sqlite`) | **read only** |
| Bank-account ↔ currency map | `proforma_resolver.COMPANY_ACCOUNT_BY_CURRENCY` | **read constant** |
| VAT code resolution | `vat_resolver.pick_vat_code` (pure, local) | **read/re-run only** |
| Proforma draft | `proforma_invoice_link_db.py` | **read only** (no schema change, no edit) |
| wFirma documents | `wfirma_client.py` (gated) | **never touched** |
| **Conflict records** | **`proforma_conflict_db.py` (this PR)** | **the only thing PR-1 writes** (+ `master_audit` append) |

**Why the workspace is orchestration, not authority (ADR-029):** a `proforma_conflicts` row is a *read-derived advisory observation* of divergence between a draft and a source authority. It does not redefine any source's truth, does not write back to masters, and does not gate workflow by itself. Resolution records an operator *decision* (audited); applying that decision to the draft (e.g. adopting a master default) happens later through the existing draft-edit endpoints — never inside the conflict store. Authority records are **merged, never replaced**: detection appends; resolution updates only the status/resolution fields and never overwrites the immutable `evidence_json`.

---

## 6. Proposed schema — `proforma_conflicts`

Storage: `settings.storage_root / "proforma_conflicts.sqlite"` (separate file, mirrors `master_audit.sqlite`). Single table.

| Column | Type | Constraint | Rationale |
|---|---|---|---|
| `conflict_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | stable row id (mirrors `master_audit.id`) |
| `proforma_id` | INTEGER | NOT NULL, indexed | the draft id (`proforma_drafts.id`) the conflict belongs to |
| `batch_id` | TEXT | nullable | for inbox linking / cross-batch grouping |
| `conflict_type` | TEXT | NOT NULL | §8 enum |
| `severity` | TEXT | NOT NULL | §9 enum |
| `authority_owner` | TEXT | NOT NULL | §10 enum — which system owns the truth |
| `field_affected` | TEXT | nullable | e.g. `currency`, `vat_code`, `line[EJL/26-27/121].hs_code` |
| `current_value` | TEXT | nullable | draft-side value (string/JSON) |
| `master_value` | TEXT | nullable | authority-side value (string/JSON) |
| `reason` | TEXT | NOT NULL | human-readable explanation naming the authority owner |
| `evidence_json` | TEXT | nullable, **immutable after insert** | structured detector output; never deleted/overwritten |
| `detector_version` | TEXT | NOT NULL | reproducibility of the detection logic |
| `dedup_key` | TEXT | NOT NULL, indexed | `f"{proforma_id}:{conflict_type}:{field_affected}"` — code-level dedup of OPEN rows |
| `detected_at` | TEXT | NOT NULL | ISO-8601 UTC, server-set |
| `status` | TEXT | NOT NULL DEFAULT `'open'` | §9b lifecycle |
| `resolution_type` | TEXT | nullable | §9c enum |
| `resolution_reason` | TEXT | nullable | operator-supplied |
| `resolved_by` | TEXT | nullable | actor (from `audit.actor_from_request`) |
| `resolved_at` | TEXT | nullable | ISO-8601 UTC |

Indexes: `ix_conflicts_proforma_status (proforma_id, status)`, `ix_conflicts_status_severity (status, severity)`, `ix_conflicts_dedup (dedup_key)`. **No DB-level UNIQUE on `dedup_key`** — dedup is enforced in code against `status='open'` rows so that a resolved-then-recurring conflict creates a *new* row and the resolved one survives as immutable history (satisfies "never delete original evidence"). No NOT NULL beyond the columns above (rollback rule: a fresh additive table with its own NOT NULLs is safe; no ALTER on existing tables).

---

## 7. Migration strategy

- `proforma_conflict_db.init_conflicts_db(path: Optional[Path] = None) -> Path` — idempotent `CREATE TABLE IF NOT EXISTS` + indexes, mirroring `core/audit.py:init_audit_db()`. Resolves path at call time (`settings.storage_root / "proforma_conflicts.sqlite"`) to support tests that monkey-patch `storage_root`.
- Called (a) once at startup from `main.py` lifespan (next to existing `reservation_db.init_reservation_db()`), and (b) lazily at the top of every db function (defensive, like `init_audit_db`).
- **Per environment:** identical idempotent init runs automatically on service start in dev / staging / prod. No manual migration step, no `ALTER` on existing tables, no data backfill. First run creates an empty table; subsequent runs are no-ops.
- The `.sqlite` file is a runtime artifact under `storage_root` → covered by `.claude/contracts/forbidden-paths.md` (`*.db` / `storage/*` never committed or deployed).

---

## 8. Conflict type enum (`conflict_type`)

Defined as `CONFLICT_TYPES: frozenset[str]` in `proforma_conflict_detector.py`. Each maps to exactly one validator (§11) and one authority owner (§10).

| Value | Description | Default severity |
|---|---|---|
| `inventory_insufficient` | requested line qty exceeds proforma-eligible inventory count for the batch | error |
| `sku_missing_or_discontinued` | line `product_code` absent from product master, or `sync_status` ∈ {`not_found`,`error`} | error |
| `sku_ambiguous` | line `design_no` maps to >1 `product_code` (`proforma_draft_sync.designs_ambiguous`) | warning |
| `currency_vs_customer_default` | draft `currency` differs from `customer_master.default_currency` | warning |
| `bank_account_currency_unsupported` | draft `currency` not in `COMPANY_ACCOUNT_BY_CURRENCY` (PLN/USD/EUR) | error |
| `customer_vat_eu_changed` | re-running `vat_resolver.pick_vat_code` on current customer yields a code differing from the draft's frozen `vat_code`/`vat_context` | warning |
| `customer_address_or_terms_changed` | `customer_master` bill-to address or `payment_terms_days` differs from draft override snapshot | warning |
| `product_hs_origin_uom_changed` | master `hs_code`/`origin_country`/`unit` differs from the draft line value | warning |
| `service_charge_defaults_changed` | `customer_master` service-charge defaults differ from draft `service_charges_json` | warning |
| `evidence_unavailable` | a validator could not read required evidence (graceful-degradation marker) | info |

---

## 9. Severity enum, status lifecycle, resolution enum

**9a. `severity` (`SEVERITIES`)**

| Value | Decision rule |
|---|---|
| `error` | Posting this draft as-is would produce an incorrect or impossible wFirma document (wrong VAT, unsupported currency, overselling inventory). Eligible to block the wFirma write **only in PR-3** when `conflict_posting_blocker=true`. |
| `warning` | Drift the operator should acknowledge but may proceed past; never blocks. |
| `info` | Advisory or could-not-verify (graceful degradation). Never blocks, never an error. |

**9b. `status` (`CONFLICT_STATUSES`)** — `open` → (`acknowledged` \| `resolved` \| `reverted` \| `superseded`). `open` = newly detected, unaddressed. `acknowledged` = operator saw a warning and chose to proceed (logged). `resolved` = operator recorded a resolution decision. `reverted` = a prior resolution was undone. `superseded` = a fresh scan replaced this row's open instance (set only when code dedup re-opens; the superseded row is retained as history). Resolution **never** deletes a row.

**9c. `resolution_type` (`RESOLUTION_TYPES`)** — `use_master_default` \| `override_with_reason` \| `regenerate_lines` \| `accept_and_proceed` \| `revert`. **In PR-1 these record the operator decision + audit only; none of them mutates the draft or any master.** (Applying the decision to the draft is a later PR via existing draft-edit endpoints.)

---

## 10. Source authority enum (`authority_owner`)

| Value | Backing module (read) |
|---|---|
| `inventory` | `inventory_state_engine.py` |
| `product_master` | `wfirma_products` / `product_descriptions` / `product_local` |
| `customer_master` | `customer_master_db.py` |
| `finance_bank` | `proforma_resolver.COMPANY_ACCOUNT_BY_CURRENCY` |
| `vat_resolver` | `vat_resolver.pick_vat_code` |
| `proforma` | `proforma_invoice_link_db.py` (draft self-consistency) |

---

## 11. Validator function signatures (`proforma_conflict_detector.py`)

All validators are **pure and read-only**, mirror `wfirma_product_compare.compare_product_metadata`, and **never raise** — on missing/unreadable evidence they return either `[]` or a single `evidence_unavailable` finding (`severity="info"`). No validator performs any network/wFirma/DHL call.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

DETECTOR_VERSION = "pr1.1"

@dataclass(frozen=True)
class ConflictFinding:
    conflict_type:   str            # ∈ CONFLICT_TYPES
    severity:        str            # ∈ SEVERITIES
    authority_owner: str            # ∈ SOURCE_AUTHORITIES
    field_affected:  Optional[str]
    current_value:   Optional[str]
    master_value:    Optional[str]
    reason:          str
    evidence:        dict           # persisted to evidence_json; immutable

# ── individual validators (each: pure, read-only, never raises) ──────────────
def check_inventory_sufficiency(*, draft: dict, batch_id: str) -> list[ConflictFinding]: ...
def check_sku_status(*, draft: dict, batch_id: str) -> list[ConflictFinding]: ...
def check_sku_ambiguity(*, draft: dict, batch_id: str) -> list[ConflictFinding]: ...
def check_currency_vs_customer_default(*, draft: dict, customer: Optional[dict]) -> list[ConflictFinding]: ...
def check_bank_account_supports_currency(*, draft: dict) -> list[ConflictFinding]: ...
def check_customer_vat_drift(*, draft: dict, customer: Optional[dict]) -> list[ConflictFinding]: ...
def check_customer_address_terms_drift(*, draft: dict, customer: Optional[dict]) -> list[ConflictFinding]: ...
def check_product_master_drift(*, draft: dict, batch_id: str) -> list[ConflictFinding]: ...
def check_service_charge_defaults_drift(*, draft: dict, customer: Optional[dict]) -> list[ConflictFinding]: ...

VALIDATORS: tuple = (  # registry the orchestrator iterates
    check_inventory_sufficiency, check_sku_status, check_sku_ambiguity,
    check_currency_vs_customer_default, check_bank_account_supports_currency,
    check_customer_vat_drift, check_customer_address_terms_drift,
    check_product_master_drift, check_service_charge_defaults_drift,
)

# ── orchestrator ─────────────────────────────────────────────────────────────
def scan_draft_conflicts(*, draft_id: int, db_path: Optional[Path] = None) -> dict:
    """Load draft (pildb.get_draft_by_id) + customer + batch read-projections,
    run every validator wrapped in try/except (one validator raising is caught
    and recorded under `skipped`, never failing the scan), and return:

        {"ok": True, "draft_id": <int>, "detector_version": DETECTOR_VERSION,
         "findings": [ConflictFinding-as-dict, ...],
         "skipped":  [{"validator": <name>, "error": <str>}, ...]}

    If the draft itself is missing → {"ok": False, "error": "draft_not_found",
    "draft_id": <int>}. Never raises to the caller."""
```

**Error modes:** validators return `[]`/`info` on missing evidence; the orchestrator catches any unexpected exception per-validator into `skipped[]` (graceful degradation, mirroring `routes_inbox` per-source isolation). The only non-200 condition is `draft_not_found`.

---

## 12. Route contracts (`routes_proforma_conflicts.py`)

`router = APIRouter(prefix="/api/v1/proforma", tags=["proforma-conflicts"])`; `_auth = Depends(require_api_key)` (from `..core.security`). All three routes carry `dependencies=[_auth]`.

### 12.1 `POST /api/v1/proforma/draft/{draft_id}/conflicts/scan`
- **Calls:** `proforma_conflict_detector.scan_draft_conflicts(draft_id=…)` → `proforma_conflict_db.upsert_open_conflicts(draft_id, findings)`.
- **Request body:** none.
- **Flag behavior:** if `settings.conflict_detection_enabled` is False → no-op: `200 {"enabled": false, "conflicts": []}` (nothing written).
- **Response 200 (enabled):** `{"enabled": true, "draft_id": int, "detector_version": str, "conflicts": [<conflict row>...], "skipped": [...]}`.
- **Status codes:** `200` ok / no-op; `404 {"error":"draft_not_found"}`; `401/403` auth.

### 12.2 `GET /api/v1/proforma/draft/{draft_id}/conflicts`
- **Calls:** `proforma_conflict_db.list_conflicts(draft_id, status=…)`.
- **Query:** `status` optional (`open`/`acknowledged`/`resolved`/`reverted`/`superseded`); `severity` optional.
- **Response 200:** `{"draft_id": int, "conflicts": [<conflict row>...]}` (empty list if none or table absent — never 500).
- **Status codes:** `200`; `401/403`.

### 12.3 `POST /api/v1/proforma/draft/{draft_id}/conflicts/{conflict_id}/resolve`
- **Calls:** `proforma_conflict_db.resolve_conflict(conflict_id, resolution_type, resolution_reason, resolved_by)` then `core.audit.audit_safe(entity="proforma_conflicts", op="transition", pk=conflict_id, before=…, after=…, request=request, reason=resolution_reason)`.
- **Request body:** `{"resolution_type": <RESOLUTION_TYPES>, "resolution_reason": <str, required for override_with_reason>}`. `resolved_by` resolved from `X-Operator`/`audit.actor_from_request(request)`.
- **Response 200:** `{"conflict": <updated row>}`.
- **Status codes:** `200`; `404` unknown conflict_id / mismatched draft_id; `409 {"error":"already_resolved"}` if status already terminal; `422` invalid `resolution_type` or missing required reason; `401/403` auth.
- **Guarantee:** updates only status/resolution columns; `evidence_json` untouched; the draft and all masters untouched.

### 12.4 Inbox Source E (`routes_inbox.py`, additive, flag-gated)
- New private `_collect_conflict_items()` reads `proforma_conflict_db.list_open_conflicts(limit=…)` and maps to the existing inbox envelope (`type:"conflict"`, `priority` from severity, `endpoint:None`). Added to the aggregator **only when `settings.conflict_detection_enabled`**; wrapped in the same per-source try/except so a dead source returns `{ok:false,error}` and never 500s. Flag off → function not invoked → inbox output byte-identical to today.

---

## 13. Feature flags and default-OFF behavior

Added to `service/app/core/config.py` as `Settings` fields (env var = UPPERCASE). **All default OFF/inert.** Not surfaced to the frontend in PR-1 (`wfirma_capabilities.py` untouched; exposure is PR-4).

| Flag | Default | Gates |
|---|---|---|
| `conflict_detection_enabled` | `False` | whether `scan` writes/returns conflicts and whether inbox Source E appears. Off → scan is a no-op, list returns `[]`, inbox unchanged |
| `conflict_ui_mode` | `"panel"` | UI rendering hint only (consumed in PR-4); inert in PR-1 |
| `conflict_resolution_auto_use_defaults` | `False` | reserved; PR-1 never auto-applies defaults regardless |
| `conflict_posting_blocker` | `False` | **defined only.** PR-1 does NOT read it in any code path. Enforcement at the wFirma write boundary (`post_proforma_draft_to_wfirma`) lands in **PR-3**, behind this flag |

**Default-OFF proof:** with the four defaults above, `scan` returns `{"enabled": false, "conflicts": []}` and writes nothing; `list` returns `[]`; inbox Source E is never collected; the post path is unmodified. The only always-on effect is the empty-table creation at startup, which has no behavioral surface.

---

## 14. Idempotency rules

- **Scan is idempotent per `dedup_key`.** `upsert_open_conflicts(draft_id, findings)` computes `dedup_key = f"{proforma_id}:{conflict_type}:{field_affected}"` for each finding and, inside one `BEGIN IMMEDIATE` transaction: (a) selects existing `status='open'` rows for the draft; (b) for a finding whose `dedup_key` matches an open row → **update** `detected_at` + `evidence_json` + values in place (no duplicate, no new audit row); (c) for a new `dedup_key` → **insert** a new open row; (d) for an open row with no matching finding this scan → set `status='superseded'` (the divergence is gone) — the row is retained as history, never deleted. Re-running scan N times with unchanged inputs converges to the same open-row set.
- **Resolve is idempotent by terminal status.** `resolve_conflict` is a no-op-then-409 if the row is already `resolved`/`reverted` (mirrors the proforma post `409`-on-terminal pattern). A repeated identical resolve does not write a second audit row.
- **Interrupted processing reconciliation.** Each scan/resolve is a single SQLite `BEGIN IMMEDIATE` transaction → atomic; a crash mid-scan leaves either the prior state or the fully-applied new state, never partial. Because conflicts are re-derivable read projections, the recovery action is simply "re-run scan" — it reconciles to truth from current source data. The audit write happens **after** the DB commit (per `audit_safe` contract); if the process dies between commit and audit, the conflict state is correct and the missing audit line is detectable (conflict row exists with no corresponding `master_audit` create) — re-scan does not duplicate it.

---

## 15. Audit and event strategy

Uses the existing **`master_audit`** authority (`core/audit.py`) — no new audit system.

| Event | When | Call (after primary DB commit) | Fields |
|---|---|---|---|
| conflict detected | new open row inserted by scan | `audit_safe(entity="proforma_conflicts", op="create", pk=conflict_id, after=<row>, request=request, reason=f"detected:{conflict_type}")` | entity, pk=conflict_id, op, actor, after_json=full row, reason, created_at |
| conflict resolved | `resolve` succeeds | `audit_safe(entity="proforma_conflicts", op="transition", pk=conflict_id, before=<old row>, after=<new row>, request=request, reason=resolution_reason)` | before_json/after_json/diff_json (status+resolution_* change), actor=resolved_by, reason |
| conflict superseded | scan supersedes a stale open row | `audit_safe(... op="transition", before=<old>, after=<superseded row>, reason="superseded_by_rescan")` | diff shows status open→superseded |

**Ordering (strict):** (1) write/commit the `proforma_conflicts` row inside its transaction; (2) THEN call `audit_safe(...)`. `audit_safe` returns `-2` on failure and is caught internally — the route MUST NOT propagate `-2`; the conflict operation's HTTP response is returned regardless (the master_audit `audit_safe` contract). Re-detection of an already-open conflict emits **no** audit row (idempotent). `master_audit_enabled` (default True) governs whether rows persist.

---

## 16. No-write guarantees

PR-1 writes to **exactly two** persistence targets: the new `proforma_conflicts.sqlite` table, and append-only rows in `master_audit.sqlite` (via `audit_safe`). PR-1 performs **no** writes to, and **no** live calls against, any of:

- wFirma — no `wfirma_client._http_request`, no `create_proforma_draft`, no convert, no product/customer/PZ create. (Validators read **local cached** product/customer rows only; `compare_product_metadata` is fed a cached row or `None`, never a live fetch.)
- DHL / carrier — no `carrier/**`, no label, no AWB, no `dispatch_record`.
- Inventory — no `inventory_state_engine.transition()`, no reservation table writes, no stock mutation. (Read `count_by_state` only.)
- Masters — no write to `customer_master`, `wfirma_products`, `product_descriptions`, `product_local`.
- Proforma drafts — no `_commit_draft_update`, no line/header edit, **no schema change**.

A regression test (`test_scan_no_live_external_calls`) asserts zero `httpx`/socket activity during a scan.

---

## 17. Test plan (exact files and test names)

**`service/tests/test_proforma_conflict_db.py`**
- `test_init_conflicts_db_idempotent`
- `test_upsert_open_inserts_new_finding`
- `test_upsert_open_dedups_same_key_no_duplicate`
- `test_upsert_supersedes_stale_open_row_not_deleted`
- `test_resolve_sets_status_and_preserves_evidence_json`
- `test_resolve_never_deletes_row`
- `test_reopen_after_resolve_creates_new_row_history_kept`
- `test_list_conflicts_filters_by_status_and_severity`

**`service/tests/test_proforma_conflict_detector.py`** (one+ per validator, with negative + graceful)
- `test_inventory_insufficient_flags_error`
- `test_inventory_sufficient_no_finding`
- `test_sku_missing_flags_error`
- `test_sku_discontinued_syncstatus_flags_error`
- `test_sku_ambiguous_design_no_flags_warning`
- `test_currency_default_mismatch_warns`
- `test_currency_matches_default_no_finding`
- `test_bank_account_unsupported_currency_errors`
- `test_bank_account_supported_currency_no_finding`
- `test_customer_vat_eu_drift_flags_warning`
- `test_customer_vat_no_drift_no_finding`
- `test_customer_address_terms_drift_warns`
- `test_product_hs_origin_uom_drift_warns`
- `test_service_charge_defaults_drift_warns`
- `test_missing_customer_degrades_to_info_not_raise`
- `test_missing_snapshot_returns_evidence_unavailable_info`
- `test_one_validator_exception_recorded_in_skipped_scan_still_ok`
- `test_scan_draft_not_found_returns_ok_false`

**`service/tests/test_proforma_conflict_routes.py`**
- `test_scan_flag_off_is_noop_returns_enabled_false`
- `test_scan_flag_on_returns_and_persists_conflicts`
- `test_scan_unknown_draft_404`
- `test_get_conflicts_filters_status`
- `test_get_conflicts_empty_when_table_absent_no_500`
- `test_resolve_updates_status_returns_conflict`
- `test_resolve_unknown_conflict_404`
- `test_resolve_already_resolved_409`
- `test_resolve_invalid_resolution_type_422`
- `test_resolve_override_without_reason_422`
- `test_all_routes_require_api_key_401`
- `test_scan_no_live_external_calls`

**`service/tests/test_proforma_conflict_audit.py`**
- `test_detect_writes_master_audit_create_row`
- `test_resolve_writes_master_audit_transition_row`
- `test_redetect_open_conflict_emits_no_new_audit`
- `test_audit_failure_returns_minus2_does_not_break_resolve`

**`service/tests/test_proforma_conflict_inbox_source.py`**
- `test_inbox_source_e_absent_when_flag_off`
- `test_inbox_source_e_lists_open_conflicts_when_flag_on`
- `test_inbox_degrades_gracefully_if_conflict_source_raises`

**Regression (must stay green, flags off → no behavior change):** `tests/test_pz_*.py` (221), `tests/test_carrier_*.py` (412), `tests/test_proforma_*.py`, `tests/test_customer_master*.py`, `tests/test_vat_resolver.py`, `tests/test_inventory_*.py`. Run per `.claude/contracts/test-baseline.md`.

---

## 18. Rollback plan

1. **First lever (no deploy):** set `CONFLICT_DETECTION_ENABLED=false` (already the default) → scan no-ops, inbox Source E disappears, list returns `[]`. System behaves as pre-PR-1.
2. **Code rollback:** revert the PR commit. The three new service/route files and five test files are deleted; the additive lines in `config.py`, `main.py`, `routes_inbox.py` are removed. No other file changed, so revert is clean.
3. **Data:** the `proforma_conflicts.sqlite` runtime file may remain on disk harmlessly (nothing reads it once the code is gone); it is never committed and may be deleted manually. No `proforma_drafts`/master schema was altered, so there is nothing to un-migrate. No `*.db` was deployed.
4. **Verification after rollback:** PZ 221 / Carrier 412 green; `GET /api/v1/inbox` returns the original four sources; no `proforma_conflicts` route resolves (404). No restart-order dependency.

---

## 19. Deploy plan

PR-1 follows the standard 7-agent deploy gate (`/deploy`) in a clean `C:\PZ-verify` session, GATE-2 queue ≤ 2 first.

1. Merge to `main` after the 7-agent gate passes (PZ 221 / Carrier 412 + new suites green; forbidden-files check confirms only the 11 allowed paths changed).
2. Robocopy `service/app → C:\PZ\app` (standard scope; no engine-root files in this PR per Lesson J). No `*.db` in scope.
3. On service restart, `init_conflicts_db()` runs in lifespan → empty table created. (Idempotent; safe on every restart.)
4. **Validate flags OFF in production:** confirm `CONFLICT_DETECTION_ENABLED`, `CONFLICT_POSTING_BLOCKER`, `CONFLICT_RESOLUTION_AUTO_USE_DEFAULTS` are unset/false in `C:\PZ\.env`; `GET /api/v1/proforma/draft/{id}/conflicts` returns `{"conflicts": []}`; `POST …/scan` returns `{"enabled": false}`; `GET /api/v1/inbox` shows the original four sources unchanged.
5. **Monitoring:** after enabling `conflict_detection_enabled=true` in **staging only**, watch for (a) scan latency, (b) `skipped[]` validator errors (graceful-degradation signal), (c) false-positive rate per `conflict_type` in `master_audit` (`entity="proforma_conflicts"`). Production stays flags-off until staging observation is clean. `conflict_posting_blocker` remains off everywhere (its enforcement code does not exist until PR-3).

---

## 20. Acceptance checklist

- [ ] Only the 11 files in §3 are modified (forbidden-files check passes).
- [ ] All four flags exist in `config.py` and default OFF; `scan` no-ops and `list` returns `[]` with defaults.
- [ ] `init_conflicts_db()` is idempotent and wired into startup; table + indexes created.
- [ ] Each of the nine validators is pure, returns structured findings, and never raises (unit-tested incl. missing-evidence → `info`).
- [ ] Orchestrator isolates a raising validator into `skipped[]`; scan still returns `ok:true`.
- [ ] Three routes behave per §12 status codes; all require `require_api_key`.
- [ ] Scan is idempotent (no duplicate open rows across repeated runs); supersede retains history.
- [ ] Resolve updates only status/resolution columns; `evidence_json` immutable; draft + masters untouched.
- [ ] `master_audit` rows written on detect (`create`) and resolve (`transition`); audit failure (`-2`) never breaks the operation.
- [ ] No live wFirma/DHL/inventory calls during scan (`test_scan_no_live_external_calls` passes).
- [ ] `conflict_posting_blocker` is defined but read by **no** PR-1 code path (grep proof); post path unmodified.
- [ ] Inbox Source E hidden when flag off (inbox output byte-identical); graceful when conflict source dead.
- [ ] PZ 221 / Carrier 412 + all new suites green.
- [ ] Rollback = flag off (zero-deploy) and clean commit revert; verified.

---

## 21. Open questions

No blocking open questions for implementation. Two design decisions are made and recorded here (not blocking, listed for operator visibility):

1. **Conflict store lives in its own `proforma_conflicts.sqlite`** (mirrors `master_audit.sqlite`) rather than co-located in `proforma_links.db`. Chosen for clean rollback and audit-locality parity; revisit only if cross-table joins with drafts become hot.
2. **`resolve` records the decision but does not apply it** to the draft in PR-1 (authority-clean; application happens through existing draft-edit endpoints in a later PR). If the operator wants one-click "apply master default" in PR-1, that becomes a scoped addition to PR-2 — it is intentionally excluded here to preserve zero-blast.
