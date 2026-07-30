# FINAL REPORT — PR #1037 (duplicate freight/insurance service-ID authority reconciliation)

Branch: `fix/advisory-service-id-draft-fallback` · PR #1037 · **OPEN / DRAFT** · head `d11502a4`
Date: 2026-07-28 · Base: `main`

Status: **MERGE-READY (draft) — held for operator review. NOT merged, NOT deployed.**

> This report supersedes the prior version, which incorrectly described the PR as a
> four-file, "zero JSX" change and mislabelled the two frontend implementations. Both
> errors are corrected below.

---

## 1. Frontend authority — two INDEPENDENT implementations (NOT a source/generated pair)

The prior report claimed the PR changed zero `.jsx` files and treated the Vite tree as a
"generated" artifact. Both are wrong. The correct picture:

- **Canonical, served implementation:** `service/app/static/v2/index.html` directly loads the
  Babel-in-browser JSX runtime file `service/app/static/v2/proforma-detail.jsx` (at
  `index.html:326`). That file **is** the current production implementation for the proforma
  detail route, and **this PR edits it directly** (24 lines — transport-wrapper unwrap +
  provenance note + friendly 502).
- **Separate Vite implementation:** `service/frontend/proforma-v2/` is an independent React app
  that builds to `service/app/static/v2/proforma-react/`. It is **not** a generator for
  `proforma-detail.jsx`, and there is **no** parity relationship between the two. It was frozen
  2026-06-29 (commit `63dd4824`, "without route switch").
- **No current route** switches the production detail page to `proforma-react/`.
- **Governance note:** the existence of two implementations is **architectural residue** and
  must not be treated as a source/generated pair. A future route-migration or retirement
  campaign may be needed — **out of scope for PR #1037**. (Do not call the Vite source
  "generated source"; do not claim parity.)

**Accurate JSX statement:** the final Gap-2 safety commit (`d11502a4`) changes no JSX. The
**overall PR does** change the live Babel-served `service/app/static/v2/proforma-detail.jsx`.

---

## 2. Apply endpoint authority flow — BEFORE and AFTER

Endpoint: `POST /api/v1/proforma/draft/{draft_id}/apply-service-charges`
(`apply_service_charges`, `routes_proforma.py:9835`).

**Amount authority (unchanged in both):** the persisted charge amount ALWAYS comes from
Customer Master. The fallback never supplies or overrides amount, currency, or charge type.

### BEFORE
- Identity resolution on the write path did **not** pass the draft's saved service id into
  `pick_freight` / `compute_insurance_suggestion`. When Customer Master had **no** service id
  for a charge type, the suggestion returned `ok:false` and the type was **skipped as
  "unresolved"** — even when the draft already carried a valid same-type wFirma service id.
- Net effect: **split authority** — the read-only preview (`suggest_service_charges`) accepted a
  same-draft saved id as a fallback identity, but explicit Apply rejected the exact same identity.

### AFTER
Identity is resolved with the **same fixed order preview uses**:
1. Customer Master service id → `service_id_source = "customer_master"`
2. same-draft, same-charge-type saved id → `service_id_source = "saved_draft_fallback"`
3. neither → `unresolved` → skipped (blocked)

The write loop then:
- **CM-resolved + charge already exists** → **SKIP** (idempotency preserved;
  `already and source != "saved_draft_fallback"`).
- **fallback-resolved + charge exists** → **UPDATE amount in place from Customer Master**,
  preserving the existing (draft-sourced) service identity. This is the only explicit-Apply
  write that touches an existing charge, and it runs *only because the operator explicitly
  selected that charge type*.
- **absent** → **ADD**.

Scope note: a same-draft fallback id can only exist when a charge of that type is already on the
draft (the id lives in `service_charges_json`). So the update-in-place behavior is
**structurally confined to the fallback case** and cannot affect the CM-resolved idempotency path.

`service_id_source` is returned in each `applied[]` entry and is a **response field only** —
never persisted (no schema drift).

