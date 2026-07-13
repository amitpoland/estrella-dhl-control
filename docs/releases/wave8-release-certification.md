# EJ Dashboard V2 Stabilization — Wave 8 Release Certification

**Certified merged state:** `origin/main` @ `37198c7d` (Waves 1–7 + user-admin audit-logging)
**Wave-8 additions:** `feat/v2-wave8-release-cert` @ `b813d53f` (2 cert-fix commits — NOT yet in main)
**Certification date:** 2026-07-13
**Status:** ⛔ **STOP — awaiting explicit operator approval before any production write.**

The V2 migration + stabilization program (7 feature waves) is code-complete and merged.
This is a certification pass, not a feature wave. No module was reopened except for the
two certification-proven concrete frontend defects fixed inline (RF-1, RF-2).

---

## 1. Merged authority state (reinspected)

| PR | Wave | Squash SHA |
|---|---|---|
| #902 | 1 — money formatter | c15b6d93 |
| #903 | 2 — New Shipment → B1 intake | 95636921 |
| #904 | 3 — SAD + Documents identity | 3efaf889 |
| #905 | 4 — Timeline read-model | a60c854f |
| #906 | 5 — Clients + Suppliers CRUD/CSV/sync | 5d0b43ea |
| #907 | 6 — Products consolidation + Designs CRUD | f0b1a306 |
| #908 | 7 — Remaining masters + capability contract (+ auth audit-logging) | 37198c7d |

All 7 PRs **MERGED**; **0 open PRs**; working tree clean. The #908 squash captured the
user-admin audit-logging (routes_auth `_audit_user_action`, core/audit VALID_OPS user ops,
test_auth_admin_audit.py — all present on main).

---

## 2. Regression (documented gate)

| Suite | Result |
|---|---|
| Golden (`test_pz_regression.py`) | **160/160** ✅ |
| Smoke (`pytest -m smoke`) | **63 passed, 1 skipped** ✅ |
| Wave suites (money, intake, documents, timeline, csv, products/designs, capabilities, remaining-masters, auth-audit) | **all green** ✅ |
| Babel compile (all changed JSX) | ✅ |
| Full 19k service suite | inconclusive in-window (un-isolated network tests stall) — authoritative pass/fail count runs in the `/deploy` QA gate against `.claude/contracts/test-baseline.md` |

**Known pre-existing baseline red (A/B-confirmed identical on base):**
`test_master_data_hard_rules.py::test_carrier_runtime_does_not_read_local_carriers_config`
— a carrier-runtime file references `carriers_config`; **not introduced by any wave**, no
carrier-runtime file was touched. → documented baseline (not a release regression).

---

## 3. Browser certification (authenticated, isolated non-prod storage)

Re-certified on merged main; **zero console errors** across every interaction.

| Workflow | Result |
|---|---|
| App boot / SPA shell | ✅ clean |
| Dashboard landing | ✅ honest MOCK banner (design-time placeholder, correctly labeled) |
| Master Data — all 13 tabs render | ✅ (Clients 2, Suppliers 2, Products 9, Designs, HS, FX 0, VAT 0, Carriers, Box Profiles, Incoterms, Units, Users, Roles) |
| Capability contract loads + drives tab availability | ✅ |
| Roles tab shows the real 8 system roles (no fake manager/operator matrix, immutable) | ✅ |
| Honest "Backend pending" / unavailable states | ✅ accurate |
| Shipment Detail — Documents identity + Timeline read-model | ✅ verified per-wave on content-identical merged code |
| New Shipment intake, CSV import preview→apply, product create-and-adopt confirm gate | ✅ verified per-wave; fiscal gates honored |

_Users admin actions are code-verified; `/auth/*` returns 401 under the API-key session in the
verify env, so they were not exercised in-browser (an env auth boundary, not a defect)._

---

## 4. Findings classification

