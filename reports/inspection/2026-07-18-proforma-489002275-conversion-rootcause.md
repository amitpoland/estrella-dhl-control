# Pro Forma → Invoice failure — root cause (proforma_id 489002275 / PROF 163/2026)

**Date:** 2026-07-18 · **Investigator:** read-only (no prod writes, no DB mutation, no invoice created)
**Subject:** draft #64, batch `SHIPMENT_1003835895_2026-07_523c9281`, client [redacted] (wfirma_customer_id redacted), 4 lines, 1953.81 EUR.

## Confirmed root cause
The 2026-07-17T10:02:10Z convert-to-invoice attempt (operator "Amit Saniya") called wFirma
`invoices/add`, which returned **`status=ERROR`** with an **empty description**. `wfirma_client`
(wfirma_client.py:1748) raised `RuntimeError("invoices/add wFirma status=ERROR: ")`; the convert route
caught it (routes_proforma.py:4289-4321) and correctly ran `mark_failed`, leaving:
- `proforma_invoice_links` #5: `status=failed`, `invoice_id=NULL`, `invoice_number=NULL`,
  `notes="RuntimeError: invoices/add wFirma status=ERROR: "`, `source_total=1953.81 EUR`.
- `proforma_drafts` #64: `draft_state=posted`, `wfirma_invoice_id=NULL`, `converted_at=NULL` (proforma
  posted fine 2026-07-14 as PROF 163/2026 id 489002275; only the INVOICE conversion failed).

**wFirma-side rejection of `invoices/add` is the cause.** The empty error detail is a secondary
**error-capture defect**: wFirma's `<parameters>`/description on the ERROR was not captured, so the
operator has no reason string. The convert failure also wrote **no `proforma_draft_events` row** (the
draft log jumps from `draft_posted` 07-14 to `product_review_confirmed` 07-17T21:49) — an **audit gap**.

## Did cleanup / deployment / storage replacement / backup restore / storage-path change contribute? — NO (proven)
- The failure is a clean wFirma API ERROR captured in the link `notes`. The code executed, reached the
  live wFirma API, parsed a well-formed ERROR response, and persisted `mark_failed`. A cleanup/storage/
  path problem manifests as ImportError / missing file / "database is locked" / path error — **not** a
  clean wFirma ERROR. Storage, code, and wFirma connectivity all worked at 10:02.
- All draft data + the full 20+ event history + the link row are intact and mutually consistent. **No
  data loss.**
- `STORAGE_ROOT=C:/PZ/storage` (stable, from prod `.env`); the only carrier/path change (#940
  `_carrier_shipment_db_path`) is unrelated to the proforma-links DB.
