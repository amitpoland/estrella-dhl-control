# Campaign A1 — PZ Authority Consolidation (Execution Brief)

**Inspected:** `origin/main @ 94b95bb` (read-only; verified + red-teamed via workflow `wf_cd38ef32-88a`)
**Date:** 2026-06-19 · **Status:** READY FOR STAGE 1 once the §0 go/no-go items are signed
**Foundation:** Wave-0 findings + idempotency verification (`pz_create` duplicate-prevention is independent of this work). Every claim cites `file:line`.

---

## 0. Objective & why discovery is complete

**Objective.** Make `operational_authority` the single home for PZ-completion truth by absorbing the wFirma guard's stale-status normalization (`_compute_effective_pz_status`, Path A + Path B) into a new canonical function, repointing all consumers, and retiring the fork — **without changing the truth itself** (the module's standing invariant, `operational_authority.py:16`).

**Why discovery is complete (and why risk dropped a category).** Wave-0 verified that PZ **duplicate prevention** (`_assert_pz_not_locked` `routes_wfirma.py:797` + `_pz_write_lock` `:888` + timeline backstop) is a **separate, independently-tested mechanism** from the PZ-**status** judgment being consolidated. The two never share a code path. Therefore this is a **readiness-authority** project, not a **write-integrity** project: a regression in the merged status function **cannot create a duplicate PZ**. The remaining write-path exposure is further bounded — `pz_create` has an **independent Guard 3 MRN re-check** (`routes_wfirma.py:2536–2544`) that blocks the actual create for the MRN-empty (Path-B) class regardless of the guard verdict. Discovery has produced exact divergence fixtures, the full consumer map, and the test/flag posture; nothing further needs inspecting before implementation.

**The conflict, proven (divergence fixtures, hand-traced from code):**

| Fixture | `derive_pz_status` | `is_pz_done` | `_compute_effective_pz_status` | guard (`eff∈_PZ_DONE`) | `pz_create` write |
|---|---|---|---|---|---|
| Normal complete (`wfirma_pz_doc_id` set, status=success) | `complete` (`oa.py:129`) | True | `(success,False)` (`rw.py:184`) | YES | proceeds |
| **Path B** (status=failed, `failed_checks`=[], cn_ok, **mrn EMPTY**, `pz_output.{pdf,generated_at}` set) | `failed` (`oa.py:133`) | False | `(partial,True)` (`rw.py:209`) | YES | **BLOCKED by Guard 3** `PZ_CREATE_NO_MRN` (`rw.py:2537`) |
| Path A (status=failed, mrn present, pz_output set) | `failed` (`oa.py:133`) | False | `(partial,True)` (`rw.py:196`) | YES | proceeds |

**Structural cause:** `derive_pz_status` treats `status=="failed"` as an unconditional terminal (`oa.py:132-133`) — no Path A/B equivalent. `_compute_effective_pz_status` deliberately rescues stale-failed audits the operator has cleared. **Blast radius of the fork:** Path B is load-bearing for the **clipboard/JSON export** endpoints (`_guard_wfirma_export` at `rw.py:1381,1447` — no subsequent MRN guard) and **pz_preview** (`_collect_pz_preview_blockers` `rw.py:289`); on `pz_create` Guard 2 passes but Guard 3 re-blocks. **Naively replacing the fork with `derive_pz_status` would 422 the export endpoints for the MRN-barcode-only shipment class** — so **Path B must be promoted, never dropped.**

**Doc-vs-code conflict (flagged):** `operational_authority.py:4-9` and `:145` already *claim* this consolidation happened; it has not. `audit_persist.py:22-24` and `audit_evidence.py:11,33` likewise name the fork as the reference. These four docstrings are factually wrong mid-migration → Stage 5 docstring sweep (R-3).

