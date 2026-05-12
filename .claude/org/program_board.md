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
| State | `pre-impl` — P1 done; **P0 scaffolding designed (2026-05-12); P2-P5 scoped and sequenced**; ADRs 012-016 hold |
| Owner | Backend Architect, Customs Compliance Reviewer, Integration Engineer (Zoho Mail) |
| Tests | `partial` — DHL clearance tests exist; P2-P5 test plans drafted (≥40/30/50/50 cases per phase); proactive-dispatch path still untested in code |
| Telemetry | `gap` |
| UI | `none` (Mac); deferred to Windows Atlas per 2026-05-12 strategic memory |
| Debt | none (D-6 closed by ADR-012..016 on 2026-05-10) |
| Live-risk gate | Per-phase: P2 (Customs Compliance + Operator Safety, 48h shadow); P3 (Operator Safety + Carrier Ops, 1 week shadow); P4 (Customs Compliance + Operator Safety + Customer Service, 72h + ≥200 classifications); P5 (Customs Compliance + Inventory/Finance + Operator Safety, 1 week + ≥30 SAD events, two-stage flag promotion) |
| Last commit | n/a (mainline; spec sequestered in ADR-012..016) |

**Planned phase sequence (designed 2026-05-12, planning artifacts at `docs/operational-memory/dhl-selfclearance/`):**
- **P0** Foundation scaffolding (state engine + coordinator + manifest namespace + 6 default-OFF flags + classifier vocabulary + per-thread reply lock + RFC822 thread tracking + tracking-event vocab extension + `is_awb_stable()` + `dhl_selfclearance_followup_v2.py` alongside legacy + admin runtime-flags endpoint) — **prerequisite to all four phases**
- **P2** ADR-013 proactive dispatch — 48h shadow
- **P3** ADR-014 tracking watcher + arrival follow-up — 1 week shadow
- **P4** ADR-015 thread clarification reply — 72h + ≥200 classifications
- **P5** ADR-016 SAD/PZC unlock + PZ trigger — 1 week + ≥30 SAD events, two-stage flag promotion

**Cross-phase invariants (per ADR-012):**
- HL1 never PZ before SAD link
- HL2 never inventory mutation before customs complete
- HL3 never agency-forward on self-clearance path
- HL4 one AWB = one thread (engine side; operator-side fresh threads handled via `thread_id_aliases[]` per Risk R1)

**Single point of catastrophic failure identified:** P4/P5 intent classifier (per reviewer-challenge 2026-05-12). Mitigation: classifier shadow validation against historical DHL email corpus is required in P0 before P2 ships to production.

**Weakest architectural assumption:** DHL thread-stationarity. DHL has been observed to initiate fresh threads server-side. Mitigation: manifest's `thread_id_aliases[]` tracks DHL-initiated fresh threads for the same AWB; P5 thread-matching falls back to AWB-keyed search.

**Wall-clock estimate (best case):** ~3 weeks from P0 start to P5 live. **Realistic with operator review queues:** 4-5 weeks.

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

### W-12 — Admin runtime-flags infrastructure

| Field | Value |
|---|---|
| State | `pre-impl` — designed 2026-05-12 as part of W-5 P0 scaffolding; reusable across future workstreams |
| Owner | Backend Architect, Security Reviewer |
| Tests | n/a (design only); P0 implementation will add ≥6 endpoint tests |
| Telemetry | n/a → `green` once implemented (audit log entry per flag flip) |
| UI | `none` — admin endpoint only, NO browser UI (Windows Atlas memory rule binding) |
| Debt | none |
| Live-risk gate | Security Reviewer sign-off on the auth surface + audit-log completeness |
| Last commit | n/a (design captured in `docs/operational-memory/dhl-selfclearance/01_P0_FOUNDATION.md`) |

**Purpose:** Provide a kill-switch mechanism for phase-scoped runtime flags (initially W-5's six `dhl_selfclearance_pN_*` flags; reusable for future workstreams). `POST /api/v1/admin/runtime-flags/<scope>` with `X-API-Key` auth via the hybrid guard from PR #23. Restartless reload via in-memory + persisted JSON store consulted by config readers before falling back to env-var defaults. Audit log entry per flip (`admin_runtime_flag_flipped` with actor, flag_name, old_value, new_value, timestamp).

**Cross-workstream coupling:** ships as part of W-5 P0 but is workstream-agnostic. Subsequent workstreams can register their own flag scopes by adding a new POST route prefix.

**Live-risk gate:** Security Reviewer must sign off that:
- Auth surface uses `require_api_key` (no separate auth path)
- Error responses are templated (no raw exception strings — engineering discipline rule)
- Audit log entry is mandatory before flag mutation persists
- No browser UI is exposed (Windows Atlas memory rule)

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
