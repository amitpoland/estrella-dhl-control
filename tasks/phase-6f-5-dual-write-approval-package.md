# Phase 6F.5 — Dual-Write Approval Package

> **Status:** awaiting operator approval. DO NOT IMPLEMENT until operator signs §13.
> **Predecessor:** 6F.4 deployed (PR #118, merge `acc92dc`).
> **Generated:** 2026-05-16.

This document is a design contract. It defines exactly what 6F.5 will and
will not do. Implementation begins ONLY after the operator signs the
approval block in §13. Everything outside the boundary defined here is
out of scope for 6F.5 and would require a separate batch + approval.

---

## 1 — Exact write boundary

| Property | Value |
|---|---|
| Trigger event | Successful local commit of a proforma post (after `pildb.mark_post_succeeded` returns inside `routes_proforma.py::post_proforma_draft_to_wfirma`) |
| Existing legacy write | `proforma_service_charges_db.upsert_charge` (called by editor UPSERT endpoints, not by /post) — **DO NOT TOUCH** |
| New write target file | `<storage_root>/finance_postings.sqlite` |
| New write target tables | `postings` (1 synthetic row per `(batch_id, client_name)`), `charges` (1 row per non-zero charge tuple) |
| New write connection | A fresh `sqlite3.connect()` against the finance DB file — never shared with the proforma transaction |
| Failure isolation | Any exception in the dual-write block is logged at WARNING and swallowed; the legacy commit's response payload is unaffected |

### What the dual-write does NOT touch

- Does NOT modify `proforma_service_charges` (the legacy table).
- Does NOT modify `proforma_links.db` at all.
- Does NOT touch `wfirma.db`, `documents.db`, `warehouse.db`, or any other DB file.
- Does NOT alter the /post route's HTTP response body or status code.
- Does NOT trigger any wFirma API call.
- Does NOT compute FX, settle, allocate payments, or close anything.
- Does NOT touch the PZ landed-cost calculation path. Hard rule **MDC-071** remains in effect.

---

## 2 — Feature flag

| Flag | Type | Default | Behaviour |
|---|---|---|---|
| `FINANCE_DUAL_WRITE_ENABLED` | env var (`bool`, parsed via Pydantic Settings) | **`false`** | When `false`, the dual-write hook is a no-op. The function does not open the finance DB, does not compute payloads, and does not log anything. |
| `FINANCE_DUAL_WRITE_SHADOW` | env var (`bool`, parsed via Pydantic Settings) | **`false`** | When `true` AND `FINANCE_DUAL_WRITE_ENABLED=true`, the dual-write computes the full payload + sha1 keys and logs at INFO `finance_dual_write_shadow batch_id=... client=... charge_type=... amount_minor=... sha1=...` — but does NOT persist. When `false`, the dual-write persists. |

### Default OFF behaviour (explicit)

On a fresh install without explicit env vars set, `FINANCE_DUAL_WRITE_ENABLED=false`. The hook becomes a single early-return guard:

```python
if not settings.finance_dual_write_enabled:
    return  # 6F.5 default OFF
```

No finance DB file is created. No log line is emitted. No measurable behaviour change vs production today.

### Enabling sequence

1. Operator sets `FINANCE_DUAL_WRITE_ENABLED=true` AND `FINANCE_DUAL_WRITE_SHADOW=true` → shadow logs accumulate for 1 week of real /post events.
2. Operator inspects logs + 6F.4 Diagnostics panel → confirms shadow payloads match expectations.
3. Operator flips `FINANCE_DUAL_WRITE_SHADOW=false` → real dual-writes begin.
4. After 1 week of clean dual-writes, 6F.6 (settlement-close + FX delta) and 6F.7 (legacy deprecation) become eligible.

---

## 3 — Source event that triggers dual-write

**Single trigger.** The hook fires from exactly one location:

```
service/app/api/routes_proforma.py
  └─ post_proforma_draft_to_wfirma(...)
      └─ ... legacy logic ...
      └─ pildb.mark_post_succeeded(...)            ← legacy commit succeeds
      └─ # ──────── 6F.5 dual-write hook ────────
          if settings.finance_dual_write_enabled:
              _finance_dual_write(draft, post_result, shadow=settings.finance_dual_write_shadow)
      └─ audit.append(...)
      └─ return 200 response
```

Critical sequencing:

- Hook fires AFTER `mark_post_succeeded`, never before.
- If `mark_post_succeeded` raised, the hook never runs.
- The hook is the LAST thing before the audit append; the response was already shaped.
- No other route calls the hook. Editor UPSERT (`set_service_charges`, `delete_service_charge`) does NOT trigger dual-write — those edit the legacy table only.

---

## 4 — Target table(s) and column mapping

### `postings` (synthetic, 1 row per posted-proforma tuple)

| Column | Value source |
|---|---|
| `id` | autoincrement |
| `wfirma_invoice_id` | `f"LIVE-{sha1('live_psc_posting:' + batch_id + ':' + client_name).hexdigest()[:16]}"` |
| `wfirma_doc_number` | `post_result.full_number` |
| `posting_kind` | literal `"proforma"` |
| `posted_at` | `_now_utc()` (local DB write time, ISO-8601) |
| `issued_total_minor` | `Σ` of all charge `amount_minor` for this tuple |
| `currency` | `draft.currency` (must be ISO-4217 and uniform within tuple) |
| `created_at` | `_now_utc()` |

### `charges` (one row per non-zero `(batch_id, client_name, charge_type)` tuple)

| Column | Value source |
|---|---|
| `id` | autoincrement |
| `posting_id` | `<synthetic_posting.id>` |
| `batch_id` | from `draft.service_charges_json[i].batch_id` |
| `client_name` | from `draft.service_charges_json[i].client_name` |
| `charge_type` | `freight` or `insurance` (other types are SKIPPED with WARNING) |
| `amount_minor` | `int((Decimal(str(amount)) * 100).quantize(Decimal('1'), rounding='ROUND_HALF_EVEN'))` — **NEVER** `int(amount * 100)` |
| `currency` | from `draft.service_charges_json[i].currency`, must be ISO-4217 |
| `source` | literal `"operator"` (distinguishes from `"legacy_backfill"` written by 6F.2.a) |
| `notes` | `f"[live:sha1={idempotency_sha1}]\n{original_note or ''}"` |
| `created_at` | `_now_utc()` |

---

## 5 — Idempotency key

### Charges

```
idempotency_sha1 = sha1(
    f"live_psc:{batch_id}:{client_name}:{charge_type}"
).hexdigest()

charges.notes = f"[live:sha1={idempotency_sha1}]\n{original_note or ''}"
```

Detection on re-run (e.g. if /post is retried with the same draft):

```sql
SELECT id FROM charges WHERE notes LIKE '[live:sha1=' || ? || ']%'
```

If a row already exists, the dual-write SKIPS that charge (does not insert duplicate). This must be a read-only probe before insert.

### Postings

```
synthetic_posting_id = f"LIVE-{sha1('live_psc_posting:' + batch_id + ':' + client_name).hexdigest()[:16]}"

postings.wfirma_invoice_id = synthetic_posting_id
```

Detection on re-run:

```sql
SELECT id FROM postings WHERE wfirma_invoice_id = ?
```

### Namespace separation from 6F.2.a backfill

| Origin | `postings.wfirma_invoice_id` prefix | `charges.notes` prefix | `charges.source` |
|---|---|---|---|
| 6F.2.a backfill | `BACKFILL-` | `[backfill:sha1=...]` | `legacy_backfill` |
| 6F.5 dual-write | `LIVE-` | `[live:sha1=...]` | `operator` |
| Real wFirma path (future) | actual numeric wFirma invoice id | (no prefix) | (other) |

All three namespaces are sha1-disjoint and prefix-disjoint. They cannot collide.

---

## 6 — Rollback plan

### Path A — Surgical delete

```sql
-- finance_postings.sqlite
DELETE FROM charges  WHERE notes LIKE '[live:sha1=%';
DELETE FROM postings WHERE wfirma_invoice_id LIKE 'LIVE-%';
```

These predicates target ONLY 6F.5 dual-write rows. The 6F.2.a backfill rows (`[backfill:sha1=...]` / `BACKFILL-...`) are left untouched. The real-wFirma rows (future) are left untouched.

### Path B — Disable flag

```
# .env (or NSSM env)
FINANCE_DUAL_WRITE_ENABLED=false
```

Then restart PZService. No new dual-writes occur. Existing rows remain for diagnostics (visible via 6F.4 panel) but are inert. Combine with Path A if a full purge is needed.

### Path C — Snapshot restore

Take a snapshot of `<storage_root>/finance_postings.sqlite` BEFORE flipping the live flag (operator runbook). Restore via `shutil.copy2` if Path A returns unexpected counts.

### What rollback never does

- Never modifies `proforma_links.db` or `proforma_service_charges` — those were never touched.
- Never modifies wFirma state — no wFirma write ever occurred.
- Never deletes 6F.2.a backfill rows — different sha1 namespace.

---

## 7 — Dry-run / shadow mode design

`FINANCE_DUAL_WRITE_ENABLED=true` + `FINANCE_DUAL_WRITE_SHADOW=true`:

- Hook computes the full payload exactly as if persisting.
- Hook computes `idempotency_sha1` and `synthetic_posting_id`.
- Hook checks `find_existing_charge(idempotency_sha1)` against the live finance DB to compute "would-be-skip" status.
- Hook logs at INFO:
  ```
  finance_dual_write_shadow batch_id=<b> client=<c> charge_type=<t>
    amount_minor=<n> currency=<ccy> sha1=<hex> would_skip=<bool>
    target_posting_id=<LIVE-...> draft_id=<d>
  ```
- Hook does NOT call `create_charge` or `create_posting`.
- No row appears in `charges` or `postings`.
- Operator reads logs via `Get-Content C:\PZ\logs\pz_stderr.log -Tail 200` (or via 6F.4 panel's `schema_version` chip to confirm DB is still empty).

Operator graduates from shadow to live ONLY after:

1. ≥ 50 shadow log entries observed across ≥ 5 distinct posting events.
2. Manual spot-check of ≥ 3 entries: amount_minor matches `Decimal(amount) * 100`, idempotency_sha1 is stable across two consecutive shadow runs of the same draft.
3. No `finance_dual_write_failed` log lines.

---

## 8 — Tests required (mandatory before PR)

### Unit tests

- `test_finance_dual_write_default_off.py`
  - flag unset → hook returns immediately, finance DB file does not get created.
  - flag set true, shadow true → no row written, INFO log emitted.
  - flag set true, shadow false → row written, idempotency key correct.

- `test_finance_dual_write_idempotent_rerun.py`
  - run /post twice with the same draft → only one `charges` row, one `postings` row.

- `test_finance_dual_write_decimal_safety.py`
  - amount `3.49` → `amount_minor == 349` (no `int(3.49 * 100) == 348` bug).
  - amount `0.025` → quantized to `2` via ROUND_HALF_EVEN, not `3`.

- `test_finance_dual_write_legacy_isolation.py`
  - dual-write runs → `proforma_service_charges` table has **zero** mutations.
  - assert via "before" `SELECT *` matches "after" `SELECT *` byte-for-byte.

- `test_finance_dual_write_error_swallow.py`
  - monkeypatch `create_charge` to raise → /post still returns 200, WARNING logged, legacy commit succeeded.

- `test_finance_dual_write_no_collision_with_backfill.py`
  - insert a backfill row with `[backfill:sha1=X]` and a live row with `[live:sha1=Y]` for the same tuple → both coexist without UNIQUE-constraint violation; `charges.source` values differ.

### Contract / source-grep tests

- `test_dual_write_source_grep.py`
  - assert hook fires AFTER `mark_post_succeeded` (regex order check inside `routes_proforma.py`).
  - assert there is NO `try/except` around `mark_post_succeeded` that swallows; the dual-write try/except is separate and downstream.
  - assert no new imports of `proforma_service_charges_db` from the dual-write helper.
  - assert no `int(.*\* *100)` pattern in the new helper (pin Decimal usage).
  - assert no calls to wFirma client / FX / settlement modules from the new helper.
  - assert flag check (`finance_dual_write_enabled`) appears textually BEFORE any `create_charge` or `create_posting` call in the new helper.

### Regression

- `python test_pz_regression.py` → must be 160/160 unchanged.
- `pytest tests/test_master_data_hard_rules.py tests/test_runner_v2_hard_rules.py tests/test_finance_postings_contracts.py` → all green.
- `pytest tests/test_finance_panel_contracts.py` → still 12/12 (panel is unaffected; this is a defense-in-depth check).

---

## 9 — Browser / API smoke required (post-deploy)

After 6F.5 deploys, perform these checks WITH `FINANCE_DUAL_WRITE_ENABLED=false` (the default):

1. POST a proforma draft via the normal /post flow → confirm 200 response unchanged.
2. `GET /api/v1/finance/postings/9999999/breakdown` → still HTTP 404 clean.
3. `stat C:\PZ\storage\finance_postings.sqlite` → byte-count unchanged (file exists but no new rows).
4. Tail `pz_stderr.log` for `finance_dual_write` substring → 0 hits.

Then flip `FINANCE_DUAL_WRITE_ENABLED=true` + `FINANCE_DUAL_WRITE_SHADOW=true`, restart, and:

5. POST a draft → confirm `finance_dual_write_shadow` INFO log appears.
6. `stat finance_postings.sqlite` → byte-count UNCHANGED (shadow mode does not write).

Then flip `FINANCE_DUAL_WRITE_SHADOW=false`, restart, and:

7. POST a draft → confirm:
   - 6F.4 Diagnostics panel: enter the new posting id → breakdown returns 200 with the charges array populated.
   - `charges.source` column for the new row = `"operator"`.
   - `postings.wfirma_invoice_id` starts with `LIVE-`.

---

## 10 — Exact hard stops

Implementation MUST stop and escalate if any of these become true:

| Stop | Condition |
|---|---|
| H1 | The implementer would need to modify `proforma_service_charges_db.py` |
| H2 | The implementer would need to modify any file under `service/app/services/wfirma*` |
| H3 | The implementer would need to modify FX, settlement, or landed-cost logic (`landed_cost.py`, `fx_*`, `golden_constants.py`) |
| H4 | The implementer would need to add a write route (`POST`/`PUT`/`PATCH`/`DELETE`) under `/api/v1/finance/` — only the existing GET breakdown is allowed |
| H5 | The implementer would need to share a DB connection or transaction between `proforma_links.db` and `finance_postings.sqlite` |
| H6 | The implementer would need to change the /post route's HTTP response body or status code |
| H7 | The dual-write would need to fire BEFORE `mark_post_succeeded` |
| H8 | A test mock would need to stub `create_charge` to "fake success" — real-builder regression test (Lesson A) is mandatory |
| H9 | The implementer would need to remove or relax the existing /post block on non-empty `service_charges_json` (line ~3538). That removal is **out of scope** — it belongs in a separate batch with its own approval. |
| H10 | The implementer would need to flip the default of `FINANCE_DUAL_WRITE_ENABLED` from `false` to `true` for any environment |
| H11 | The implementer would need to write the live flag via the API (config endpoints) instead of via env / NSSM |
| H12 | The implementer would need to add a UI button labelled "post charge" / "create charge" / "trigger dual-write" / "post payment" |
| H13 | The implementer would need to call any backfill function from the runtime path |

---

## 11 — Why this does NOT mutate existing ledger/posting behaviour

The dual-write is **strictly additive**. Specifically:

1. **The legacy posting path is unchanged.** `mark_post_succeeded`, the wFirma call sequence, the audit record, and the /post response are all bit-identical to today's behaviour. The dual-write attaches AFTER all of them.
2. **The legacy table `proforma_service_charges` is read-only from the dual-write perspective.** The dual-write helper does not `INSERT`, `UPDATE`, or `DELETE` against it. A source-grep contract test enforces this mechanically (Lesson A pattern).
3. **The ledger of record remains wFirma.** The new `postings` rows are LOCAL diagnostic synthetics with `wfirma_invoice_id LIKE 'LIVE-%'`, which the wFirma path will never produce. They cannot be mistaken for real wFirma invoices.
4. **No FX conversion, no settlement-close, no payment-allocation runs.** Those are deferred to 6F.6.
5. **No customer-facing UI changes.** The 6F.4 panel is read-only and was already shipped. The /post flow looks identical to operators.
6. **Default OFF.** Without explicit operator intervention via env var, the hook never executes. Production behaviour on day-of-deploy is unchanged.
7. **Failure-isolated.** Any dual-write error is swallowed (logged at WARNING). The legacy commit's success path never reverses.

Reference precedents: 6F.1 (schema additive only), 6F.1.5 (dormancy contracts), 6F.3 (read-only endpoint, lazy init_db), 6F.4 (read-only panel, no auto-fetch). 6F.5 follows the same additive philosophy, with the additional constraint that it is the FIRST write-bearing batch in Phase 6F.

---

## 12 — Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | `service_charges_json` on /post is currently a HARD BLOCK (raises `ValueError`) — dual-write fires only for charge-free drafts today | Medium | Explicit INFO log when /post commits with empty charges; test plan covers both empty and non-empty paths once block is lifted in a future batch |
| R2 | Float→Decimal conversion drift (e.g. `int(3.49 * 100) == 348`) | High if implemented wrong | Mandatory Decimal regex contract test; reuse 6F.2.a pattern verbatim |
| R3 | Implementer accidentally shares a DB connection across the two SQLite files | High | Code review checks for two distinct `sqlite3.connect` calls; the finance helper opens its own connection |
| R4 | Dual-write exception bubbles up and rolls back the legacy commit | Catastrophic | `try/except Exception` around the entire dual-write block; failure logs at WARNING and returns; mandatory `test_finance_dual_write_error_swallow.py` |
| R5 | Race condition: two concurrent /post calls on the same draft | Low (drafts are single-poster) | sha1 idempotency: even if two writes both fire, only the first commits the row; the second detects via `notes LIKE '[live:sha1=X]%'` and skips |
| R6 | Operator forgets to disable the flag before a rollback deploy | Low | Rollback runbook (§6) explicitly lists Path B (set flag false + restart) as primary disable; Path A (DELETE SQL) is secondary |
| R7 | Confusion between `BACKFILL-`, `LIVE-`, and real wFirma postings in 6F.4 panel | Medium (operator UX) | Panel `wfirma_invoice_id` field already displays the value verbatim; document the three prefixes in the operator README before 6F.5 deploy |

---

## 13 — Approval block

```
6F.5 Dual-Write — Operator Approval

Read this entire document: ___ (yes / no)
Approves §1 write boundary:            ___ (yes / no)
Approves §2 feature flag defaults OFF: ___ (yes / no)
Approves §3 hook location after mark_post_succeeded: ___ (yes / no)
Approves §5 idempotency-key scheme (sha1, [live:sha1=...] notes prefix, LIVE- posting prefix): ___ (yes / no)
Approves §6 rollback plan (Path A SQL + Path B flag-off): ___ (yes / no)
Approves §7 shadow-mode design: ___ (yes / no)
Approves §10 hard stops (H1–H13): ___ (yes / no)

Approved by: __________________________
Date/time:   __________________________
Notes:
```

Until this block is signed and merged, `6F.5` remains `blocked` with
reason **"Write-bearing batch. Requires operator approval of 6F.5 dual-write approval package before implementation."**

---

## 14 — Exact next command if operator approves

```bash
# 1. Create the implementation branch from current main.
cd "C:/Users/Super Fashion/PZ APP"
git checkout main && git pull --ff-only origin main
git checkout -b feat/phase-6f-5-dual-write

# 2. Files to create/modify (implementer should NOT exceed this list without re-approval):
#    - service/app/core/config.py: add two Field(default=False, env=...) lines
#    - service/app/services/finance_dual_write.py: NEW, hosts _finance_dual_write() helper
#    - service/app/api/routes_proforma.py: 5-line hook inside post_proforma_draft_to_wfirma,
#      after mark_post_succeeded, before audit.append
#    - service/tests/test_finance_dual_write_*.py: 6 new unit test files (see §8)
#    - service/tests/test_dual_write_source_grep.py: NEW contract test
#    - tasks/campaign-state.json: 6F.5 active -> pr_open

# 3. Run gate tests before commit:
cd service
python -m pytest tests/test_finance_dual_write_*.py tests/test_dual_write_source_grep.py -v
python -m pytest tests/test_finance_postings_contracts.py tests/test_finance_panel_contracts.py tests/test_master_data_hard_rules.py tests/test_runner_v2_hard_rules.py -q
cd ..
PYTHONIOENCODING=utf-8 python test_pz_regression.py  # must be 160/160
```

After PR opens, the standard 7-agent deploy gate applies. Default-OFF behaviour means the deploy itself is a low-risk runtime change (no observable behaviour shift until env var flip).