**Confirmed consumer map — 7 call sites, 3 files** (V2; not the 2 the original plan named):
| Consumer | File:line | Notes |
|---|---|---|
| `_collect_pz_preview_blockers` | `routes_wfirma.py:289` | high-traffic read path |
| `_guard_wfirma_export` | `routes_wfirma.py:341` | used by clipboard 1381, json 1447, preview 1622, adopt 1830, sync-names 2221, **pz_create 2532** |
| `wfirma_pz_preview` (×3 inline) | `routes_wfirma.py:1594, 1648, 1774` | builds `effective_status`/`status_normalized` in JSON |
| `restamp_pz_status_if_done` | `audit_persist.py:99` (lazy import) | **delegates** to fork — not independent |
| `_effective_pz_status_done` | `audit_evidence.py:103` (lazy import) | **delegates** to fork — not independent |
| `routes_dashboard._derive_pz_status` | `routes_dashboard.py:31,347` | **already canonical** — no repoint |

No third independent authority exists (V2: both lazy-import sites delegate). `_PZ_DONE` (`= operational_authority.PZ_DONE = {success,partial}`, re-exported `rw.py:131`) migrates alongside.

---

## Stage 1 — Add `operational_authority.compute_effective_pz_status()`
**Scope.** Add a NEW exported function to the leaf module `operational_authority.py`, encapsulating the Path-A/Path-B normalization currently in `routes_wfirma._compute_effective_pz_status` **byte-for-byte behaviorally** (changes WHERE, not WHAT). Returns the same `(effective_status, normalized_flag)` tuple. **`derive_pz_status` and `is_pz_done` are NOT modified** and `is_pz_done` MUST continue to call `derive_pz_status`, never the new function (red-team B). No call site is repointed yet (additive only).
- **Explicit decision required (red-team F):** the fork ignores `engine_error` (checks only `failed_checks`, `rw.py:186`); `_collect_pz_preview_blockers` emits `BLOCKER_ENGINE_ERROR` separately. To preserve the "WHERE not WHAT" invariant, the new function **reproduces this exactly** (does NOT gate on `engine_error`); document that `engine_error` hard-blocking lives only in `_collect_pz_preview_blockers`. Any change here is a behavior change and out of A1 scope.
**Acceptance criteria.** New function present + exported in `__all__`; `derive_pz_status`/`is_pz_done` byte-identical to HEAD; module docstring updated to declare the *two-surface* model (display = `derive_pz_status`; guard/creatability = `compute_effective_pz_status`) with an explicit warning that `is_pz_done` must not call the latter; full existing test suite green (additive change breaks nothing).
**Test requirements.** Unit tests for the new function mirroring `test_wfirma_pz_guard_normalization.py` (Path A, Path B, fast-path `stored∈_PZ_DONE`, failed_checks block, cn-unresolved block).
**Rollback.** Trivial/additive — delete the new function; nothing consumes it yet.

