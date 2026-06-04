# ATLAS REALITY AUDIT — FINAL CONSOLIDATED REPORT
**Part 1 (endpoints/source) + Part 2 (authenticated render) + Phase A (data-quality) + Phase B (BUILD/architectural). Phase C = gated remediation, AWAITING AUTHORIZATION.**

Date: 2026-05-30 · Instance: https://pz.estrellajewels.eu (Windows production) · Mode: LOOK-ONLY throughout (GET-only; no write/click on action controls; no login created; no held action fired).

---

## 0. Executive summary — the honest, item-by-item result

Render-first + adversarial-verified verdicts **refute as often as they confirm**. Of the flagged problems with a verdict:
- **REFUTED (LIVE / mechanism exists):** P1, P2, P6, P7, P9, P10, P18, P24 — eight.
- **CONFIRMED:** P4, P5, P11, P19, P20, P21, P22, P23, P26, Coverage-Matrix-fake-LIVE, + the new next-action incoherence (P3-adjacent) and shipment-v2 wrong-key cards (#396 + AI-decision).
- **Architectural / deferred:** P8, P12, P13, P17, P25 (judgment; P12/P13 need a non-admin session).
- **Out of scope:** P14, P15 (DHL Wave-2 shadow).
- **Not recovered (backfill from Mac):** P16, P27, P28, P29.

Two agent over-reports were caught by the adversarial gate (P10, P18) — automated source sweeps missed the duplicate-detection layer. This is the gate doing its job.

---

## 1. PHASE A — Data-quality verdicts (parallel fan-out + orchestrator adversarial gate)

| P# | Verdict | Mechanism evidence | Vocab |
|---|---|---|---|
| **P10** dup packing rows, no detection | **REFUTED** | Row dedup-key `(batch,invoice,line_pos,design,bag_id)` `packing_db.py:310`; document dup-detection `is_duplicate`/`canonical_id`/ghost `routes_packing.py:1982-2034`, surfaced in dashboard "Link packing files" flow. Detection + guidance exist. | LIVE |
| **P18** SUOKKO 4×, no dedup | **REFUTED (narrow gap)** | Hash-dedup guard + ghost detection + canonical selection exist (`packing_db.py:246`, `routes_packing.py:1995`). Residual gap: file-on-disk overwrite (same filename, `routes_packing.py:347`) has no existence guard, and historical pre-dedup ghost rows persist. Data layer dedups; on-disk file does not. | WIRE (file-overwrite guard only) |
| **P19** Poland packing fields=0 silent | **CONFIRMED** | 0-row parse returns `{ok:true,total_rows:0}` HTTP 200; failure buried in `parser_diagnostic`, not raised as error (`global_packing_parser.py:355`, `routes_packing.py:369-373,527`). 0-result not *distinguished* from legit-empty. Adversarial: Global lists never legit-empty (245-row format). | BUILD (surface extraction failure distinctly) |
| **P20** invoice fields=0 silent | **CONFIRMED** | Invoice parser logs "no item lines parsed" but returns `items:[]`; totals computed 0 while header totals preserved (`pz_import_processor.py:1206-1253,211`). Logged, not surfaced as blocking. | BUILD (surface extraction failure) |
| **P21** inconsistent row-count visibility | **CONFIRMED** | ≥5 independent count sources: `/lines` (1770), `/lane-readiness` (1550), per-doc sales counts (806-836), dashboard display (`dashboard.html:17557`), warehouse missing-scans (`warehouse_audit.py:60`) — `packing_lines` vs `sales_packing_lines` tables, different aggregation → can disagree. No single source of truth. | BUILD (unify count authority) |
| **P22** doc registry stuck pending, no retry | **CONFIRMED** | `shipment_documents.parser_status/extraction_status` default "pending" (`document_db.py:502`), only changed by explicit manual ops; no background retry/timeout. Manual recheck exists (`routes_dashboard.py:3492`) but operator-only. | BUILD (auto-retry / timeout-to-failed) |
| **P23** AWB doc-state ambiguous | **CONFIRMED** | AWB state spread across `inputs.awb` (intention), `source_files.awb` (presence), `awb_fields` (parsed), `tracking_no` (business id) — no reconciling authority; layers can independently succeed/fail (`routes_dashboard.py:491,868`; `shipment-detail.html:6567,3835`). | BUILD (single AWB doc-state authority) |

**Adversarial gate notes:** P10/P18 downgraded from agent-CONFIRMED to REFUTED (agents missed `packing-documents` dup-detection). P19/P20 framed precisely as "0-result not distinguished from failure" (not blanket "silent"). All CONFIRMED are HIGH-confidence, source-backed; none required auth-gated payload to verdict the mechanism.

---

## 2. PHASE B — BUILD plans (planning only, NO code) + architectural parking

**BUILD plans (last-mile operator layer; target V2; existing endpoints feed them):**
- **P5 grouped timeline** — Timeline renders real DHL events ungrouped. PLAN: group by workflow phase (intake → customs → clearance → delivery) keyed on event type; collapse raw stream under phase headers. Feed: existing `GET /api/v1/tracking/shipment/{id}/timeline`. Target: V2 shipment surface. Rollback: revert renderer.
- **P4 actionable intelligence** — Intelligence shows advisory text (SLA suggestion) with no action control. PLAN: render `agents/decision.all_actions[]` as operator controls (Acknowledge / Escalate) wired to existing action endpoints; no auto-fire. Feed: `GET /api/v1/agents/decision/{id}`. Target: V2. Rollback: revert.
- **P11 proposal generation** — Proposals fetches `action-proposals` (200) but renders empty. PLAN: generate proposals from decision-engine `all_actions` + readiness gaps so the surface populates. Feed: `agents/decision` + `action-proposals`. Target: V2. (Backend generation gap — coordinate with P4.) Rollback: revert.

**Architectural parking (operator decision — NOT verdicted here):**
- **P12 security wall / P13 role model** — render ran ADMIN-only; admin can act across tabs (weakens P12). The non-admin lock dimension is **unverifiable without a non-admin authenticated session the operator must provide**. NOT forced. No login created/seeded (prohibited territory).
- **P17 rebuild vs complete** — render evidence favors **targeted V2 completion** (V2 pages largely work; gaps are wrong-key cards + honest stubs) over wholesale replacement. Strategic call: operator's.
- **P8 (5 duplicate PZ panels) / P25 (8 conflicting overview panels)** — UX-consolidation positions; operator design call, not pass/fail.

---

## 3. PHASE C — CONSOLIDATED REMEDIATION PLAN · HALT · per-surface authorization required

NO CODE until authorized. Implement one surface at a time, render-verify after each, fire nothing, rollback ready.

### Track 1 — UI conversion (Approval-Not-Block rule)
| # | Surface | Disposition | Target (Lesson F) |
|---|---|---|---|
| S2 | shipment-v2 Documents card (#396) | WIRE correct keys (files_detail) | **V2** — clean win, do first |
| S3 | shipment-v2 AI Decision card | WIRE `primary_action`/`status`/`next_step` | **V2** — clean win |
| S1 | Inbox Mark-read/Snooze/Bulk (P26) | **HIDE** now (honest) or WIRE if persistence wanted | **V2** `atlas/inbox-v2.html` |
| S6 | atlas/* pending stubs | HIDE until wired | **V2** atlas/* |
| S4 | next-action incoherence (P3) | read authoritative `agents/decision.next_step` | ⚠️ **V1-frozen** — ruling |
| S5 | Coverage Matrix fake-LIVE | relabel "documented coverage" (low sev) | **V2** / when next touched |

### Track 2 — Data-quality backend (Phase A CONFIRMED → BUILD; customs/wFirma-adjacent = gated)
| # | Item | Disposition |
|---|---|---|
| D1 | P19 Poland packing fields=0 | surface extraction failure distinctly (not ok:true on 0-parse) |
| D2 | P20 invoice fields=0 | surface invoice extraction failure (don't store 0-item silently) |
| D3 | P21 row-count divergence | unify to a single count authority |
| D4 | P22 registry stuck-pending | auto-retry / timeout-to-failed + operator retry surfacing |
| D5 | P23 AWB doc-state | single reconciling AWB doc-state authority |
| D6 | P18 file-overwrite | add on-disk existence/hash guard before write (narrow) |

**Rulings needed:** (1) authorize surfaces — clean path **S2, S3, S1, S6 (all V2)**; (2) Lesson-F on **S4** (critical-fix exception — wrong operator guidance — vs V2-only) and **S5** (low-sev, V2); (3) wFirma post informed-override (non-blocking); (4) Track-2 D1–D6 are backend changes on extraction/registry — authorize as a separate batch (each with regression test + rollback per Lesson A/I).

**None of S1–S6 needs the held-approval-inbox contract** (all WIRE/HIDE/relabel, not system-proposed auto-fire). Gated wFirma buttons stay as operator-initiated-with-context.

---

## 4. Full P# ledger
LIVE/refuted: P1, P2, P6, P7, P9, P10, P18, P24. · Confirmed-BUILD/WIRE: P4, P5, P11, P19, P20, P21, P22, P23, P26. · FAKE: Coverage Matrix. · New: shipment-v2 Documents (#396) + AI-decision wrong-key; next-action incoherence (P3 partial). · Architectural: P8, P12, P13, P17, P25 (P12/P13 need non-admin session). · Out of scope: P14, P15. · Backfill from Mac: P16, P27, P28, P29.

**HALT — awaiting per-surface authorization + Lesson-F rulings (S4/S5) + Track-2 go.**
