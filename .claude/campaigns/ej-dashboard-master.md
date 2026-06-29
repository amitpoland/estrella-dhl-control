# EJ Dashboard — Master Campaign

**Adopted:** 2026-06-29  
**Status:** ACTIVE  
**Owner:** amitpoland  

---

## Mission

Build a single event-driven ERP platform where:

- **wFirma** is the accounting authority.
- **EJ Dashboard** is the authority for logistics, customs, warehouse, shipping, inventory, and operator workflows.
- Every integration is event-driven.
- Every business authority has exactly one owner.
- Every change is auditable and replayable.

---

## Program Dashboard

_Update counts and bar every time a phase is marked complete._

| Track | Name | Done / Total | Progress |
|---|---|---|---|
| A | React / Proforma | 3 / 9 | `███░░░░░░░` 33% |
| B | wFirma Integration | 3 / 10 | `███░░░░░░░░░░░` 30% |
| C | Customer Master | 0 / 7 | `░░░░░░░░░░` 0% |
| D | Warehouse & Inventory | 0 / 6 | `░░░░░░░░░░` 0% |
| E | Customs & Shipping | 0 / 6 | `░░░░░░░░░░` 0% |
| F | Finance & Reporting | 0 / 6 | `░░░░░░░░░░` 0% |
| G | AI & Automation | 0 / 6 | `░░░░░░░░░░` 0% |
| **Total** | | **6 / 50** | **`██░░░░░░░░░░░░░░░░░░` 12%** |

---

## Architecture Rules (Locked — permanent)

These rules apply to every PR, every sprint, every session. A change that violates a rule is
incomplete until the violation is resolved.

| # | Rule |
|---|---|
| 1 | One authority per business domain |
| 2 | Immutable event log |
| 3 | Immutable snapshots |
| 4 | Separate enrichment layer |
| 5 | No direct webhook → business table writes |
| 6 | Operator-entered data is never overwritten automatically |
| 7 | Every integration must be replayable |
| 8 | Every state transition must be observable |
| 9 | Background processing only — after webhook acknowledgment |
| 10 | Every feature must fit this architecture before implementation begins |

Cross-reference: `service/docs/production_deployment_rule.md`, `CLAUDE.md §Engineering Lessons`

---

## Execution Strategy (per session)

1. Read this document.
2. Identify the next incomplete phase on the active track.
3. Complete that phase end-to-end (code → tests → PR → deploy → verify).
4. Update the roadmap below.
5. Move to the next phase.

No jumping between unrelated tracks unless the task is a production hotfix.
Every phase ends with a verified production deploy — not a merged PR.

---

## Track A — React / Proforma

**Authority:** EJ Dashboard owns proforma lifecycle, operator workflow, and UI.

| Phase | Status | PR / SHA |
|---|---|---|
| D1 — Atlas shell | ✅ COMPLETE | PR #791 / `1619009b` |
| D2 — Renderer parity | ✅ COMPLETE | PR #789 / `1e1ff9f3` |
| D3 — Editable fields (incoterm, insurance_eur) | ✅ COMPLETE | PR #792 / `d1df260b` |
| D4 — (next) | ⏳ PENDING | — |
| D5 | ⏳ PENDING | — |
| D6 | ⏳ PENDING | — |
| UI cleanup | ⏳ PENDING | — |
| Audit polish | ⏳ PENDING | — |
| Workflow completion | ⏳ PENDING | — |

---

## Track B — wFirma Integration

**Authority:** wFirma owns all accounting documents. EJ Dashboard reads via event pipeline only.

| Phase | Status | PR / SHA |
|---|---|---|
| Phase 1 — Webhook Capture | ✅ COMPLETE | PR #794 / deployed |
| Phase 2A.1 — Processing + Snapshots | ✅ COMPLETE | PR #795 / `c3f1229a` |
| Phase 2A.2 — Diagnostics endpoint | ✅ COMPLETE | PR #796 / pending merge+deploy |
| Phase 2B — Safe Enrichment (3 fields) | ⏳ PENDING | — |
| Phase 3 — Customer Sync | ⏳ PENDING | — |
| Phase 4 — Payment Sync | ⏳ PENDING | — |
| Phase 5 — KSeF Sync | ⏳ PENDING | — |
| Phase 6 — Credit Notes | ⏳ PENDING | — |
| Phase 7 — Inventory Sync | ⏳ PENDING | — |
| Phase 8 — Full Event Bus | ⏳ PENDING | — |