## Stage 2 — Parity coverage (the long-term anti-drift guard)
**The test that must exist:** `test_pz_authority_parity.py` comparing the **two authority surfaces** on identical fixtures, using normalized predicates (red-team C — raw string equality is meaningless across value spaces):
```
display_complete(a) = (derive_pz_status(a) == "complete")        # dashboard truth
creatable(a)        = (compute_effective_pz_status(a)[0] in PZ_DONE)  # guard truth
```
**Fixture classes & assertions:**
1. Non-Path-B (normal): `creatable(a) == display_complete(a)` — must agree.
2. Path A (mrn present, cn_ok, fc empty): both True.
3. **Path B (status=failed, fc=[], cn_ok, mrn EMPTY, pz_output set):** assert the **intentional divergence** — `creatable(a) is True` AND `display_complete(a) is False`. (A test asserting universal agreement is wrong by design.)
4. Fast-path (`status∈{success,partial}`): both agree without touching CN.
5. **Half-state (R-4):** `wfirma_pz_doc_id` set + `status="failed"` — `derive_pz_status`→`complete` (precedence 0, `oa.py:128`) while the fork has no doc_id check; **document the delta** (the new function's behavior on this state must be a deliberate, recorded choice, not drift).
Import directly from `operational_authority` (NOT via the `routes_dashboard` re-export, red-team C).
**Why it's long-term protection:** it pins, in CI, the *exact, intended* relationship between the dashboard badge and the wFirma guard — including where they are *supposed* to differ (Path B). Any future edit that makes the guard agree with the badge on Path B (or makes the badge show `complete` for MRN-unparseable batches) fails this test. It is the regression that the original ATLAS-P1 consolidation lacked, which is why the fork survived undetected.
**Acceptance threshold to proceed to Stage 3:** all 5 fixture classes green in CI; the Path-B divergence assertion explicitly present.
**Rollback.** Test-only; revert the file.

## Stage 3 — Shadow comparison (production, log-only)
**Mechanism (red-team A — critical):** because `WFIRMA_CREATE_PZ_ALLOWED` defaults **OFF** (`config.py:280`; create/adopt never reach the guard), the **only production-reachable signal path is `pz_preview`** (structured blockers default ON). Therefore **wrap `_compute_effective_pz_status` itself** with a shadow log — a single injection point that covers **all 7 call sites** and fires on every operator open of the wFirma panel:
```
legacy = _compute_effective_pz_status(audit)
shadow = operational_authority.compute_effective_pz_status(audit)
log.info("[pz-shadow] batch=%s legacy=%r shadow=%r match=%s", batch_id, legacy, shadow, legacy==shadow)
# behavior continues to use legacy; shadow is logged only
```
**"Parity remains clean" =** zero `match=False` events. **Divergence looks like:** any `match=False` line — investigate the audit fixture; it indicates the promoted logic differs from the fork (a Stage-1 porting bug, since behavior was meant to be identical).
**Acceptance threshold to proceed to Stage 4 (red-team D + R-6):** **≥50 production-batch shadow evaluations over ≥3 calendar days with zero divergence, AND at least one observed Path-B batch** (MRN-unparseable + `pz_output` present). Zero-divergence with no Path-B batch observed is **insufficient** — Path B would be untested in prod.
**Rollback (R-5).** Remove the shadow wrapper. No schema, no behavior change to revert.

## Stage 4 — Feature-flag activation + repoint
**Flag (red-team G):** add `WFIRMA_GUARD_CANONICAL_PZ`, **per-request `os.getenv` read, default OFF**, matching the existing `_pz_preview_structured_enabled()` pattern (not a typed `settings` attribute); add to `.env.example`.
**Repoint — ALL 7 call sites (R-1), behind the flag:** `routes_wfirma.py:289, 341, 1594, 1648, 1774` → canonical; `audit_persist.py:99` and `audit_evidence.py:103` → drop the `routes_wfirma` lazy import, import `compute_effective_pz_status` + `PZ_DONE` from `operational_authority` (**before** any retirement, R-2; else the lazy import silently no-ops and stale-status restamp stops working). `routes_dashboard` needs no change.
**Rollout & monitoring.** Deploy with flag OFF (legacy path live, shadow still logging). Flip ON in one environment; monitor the shadow log + the `pz_preview` response fields (`stored_status`/`effective_status`/`status_normalized`, `rw.py:1610-1612`) for any change vs the shadow baseline. **Abort conditions:** any divergence event post-flip, any `pz_preview` 5xx, any export-endpoint 422 regression on a known Path-B batch → flip flag OFF (instant rollback, no redeploy).
**Acceptance to proceed to Stage 5:** flag ON in production ≥3 days, zero divergence, export endpoints + `restamp_pz_status_if_done` verified working on a stale-status batch (R-2 regression test green).

## Stage 5 — Retirement
**When safe:** flag ON and stable per Stage-4 gate AND **`git grep '_compute_effective_pz_status'` across the whole tree returns only the definition** (mandatory gate, red-team D — confirms all 7 sites repointed).
**Actions:** delete `routes_wfirma._compute_effective_pz_status` + the `_PZ_DONE` re-export (`rw.py:131`; consumers now import `PZ_DONE` from `operational_authority`, A-4); remove the flag (canonical is now the only path); **docstring sweep (R-3):** correct `operational_authority.py:4-9` & `:145`, `audit_persist.py:22-24`, `audit_evidence.py:11,33` to reflect the now-true single-authority state; optionally simplify the `audit_evidence.py:103` lazy import to a top-level import (A-1, leaf module → no cycle).
**Sign-off gates:** Stage-4 acceptance met; git-grep gate clean; parity test (Stage 2) still green against the canonical-only code.
**Rollback (R-5):** restore `_compute_effective_pz_status` from tag `archive/pre-a1-stage5-2026-06-19`, revert the `audit_persist.py`/`audit_evidence.py` imports, redeploy. (Stage 5 is the only irreversible-by-default stage; the tag makes it recoverable.)

---

## Out of scope (why nothing else starts now)
- **Discovery is closed:** the conflict, its exact divergence, the 7-site consumer map, and the test/flag posture are all verified at `94b95bb`. No further inspection precedes implementation.
- **`_compute_pz_lifecycle_state` (`rw.py:1040`) and `_compute_pz_lock_status` (`rw.py:1196`)** derive from `wfirma_pz_doc_id`/`pz_source`/timeline, **not** from the fork — out of scope (A-2), do not touch.
- **Atlas / Shipment / Proforma consolidation must NOT start:** confirmed clean boundary (A-3) — `derive_pz_status` is imported only by `routes_dashboard.py:31`, `is_pz_done` has zero external callers, and no Atlas/Proforma/Shipment route touches `_compute_effective_pz_status`. Those are separate campaigns; starting them now would violate the one-domain-per-wave sequencing and dilute the shadow signal.

---

## Risk register — authority-verdict mismatch (dashboard vs guard)
| Risk | Where it bites | Detected/prevented by |
|---|---|---|
| **Promoted logic diverges from the fork** (Stage-1 porting bug) | guard/preview returns differ silently | Stage 2 parity test (intentional-divergence-aware) + Stage 3 shadow zero-divergence gate |
| **Path B folded into `derive_pz_status`** → dashboard badge flips to `complete` for MRN-unparseable batches | dashboard contradicts Guard 3 (`PZ_CREATE_NO_MRN`) — the original ATLAS-P1 bug | Stage 1 keeps `derive_pz_status` unchanged + docstring/`__all__` guard that `is_pz_done` never calls the new fn (red-team B) |
| **Naive parity test passes while real drift persists** | Path-B class undetected | Stage 2 must assert the intentional divergence on a Path-B fixture (red-team C) |
| **Shadow never observes Path B** (rare batches) → false confidence | retirement on untested logic | Stage 3 gate requires ≥1 observed Path-B batch, not just N clean days (red-team D) |
| **Lazy-import cutover misses `audit_persist`/`audit_evidence`** | `restamp_pz_status_if_done` silently no-ops → stale-status bug returns | R-2: repoint those imports before retirement + restamp regression test |
| **`engine_error` vs `failed_checks` inconsistency** | `creatable=True` while `BLOCKER_ENGINE_ERROR` present | Stage 1 explicit decision (preserve current split) + documented |
| **Flag defaults ON / wrong posture** | behavior flips before shadow validation | red-team G: per-request `os.getenv`, default OFF, matches `_pz_preview_structured_enabled` |

**Residual risks (accepted, monitored):** (1) Path-B batches may be rare in the shadow window — mitigated by the explicit "≥1 Path-B observed" gate, not eliminated. (2) The half-state `wfirma_pz_doc_id`+`status=failed` (R-4) is a documented behavioral delta the parity test pins; if the canonical function's choice there is ever revisited it must update that test. (3) Crash-window interaction (`pz_create` audit-write-failed) is unchanged by A1 — duplicate prevention remains the independent `_assert_pz_not_locked`/timeline mechanism.

---

## §0 Go/No-Go for Stage 1 (sign before code)
1. Accept the **two-surface model**: `derive_pz_status` (display) stays unchanged; new `compute_effective_pz_status` (guard/creatability) absorbs Path A/B. ☐
2. Accept that **Path B is promoted, not dropped** (else export endpoints 422 for MRN-barcode shipments). ☐
3. Accept the **7-site repoint set** (incl. `audit_persist.py:99`, `audit_evidence.py:103`) and the **import-before-retire** ordering. ☐
4. Accept the Stage-3 gate requires an **observed Path-B batch**. ☐
5. Accept the Stage-1 **`engine_error` decision** (preserve current behavior; no new gating). ☐

No new authority conflict emerged that blocks implementation. A1 is the **only** wave that may proceed now.
