# Program Board

The persistent state of every workstream. **This file is the
operational truth.** A new session reads this row by row and
*knows* without re-deriving from `git log`.

> Update protocol: every phase commit updates the row(s) it
> touched. The Coordinator updates the board at every mode
> transition. The board never lags more than one commit.

## Column legend

| Column | Meaning |
|---|---|
| Workstream | The named campaign or surface area. |
| State | `design` → `pre-impl` → `impl-N` → `release` → `live-shadow` → `live-prod` → `closed`. |
| Owner | Lead role (per `roles.md`). All listed roles co-own. |
| Tests | `green` / `red` / `partial` / `n/a` at the most recent commit. |
| Telemetry | `green` / `gap` / `none`. Gap = hit-or-miss; none = explicit absence. |
| UI | `live` / `partial` / `none` / `n/a`. |
| Debt | Outstanding rows tracked under `governance_debt` below. |
| Live-risk gate | What must be true before a `live_*_enabled` flag flips. |
| Last commit | Short SHA of the most recent commit on the row. |

State transitions are linear by default; backward transitions
(`impl-3 → pre-impl`) require Coordinator approval and an ADR
note explaining why.

---

## Active workstreams

### W-1 — DHL carrier label workflow

| Field | Value |
|---|---|
| State | `pre-release` (DL-F3.5 hardening complete; awaiting RELEASE mode) |
| Owner | Backend Architect, Integration Engineer, Security Reviewer, QA Lead |
| Tests | `green` — 1238/1238 carrier+DHL suite, 17/17 hardening, 14/14 telemetry+E2E |
| Telemetry | `green` — `carrier_live_fallback_to_stub` token live; webhook accept/ignore/reject events; CarrierEvent table |
| UI | `partial` — proposal listing routes exist; operator action surface in dashboard not yet shipped |
| Debt | `D-1`, `D-2` (D-3 closed by ADR-017 on 2026-05-10) |
| Live-risk gate | Production Readiness Reviewer sign-off + Operator Safety Reviewer sign-off + non-empty `carrier_dhl_webhook_ip_allowlist` + DHL sandbox handshake passed |
| Last commit | `c5ef1e2` |

**Phases shipped (this branch, vs `f4a49a8` baseline):**
- DL-F3.5a — `f41c594` — idempotency by (batch_id, reference)
- DL-F3.5b — `dba6abc` — redact DHL response echoes
- DL-F3.5c — `040e57e` — PLT path containment + IP allowlist mandatory when live
- DL-F3.5d — `c5ef1e2` — fail-loud telemetry + live-AWB E2E

**Defaults preserved:** `carrier_dhl_live_enabled=False`,
`carrier_dhl_shadow_mode=False`, `carrier_dhl_paperless_trade_enabled=False`,
`dhl_express_api_status="pending"`. ADR-010 holds.

---

### W-2 — Operator dashboard (HTML)

| Field | Value |
|---|---|
| State | `impl-ongoing` (read-only surfaces shipped; no carrier-actions UI yet) |
| Owner | Implementation Engineer, Dashboard Reviewer, Operator Safety Reviewer |
| Tests | `partial` — pre-existing dashboard test failures noted in audit (W-7) |
| Telemetry | `gap` — operator click events not structured |
| UI | `live` (read-only), `none` (carrier actions, customs actions, wFirma actions) |
| Debt | `D-4`, `D-5` |
| Live-risk gate | Operator Safety Reviewer sign-off on disabled-state UX, confirmation dialogs, and irreversible-action warnings |
| Last commit | `9c6329f` |

---

### W-3 — Customs / PZ engine

| Field | Value |
|---|---|
| State | `live` (closed for May 2026 cohort; gold tests at 160/160) |
| Owner | Customs Compliance Reviewer, Backend Architect, QA Lead |
| Tests | `green` — `make verify` 160/160 |
| Telemetry | `gap` — VERIFY-GAP markers exist; structured-log path is partial |
| UI | `partial` — dashboard shows results, no manual override surface |
| Debt | none currently |
| Live-risk gate | n/a — already live |
| Last commit | n/a (mainline) |

---

### W-4 — wFirma PZ + invoice conversion

| Field | Value |
|---|---|
| State | `closed` (PROF 94/2026 → WDT 84/2026 sequence verified; project memory `project_wfirma_pz_invoice_flow.md`) |
| Owner | Integration Engineer (wFirma), Audit Evidence Reviewer |
| Tests | `green` — live writers under feature flag |
| Telemetry | `green` |
| UI | `partial` — actions visible in dashboard read-only |
| Debt | none |
| Live-risk gate | n/a — closed |
| Last commit | n/a |