### (a) Real defects fixed before release (inline, this wave)
- **RF-1** — `client-detail.jsx` save/confirm buttons said "Save Changes" → **"Save to Customer Master"** (§7 write-target naming). ✅ fixed `b813d53f`.
- **RF-2** — `client-detail.jsx` + `supplier-detail.jsx` modal overlays used bare `rgba()` → `var(--overlay, …)` (dark-mode theme break). ✅ fixed `b813d53f`.

### (b) Honest-unavailable capabilities (correct as-is, no action)
- VAT wFirma sync (no endpoint), carrier live-ping (config-only), Roles CRUD (immutable), user edit/delete (no endpoint), CSV where not built, FX reference-only.
- Reports / Admin / Shipping-Ops V2 pages serve MOCK data behind an honest banner — **out of Waves 1–7 scope** (not migrated), not a duplicate-authority violation.

### (c) Pre-existing / deferred to chips (non-blocking)
| Finding | Source | Chip |
|---|---|---|
| Security: 2 MED (doc delete/replace + wFirma customer sync-apply role gates) + 4 LOW (Windows reserved names, batch_id traversal parity, role-enum exposure, admin self-demotion) | security cert | `task_2fd1c281` |
| Architecture RISK-1: backend `routes_proforma.py:8045` deep-links to legacy `customer-master-v2.html` (V2 has no `?contractor_id=` deep-link yet) | architecture cert | `task_f28d0647` |
| Frontend §3/§8: hardcoded hex in dashboard/shipment-detail/client-detail, missing filter-button testids, stale `WRITE_DISABLED_REASON` text | frontend cert | `task_6c57a894` |
| `GOLD + '22'` → invalid CSS `var(--accent)22` (transparent bg) in dashboard-page.jsx | frontend cert (RF-4) | `task_d9bc6ba2` (operator-started earlier) |
| `_callM` sends writes without X-Operator if the name prompt is dismissed (Waves 5–7) | Wave-6 security | `task_46fe6fbe` |

### Architecture posture (documented, not a defect)
- **RISK-3** — the V1 SPA (`dashboard.html`) remains live at `/dashboard/`. This is the **documented V1-frozen migration posture** (V2 = consolidation authority per the FRONTEND AUTHORITY CONSTITUTION; full V1 retirement is a separate future decision). RISK-1 is the same class (incomplete V1→V2 cutover).

---

## 5. Reviews (architecture / security / frontend)

| Review | Verdict |
|---|---|
| **Security** (security-permissions, aggregate Waves 1–7) | **CLEAN — no CRITICAL/HIGH.** Confirmed: no secrets, `password_hash` absent from responses/logs/audit, wFirma fiscal write-gates intact, XSS allowlist + nosniff/CSP on inline serve, CSV formula-injection neutralised + system-column block + no soft-delete leak, parameterised SQL, `audit_safe` on all writes. 2 MED + 4 LOW → `task_2fd1c281`. |
| **Frontend-flow** (aggregate V2) | **ISSUES** — 2 concrete defects fixed inline (RF-1/RF-2); rest §3/§8 polish → chips. No fake readiness, honest-unavailable accurate, capability contract drives writes, Lesson-M compliant, confirm-before-destructive present. |
| **Architecture / authority** (frontend-authority-inspector) | **RISKS FOUND** — capability contract CLEAN (single consumer, no hardcoded availability); every wave-touched module verified ONE-AUTHORITY. RISK-1 (legacy deep-link) + RISK-3 (V1 live) = incomplete-cutover posture → `task_f28d0647`. |

---

## 6. Production delta, backup, hashes, rollback

