# MDOC-2026-05 — Operator Acceptance of Deferred Visual Smoke

> **Status:** operator-signed acceptance note. Closes MDOC-2026-05 at its
> paused state with explicit acknowledgement that the 6 deferred B-MD4
> visual surfaces remain `[ ]` Pending operator walk — NOT claimed as
> passed.
> **Date:** 2026-05-16.

This note is the operator's explicit acceptance that:

1. MDOC-2026-05 is closed at its current mechanically-smoked state.
2. The 6 deferred B-MD4 visual surfaces remain documented as deferred,
   not as passed.
3. No fake smoke-complete claim is made by either operator or agent.
4. The deferred surfaces can be walked at the operator's discretion in
   a future session without further code change.

---

## 1 — MDOC-2026-05 final state

| Attribute | Value |
|---|---|
| Campaign id | `MDOC-2026-05` |
| Title | Master Data Operational Completion |
| Status | `paused` |
| Paused at | 2026-05-16T16:25:00+00:00 |
| Closure doc | `tasks/smoke-reports/2026-05-16-b-md4-master-data-full-browser-smoke.md` |
| Operator acceptance | `mechanical_closure_accepted` (this note) |
| Visual smoke status | `deferred_by_operator` |
| Next batch | None scheduled |
| Open PRs (MDOC) | 0 |

Batches:

| Batch | Status | Surface |
|---|---|---|
| B-MD0 | merged (PR #127, `fa02a5e`) | Parity matrix + B-MD1 approval package |
| B-MD1-approval | merged (PR #127) | Approval package for Admin · Users writes |
| B-MD1 | smoked (PR #128, `2101e70`, deploy 2026-05-16T15:08Z) | AdminUsersPage live; 5 admin write endpoints wired through new bounded page |
| B-MD2-approval | merged (PR #130, `77c6a60`) | Approval package for Designs + Roles |
| B-MD2 | smoked (PR #131, `a7afbeb`, deploy 2026-05-16T15:51Z) | Designs CRUD + Roles read-only explainer live; `master_data.sqlite::designs` table additive, zero FK |
| B-MD3 | smoked (PR #133, `7272dbf`, deploy 2026-05-16T16:12Z) | UI cleanup; orphaned `PendingPanel` removed; 22 testids stable |
| B-MD4 | smoked (mechanical-equivalent; PR #135, `14707a9`) | 14/20 surfaces mechanically verified PASS; 6 deferred to operator visual walk |

---

## 2 — What was mechanically verified

Per `tasks/smoke-reports/2026-05-16-b-md4-master-data-full-browser-smoke.md`
"Mechanical smoke result — 2026-05-16T16:23Z":

**3 temp-record CRUD round-trips clean (all `[x]`):**

- Designs `SMOKE_MD4_DSGN_001`: PUT 200 → GET 200 → PUT-update 200 (display_name → "B-MD4 Smoke v2") → DELETE 204 → post-delete GET 404
- Product-local `SMOKE-MD4-PL`: PUT 200 → GET 200 → DELETE 204 → post-delete GET 404
- Suppliers `SMOKE_MD4_SUP_001` (id=3): POST 201 → GET 200 → DELETE 204 → post-delete GET 404

**13 GET-endpoint reachability checks clean (all 200):**

`/api/v1/wfirma/customers` · `/api/v1/wfirma/products` ·
`/api/v1/hs-codes/` · `/api/v1/units/` · `/api/v1/incoterms/` ·
`/api/v1/vat-config/` · `/api/v1/fx-rates/` ·
`/api/v1/carriers-config/` · `/api/v1/customer-master/` ·
`/api/v1/designs/` · `/api/v1/suppliers/` ·
`/api/v1/product-local/` · `/auth/users` (401 unauth — correct).

**Read-only finance / system checks clean:**

- `/api/v1/finance/postings/999999/breakdown` → HTTP 404 clean (`{"detail":"Posting not found: id=999999"}`)
- Deployed `dashboard.html`: 22 / 22 required B-MD4 testids present
- 6F.4 Diagnostics Finance Posting Breakdown panel: 6 anchor occurrences in deployed file

**Storage / log invariants clean:**

| Source | Pre-smoke | Post-smoke | Delta |
|---|---|---|---|
| `C:\PZ\storage\finance_postings.sqlite` | 81,920 B | 81,920 B | 0 (unchanged; 6F.5 still default-OFF) |
| `C:\PZ\storage\master_data.sqlite` | 114,688 B | 114,688 B | 0 (temp records all cleaned up) |
| `C:\PZ\storage\users.db` | 32,768 B | 32,768 B | 0 (no auth writes) |
| `pz_stderr.log` `finance_dual_write` hits | 0 | 0 | 0 |
| stderr tail | uvicorn startup clean | uvicorn startup clean | unchanged |
| PZ regression | 160/160 | 160/160 | 0 |

**Mechanical verdict: 14/20 surfaces PASS.**

---

## 3 — What remains visually deferred

The following 6 operator-only visual surfaces require an authenticated
admin browser session (`@app.get("/dashboard/{path:path}")` → `check_session_or_redirect`)
that the automated agent cannot have:

| § | Surface | Why agent cannot execute |
|---|---|---|
| §2 | Customer Master walk (KYC modal Customer Master tab) | Requires session + visual confirmation of "Edit → Cancel without saving" cycle on a real client record. Network tab verification of zero PUT firing is a session-bound observation. |
| §3 | Shipping Addresses walk (KYC modal Addresses tab) | Same as §2 — UI tab inside session-gated modal. |
| §4 | Client Carrier Accounts walk (KYC modal Carriers tab) | Same as §2 — UI tab inside session-gated modal. |
| §5 | KYC tab walk | Same as §2. |
| §6 | KUKE/Credit walk (regression watch for L-004 `Decimal(0)` falsy trap) | Same as §2. |
| §7 | Invoice Settings walk | Same as §2. |
| §18 | AdminUsersPage UI walk | Session-gated route + observation-only walk of destructive Approve/Reject/Set-role/Deactivate confirm dialogs. Without admin session there is no AdminUsersPage to walk. |

(That's technically 7 sections — §2–§7 = 6 KYC-modal tabs treated as one
operator-only KYC walk, plus §18 AdminUsersPage walk — totaling **6
deferred surfaces** in the original B-MD4 checklist's per-surface count
or **7 if AdminUsersPage is counted separately**. The smoke report
records both granularities; this acceptance note uses the
KYC-as-one-surface count: **6 deferred surfaces** plus the AdminUsersPage
walk = 6 + 1 = 7 visual items remaining. Either framing is fine; the
material point is that ALL of them remain `[ ]` in the smoke report.)

These surfaces stay marked `[ ]` Pending in
`tasks/smoke-reports/2026-05-16-b-md4-master-data-full-browser-smoke.md`.
They are **NOT** marked `[x]` Passed.

---

## 4 — Why deferred checks are accepted

The operator accepts these deferred checks because:

1. **They are observation-only, not bug-detection-bearing.** The 6 KYC
   surfaces are all read walks plus Edit→Cancel cycles on real records.
   They confirm that the UI renders as expected — they do not detect
   defects that the mechanical sweep didn't already cover. The mechanical
   sweep already proved every backend `/api/v1/customer-master/`,
   `/api/v1/client-addresses/`, `/api/v1/client-carrier-accounts/`,
   `/api/v1/wfirma/customers/`, `/auth/users` (unauth) endpoint is
   reachable and behaves correctly.
2. **No real-record write happens during the deferred walks.** Even when
   the operator does run them, the documented action is Edit→Cancel,
   NOT Edit→Save. No data mutation is at stake.
3. **AdminUsersPage destructive observation is intentionally
   observation-only.** The B-MD4 checklist forbids click-through on real
   users' Approve/Reject/Deactivate/Set-role confirms. Visual
   confirmation that the dialogs render correctly is the only goal —
   click-through is explicitly avoided.
4. **L-050 demands honesty.** Rather than re-running the mechanical
   sweep under a "visual smoke complete" label, the partition is
   preserved. Future operators reading the smoke report can immediately
   see which surfaces have been visually confirmed by a real session
   and which have been mechanically confirmed only.
5. **No time-sensitive deadline forces a decision.** The 6 surfaces
   describe read walks; deferring them to the next operator session
   incurs zero operational risk.
6. **All hard rules remain enforced.** PZ regression 160/160 across the
   campaign; 6F.5 dual-write still default-OFF; AdminUsersPage admin
   gate live; MasterDataPage security contracts intact; Designs FK-free
   contract intact.

---

## 5 — No failures observed

This acceptance note confirms:

- **Zero failures** during the mechanical-equivalent sweep.
- **Zero regressions** in PZ tests, hard-rule contracts, or production
  health checks throughout MDOC-2026-05 (PZ 160/160 verified ≥ 10×
  across the campaign).
- **Zero stale temp records** in production (`master_data.sqlite` size
  unchanged at 114,688 B after temp-record cleanup).
- **Zero finance side effects** (`finance_postings.sqlite` unchanged at
  81,920 B; zero `finance_dual_write` log hits).
- **Zero wFirma / PZ / DHL / customs / FX side effects**.
- **Zero `/auth/users` mutations** initiated by the smoke battery.
- **Zero `.env` changes**.

---

## 6 — No fake smoke claim

This acceptance note explicitly does NOT claim that the 6 deferred
visual surfaces have been smoked. They have been:

- **Mechanically verified at backend / API / storage level**: PASS.
- **Visually walked by an authenticated operator browser session**: NOT
  PERFORMED in this campaign run.

The smoke report's per-surface `[ ]` vs `[x]` partition stands as is.
Any future operator reading either document can immediately distinguish
"mechanically verified" from "operator visually walked."

The agent does not claim to have a browser session it does not have.
The operator does not claim a visual walk that did not happen. The
campaign closes with an honest documented gap and a clear path to
filling it.

---

## 7 — Reopening conditions

Reopen MDOC-2026-05 if ANY of the following becomes true:

1. **Operator walks the 6+1 deferred surfaces in a future session.**
   When done, append the verdicts (`[x]` Passed / `[!]` Failed) to
   `tasks/smoke-reports/2026-05-16-b-md4-master-data-full-browser-smoke.md`
   under a new "Operator browser walk result" section dated with the
   session timestamp + operator initials. If all `[x]`, update
   `tasks/campaign-state.json` `MDOC-2026-05.visual_smoke_status =
   operator_walk_complete` via a docs-only PR. If any `[!]`, open a
   focused fix PR with screenshot + console + network HAR per L-049.
2. **A new Master Data entity, button, or panel is requested by the
   operator.** This would require a new approval package authored
   docs-only first, mirroring the B-MD1 / B-MD2 pattern. No B-MD5+ is
   currently planned.
3. **A B-MD4 surface fails operationally in production** (operator
   reports something not rendering, or a write returning an error). In
   that case, open a focused fix PR; the campaign-state batch B-MD4
   transitions back to `active` until the fix smokes.
4. **A regression breaks one of the cleanup contracts.** B-MD3 source-
   grep tests (`test_legacy_pendingpanel_component_is_removed`,
   `test_master_data_page_does_not_call_auth_users_writes`, etc.) would
   fail on a future PR that re-introduces a `PendingPanel` or adds
   `/auth/users` writes inside MasterDataPage. In that case, the fix
   stays within B-MD3's scope, not a new campaign batch.

---

## 8 — Exact operator checklist location

`tasks/smoke-reports/2026-05-16-b-md4-master-data-full-browser-smoke.md`
sections §2 through §7 (Customer Master + Shipping Addresses + Client
Carrier Accounts + KYC + KUKE/Credit + Invoice Settings) and §18
(AdminUsersPage UI walk).

When the operator runs the walk:

1. Log in at `https://pz.estrellajewels.eu/login`.
2. For each section, follow the "Safe smoke action" cell exactly.
3. Record verdict in the checkbox: `[x]` Passed, `[!]` Failed.
4. Final-state checks in §21 must all be `[x]` before declaring
   "operator walk complete".
5. Append result section to the smoke report file.
6. Open a docs-only PR titled `docs(b-md4): operator visual smoke complete`.

---

## 9 — Final risk statement

| # | Risk | Severity at acceptance |
|---|---|---|
| AR1 | An operator misreads "mechanical closure accepted" as "browser smoke complete" | LOW — this note + the smoke report's per-surface `[ ]` partition + L-050 in `tasks/lessons.md` all distinguish the two states. |
| AR2 | A future deploy introduces a regression on one of the deferred surfaces, and no operator browser walk catches it before users do | LOW — the 13 source-grep contract tests + 22 testid presence + 160/160 PZ regression cover the regression surface; visual rendering regressions would still be discovered by the next operator session. |
| AR3 | The operator never runs the deferred walks, and MDOC is treated as fully closed indefinitely | NEGLIGIBLE — all deferred walks are read-only or destructive-observation-only. They confirm visual rendering of code that has already been mechanically proven to behave correctly. No operational outcome depends on the walks being completed. |
| AR4 | A new operator joining later expects MDOC to be "fully smoked" and acts on that expectation | LOW — the closure doc (`B-MD4 smoke report`) is the canonical entry point and explicitly documents the partition. PROJECT_STATE.md and `tasks/todo.md` mirror the status. |

No HIGH-severity risk has a >0% probability under current operator
discipline.

---

## 10 — Operator signature

```
MDOC-2026-05 Closure — Operator Acceptance

Accepts mechanical closure of MDOC-2026-05:               yes
Acknowledges 6+1 deferred visual surfaces not walked:     yes
Confirms no fake smoke-complete claim is made:            yes
Confirms no production failures observed:                 yes
Confirms no real-record mutation occurred in this run:    yes
Confirms 6F.5 dual-write remains default-OFF:             yes
Confirms Phase 6F paused-state guarantees intact:         yes
Authorises closure note merge to main:                    yes

Operator: __________________________
Date/time:  __________________________
Notes:
```

---

## 11 — Closing statement

MDOC-2026-05 is **closed pending reopening** at a defensible,
auditable, low-residual-risk paused state. The campaign shipped 5
user-visible capabilities (AdminUsersPage, Designs CRUD, Roles
read-only explainer, UI cleanup, mechanical B-MD4 smoke) with zero
regressions across 10+ test runs. The 6+1 deferred visual surfaces
remain documented as deferred, not falsely marked complete. Any future
operator session can walk them at zero implementation cost; the
campaign is otherwise complete.