---

### W-5 — DSK forward + DHL self-clearance

| Field | Value |
|---|---|
| State | `pre-impl` — P1 done per memory; P2-P5 sequestered as ADRs (012-016) |
| Owner | Backend Architect, Customs Compliance Reviewer, Integration Engineer (Zoho Mail) |
| Tests | `partial` — DHL clearance tests exist; proactive-dispatch path untested |
| Telemetry | `gap` |
| UI | `none` |
| Debt | none (D-6 closed by ADR-012..016 on 2026-05-10) |
| Live-risk gate | Customs Compliance Reviewer sign-off + audit-evidence completeness |
| Last commit | n/a (mainline; spec sequestered in ADR-012..016) |

---

### W-6 — Cowork action runner + email service

| Field | Value |
|---|---|
| State | `live` (per CLAUDE.md section 9; active in production) |
| Owner | Backend Architect, Security Reviewer, Audit Evidence Reviewer |
| Tests | `green` |
| Telemetry | `green` — explicit event taxonomy in `cowork_result_processor.py` |
| UI | `partial` |
| Debt | none currently |
| Live-risk gate | n/a — already live |
| Last commit | n/a |

---

### W-7 — Pre-existing dashboard test failures (audit finding)

| Field | Value |
|---|---|
| State | `closed` — repaired across B1.a + B1.b + B1.c on 2026-05-10 |
| Owner | Implementation Engineer, QA Lead |
| Tests | `green` — 875/875 dashboard suite at `37fda67` |
| Telemetry | n/a |
| UI | n/a |
| Debt | none (D-4 closed by W-7) |
| Live-risk gate | none (not a live-flag-bearing surface) |
| Last commit | `37fda67` (B1.c card-wiring repair) |

---

### W-8 — Newsletter classification job

| Field | Value |
|---|---|
| State | `live` (cron 47409aab; per `NEWSLETTER_RUN_LOG.md` memory) |
| Owner | Implementation Engineer (Cliq), Observability Engineer |
| Tests | `partial` |
| Telemetry | `green` |
| UI | n/a |
| Debt | none |
| Live-risk gate | n/a |
| Last commit | n/a |

---

### W-9 — Inventory campaign (Group A + Group B + B.1 + B.2)

