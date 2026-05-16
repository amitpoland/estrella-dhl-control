# `/post` Block-Lift — Read-Only Inspection

> **Status:** inspection only. NO code change. NO route change. NO env change.
> Scopes what a future block-lift batch would need to do.
> **Date:** 2026-05-16.

This document inspects the existing `/post proforma` block on non-empty
`service_charges_json` and answers 11 questions about whether/when to lift it.
It does NOT lift the block.

---

## 1 — Why `/post` currently blocks non-empty `service_charges_json`

`routes_proforma.py::_build_proforma_request_from_draft` (line 3508–3542) raises
`ValueError` when a posted draft carries any operator-entered service charges:

```python
# Service-charge block
try:
    charges = json.loads(draft.service_charges_json or "[]") or []
except Exception:
    charges = []
if charges:
    raise ValueError(
        "service_charges present but wFirma service-product mapping not "
        "configured — remove the charges or wait for Phase 6 wiring"
    )
```

**Reason:** the wFirma `invoices/add` XML payload requires every line to
reference a `<good>` by `wfirma_good_id` (see `wfirma_client.py` `ProformaRequest`
docstring at line 134–166: *"contractor and goods are referenced BY ID — not by
inline name fields"*). Freight and insurance charges are not "goods" in the
product master — they are service items. To post them to wFirma as proforma
lines, each charge type would need a corresponding wFirma "service product"
with a stable `wfirma_good_id`, and the route would need to look that id up
and inject it as a `ReservationLine` at posting time. That mapping does not
exist today.

The block is **prophylactic, not malicious**: it prevents a half-built mapping
from silently producing a proforma whose totals omit the freight/insurance lines
the operator entered.

---

## 2 — Exact line/function enforcing the block

| Location | Detail |
|---|---|
| File | `service/app/api/routes_proforma.py` |
| Function | `_build_proforma_request_from_draft(draft)` |
| Lines | **3508–3542** (block sub-section: **3533–3542**) |
| Trigger | `json.loads(draft.service_charges_json or "[]")` returns a non-empty list |
| Error type | `ValueError` (not HTTP exception) |
| Caller-side | `post_proforma_draft_to_wfirma` calls `_build_proforma_request_from_draft` at line **3753**. The route catches `ValueError`, formats it as a `{ok: false, status: "blocked", blocking_reasons: [...]}` JSONResponse via `_blocked_post_response()` (line 3494). |
| Effect on draft | None — `mark_post_succeeded` never fires; draft stays in its previous state. |
| Effect on wFirma | None — XML is never built, request is never sent. |

The block is **a single ValueError raise** in a pure function. Removing it is
syntactically one line. Lifting it safely requires substantive plumbing
elsewhere — see §3.

---

## 3 — What a future block-lift batch would need to change

A safe block-lift batch is **substantial**. Estimated effort: 1 PR, 6–10 files,
two write-bearing paths (service-product registration + service-line injection).
The work breaks into 5 components:

### 3.1 — Service-product registration (new wFirma master data)

Each allowed charge type (`freight`, `insurance` from `proforma_service_charges_db.ALLOWED_CHARGE_TYPES`) needs a corresponding wFirma "good" entry:

- New wFirma `goods/add` POST per charge type (one-time setup, operator-driven).
- New row in `master_data.sqlite::charge_type_wfirma_mapping` (or extension of `master_data.charge_types` if such a table exists; check first) recording `{charge_type, wfirma_good_id, vat_code_id, currency, unit}`.
- A new read-only endpoint `GET /api/v1/master/charge-type-mapping` for operator visibility.
- Migration to seed the mapping in production once (operator-gated, separate approval).

### 3.2 — `ProformaRequest` schema extension

`wfirma_client.py::ProformaRequest` (line 134) currently has `lines: List[ReservationLine]`. Two options:

**Option A — Add service-charge lines to `.lines`** (simpler):
Each charge entry becomes an additional `ReservationLine` with:
- `wfirma_good_id` = looked up from `charge_type_wfirma_mapping`
- `qty` = 1
- `unit_price` = charge amount
- `currency` = charge currency

No XML schema change; `_build_proforma_xml` already iterates `req.lines`.

**Option B — Add a separate `service_charges: List[ServiceChargeLine]`** (more explicit, harder):
New dataclass, new XML branch. Higher integration cost.

Recommend **Option A**. It reuses the validated XML path.

### 3.3 — `_build_proforma_request_from_draft` change

Replace the `if charges: raise ValueError(...)` block (lines 3538–3542) with:

```python
if charges:
    if not settings.proforma_service_charges_enabled:
        raise ValueError("service_charges present but block-lift flag is OFF")
    from ..services.charge_type_wfirma_mapping_db import get_mapping_for_type
    for ch in charges:
        m = get_mapping_for_type(ch["charge_type"])
        if not m or not m.wfirma_good_id:
            raise ValueError(f"no wFirma good_id mapped for charge_type={ch['charge_type']!r}")
        # validate currency matches draft currency; build a ReservationLine.
        ...
```

### 3.4 — Test surface extensions

Existing tests that assert `service_charges_json == "[]"`:

| File | Lines | Implication |
|---|---|---|
| `service/tests/test_proforma_drafts_lifecycle_phase1.py` | 184, 210, 296 | These pin the empty default at create time. Unaffected by the lift. |
| `service/tests/test_proforma_drafts_lifecycle_phase2.py` | 199–200 | Same — empty at draft creation. |
| `service/tests/test_proforma_drafts_lifecycle_phase3.py` | 216, 230, 237 | Tests that UPSERT charges into the draft. Unaffected by the lift. |
| `service/tests/test_proforma_drafts_lifecycle_phase4.py` | 285 | Empty at convert-time. Unaffected. |

**New tests required** for the block-lift PR:
- Service-product mapping resolution (positive + negative).
- `_build_proforma_request_from_draft` correctly emits N+M lines for N goods + M charges.
- Mixed-currency draft+charge produces `ValueError` (not silent posting).
- Missing mapping for a present charge type produces a clean `blocked` response, not a 500.
- Real-builder test (Lesson A): post a draft with one freight charge → wFirma XML contains a line with the mapped good_id, qty=1, unit_price=charge.amount. (Stub the wFirma HTTP layer, NOT the XML builder.)

### 3.5 — Source-grep contracts (mandatory)

| Contract | Purpose |
|---|---|
| Block-lift is feature-flagged | `settings.proforma_service_charges_enabled` defaults False; flag check precedes the new lookup |
| Mapping table is read-only from route | No `INSERT/UPDATE/DELETE` against `charge_type_wfirma_mapping` from `routes_proforma.py` |
| No legacy table mutation | `proforma_service_charges` still read-only on the /post path |
| Currency consistency | All charges' currencies must match draft currency (existing single-currency check at line 3544 must include charges) |
| No FX conversion injected | Charge amounts must reach wFirma in their source currency; no FX rate applied at /post |

---

## 4 — Can 6F.5 dual-write work BEFORE block-lift?

**Yes — but with degraded evidence.**

The 6F.5 dual-write hook (routes_proforma.py line ~3874, inside `post_proforma_draft_to_wfirma`) fires AFTER `mark_post_succeeded` returns. That sequencing means:

| Draft state | Today (block in place) | After block-lift |
|---|---|---|
| `service_charges_json == "[]"` | /post succeeds → dual-write fires → 0 charges + 1 LIVE-* posting written | Same |
| `service_charges_json != "[]"` | /post raises `ValueError` → `_blocked_post_response()` returns 400 → `mark_post_succeeded` never fires → **dual-write hook never reached** | /post succeeds → dual-write fires → N charges + 1 LIVE-* posting written |

So today, 6F.5 dual-write CAN be activated and IS functional, but it produces:
- One `LIVE-` posting per successful /post (with `issued_total_minor: 0` because no charges)
- Zero `charges` rows (since the only drafts that succeed have empty service_charges_json)

This was a documented Risk R1 in the dual-write approval package, and Risk OR1 in the decision memo.

The dual-write does NOT depend on block-lift to *function* — it depends on it to produce *useful evidence*. With the block in place, shadow mode logs one aggregate `finance_dual_write_shadow posting` line per /post, but zero per-charge lines.

---

## 5 — Is block-lift required before shadow activation gives useful evidence?

**Yes, for charge-level evidence. No, for hook-presence evidence.**

| Evidence target | Achievable without block-lift? |
|---|---|
| Hook fires after `mark_post_succeeded` | Yes — every /post triggers the aggregate shadow log line |
| Failure isolation works | Yes — monkeypatch test already proved it |
| sha1 idempotency keys stable | Yes — re-posting the same draft logs the same `synthetic_posting_id` |
| `Decimal(str(x)) * 100` correct for real charges | **No** — no real charge reaches the helper today |
| Backfill / live namespace coexistence under production load | **No** — production has 0 backfill rows AND 0 charges per posted draft |
| Operator workflow unchanged when dual-write active | Yes — operator UX is unchanged regardless of charge presence |

If the operator's goal in shadow mode is to validate the HOOK is wired
correctly, shadow without block-lift is sufficient. If the goal is to
validate CHARGE PAYLOAD CORRECTNESS, block-lift is required first.

The decision memo (`tasks/phase-6f-5-shadow-decision-memo.md` §4 R2) already
flagged this: shadow log volume would be sparse without block-lift.

---

## 6 — Required feature flag for block-lift

**Recommendation: one new flag**, default OFF, mirroring the 6F.5 pattern:

```python
# service/app/core/config.py
proforma_service_charges_enabled: bool = Field(
    default=False, env="PROFORMA_SERVICE_CHARGES_ENABLED"
)
```

Reasons for default-OFF:
- The block protects against half-built service-product mapping.
- Operator must explicitly enable per-environment.
- Rollback = 30 seconds (env clear + restart).

Reasons NOT to reuse `FINANCE_DUAL_WRITE_ENABLED`:
- Different scope (wFirma posting behaviour vs local-DB dual-write).
- Either can be enabled without the other.
- Coupling them would make rollback ambiguous.

The block-lift is **independent of 6F.5 activation**:
- Shadow / live dual-write can be active or inactive irrespective of block-lift.
- Block-lift can be active or inactive irrespective of dual-write.
- The four combinations are all valid and well-defined.

---

## 7 — Required source-grep contracts (for block-lift PR)

Mirror the 6F.5 source-grep pattern. Required new contracts:

| Contract test name (suggested) | What it pins |
|---|---|
| `test_block_lift_flag_default_false` | `Field(default=False, env="PROFORMA_SERVICE_CHARGES_ENABLED")` present in config.py |
| `test_block_lift_flag_check_precedes_charge_processing` | In `_build_proforma_request_from_draft`, the flag check appears textually BEFORE the mapping lookup |
| `test_charges_block_raises_when_flag_off` | The legacy `ValueError("service_charges present...")` branch still exists and is reachable when the flag is False |
| `test_charges_block_lifts_when_flag_on_with_mapping` | When flag is True AND mapping exists for each charge type, the function returns a ProformaRequest with N+M lines |
| `test_charges_block_lifts_to_blocked_response_when_mapping_missing` | When flag is True AND mapping missing for any present charge type, `ValueError` is raised cleanly (becomes 400 `blocked` response — never 500) |
| `test_charge_amount_currency_consistency` | All charges in a draft must share the draft's currency (no implicit FX) |
| `test_mapping_db_no_writes_from_route` | Source-grep: `routes_proforma.py` does not contain `INSERT/UPDATE/DELETE` against `charge_type_wfirma_mapping` |
| `test_no_fx_conversion_injected_at_post` | Source-grep: no `nbp` / `fx_rate` / `convert_currency` imports added to `_build_proforma_request_from_draft` |

---

## 8 — Required real-builder tests (Lesson A)

The PR must include at least **two real-builder tests** that:

1. Build a draft with one freight charge entry in `service_charges_json`.
2. Set `settings.proforma_service_charges_enabled = True` (monkeypatch).
3. Seed `charge_type_wfirma_mapping` with a real row `{freight → wfirma_good_id=42, currency=EUR}`.
4. Invoke the REAL `_build_proforma_request_from_draft` (no stub of `_build_proforma_request_from_draft` itself).
5. Assert the returned `ProformaRequest.lines` has N+1 entries, with the last entry matching the charge.
6. Assert `_build_proforma_xml(req)` (REAL builder) produces XML that contains exactly one `<good><id>42</id></good>` block AND the correct unit_price element.

The second real-builder test exercises the multi-charge path (freight + insurance) and asserts both are emitted.

Stubbing the wFirma HTTP call is permitted; stubbing the XML builder is not.

---

## 9 — Required browser/API smoke (post-deploy)

Block-lift would be deployed with `PROFORMA_SERVICE_CHARGES_ENABLED=false`
(default), so first smoke is identical to today:

1. POST a charge-free draft via /post → confirm 200 response unchanged.
2. POST a draft with non-empty `service_charges_json` via /post → confirm 400 `blocked` response with the legacy error message ("service_charges present but block-lift flag is OFF" or equivalent).

Then with the flag flipped to true and mapping seeded:

3. POST a charge-bearing draft → confirm 200, confirm wFirma proforma `fullnumber` returned, confirm wFirma proforma in the wFirma dashboard contains the service line(s).
4. If 6F.5 dual-write is also active (shadow or live), confirm the charge appears in the 6F.4 Diagnostics finance panel breakdown.
5. Confirm legacy `proforma_service_charges` table size unchanged (no new writes from the route — only reads).

---

## 10 — Risks and rollback

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| BLR1 | Operator activates block-lift before service-product mapping is seeded in wFirma → first charge-bearing /post fails | MEDIUM (clean failure, not silent corruption) | Mapping lookup raises `ValueError` → `_blocked_post_response()` returns 400 with explicit reason. Operator seeds mapping, retries. |
| BLR2 | wFirma's `invoices/add` accepts the new line but renders it differently from how the operator entered the charge (e.g. VAT applied) | MEDIUM | Mandatory smoke step in §9.3 verifies wFirma rendering before declaring success |
| BLR3 | Block-lift accidentally activates dual-write coupling (e.g. dual-write becomes mandatory) | LOW | Source-grep contract enforces independence — the two flags are checked separately in different files |
| BLR4 | Multi-currency drafts now have to validate charge currency = draft currency | MEDIUM | New test `test_charge_amount_currency_consistency` pins this; route raises `ValueError` on mismatch |
| BLR5 | Existing tests that assert `service_charges_json == "[]"` start failing if a new test fixture sets non-empty charges | LOW | Existing tests are at draft-creation time; they remain valid. Block-lift only changes /post-time behaviour. |
| BLR6 | Race condition: operator edits charges between /preview and /post; the preview shows different totals than the posted proforma | LOW | Same risk exists today for line edits; standard "draft is the source of truth" model applies |
| BLR7 | A future Phase 6F.6 settlement-close batch assumes charges-on-posting and breaks without block-lift | LOW (timing only) | 6F.6 must explicitly declare its dependency on block-lift in its approval package |

### Rollback paths

| Path | Cost | Reversibility |
|---|---|---|
| **A — Flag-off** | 30 seconds (NSSM env clear + restart) | Full. Charges already posted to wFirma remain posted (correct — they're real invoices). No DB cleanup needed. |
| **B — Code revert** | Full deploy cycle | Full. `git revert -m 1 <merge-sha> --no-edit` + robocopy + restart. |
| **C — wFirma side** | Manual operator work | Partial. If wFirma proformas were issued with wrong line shapes, operator must cancel/correct in wFirma. The PZ App does not auto-cancel wFirma documents. |

---

## 11 — Recommendation: lift now, defer, or keep blocked

**Recommendation: DEFER block-lift.** Do not lift in this campaign window.

Rationale:

1. **Block-lift is a write-bearing batch with two write paths** (service-product registration + service-line injection at /post). It deserves its own approval package, its own decision memo, and its own multi-agent review. Bundling it with shadow activation would create an unsafe coupling.

2. **6F.5 dual-write can be activated independently for hook-presence evidence.** If the operator's near-term goal is to validate the dual-write hook is wired correctly in production, shadow activation (without block-lift) is sufficient. Charge-level payload validation can wait.

3. **Production has not requested service charges on proforma yet.** The legacy `proforma_service_charges` table is empty (0 rows; §3 of `tasks/phase-6f-2f-freeze.md`). The block has never been hit in production. Lifting it now would solve a problem no operator has actually encountered.

4. **The block message itself is correct.** *"service_charges present but wFirma service-product mapping not configured"* is an honest description of the current state. Removing it without seeding the mapping would replace a clean blocked response with a wFirma XML failure (worse UX).

5. **Lessons L-037 (deployed != activated) and L-039 (DEFER is first-class) both apply.** The repo's discipline of separating capability shipping from capability activation has paid off — keep the pattern.

### When to reopen this question

Lift-now becomes defensible when ALL of these are true:

- An operator workflow has emerged that requires posting a proforma with explicit freight/insurance lines visible in wFirma (not just stored locally).
- wFirma service-product master data has been seeded by the operator (one good per charge type, plus VAT codes).
- The operator has signed off on a separate `tasks/phase-6f-post-block-lift-approval-package.md`.

Until then, the block stays as a prophylactic — it costs nothing and prevents
half-built mappings from silently producing wrong invoices.

---

## 12 — Summary table

| Question | Answer |
|---|---|
| Why does /post block non-empty service_charges_json? | No wFirma service-product mapping exists (line 3538–3542) |
| Where? | `routes_proforma.py::_build_proforma_request_from_draft`, raised by line 3539 `ValueError` |
| What would block-lift change? | 5 components: service-product registration, mapping table, ProformaRequest line injection, ~6 new tests, source-grep contracts |
| Can 6F.5 dual-write work before lift? | Yes for hook-presence; no for charge-payload evidence |
| Is lift required before shadow activation gives useful evidence? | Required for charge-level evidence; not required for hook-presence evidence |
| Feature flag? | `PROFORMA_SERVICE_CHARGES_ENABLED`, default False, mirrors 6F.5 pattern |
| Source-grep contracts? | 8 new contracts (§7) |
| Real-builder tests? | ≥ 2 (single charge + multi-charge) per Lesson A (§8) |
| Browser/API smoke? | 5 steps (§9), gates the wFirma rendering |
| Risks? | 7 risks (§10); top severity MEDIUM (BLR1 + BLR2 + BLR4) |
| Recommendation? | **DEFER.** Operator has not requested the capability; the block is correct as-is. |

---

## 13 — Hard rule status (no change from prior Phase 6F state)

| Rule | Status |
|---|---|
| No code change in this batch | ✅ this is inspection-only |
| No route change | ✅ |
| No env change | ✅ no flags set; no NSSM changes |
| No activation | ✅ 6F.5 remains default-OFF; shadow remains blocked |
| No DB write | ✅ |
| No wFirma/proforma posting behaviour change | ✅ block stays in place |
| No PZ/FX/settlement change | ✅ |
| 6F.5 deployed default-OFF, flags verified at 4 sources | ✅ unchanged |
| 6F.2.d live backfill deferred | ✅ unchanged |
| 6F.2 sub-campaign frozen with §12 reopening criteria | ✅ unchanged (closed 2026-05-16 in PR #124) |