### Malformed-data fail-safe (added this reconciliation — `d11502a4`)
`update_draft_service_charge` locates its target by `int(c.get("charge_id") or 0) == charge_id`.
A fallback re-apply therefore must never call it with `charge_id == 0`, which would silently
match a malformed persisted row carrying no `charge_id`. The apply loop now guards
`charge_id <= 0` (and a non-int `charge_id`): it **skips the type with an explicit reason**
instead of updating a wrong/malformed charge. **Malformed persisted draft data is never a valid
fallback target.** Pinned by `test_apply_fallback_malformed_charge_id_fails_safe`.

---

## 3. Files changed (COMPLETE PR set — 8 files)

`git diff --name-only origin/main...HEAD` (merge-base `dd59559f` → head `d11502a4`):

| File | Change |
|---|---|
| `service/app/api/routes_proforma.py` | Read endpoint passes each type's saved id as fallback; explicit Apply resolves identity with the same order (symmetric `pick_freight`/`compute_insurance_suggestion`), refreshes amount from CM, preserves saved id, upsert scoped to the fallback case, **`charge_id<=0` fail-safe guard**; read-side `handleCalculateFromCM` skip-reason wrapper fix. |
| `service/app/services/customer_master.py` | `pick_freight`/`compute_insurance_suggestion` gain optional `draft_service_id`/`draft_service_label`; every return dict carries `service_id_source`. Amount reads exclusively from CM; insurance-disabled block stays ahead of fallback. |
| `service/app/services/proforma_invoice_link_db.py` | `update_draft_service_charge` accepts `formula_basis` (wholesale-editable) with `add`'s forbidden-prefix guard (`cif`/`customs`/`import`/`pz_`/`sad_`/`zc429_`); `charge_type` immutable; emits `draft_service_charge_updated`. |
| `service/app/static/v2/proforma-detail.jsx` | **(the live Babel-served detail page)** unwrap the `{ok,data}` suggestions wrapper; render provenance note; friendly wFirma 502 with one-click retry. |
| `service/docs/authority-graph-commercial-draft.md` | Appendix documenting the reconciliation rule + invariants; corrected so the shared preview+Apply order, in-place fallback update, and malformed-`charge_id` fail-safe read accurately (no stale "Apply takes no fallback" text). |
| `service/tests/test_proforma_customer_authority.py` | `TestApplyServiceChargesFallback` — 10 apply-path tests (amount-from-CM, id preserved, CM unchanged, cross-type isolation, CM-wins-over-fallback, only-selected-type-touched, update audit event, preview/Apply source parity) **+ malformed-`charge_id` fail-safe test**. |
| `service/tests/test_proforma_service_charges_panel.py` | Panel-level coverage of the provenance note / suggestions rendering. |
| `service/tests/test_service_id_draft_fallback.py` | Source labelling, amount-always-from-CM, no-mutation, insurance-disabled-beats-fallback, route-level cross-type isolation; docstring updated for the symmetric Apply authority. |

Not part of the PR commit: `.claude/contracts/test-baseline.md` (pre-existing working-tree change
from a prior session; left unstaged and out of scope).

---

## 4. Tests executed and results

| Suite | Result |
|---|---|
| Root golden regression `python test_pz_regression.py` | **160 / 160 passed, 0 failed** |
| `tests/test_proforma_customer_authority.py` | **26 / 26 passed** |
| `tests/test_service_id_draft_fallback.py` | **23 / 23 passed** |
| `tests/test_proforma_service_charges_panel.py` | **17 / 17 passed** |
| `tests/test_proforma_commercial_charge_authority.py` | **21 / 21 passed** |
| Smoke subset `pytest tests/ -m smoke` | **63 passed, 1 skipped** |