- The archive copy `C:\PZ-archive\evidence-2026-07-17\...\proforma_links.db` **predates** the 10:02
  convert (it has draft #64 + event #1079 but **not** links row #5) — a normal earlier backup, **not a
  restore over prod**.
- **Verdict: cleanup/deploy/storage/backup/path did NOT contribute.** Single cause: wFirma `invoices/add`
  ERROR.

## Read-only wFirma verification (live GET, safest lookup)
`fetch_invoice_xml("489002275")` → proforma **exists**, `fullnumber=PROF 163/2026`, `type=proforma`,
`total=1953.81`, `currency=EUR`, `date=2026-07-14`. A bounded read-only invoice scan found **no** VAT
invoice back-referencing PROF 163/2026. Combined with the link never capturing an `invoice_id` and
`invoices/add` returning ERROR, the evidence is that **no invoice was created**. (A definitive
exhaustive check needs a contractor-scoped `invoices/find`, which the recovery flow performs at runtime.)

## Complete flow trace (Route → Service → wFirma → Conversion Link → Persistence)
1. **Route** `POST /api/v1/proforma/.../convert` (routes_proforma.py) — privileged-auth gated.
2. **Duplicate guard** `plink.create_pending_link` (proforma_invoice_link_db.py:211) — `proforma_id`
   UNIQUE; raises `ProformaAlreadyConverted` if a row exists.
3. **wFirma** `invoices/add` (wfirma_client.py:1748) → **status=ERROR** → RuntimeError.
4. **Conversion link** `plink.mark_failed` (routes_proforma.py:4295) → link row `failed`, no identity;
   row deliberately **never deleted** (it is the duplicate guard; wFirma might hold a real invoice).
5. **Persistence** proforma_links.db `proforma_invoice_links` #5 + draft #64 unchanged.

## The gap (why this is a dead-end today)
`reconcile_invoice_link` (#939, routes_proforma.py:11751) can repair a `failed` link **only when an
invoice identity is available** — captured on the row, or operator-supplied id/number. For a genuinely
failed conversion **no invoice number exists to supply**, so reconcile blocks at
"no wfirma_invoice_id available" (routes_proforma.py:11939). Re-pressing Convert hits
`ProformaAlreadyConverted` and is **blocked**. So proforma 489002275 is stuck: failed link, no identity,
un-retryable, un-reconcilable. **This is the "failed link without invoice identity" recovery gap.**

## PR — #945 ✅ MERGED & VERIFIED (NOT deployed)
https://github.com/amitpoland/estrella-dhl-control/pull/945 · base `main` · reviewed head `49a24cd1` · 4 files.
Focused delta re-gate on `49a24cd1` — **3/3 reviewers cleared, zero blockers** (security-write-action
REQUIRED resolved, backend-safety B1+R1 resolved, reviewer-challenge VERDICT PASS). Squash-merged by
operator (agent `gh pr merge` fail-closed by pz-deploy-guard) at **2026-07-18T08:24:50Z** →
new origin/main = **`603e00d68d5aa7add56f134a5b2ea1a46032129a`** (parent `4676057` = #940).
**Post-merge verification on merged main** (C:\PZ-main @ 603e00d6): HEAD=603e00d6, tree clean,
`diff --check` clean, squash = the 4 recovery files. Tests on merged main: recovery **19 passed**,
reconcile+recovery **73 passed**, golden **160/160**. deployment_performed: **false**.
**Rollback:** `git revert 603e00d68d5aa7add56f134a5b2ea1a46032129a`.
Next gate: 7-agent deploy gate (operator) before any production deploy. Production recovery of
proforma 489002275 remains a separate operator-gated action (no retry / no invoices/add performed).

## 7-agent pre-deploy gate — ✅ 7/7 PASS, zero blockers (2026-07-18, READY-TO-DEPLOY)
Run against merged main `603e00d6` (read-only; nothing deployed/synced/restarted).
1. git-diff/forbidden-paths — CLEAR (4 files SAFE_CODE/ROUTE_API/TEST_ONLY; no forbidden path; no
   root-engine file → standard `service/app → C:\PZ\app` sync covers it; Lesson J N/A).
2. backend-impact — CLEAR (no new router; `_auth_write` preserved on convert+reconcile retry paths;
   no new dep; no platform import).
3. persistence/migration — CLEAR (no CREATE/ALTER/DROP; `VALID_STATUSES` unchanged; conditional UPDATE
   on existing columns; UNIQUE guard preserved; no migration needed on live proforma_links.db).
4. security/write-action — CLEAR (no creds; no auth downgrade; no injection — proforma_number not in the
   wFirma XML body; discovered id numeric-guarded; parameterized SQL; GET-only discovery).
5. qa/regression — CLEAR (PZ 257/257, Carrier 584/584, golden 160/160; 19-test recovery + 73-test
   reconcile coverage; the 8 broader-suite fails are pre-existing on parent 4676057, outside metered
   suites → GATE-4 disposition in a separate session, chip filed).
6. release-manager/rollback/observability — CLEAR (rollback `git revert 603e00d6 --no-edit`,
   additive-only; deploy source = **C:\PZ-main** (C:\PZ-verify ineligible — not on main); append-only
   audit events + wFirma error-detail capture confirmed).
7. lead-coordinator / reviewer-challenge (final) — **READY-TO-DEPLOY**; both flags dispositioned
   non-blocking.

**Deploy authorized by the gate — NOT executed (operator-only).** Sync source `C:\PZ-main\service\app →
C:\PZ\app` (`/XD storage`, **NO `/MIR`** per release-manager); stop→sync→start PZService; post-deploy
health + probe the new fields with a NOOP proforma id (never 489002275). Production recovery of 489002275
remains a separate operator-gated action.

## Permanent solution — branch `fix/proforma-failed-link-recovery` (NOT merged/deployed)
Single-authority recovery (extends `reconcile_invoice_link` + the convert route — no parallel path),
"discovery-first + explicit operator confirm" (operator-ratified 2026-07-18). Commits `c49770b0`
(feature) + `49a24cd1` (GATE-1 review fixes) off main `4676057`.

**Files changed (3 source + 1 new test, +≈430/−24):**
- `service/app/services/proforma_invoice_link_db.py` — `reopen_for_retry()` (concurrency-safe
  failed→pending conditional UPDATE; never deletes; preserves the note; keeps `proforma_id` UNIQUE).
- `service/app/services/wfirma_client.py` — `find_invoices_for_proforma()` (READ-ONLY orphan discovery
  by description back-reference) + `extract_error_detail()` (surfaces nested wFirma `<errors>`/
  `<parameters>` — fixes the empty-note error-capture gap).
- `service/app/api/routes_proforma.py` — reconcile no-identity branch (discovery: one→verify+mark_issued,
  >1→refused, non-numeric id→refused, none→retry_ready); convert retry acceptance (2b guard exception +
  **code-enforced discovery before invoices/add** + reopen); error-capture; convert-fail / retry-started /
  retry-ready draft events (audit-gap fix).
- `service/tests/test_proforma_failed_link_recovery.py` (new) — 19 tests, six required areas.

**GATE-1 review (backend-safety + security-write-action + reviewer-challenge) — 1 blocker, fixed:**
All three flagged that discovery-first was documentation-only, so a direct `retry_failed_link=true` (esp.
the network-timeout split-brain: add succeeded but the response was lost) could duplicate an invoice.
**Fixed** by code-enforcing the read-only discovery inside the retry branch (invoices/add refused if any
orphan is found — test asserts 0 add-calls). Also fixed: non-numeric discovered id now refuses; the
retry_ready message no longer overclaims; success-path test added. Confirmed-safe by reviewers: duplicate
guard (proforma_id UNIQUE, single row), reopen race-safety (8-thread test, one winner), read-only
discovery, never-delete, all fiscal write gates (privileged auth, confirm token, X-Operator,
create-allowed flag, readiness) intact on the retry.

**Known residual limitations (POST-MERGE follow-ups, documented, non-blocking):**
- Discovery scan is bounded (`_INVOICE_LEDGER_SAFETY_CAP`=5000; no wFirma-side date/contractor filter —
  fields unverified per Phase-C §19). On a very large account an orphan beyond the cap could be missed;
  harden by scoping the find to contractor+recent-date. The create-time re-check reduces reliance on
  operator discipline but shares this bound.
- `mark_failed` overwrites the single `notes` field on a re-failure (the reopen trace survives in the
  append-only draft event log — no audit loss).
- A discovered-orphan reconcile rebuilds the plan without the original convert overrides; a mismatch
  refuses (safe — never wrong-links). A stranded `pending` after a double-failure is repairable via the
  existing reconcile split-brain path.

**Test results:** new suite **19 passed**; existing `test_invoice_link_reconcile` + new = **73 passed**;
root golden **160/160** (engine untouched); affected-surface regression = **0 new failures** (8
convert-series fails are pre-existing on main `4676057`, verified). Pre-commit smoke 63 passed ×2.

**Rollback:** the change is unmerged (branch only) — abandon = delete the branch. If later merged:
`git revert <squash-sha>` (self-contained; additive only — no destructive schema/status migration,
`VALID_STATUSES` unchanged, the failed link remains the duplicate guard).