### Delta
- **Target (release):** `origin/main` `37198c7d` **+ Wave-8 fixes** (`feat/v2-wave8-release-cert` `b813d53f`, RF-1/RF-2 + this cert) — **merge the Wave-8 PR into main first**, then deploy `main`.
- **Baseline (rollback point):** the **currently-deployed SHA on `C:\PZ` (operator must confirm)**. Per PROJECT_STATE the last recorded prod-verified SHA was `b1caafd4`; **many PRs (the 7 V2 waves + ~20 intervening merges) have landed since**, so the real deploy delta is large — the `/deploy` gate diffs against the live tree for the exact set.
- **Footprint (this program):** 7 wave commits, **35 files under `service/`** (+6845/−526). Backend routes (auth, customer_master, intake, master_data, suppliers, upload, wfirma_capabilities, proforma), services (master_csv, timeline_milestones, document_db, customer_master_db, packing_db, +schema), core/audit, main.py; V2 frontend (master-page, shipment-detail, modals, pz-api, dashboard-page, + new supplier-detail/design-detail/master-record-edit, components, index.html); tests.

### Deploy plan (Lesson J verified)
- **NO root-level engine files changed** (`pz_import_processor.py`, `polish_description_generator.py`, `pz_calculator.py`, `customs_description_engine.py`) → the standard **single** `service/app → C:\PZ\app` robocopy covers the entire release. **No separate engine sync required.**
- **DB schema:** changes are **additive** (`document_db` is_current/superseded_by; new tables/columns in customer_master/packing/proforma-link/warehouse dbs) applied by each `*_db.py` init on service start — **no manual migration**. Confirm on the persistence gate.

### File-hash anchors (target `37198c7d`; regenerate against final merged SHA at sync time)
```
routes_auth.py        01d61d940ff0bff300d2a4fa616718ce458c6eb6
routes_master_data.py 3a9f8049b9d4d78c600f034f49eb10c9b0887181
routes_upload.py      7d4c86bbe35163952a8ac60517114195d55de891
core/audit.py         e5d882b000f22cce6799cd93d1a76bcb98c4aaec
main.py               10453a23a2d8103a61266d388f5da138676b9b71
static/v2/master-page.jsx        19054dc3a06a42fa7b6ccb27f32713350f312200
static/v2/master-record-edit.jsx e0ee7023e9c1762a4254d0635991331e7465a5d9
```
Per deploy-source discipline: hash-verify the sync source at the final SHA **before and after**
robocopy; the `/deploy` release-manager emits the authoritative full manifest.

### Backup + rollback card
1. **Before sync:** back up `C:\PZ\app` (robocopy mirror to `C:\PZ\app.bak.<yyyymmdd-hhmm>`), and record the current deployed SHA.
2. **Deploy:** stop `PZService` (NSSM) → verify STOPPED → robocopy `service/app → C:\PZ\app` (`/XD storage` deploy-hygiene) → start → verify RUNNING (health endpoint 200).
3. **Rollback (if verification fails):** stop `PZService` → robocopy `C:\PZ\app.bak.<ts> → C:\PZ\app` (mirror) OR `git checkout <baseline-SHA>` in the deploy source + re-robocopy → start → verify RUNNING. Storage (`C:\PZ\storage`) is untouched by deploy (`/XD storage`), so no data rollback needed.
4. **Post-deploy verify:** capability endpoint 200; a master-tab read; one create+auto-refresh; scheduler/webhook health; no new stderr.

---

## 7. Go / No-Go

**Recommendation: GO — conditional on (a) merging the Wave-8 PR into main and (b) the full 7-agent `/deploy` gate + explicit operator approval.**

- ✅ All 7 waves merged; capability/authority ONE-AUTHORITY for every wave module; security CLEAN (no HIGH); browser cert clean (0 console errors); golden + smoke + wave suites green; 2 concrete frontend defects fixed.
- 🔶 Non-blocking follow-ups tracked in chips (`task_2fd1c281`, `task_f28d0647`, `task_6c57a894`, `task_d9bc6ba2`, `task_46fe6fbe`).
- ⛔ **Production write is operator-only.** This certification performs **no** production write. Deploy proceeds only via `/deploy` (7-agent gate) after explicit operator approval and operator confirmation of the currently-deployed baseline SHA.