The operator validation set is each pinned by a fallback test: preview read-only & no
auto-apply; fallback Apply succeeds with amount from CM (120, not the draft's 50), source
`saved_draft_fallback`, existing id preserved; CM byte-unchanged; only selected type touched;
freight id can't satisfy insurance and vice-versa (amount 5.00 from CM); both missing → blocked;
CM id wins over draft fallback; update audit event emitted; **malformed `charge_id` fails safe
(no applied, skipped with reason, no `draft_service_charge_updated` event)**; posting/conversion
read only persisted charges.

**Pre-existing failures (NOT caused by this PR) — reported separately, NOT counted as green:**
`tests/test_pr2c3b_customer_master.py` — **5 tests fail at setup** in that file's own
`_make_draft` seed helper, which issues `ON CONFLICT(batch_id, client_name) DO NOTHING`.
Committed `init_db` builds the 3-column unique index
`uq_pd_batch_client_gen (batch_id, client_name, clone_generation)` and **no** 2-column unique
constraint, so the seed raises `sqlite3.OperationalError: ON CONFLICT clause does not match any
PRIMARY KEY or UNIQUE constraint` regardless of this PR's code. My change is a single hunk in
`apply_service_charges` + a DB helper key addition, nowhere near `init_db` or the migration.
Tracked schema/harness drift — GATE-4 **SCHEDULED**, out of scope for PR #1037.

---

## 5. Safety proofs

- **Customer Master never written.** The fallback supplies identity only; the only DB writes are
  `add_draft_service_charge` / `update_draft_service_charge` against the **proforma draft** DB.
  `test_apply_fallback_does_not_mutate_customer_master` asserts `freight_service_id` stays `None`
  in CM after a fallback Apply.
- **Preview remains read-only.** `suggest_service_charges` performs no DB writes; no Gap-2 change
  added a write to the preview path.
- **Only explicit, operator-selected Apply mutates draft charges.** The loop iterates exactly the
  charge types in the request `apply` array; `test_apply_only_selected_type_is_touched` proves an
  unselected type is never written.
- **Cross-contamination blocked.** Freight id cannot satisfy insurance and vice-versa; CM id wins
  when present.
- **Malformed persisted data never updated in place.** `charge_id<=0` fail-safe skips instead of
  calling the updater with a matching-everything `0`.

---

## 6. Rollback procedure

- **Un-ship the malformed-safety commit (keep earlier fallback work):** `git revert --no-edit d11502a4`.
- **Un-ship the whole Gap-2 fallback:** revert back to the pre-fallback tip on the branch, or
  close PR #1037 (draft) — nothing is on `main`, nothing deployed, so no production rollback.
- No schema migration was introduced; `service_id_source` is not persisted; `formula_basis` on
  `update_draft_service_charge` is additive and guarded — reverting removes it cleanly.

---

## 7. Governance

- **Lesson N:** the fallback is advisory *identity* resolution; it never promotes an advisory
  signal into a fiscal blocker nor demotes a true blocker. Amount authority stays with Customer
  Master.
- **Lesson O:** the endpoint's external contract is unchanged; tests were migrated/added in the
  same PR (no silent break; no route weakened).
- **GATE 6 (backend substitution):** the backend endpoint is exercised end-to-end through the
  FastAPI test client and the required `draft_service_charge_updated` audit event is asserted —
  the route-test + audit-log substitution for backend-only work. The **JSX change** (live
  `proforma-detail.jsx`) still requires GATE-6 live browser verification post-deploy (recorded as
  a deploy-gate follow-up; this PR is held in draft).
- **FRONTEND AUTHORITY CONSTITUTION:** §1 above records that `proforma-detail.jsx` is the one
  canonical served implementation for this route; the Vite `proforma-v2/` tree is unswitched
  residue, flagged for a separate migration/retirement decision.
- **Scorecard (RULE 6):** `.claude/memory/scorecards/2026-07-28-advisory-service-id-draft-fallback.md`.

**HOLD:** stops here at merge-ready draft for operator review. Do not merge or deploy. Promoting a
draft service ID **into Customer Master** remains a separate, hard-gated campaign (financial
approval + security review) and was not built — this PR keeps Customer Master read-only.