**Phase 2B scope (locked):** enrich exactly three fields via existing `write_postposting_enrichment()`
at `proforma_invoice_link_db.py:1427` — `wfirma_issue_date`, `wfirma_payment_due`,
`wfirma_payment_method`. No new write paths. Only fires after SNAPSHOTTED events confirmed in production.

---

## Track C — Customer Master

**Authority:** EJ Dashboard owns customer identity; wFirma Sync via Track B event pipeline.

| Item | Status |
|---|---|
| Payment Terms Authority | ⏳ PENDING |
| Payment Method Authority | ⏳ PENDING |
| Customer Defaults | ⏳ PENDING |
| Customer Webhook Sync | ⏳ PENDING |
| Customer Statements | ⏳ PENDING |
| Outstanding Balance | ⏳ PENDING |
| Credit Control | ⏳ PENDING |

---

## Track D — Warehouse & Inventory

**Authority:** EJ Dashboard owns all warehouse operations and inventory state.

| Item | Status |
|---|---|
| Inventory Authority | ⏳ PENDING |
| Warehouse Events | ⏳ PENDING |
| Shipment Lifecycle | ⏳ PENDING |
| Scan Workflow | ⏳ PENDING |
| Stock vs Customer Goods separation | ⏳ PENDING |
| Inventory Synchronization | ⏳ PENDING |

---

## Track E — Customs & Shipping

**Authority:** EJ Dashboard owns all customs evidence chains and shipment status.

| Item | Status |
|---|---|
| DHL | ⏳ PENDING |
| CMR | ⏳ PENDING |
| Packing | ⏳ PENDING |
| Customs | ⏳ PENDING |
| Shipment Status | ⏳ PENDING |
| Export Lifecycle | ⏳ PENDING |

---

## Track F — Finance & Reporting

**Authority:** wFirma owns financials; EJ Dashboard owns operational metrics and management reporting.

| Item | Status |
|---|---|
| Dashboards | ⏳ PENDING |
| KPIs | ⏳ PENDING |
| Audit Reports | ⏳ PENDING |
| Operational Metrics | ⏳ PENDING |
| Financial Metrics | ⏳ PENDING |
| Management Reports | ⏳ PENDING |

---

## Track G — AI & Automation

**Dependency:** Tracks A–F must have stable authority boundaries before AI layer is added.

| Item | Status |
|---|---|
| AI document processing | 🔮 FUTURE |
| Email automation | 🔮 FUTURE |
| Workflow assistants | 🔮 FUTURE |
| Intelligent search | 🔮 FUTURE |
| Predictive alerts | 🔮 FUTURE |
| Operational copilots | 🔮 FUTURE |

---

## Immediate next priorities (as of 2026-06-29)

1. Merge and deploy PR #796 (Phase 2A.2 diagnostics)
2. Start Phase 2B — Snapshot → Business Enrichment
3. Return to Track A and complete D4
4. Continue Customer Master synchronization (Track C)
5. Payment synchronization (Track B Phase 4 / Track C)

---

## Dependencies Matrix

Use this to answer "what must be done first?" and "what does this phase unlock?"

| Phase | Depends On | Blocks |
|---|---|---|
| **Track A** | | |
| D4 | D3 ✅ | D5 |
| D5 | D4 | D6 |
| D6 | D5 | Workflow Completion |
| Workflow Completion | D6 | Track F Dashboards |
| **Track B** | | |
| Phase 2B — Enrichment | Phase 2A.2 ✅ | Phase 3 (Customer Sync), Phase 4 (Payment Sync) |
| Phase 3 — Customer Sync | Phase 2B | Track C Customer Defaults, Payment Sync |
| Phase 4 — Payment Sync | Phase 2B, Phase 3 | Track C Statements, Phase 5 (KSeF) |
| Phase 5 — KSeF Sync | Phase 2B | Phase 6 (Credit Notes) |
| Phase 6 — Credit Notes | Phase 5 | Track F Financial Metrics |
| Phase 7 — Inventory Sync | Track D Warehouse Authority | Phase 8 (Event Bus) |
| Phase 8 — Full Event Bus | Phases 3–7 | Track G AI & Automation |
| **Track C** | | |
| Customer Defaults | Phase 3 (Customer Sync) | Payment Terms Authority |
| Payment Terms Authority | Customer Defaults | Outstanding Balance |
| Outstanding Balance | Payment Terms | Customer Statements |
| Customer Statements | Outstanding Balance | Credit Control |
| Credit Control | Customer Statements | Track F Management Reports |
| **Track D** | | |
| Warehouse Authority | — (no hard deps) | Phase 7 (Inventory Sync), Shipment Lifecycle |
| Shipment Lifecycle | Warehouse Authority | Track E Shipment Status |
| Inventory Synchronization | Warehouse Authority, Phase 7 | Track F Operational Metrics |
| **Track E** | | |
| DHL | Shipment Lifecycle | Shipment Status, Export Lifecycle |
| Shipment Status | DHL, Customs | Track F Operational Metrics |
| Export Lifecycle | CMR, Packing, Customs | Track F Audit Reports |
| **Track F** | | |
| Operational Metrics | Track D + Track E stable | Dashboards, KPIs |
| Financial Metrics | Track C stable, Phase 4 (Payment Sync) | Management Reports |
| Dashboards | Operational + Financial Metrics | Track G Predictive Alerts |
| Management Reports | Dashboards, Financial Metrics | — |
| **Track G** | | |
| All AI & Automation | Tracks A–F mature | — |

