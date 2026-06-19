# EJ Dashboard Portal — Platform Remediation Master Campaign

**Status**: PLANNED — awaiting operator approval of backlog dispositions (GATE 4)
**Created**: 2026-06-12
**Audit basis**: 24-agent adversarial audit (workflow run `wf_301c16fc-39e`), verified against `C:\PZ-verify` @ `ff1f4b5` (= origin/main = production)
**Scorecard**: `.claude/memory/scorecards/2026-06-12-platform-remediation-audit.md`
**Owner**: Executive Engineering Lead (orchestration layer) · Operator approves all phase gates

---

## 1. Executive Summary

A 24-agent audit (11 domain auditors + adversarial verifiers + completeness critic) inspected
the platform against the remediation brief. **The platform is materially healthier than the
brief assumed.** Of 12 CRITICAL/HIGH findings raised, after adversarial verification:

| Verdict | Count | Meaning |
|---|---|---|
| **Confirmed actionable** | 2 | Business-write audit-trail gap; Lesson M disabled-button violations in `v2/index.html` |
| Confirmed correct-by-design | 1 | Carrier webhook HMAC custom auth (documented contract) |
| Already governed | 4 | V1→V2 debt (Lesson F), DHL live API (ADR-026 Phase D), outbound UI flag, V1 status-map duplication (freeze) |
| Refuted with evidence | 5 | Test-failure "crisis", test isolation, CI enforcement, rollback complexity, V2 readiness computation |