| Field | Value |
|---|---|
| State | `live` (read + write paths shipped together; PRs #16–#21 on `main`) |
| Owner | Backend Architect, Implementation Engineer, Dashboard Reviewer, QA Lead |
| Tests | `green` per Group B validation report (`feat/overnight-test-validation-report`) |
| Telemetry | `partial` — lifecycle state-transition events present; aggregator counts live; structured operator-action events still gap |
| UI | `live` — inventory state strip + piece detail drawer + sample-out drawer + Move-stock action wired on `BatchDetailPage` |
| Debt | none currently (Sample-out Stage 2 carved out as W-10) |
| Live-risk gate | n/a — read + write paths shipped together; per-button live gates passed in Group B campaign |
| Last commit | `a0fcf96` (Merge PR #21 `feat/aggregator-samples-live` — Stage 2 aggregator counts SAMPLE_OUT for samples tile) |

**Phases shipped (against `c702eba` baseline at PR #3 Atlas composition merge):**
- Group A — PR #16 `c2902dc` — activate Move stock (router wiring + migration precheck hardening + DB UNIQUE idempotency)
- Group B — PR #11..#15 (integration branch `integrate/group-b-inventory-read-paths` → merge `e9f2c43`) — read paths: `GET /inventory/state/{batch_id}`, `GET /inventory/pieces/{piece_id}`, batch state strip, piece detail drawer
- Phase B.1 write — PR #17 `914bad6` — Sample-out / Sample-return lifecycle write
- Phase B.1 UI — PR #18 `fe9c1ba` — Sample-out drawer surfaces (pill, aging, mutation forms)
- Phase B.2 — PR #19 `eca4d1c` — unified piece timeline (lifecycle + movement + sample chronology)
- Cleanup — PR #20 `3fb37e5` — stale Inventory page copy after Move stock + Sample-out went live
- Phase B.1 Stage 2 — PR #21 `a0fcf96` — aggregator counts SAMPLE_OUT for samples tile

**Linked design docs** (on side branches, pending promotion to `main` in current governance batch):
- `feat/doc-1-v2-allocation-ledger` → `INVENTORY_STATE_MACHINE.md` (v2 extend-existing architecture)
- `feat/doc-2-button-registry` → `BUTTON_REGISTRY.md` (9 inventory buttons)
- `feat/doc-3-data-source-mapping` → `DATA_SOURCE_MAPPING.md` (all states)
- `feat/doc-4-failure-modes` → `FAILURE_MODES.md` (buttons + transitions)
- `feat/inventory-risk2-designs` → `RISK_2_DESIGNS.md` (Risk-2 button contracts)
- `feat/inventory-risk34-stubs` → `RISK_3_4_DESIGN_STUBS.md` — **explicitly deferred ("NOT FOR OVERNIGHT IMPL")**

**Known governance gap closed by W-9:** the inventory campaign shipped without a program-board row for one campaign cycle. Surfacing here in retrospective per the board's own self-rule on row staleness.

---

### W-10 — Sample-out Stage 2 (lifecycle continuation)

| Field | Value |
|---|---|
| State | `pre-impl` (design done; gated on §8 operator decisions) |
| Owner | Backend Architect, Implementation Engineer, Audit Evidence Reviewer |
| Tests | n/a (design phase only) |
| Telemetry | n/a |
| UI | n/a |
| Debt | none |
| Live-risk gate | §8 operator decisions resolved + Audit Evidence Reviewer sign-off on the post-Stage-1 evidence chain |
| Last commit | `0ffc52b` on `feat/sample-out-design` (docs: resolve §8 operator decisions before Stage 2) |

**Predecessor:** W-9 Phase B.1 shipped Stage 1 (Sample-out / Sample-return lifecycle write + drawer + aggregator). Stage 2 continues the lifecycle once §8 decisions land.

---

### W-11 — Reconciliation engine (retroactive)

| Field | Value |
|---|---|
| State | `design` (Stage 1 design inspection complete) |
| Owner | Backend Architect, Customs Compliance Reviewer, Audit Evidence Reviewer |
| Tests | n/a |
| Telemetry | n/a |
| UI | n/a |
| Debt | none |
| Live-risk gate | TBD (post Stage 1 design lock) |
| Last commit | `958d1db` on `feat/reconciliation-engine-inspection` (docs: retroactive reconciliation engine Stage 1 design) |

**Note:** this is the *retroactive* reconciliation engine — read-only inspection over historical batches to surface drift / missing-evidence anomalies. Live-impact gate cannot be set until Stage 1 design transitions to a pre-impl phase plan.

---

## Governance debt

Items the system has noticed but is not currently fixing. The
Coordinator pulls from this list when deciding the next campaign.

| ID | Description | Owner role | Severity |
|---|---|---|---|
| D-1 | DHL webhook activate-call has no per-event HMAC because DHL doesn't sign — IP allowlist is the only structural mitigation (ADR-009 caveat) | Security Reviewer | P1 — review before live-prod |
| D-2 | Operator dashboard has no carrier-actions UI; create-shipment / cancel-shipment must be invoked via API | Implementation Engineer + Dashboard Reviewer | P2 |
| D-5 | Operator click events not structured-logged; click-path observability is gap | Observability Engineer | P3 |

---

## Closed workstreams (audit trail)

| ID | Workstream | Closed at | Note |
|---|---|---|---|
| C-1 | DL-A → DL-F3 carrier core (`f4a49a8` baseline) | May 2026 | Org Bootstrap commit froze governance frame |
| C-2 | Service Hardening May 2026 | 2026-05-05 | Project memory: `project_service_hardening_may2026.md` |
| C-3 | wFirma PZ + invoice conversion | 2026-05-06 | Project memory: `project_wfirma_pz_invoice_flow.md` |

---

## How to update this file

- **Implementation Engineer** updates the row's progress columns
  (State, Tests, Telemetry, UI, Debt) only on the row their phase
  touched.
- **Coordinator** updates strategy columns (Owner, Live-risk
  gate) and adds / removes rows.
- **ADR Historian** is notified when a row enters `release` so an
  ADR captures the cutover decision.
- **Reviewer roles** never edit the board; they file findings the
  Coordinator translates into rows.

A row that has not been updated in the last campaign cycle is a
governance smell — surface it in the next PRE-IMPLEMENTATION
dry-run.