**Reading rules:**
- A phase with all Depends-On marked ✅ is eligible to start now.
- A phase blocked on a pending item cannot start until that item deploys to production.
- "No hard deps" means the phase can be scoped and started independently, but must not create authority conflicts with in-progress tracks.

---

## Architecture Decision Log

Every architectural decision that cannot be changed without a campaign amendment.
"Locked" means the decision is binding on all future phases — deviation requires operator approval and a new ADR entry.

| ADR | Decision | Rationale | Status |
|---|---|---|---|
| ADR-001 | Immutable event log | Enables replay, audit trail, and safe reprocessing without data loss | Locked |
| ADR-002 | Snapshot before enrichment | Decouples wFirma API availability from business logic — enrichment runs from stored snapshot, not live API | Locked |
| ADR-003 | Single authority per domain | Eliminates competing sources of truth; each field has exactly one system allowed to write it | Locked |
| ADR-004 | Replay-first architecture | Any event can be reprocessed from Layer 1 without side effects; snapshots are append-only | Locked |
| ADR-005 | No business writes in Phase 2A | Validates the snapshot pipeline in production before touching business tables; reduces blast radius | Locked |
| ADR-006 | `operator_override` flag on enrichment fields | Makes dual-write race deterministic: if `operator_override=true`, enrichment logs and skips — operator always wins | Locked |
| ADR-007 | Webhook key rotation via maintenance window (no dual-key) | Simplest safe path; auth layer rejects mismatched key (safe fail); rotation documented in ops runbook | Locked |
| ADR-008 | Background processing only — webhook handler returns 200 immediately | Prevents duplicate delivery from wFirma retries; all processing happens async in APScheduler | Locked |
| ADR-009 | Track G (AI) blocked until Tracks A–F have stable authority boundaries | AI layer must operate on clean data with clear ownership — unstable authorities produce untrustworthy AI output | Locked |

_To propose an amendment: open a governance PR against this file with the new ADR entry and a rationale. Changes to Locked decisions require operator approval before implementation begins._

---

## Program Risks

_Review this table at the start of any session that touches a risk-adjacent area._

