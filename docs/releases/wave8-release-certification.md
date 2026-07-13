# EJ Dashboard V2 Stabilization — Wave 8 Release Certification

**Base:** `origin/main` `37198c7d` (Waves 1–7 + user-admin audit-logging)
**Merged release SHA (origin/main after #909→#910→#911→#912 squash):** `13bf8d4c`
**Provisional detached candidate (pre-merge):** `88ade86d`
**Certification date:** 2026-07-13
**Status:** ⛔ **MERGED to `origin/main` @ `13bf8d4c` (#909→#910→#911→#912); re-certified post-merge (zero Wave-8 regressions). Awaiting operator-approved `/deploy`. No production write occurred.**

This certification describes the **exact combined candidate** `88ade86d`, assembled from `origin/main` + the four reconciled Wave-8 PRs, verified as one tree — not any earlier state.

---

## 1. Reconciliation outcome — the PR set (all MERGEABLE, pairwise coherent)

| PR | Head | Owns | Files |
|---|---|---|---|
| **#909** | `8cbf89e6` | Wave-8 cert + RF-1/RF-2 (client/supplier modal: "Save to Customer Master" label + `var(--overlay)`) | client-detail, supplier-detail, this cert doc |
| **#910** | `0b0a6714` | Security hardening (doc delete/replace + wFirma sync-apply role gates, Windows reserved-name, traversal parity, last-admin guard) **+ self-contained Wave 5-8 RBAC allowlist reconciliation** incl. Customer-Master VAT `_write_auth` | routes_auth/customer_master/intake/upload/wfirma_capabilities + test_wave8_security_hardening + test_rbac_structural_allowlist |
| **#911** | `de6f9e0b` | Customer Master **V2 deep-link authority cutover** (`/v2/master?entity=clients&contractor_id=<id>` → Clients tab + ClientDetailModal); legacy `customer-master-v2.html` refs repointed (reference-only) | routes_proforma, proforma-detail-v2.html, shipment-detail.html, master-page.jsx, test_freight_authority_blocker_repair |
| **#912** | `50f3d15b` | Frontend hygiene: **`GOLD+'22'` invalid-CSS fix** (→ `var(--accent-subtle)`), filter testids, design tokens, honest `WRITE_DISABLED_REASON` fallback | client-detail, dashboard-page, master-page, shipment-detail + test_wave8_frontend_polish_contract |

**Superseded / not shipped:** `claude/bold-wing-038fac` `1982d6db` (RBAC 5-7) — **DUPLICATE**, subsumed by #910's `0b0a6714` (RBAC 5-8; CM-VAT byte-identical). Not integrated.

**Overlaps resolved (clean 3-way, both authorities preserved):**
- `client-detail.jsx` = #909 (save label ×2 + overlay ×2) **+** #912 (error-banner `var(--badge-red-bg)` ×3).
- `master-page.jsx` = #911 (deep-link `contractor_id` ×17) **+** #912 (honest fallback text).
- `test_rbac_structural_allowlist.py` = **#910 only**.
- `GOLD+'22'` corrected **exactly once** (#912).

---

## 2. Final merge order (from real heads)

1. **#909** `8cbf89e6`
2. **#910** `0b0a6714`
3. **#911** `de6f9e0b`
4. **#912** `50f3d15b`
5. Certification refresh — **included in #909** (this document); no separate PR.

Order verified by building the detached candidate in this sequence with **zero conflicts**.

---

## 3. Verification on the exact combined candidate `88ade86d`

| Gate | Result |
|---|---|
| Golden (`test_pz_regression.py`) | **160/160** ✅ |
| Smoke (`pytest -m smoke`) | **63 passed, 1 skipped** ✅ |
| Combined targeted battery (RBAC, security-hardening, freight/deep-link, frontend-polish contract, money, capabilities, CSV, documents, timeline, products/designs, remaining-masters, auth-audit) | **126 passed** ✅ |
| Babel compile (client-detail, supplier-detail, master-page, dashboard-page, shipment-detail) | ✅ all 5 |
| Overlap proof (grep) | client-detail = #909+#912 ✅ · master-page = #911+#912 ✅ · `GOLD+'22'` = 0 ✅ |

**Full-suite handling:** a raw un-sandboxed full `service/tests` run on the merged-main-equivalent returned **18316 passed / 1431 failed / 72 skipped** (2:52:19, exit 0). This is **not a release verdict** — it is dominated by cross-test storage-leak pollution and **network/live-service-dependent** suites (`test_zc429_recovery_flow`, `test_zc429_lineage_panel`, `test_wfirma_pz_supplier_resolution`) that fail without the `#898` conftest sandbox + live wFirma/email. The **authoritative** full-suite classification with the sandbox, against `.claude/contracts/test-baseline.md`, is executed by the `/deploy` QA gate at deploy time.

### 3.1 Post-merge re-certification on the actual merged SHA `13bf8d4c`

Overlaps confirmed survived the four squashes (grep on `origin/main`): client-detail = #909 label(×2)+overlay(×2)+#912 banners(×3), no stale rgba; master-page = #911 deep-link `contractor_id`(×17)+honest fallback, roles fallback = the real `STATIC_ROLES_NAMES` (fake matrix = 0); dashboard `GOLD+'22'` = **0**, `var(--accent-subtle)` + filter testid present; shipment-detail `timelineMilestones`(×2)+SAD wiring intact; RBAC allowlist test = #910's Wave 5-8 version.

| Gate | Release `13bf8d4c` | Base `37198c7d` (A/B) | Verdict |
|---|---|---|---|
| Golden | **160/160** ✅ | — | pass |
| Smoke | **63 passed** ✅ | — | pass |
| PZ floor (`test_*pz*.py`) | **1006 passed** (≥257) · 36 failed | **36 failed / 1006 passed — identical** | floor met; 36 A/B-pre-existing |
| Carrier floor (`-k carrier`) | **911 passed** (≥584) · 17 failed | **17 failed / 910 passed — identical** | floor met; 17 A/B-pre-existing |
| Targeted Wave 1-8 + sec + RBAC + freight + audit battery | **202 passed** · 8 failed | **8 failed — identical** (`test_cm_apply_*`, 401 admin-gated) | 8 A/B-pre-existing |
| Babel (5 JSX) | ✅ | — | pass |
| PII scan (changed files) | clean | — | pass |

**Zero Wave-8 regressions.** Every failure on `13bf8d4c` (cm_wfirma-apply 8, carrier 17, PZ 36) fails **identically** on the pre-Wave-8 base `37198c7d` — A/B-proven pre-existing (not introduced by #909/#910/#911/#912). The `#898` storage-sandbox conftest is present. No **unexpected ERROR**. The full sandboxed count vs `test-baseline.md` remains the `/deploy` QA gate's authoritative check.

---

## 4. Browser certification (candidate `88ade86d`, isolated non-prod storage)

- **Exact final candidate served + booted clean — zero console errors** (verified on `88ade86d`).
- **Per-PR visual verification (same code, now clean-merged):** #909 client/supplier modal fixes + Wave-8 combined-state (13 master tabs, capability contract, real-8 roles, honest states, 0 console errors); #911 deep-link `?entity=clients&contractor_id=<id>` opens Clients + ClientDetailModal and supplier-entity selection (browser-verified on its branch, GET-only); #912 token/testid changes (Babel + contract-test verified).
- **Constraint:** the deep-link **live** re-run on the combined SHA was limited by the detached-worktree preview (empty storage + query-param navigation guard); its behaviour is covered by #911's branch verification + the clean-merge proof (deep-link code present ×17, coexisting with the polish fallback). This is the one item to spot-confirm during the operator's `/deploy` browser step against real data.

---

## 5. Findings classification

- **(a) Fixed in this candidate:** RF-1/RF-2 (#909), the 2 MEDIUM + 4 LOW security items minus LOW-3 (#910), RISK-1 CM deep-link (#911), RF-3/5/6/7/8 + `GOLD+'22'` (#912).
- **(b) Honest-unavailable (correct as-is):** VAT wFirma sync, carrier live-ping, Roles CRUD, user edit/delete, CSV where not built, FX reference-only; Reports/Admin/Shipping-Ops MOCK pages (out of Waves 1–7 scope).
- **(c) Documented posture / deferred:** V1 SPA still live at `/dashboard/` (documented V1-frozen migration posture); security LOW-3 role-enum exposure (REJECTED — the Users/Roles tabs consume the enum); `_callM` X-Operator gap (chip `task_46fe6fbe`).
- **Pre-existing baseline red (A/B-confirmed on base, no carrier file touched):** `test_carrier_runtime_does_not_read_local_carriers_config`.
- **Pre-existing PII note (NOT introduced here):** `client-detail.jsx` NIP/VAT/EORI placeholders (`PL5252312345`, from Wave 5, already in main) — flagged for a separate sanitisation decision.

---

## 6. Production delta, backup, rollback

- **Target (release):** `origin/main` **after merging #909 → #910 → #911 → #912** (= content of `88ade86d`).
- **Rollback anchor:** the **currently-deployed `C:\PZ` SHA — operator must confirm** (deploy-guard blocks reading it here). Last recorded prod-verified SHA per PROJECT_STATE was `b1caafd4`; the 7 V2 waves + Wave-8 PRs + ~20 intervening merges have landed since, so the real deploy delta is large — the `/deploy` gate diffs against the live tree for the exact set.
- **Deploy plan (Lesson J verified):** **no root-level engine files changed** → the standard **single** `service/app → C:\PZ\app` robocopy covers the release; no separate engine sync.
- **DB schema:** additive columns/tables applied by each `*_db.py` init on service start — no manual migration; confirm on the persistence gate.
- **Hash verification:** per deploy-source discipline, hash-verify the sync source at the final merged SHA **before and after** robocopy; the `/deploy` release-manager emits the authoritative manifest.
- **Rollback card:** (1) back up `C:\PZ\app` → `C:\PZ\app.bak.<ts>` + record deployed SHA; (2) deploy = stop `PZService` → verify STOPPED → robocopy (`/XD storage`) → start → verify RUNNING (health 200); (3) rollback = stop → restore `app.bak.<ts>` (or `git checkout <baseline>` + re-robocopy) → start → verify; storage (`C:\PZ\storage`) untouched, no data rollback.

---

## 7. Go / No-Go

**GO — conditional on** merging the four PRs in order + the full 7-agent `/deploy` gate + explicit operator approval + operator-confirmed deployed baseline SHA.

- ✅ All 7 waves + Wave-8 reconciliation form one coherent candidate `88ade86d`; every accepted fix exists exactly once; no duplicate authority/route/writer; overlaps preserve both authorities; golden 160/160 + 126 targeted + smoke 63 green; zero console errors on the exact candidate.
- ⛔ **This is a local integration candidate — not pushed, not deployed. No production write occurred; no service restart; `C:\PZ` untouched.** The operator performs all merges and the deploy.