Major remediation-brief assumptions that are **already done or governed**: Customer Master is
healthy (60+ field schema, resolution authorities wired); mock data eliminated (17/17 V2 pages
WIRED, Atlas closure 2026-06-06); proforma authority is backend-derived (PR #548); reservation
root-cause closed. The real work is: **two compliance hotfixes, a small set of workflow-class
hardening items, the operator's write-enablement priorities (M3/M4/M6), and a supplemental
audit of 9 subsystems (~40% of business logic) the first pass under-covered.**

No code was written this turn, per the brief ("Inspect first. Plan second."). Execution starts
only after operator approves the backlog dispositions and a GATE 2 PR slot frees.

---

## 2. Current State Diagnosis

Classification of every audited surface (12-way taxonomy from the brief):

### Correctly wired (no action)
- All 17 V2 pages (WIRED, 304 data-testids across 22 files); proforma readiness rendered from
  backend authority (`routes_proforma.py:6071-6107`, `proforma-detail.jsx:2046`)
- 69/71 routers registered with consistent `_auth = Depends(require_api_key)`;
  `_WRITE_CAPABLE_ROLES` allowlist (`core/security.py:57`)
- Customer Master: `pick_email` / `resolve_billing_address` / `resolve_delivery_address`
- CarrierCoordinator: idempotency + shadow mode (SIM-* AWBs); label-package generation working
- `process_batch()` single calculation path confirmed; `derive_pz_status` / freight authority /
  SAD invoice authority all single-authority
- Carrier webhook HMAC (`routes_carrier_webhook.py:40-50`) — correct per
  `service/docs/carrier_dashboard_contract.md:362`
- email_service implements Lesson E guards

### Production risk / compliance gap (P0)
- **Lesson G**: `FileResponse` without `no-store` headers at `routes_tracking_db.py:58`
  (tracking XLSX), `routes_dsk.py:291` (DSK PDF), `routes_dashboard.py:2262` (email
  attachments). Compliant counterexamples: `routes_pz.py:1410,1432`, `routes_dhl_clearance.py:3402`
- **Lesson M**: `v2/index.html:662` ('+ Connect Carrier'), `:673` ('↻ Re-probe All'),
  `:684` ('⬇ Export CSV') — disabled with NO title/reason attribute (atlas counterparts comply)

### Unsafe write pattern (P1 — workflow-class)
- 98 services perform writes; only 19 use `timeline.log_event` / `audit_persist`.
  `document_db.py:687` raw `DELETE FROM document_extraction_json`; document_db (25+ writes),
  packing_db (14+), warehouse_db (11+), tracking_db, master_data_db (16+) have no audit hooks.
  Infrastructure exists (proforma_draft_sync, execution_engine, shipment_closure use audit_persist)

### Missing route / dead module
- `routes_reservations.py`: 6 endpoints, **not registered in main.py** — dead module

### Duplicate authority (MEDIUM)
- `_normalize_name` ×3: `customer_resolution_authority.py:60`, `routes_proforma.py`
  (`_normalize_client_name`), `routes_dashboard.py:2424`
- DHL follow-up: legacy `dhl_followup_sla.py` + v2 `dhl_selfclearance_followup_v2.py` coexist,
  routed by `clearance_path` with no documented routing authority owner

### Backend exists, not connected / missing service
- M6 drafts search route missing; M3 (CMR PDF) + M4 (doc generation) DISABLED_WITH_REASON
  (Lesson M compliant); M1 hard delete unimplemented
- No automated SQLite backup; circuit breakers in-memory (reset on restart)
- No outbound AWB tracking-registration path
- N935 XML corruption → unverified, no manual operator entry path
- CN-HSN chapter-level mismatch lacks guided operator workflow

### Workflow bypass (MEDIUM)
- Shipment creation accepts raw `recipient_address` dict, bypassing Customer Master
  `resolve_delivery_address`

### Frontend polish (P3)
- 30+ hardcoded hex colors (`client-detail.jsx:44`, `dashboard-page.jsx:148-226`,
  `estrella-doc-packing.jsx:38-91`); direct `fetch()` bypassing transport
  (`api-status-page.jsx:378`, `master-page.jsx:427`)

### Read-only placeholder / informational (LOW, accepted)
- V1 dashboard ship-to reads stale wfirma_db (`routes_dashboard.py:2437-2469`) — V1 frozen
- ZC429 intake hard-codes `plwawecs@dhl.com` sender (SPOF); VAT validation manual-only
- `email_ingestion_worker.py:196-204` lacks ENV=production assertion (Lesson E property 5)

### Test debt (governed + one real item)
- Baseline isolates 631 enforced passes (218 PZ + 413 carrier); ~1,033 full-suite failures
  governed as OQ4 / Issue #366. **Real item**: CN-HSN classifier 13/35 tests failing
  (Issue #567 test-context drift — exists in PROJECT_STATE.md OPEN QUESTIONS; the verifier's
  "does not exist" claim was a repo-grep error)
- Write-route test coverage thin (only 3 `test_routes_*` files cover POST/PUT/DELETE routes)

### Audit blind spots (Phase 1b scope — ~40% of business logic never audited)
`inventory_state_engine.py` (6-state lifecycle, 63 test files); `sales_packing_matcher.py`;
email ingestion/evidence pipeline (44 files); `finance_postings_db.py` + `finance_dual_write.py`
(Phase 6F); cowork agents (`cowork_coordinator.py` / `decision_engine.py` /
`proposal_engine.py` — **never evaluated against Lesson E**); Zoho layer (73 files);
`pipelines/` (customs/dhl/pz/shipment); `tools/` (22 scripts); root engines
(`customs_description_engine.py`, `pz_import_processor.py`, `polish_description_generator.py` — Lesson J scope)

---

## 3. Authority Map

| Domain | Authority owner | Status |
|---|---|---|
| PZ calculation | `process_batch()` (engine, frozen) | ✅ single path confirmed |
| PZ lifecycle status | `derive_pz_status(audit)` | ✅ single authority |
| Freight/insurance allocation | engine, proportional-by-value | ✅ immutable rule |
| Duty | ZC429/A00 only | ✅ immutable rule |
| SAD invoice reference | `sad_invoice_authority` | ✅ single authority |
| Proforma readiness | backend `routes_proforma.py:6071-6107` | ✅ frontend renders only |
| Customer identity/addresses | `customer_resolution_authority` + resolve_* | ✅ healthy; ❗ shipment-create bypass (B19) |
| Customer name normalization | — | ❗ split ×3 (B5) |
| DHL follow-up routing | — | ❗ no documented owner for clearance_path split (B6) |
| Document lineage | documents.db / packing.db / audit JSON | ❗ fragmented, no single registry (B21) |
| Business-write evidence | timeline/audit_persist | ❗ 19/98 services only (B4) |
| Inventory lifecycle | `inventory_state_engine.transition()` | ⬜ not audited — Phase 1b |
| Finance postings | finance_postings_db + dual_write | ⬜ not audited — Phase 1b |

---

## 4. Architecture Map (verified)

- **Backend**: FastAPI, 71 router modules (69 registered), 201 services, SQLite + JSON audit
  storage. Auth via `require_api_key` + `_WRITE_CAPABLE_ROLES`.
- **Frontend**: V1 (`dashboard.html`, `shipment-detail.html`) FROZEN per Lesson F. V2: vanilla
  HTML + Babel JSX, layered `pz-api.js` (transport) → `pz-state.js` (normalize/cache) →
  `pz-components.js` (primitives) → pages; `dashboard-shared.js` domain-free (verified pure).
- **Carrier**: ADR-026 phasing — `carrier_api_status="pending"` (config.py:318) → 503;
  shadow mode SIM-*; Phase D `NotImplementedError` in `DhlExpressLiveAdapter` (live.py:47-50)
  is an intentional boundary.
- **Deploy**: NSSM `PZService` :47213, Cloudflare tunnel → pz.estrellajewels.eu; robocopy
  `service/app → C:\PZ\app`; root engines → `C:\PZ\engine\` separately (Lesson J).
- **Observability**: Guardian health (`routes_debug.py:95-304`); basic logging (not structured);
  in-memory circuit breakers; **no automated DB backup**.

---

## 5. Agent Organization

**Senior Architect** = `system-architect` agent with phase-gate sign-off authority; every phase
exit requires its written verdict plus operator approval. Substitutions per GATE 5.

| Team | Lead agents | Scope |
|---|---|---|
| Architecture | system-architect, reviewer-challenge | Phase gates, authority rulings, ADRs |
| DHL Platform | dhl-customs, email-evidence-recovery | B6, B12, ZC429/N935, follow-up engines |
| Proforma & Accounting | sales-proforma, wfirma-integration, finance-accounting-logic | B9–B11, M-feature enablement |
| Customer Master | client-contractor-mapping | B5, B19 |
| Documents & Workflow | document-intelligence, database-storage | B1, B4, B21 |
| Frontend Experience | frontend-ui, ux-flow, frontend-flow-reviewer | B2, B15, B16, B18, Lesson M sweeps |
| Backend Platform | backend-api, backend-safety-reviewer, security-permissions | B3, B8, B19, route hygiene |
| QA & Reliability | testing-verification, test-coverage-reviewer, gap-hunter | B14, write-route coverage, chaos program |
| DevOps & Release | deployment-windows-ops, release-manager + 7-agent deploy gate | B7, B17, all deploys |

---

## 6. Execution Plan (6 phases)

Execution is sequenced **behind the locked GATE 2 queue**: #568 (operator merge) → #570 →
SHIPMENT_9938632830 recovery → #522 rebase → #498. Campaign PRs enter only when a slot frees.

| Phase | Content | Exit gate |
|---|---|---|
| **1 — Compliance hotfix** | B1 + B2 + B3 in one small PR ("compliance hotfix") | Tests green incl. new Lesson G regression; browser check on 3 buttons (GATE 6); 7-agent deploy gate |
| **1b — Supplemental audit** | 9 missed subsystems, same adversarial-verification method; cowork agents evaluated against Lesson E | Verified findings merged into this backlog; architect sign-off |
| **2 — Workflow-class hardening** | B4 (audit-trail standard, flagship Lesson I evidence-layer), B5, B6, B7, B8, B19 | Audit-write helper adopted by ≥3 highest-write DBs; backup restore drill passed |
| **3 — Write-enablement** (operator priority) | B9 (M6 search), B10 (M3 CMR), B11 (M4 generate; M1 → REJECTED), B12, B13, B14 | Each M-feature: backend + UI + tests + GATE 6 browser chain |
| **4 — Reliability & chaos** | Chaos game days 1–5 (§8); circuit-breaker persistence decision; B17 | All 5 game days executed with written results; playbooks updated |
| **5 — Polish & closure** | B15, B16, B18, B20, B21 design note; production-readiness re-assessment | Architect final sign-off; campaign closure report + scorecard |

Governance invariants for every phase: never patch a single shipment/AWB; no shipment-specific
logic; no duplicate authority; no state-machine bypass; every fix ships with a regression test,
audit trail, idempotency, and rollback path (Lesson I six-step framework applied per incident).

---

## 7. Risk Playbooks (5)

1. **Stale-artifact / cache regression** — Lesson G checklist: disk file → audit pointers →
   registry rows → resolver → HTTP headers → browser cache. Never patch the generator first.
2. **Unaudited destructive write** — freeze the write path, reconstruct from timeline + audit
   JSON; if irrecoverable, restore from backup (post-B7); file workflow-class fix per Lesson I.
3. **Deploy skew (engine vs app)** — Lesson J: verify `C:\PZ\engine\` with `Select-String`
   content grep, never Python-import; re-sync engine files explicitly; rollback via
   `production_deployment_rule.md:173-194` levels.
4. **Email automation incident** — Lesson E containment: stop worker, verify idempotency log,
   check sent-state durability, assert ENV guard before restart (B8 closes the known gap).
5. **Carrier webhook anomaly** — HMAC validation is correct-by-design; on signature failures
   check secret rotation first; replay protection via idempotency keys; never disable
   validation to "unblock".

---

## 8. Chaos Engineering Program (5 game days — honest single-node scope)

1. **Restart drill**: NSSM stop/start + PYCACHE rule; verify circuit-breaker reset behavior is
   understood and documented (in-memory = known reset).
2. **Backup-restore drill** (after B7): restore SQLite snapshot to scratch path, run read-only
   verification queries; measure RTO.
3. **Circuit-breaker forced-open**: force DHL/wFirma breakers open; verify operator-visible
   degradation messages, no silent failures.
4. **Webhook signature fuzzing**: malformed/expired/replayed signatures against carrier
   webhook; expect 100% rejection with audit entries.
5. **Shadow-mode flag drill**: toggle carrier shadow flags; verify SIM-* isolation; confirm
   `carrier_api_status="pending"` gate never opens unintentionally.

Each game day produces a written result file under `docs/inspection/` and updates §7 playbooks.

---

## 9. Deployment Strategy

Unchanged and reaffirmed: every production sync runs the full 7-agent gate; robocopy
`service/app → C:\PZ\app`; root engines explicitly to `C:\PZ\engine\` (Lesson J);
ASCII-only manifests; post-deploy file-content verification via `Select-String`; smoke +
SHA recorded in PROJECT_STATE.md before next campaign PR opens (sprint-sequencing rule).
Campaign adds: pre-deploy SQLite backup hook once B7 lands.

## 10. Rollback Strategy

Per-deploy rollback command pinned by `deploy_release_manager` to the specific SHA (existing
rule). Schema policy stays additive-only (`CREATE TABLE IF NOT EXISTS`, no alembic — verified
as deliberate design). B7 adds restore-from-snapshot as the data-layer rollback path; B4's
audit-write standard preserves reconstructability. M-feature enablement PRs (Phase 3) must
each declare a feature-level disable path (flag or route guard) before merge.

## 11. Test Strategy

- Baseline contract stays authoritative: 218 PZ + 413 carrier = 631 enforced
  (`.claude/contracts/test-baseline.md`); full-suite legacy failures remain governed (OQ4/#366)
  — NOT in campaign scope to mass-fix.
- Every backlog item ships with a regression test named in its PR (GATE 1).
- B14 closes the CN-HSN 13/35 drift (#567) and returns the classifier suite to baseline.
- Write-route coverage: each Phase 2/3 PR touching a POST/PUT/DELETE route adds a route-level
  test; target ≥1 test file per write router touched (closes the 3-file gap incrementally,
  not big-bang).
- GATE 6 browser verification on every UI-touching PR; backend-only PRs use curl + audit-log.

## 12. Phase Gates

Every phase exit requires: (1) Senior Architect written verdict, (2) all phase PRs merged +
deployed + smoke-verified with SHA recorded, (3) scorecard produced (RULE 2) and cited in
PROJECT_STATE.md (RULE 6), (4) zero unresolved HIGH findings introduced by the phase,
(5) operator acknowledgment. Phase 1 additionally gates on the GATE 2 queue being ≤2 open
implementation PRs at open time.

## 13. Production Readiness Assessment

**Current grade: B+ (production-stable with bounded compliance debt).**
Strengths: single calculation authority, backend-owned readiness, consistent route auth,
idempotent carrier coordinator, governed test baseline, disciplined deploy gate.
Bounded debt: 3 Lesson G endpoints (B1), 3 Lesson M buttons (B2), audit-trail coverage 19/98
services (B4), no DB backup automation (B7), dead reservation module (B3).
Unknowns: the 9 un-audited subsystems (Phase 1b) — grade is provisional until that closes.
Nothing found justifies an emergency freeze; the GATE 2 queue proceeds as locked.

---

## 14. Prioritized Backlog (with proposed GATE 4 dispositions)

| ID | P | Item | Evidence | Proposed disposition |
|---|---|---|---|---|
| B1 | P0 | Lesson G `no-store` headers on 3 endpoints + regression test | routes_tracking_db.py:58, routes_dsk.py:291, routes_dashboard.py:2262 | SCHEDULED — Phase 1 PR |
| B2 | P0 | Lesson M disabled-reason titles on 3 buttons + carriers-page generic-reason sweep | v2/index.html:662/673/684 | SCHEDULED — Phase 1 PR |
| B3 | P0 | `routes_reservations.py` disposition: register in main.py or archive-tag as dead | 6 unregistered endpoints | SCHEDULED — Phase 1 PR (investigate-then-decide) |
| B4 | P1 | Business-write audit-trail standard (shared helper; adopt in document_db, packing_db, warehouse_db, tracking_db, master_data_db) | document_db.py:687 et al.; 19/98 coverage | SCHEDULED — Phase 2 flagship |
| B5 | P1 | Consolidate `_normalize_name` ×3 into customer_resolution_authority | 3 sites | SCHEDULED — Phase 2 |
| B6 | P1 | DHL follow-up routing authority: document clearance_path split + integration test (Path A→v2, Path B→legacy) | dual engines | SCHEDULED — Phase 2 |
| B7 | P1 | SQLite backup automation (`.backup()` + retention + pre-deploy hook) | no backup exists | SCHEDULED — Phase 2 |
| B8 | P1 | ENV=production assertion in email_ingestion_worker; evaluate cowork agents vs Lesson E | worker:196-204 | SCHEDULED — Phase 2 (cowork part feeds Phase 1b) |
| B19 | P1 | Shipment creation must route recipient_address through `resolve_delivery_address` | raw dict bypass | SCHEDULED — Phase 2 |
| B9 | P2 | M6 drafts search route + UI | missing route | SCHEDULED — Phase 3 |
| B10 | P2 | M3 CMR PDF generation enablement | DISABLED_WITH_REASON | SCHEDULED — Phase 3 |
| B11 | P2 | M4 doc-generation orchestration; **M1 hard delete → REJECTED** (wFirma PZ delete is MANUAL-ONLY by pinned test; hard delete contradicts audit-trail invariant) | routes_proforma.py | SCHEDULED (M4) / **REJECTED (M1)** |
| B12 | P2 | N935 manual operator entry path (corrupt XML fallback) | no fallback | SCHEDULED — Phase 3 |
| B13 | P2 | CN-HSN chapter-level mismatch guided operator workflow | no guided path | SCHEDULED — Phase 3 |
| B14 | P2 | Fix CN-HSN classifier test drift (13/35 failing) | Issue #567 | ISSUE (exists: #567) — Phase 3 |
| B20 | P2 | Outbound AWB tracking-registration path | missing | SCHEDULED — Phase 3 (after carrier-gate review) |
| B15 | P3 | Replace 30+ hardcoded hex with CSS custom properties | 3 jsx files+ | SCHEDULED — Phase 5 |
| B16 | P3 | Consolidate direct `fetch()` into pz-api transport | 2 sites | SCHEDULED — Phase 5 |
| B17 | P3 | Structured logging (JSON lines) for services | basic logging | SCHEDULED — Phase 4 |
| B18 | P3 | data-testid evenness sweep | 304/22 files | SCHEDULED — Phase 5 |
| B21 | P3 | Document-lineage consolidation design note (single registry decision) | 3 stores | SCHEDULED — Phase 5 (design only) |
| 1b | P1 | Supplemental audit: 9 missed subsystems (inventory, matcher, email pipeline, finance, cowork, Zoho, pipelines/, tools/, root engines) | completeness critic | SCHEDULED — Phase 1b |

LOW/informational items accepted without backlog entry (ZC429 sender SPOF, VAT manual-only,
V1 ship-to staleness) — recorded here as the explicit REJECTED-for-now register; revisit at
Phase 5 closure.

---

## 15. Exact Next Action

1. **Operator**: merge PR #568 (READY-TO-DEPLOY) — head of the locked GATE 2 queue.
2. **Operator**: approve/amend the GATE 4 dispositions in §14 (notably M1 = REJECTED).
3. **First campaign PR** (when a GATE 2 slot frees): Phase 1 compliance hotfix — B1 + B2 + B3,
   single small PR, full gate discipline.
4. This document rides the next docs-PR slot (GATE 2 docs exception) — it is currently on-disk
   only, uncommitted.