| Risk | Status | Owner | Mitigation |
|---|---|---|---|
| Authority conflict — two systems write the same field | **Mitigated** | Architecture rules 1 + 6 | One-authority-per-domain rule enforced at PR review; enrichment whitelist locks Phase 2B to 3 fields |
| Data overwrite — automatic sync clobbers operator-entered values | **Mitigated** | Enrichment layer (rule 6) | `write_postposting_enrichment()` writes only whitelisted fields; operator overrides never touched |
| Replay failure — reprocessing produces different output | **Mitigated** | Immutable event log + snapshots (rules 2, 3, 7) | Events and snapshots are append-only; replay test mandatory for every enrichment phase |
| Scheduler outage — APScheduler stops, events accumulate | **Monitored** | Phase 2A.2 diagnostics endpoint | `scheduler_health` field returns `late` / `stopped`; dead-letter count visible in `/wfirma/status` |
| Dead-letter accumulation — events permanently fail | **Monitored** | Phase 2A.2 diagnostics endpoint | `recent_dead_letters` list in status response; `fetch_failures` counter; alerts can be wired to this endpoint |
| External API change — wFirma changes XML schema | **Open** | wFirma integration | Snapshots store raw XML alongside parsed JSON; parser failures land in dead-letter, not silently corrupt data; schema version field planned for Phase 3 |
| wFirma webhook key rotation — HMAC key changed without updating Dashboard | **Monitored (Runbook defined)** | Ops / deployment | Rotation procedure: (1) generate new key → (2) update production config → (3) update wFirma → (4) monitor auth failures for one tick cycle → (5) remove old key → (6) record rotation timestamp in ops log. Safe fail: auth layer rejects mismatched key, no silent corruption. |
| Phase 2B scope creep — enrichment field list grows beyond 3 | **Mitigated** | Campaign DoD + reviewer-challenge | Field whitelist locked in this document and in phase-specific DoD; reviewer-challenge blocks any PR that adds a fourth field without a campaign amendment |
| Dual-write race — operator edits a field while enrichment is writing | **Mitigated (Design)** | Phase 2B implementation | Enrichment fields carry `last_authority`, `last_updated_at`, `operator_override`, `operator_override_at`. If `operator_override=true`, enrichment logs a warning and skips — never overwrites. Race is deterministic: operator wins. |
| Schema drift — processing DB schema diverges across deploys | **Mitigated** | Immutable event log (rule 2) | Raw events always replayable from Layer 1; worst case is replay, not data loss |

**Status legend:** Mitigated = risk controlled by existing architecture or code. Monitored = risk visible via tooling, not yet eliminated. Open = acknowledged, no mitigation yet — needs a plan before the relevant phase starts.

---

## Definition of Done

### Universal gates (every phase, no exceptions)

| Gate | Criterion |
|---|---|
| 1 | All named phase deliverables implemented |
| 2 | No cross-authority boundary violations (architecture rules 1–10) |
| 3 | Tests pass: unit + integration + smoke |
| 4 | Production deployed and verified — `verify_deploy_close.ps1` all 8 conditions ✅ |
| 5 | Live endpoint or feature manually confirmed in production (curl / browser) |
| 6 | `TASK_STATE.md` updated with SHA, deploy date, and test counts |
| 7 | Campaign dashboard updated — progress counts + phase marked ✅ |
| 8 | No open HIGH or CRITICAL findings from the deploy gate |

**"Implementation complete" is not Done. "Merged" is not Done.**  
Done = production verified + records updated.

### Phase-specific additions

**Phase 2B — Safe Enrichment**
- [ ] Only `wfirma_issue_date`, `wfirma_payment_due`, `wfirma_payment_method` written
- [ ] Write path is exclusively `write_postposting_enrichment()` at `proforma_invoice_link_db.py:1427`
- [ ] No operator-entered override fields touched
- [ ] Regression test confirms no other fields mutated
- [ ] State transitions logged: SNAPSHOTTED → MATCHED → ENRICHED → COMPLETED
- [ ] Replay test: reprocessing the same snapshot produces identical output

**Phase 3 — Customer Sync**
- [ ] Contractor match uses existing dedup logic — no new duplicate records created
- [ ] No operator-entered customer fields overwritten

**Phase 4 — Payment Sync**
- [ ] Payment state derived from wFirma events only — no operator field mutated
- [ ] Idempotent: same payment event processed twice produces the same result

**Phase 5 — KSeF Sync**
- [ ] KSeF number written only after confirmed receipt from wFirma
- [ ] No writes on unconfirmed / pending KSeF state

**Track D — Warehouse Authority**
- [ ] Stock goods and Customer Goods separated at DB level (distinct table or `ownership` column)
- [ ] No wFirma write triggered by warehouse event

**All enrichment phases (2B, 3, 4, 5, 6, 7)**
- [ ] Replay test: reprocessing any historical snapshot produces identical enrichment output
- [ ] Zero writes on RECEIVED or FETCHING state — only on SNAPSHOTTED or later

---

## Changelog

| Date | Change |
|---|---|
| 2026-06-29 | Campaign adopted; Track A D1–D3 and Track B Phases 1–2A.2 marked complete |
| 2026-06-29 | Dependencies Matrix added |
| 2026-06-29 | Program Dashboard and Definition of Done added |
| 2026-06-29 | Program Risks register added; Architecture Decision Log (ADR-001–009) added |
| 2026-06-29 | Dual-write race resolved → Mitigated (operator_override design); Key rotation → Monitored (runbook defined) |
