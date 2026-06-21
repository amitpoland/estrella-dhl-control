# FEATURE_SCORECARD.md

One row per `/feature` invocation. Fill in immediately after CLOSE phase.
Do not aggregate — raw rows are more useful than summaries during the observation period.

---

## Status

**Observation Status: ACTIVE**
**Development Status: ACTIVE**

**Rule:** A completed `/feature` execution creates a scorecard entry.
The absence of scorecard entries must **never** prevent development work.
Observation runs in parallel with development; it is informational only and
never a gate. See `docs/governance/OBSERVATION_IS_NOT_A_GATE.md`.

---

## Scorecard rows

| Date | Task | Selected Skill | Confidence | Authority Correct | Protocol Completed | Unexpected HOLD | Scope Drift | Drift Started At | Session Length | Backlog Items | Outcome | Lessons | Duration | Files Read | Files Chg | Test Time | RC Findings | Fallback | GATE 6 Pend | Ctx Pressure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | HIGH/MEDIUM/LOW | Y/N | Y/N | Y/N | Y/N | None/Discovery/Plan/Implement/Verify | <30m/30-60m/1-2h/2-4h/4h+ | | SUCCESS/PARTIAL/FAILED | | ~Nm | ~N | N | Ns / N/A | N (verdict) | Y/N | Y/N | text |
| 2026-06-20 | PR-2 Contractor-at-Birth Projection (#673, merged f652de0) | AUTHORITY_MAP §1/§9/§12 (proforma/wfirma/readiness domain skills planned-not-built — substituted per SKILL_ROUTING) | HIGH | Y | Y | N | N | None | 2-4h | 7 (B-002..B-008, all SCHEDULED) | SUCCESS | (1) Don't re-key client_name-keyed tables — contractor_id is a reference, not the storage key (service charges + authority joins would orphan). (2) Centralised derive-from-shipment_documents self-heals every birth call site (avoided editing 5 routes). (3) Broad single-process `pytest -k` is unreliable in a bare worktree — pre-existing failures reproduce on clean origin/main; isolated/smoke suites are the authoritative signal. (4) PLAN-stage reviewer-challenge + gap-detection caught the design-defining constraint before any code was written. | — | — | — | — | — | — | — | — |
| 2026-06-21 | PR-3 Dropdown selection wins — canonical name overrides parsed draft name + safe migration (#675, merged 7b94a73) | AUTHORITY_MAP §1/§9/§12 (proforma/wfirma domain skills planned-not-built) | HIGH | Y | Y | N | N | None | 4h+ | 3 (B-009..B-011, all SCHEDULED) | SUCCESS | (1) A draft-only rename creates split-brain — the whole sales pipeline keys off client_name; canonicalize the chain consistently + move authority onto contractor_id. (2) "Canonical wins" must be MONEY-SAFE: a frozen/posted canonical can never receive re-entered charges → preserve, never drop; disclose every dropped non-zero amount. (3) The multi-stage adversarial battery PAYS OFF — each FINAL stage caught a real bug the prior stage missed (split-brain → frozen-charge-loss CRITICAL → latent NameError that shipped in PR-2). (4) Operator decisions on irreversible financial behavior (charge-collision rule) belong to the operator — surfaced via AskUserQuestion, implemented their choice with a non-silent safety net. | — | — | — | — | — | — | — | — |
| 2026-06-21 | Proforma authority UI (V1) — customer-authority summary above lines + per-line canonical description + visible blocked records (#677, merged 308145d) | AUTHORITY_MAP §14 (proforma description + draft-screen authority — added this PR) | HIGH | Y | Y | N | N | None | 2-4h | 3 (B-012..B-014, all SCHEDULED) | SUCCESS | (1) Before changing a display surface adjacent to a financial post, READ the post call — the wFirma line name is design_no/product_code, not name_pl/description, so the description change is provably display-only (the PLAN reviewer-challenge caught this, making B safe). (2) "Reuse the canonical engine" was already 80% done — enrich already stamps description_pl/_en/_bilingual on the line; the gap was the UI showing the short generic name. Discover what's already wired before building. (3) V1-frozen UI = additive + duplicate-not-move; a read-only summary above lines satisfies "customer before lines" without relocating the editable block (lower risk). (4) GATE-6 for a not-yet-deployed UI change = offline Babel compile (0 fail) + structural tests now; live behavioural verify deferred to deploy — an honest, proportionate disposition. | — | — | — | — | — | — | — | — |
| 2026-06-21 | Proforma readiness status display in V2 shipment detail tab | `backend-route-and-service-builder` (PROFORMA fallback; `proforma-engine` MISSING) | MEDIUM | Y | Y | N | N | None | <30m | B-015: MISSING_SKILL proforma-engine (SCHEDULED) | PARTIAL — PR #687; GATE 6 pending operator browser verification | reviewer-challenge returned REVISE on plan (draft_state field name, 8 lifecycle states, write-on-read stagger) — all resolved before implementation; no HOLD; GATE 6 cannot complete in remote container | — | — | — | — | — | Y | Y | session in remote container; no pressure |
| 2026-06-21 | Improve DHL shipment detail diagnostics and operator visibility | `frontend-design` + `pz-shipment` (HIGH confidence; UI_FRONTEND + DHL_CUSTOMS tie) | HIGH | Y | Y | N | N | None | <30m | none | PARTIAL — PR #687 updated; GATE 6 pending operator browser verification | reviewer-challenge returned FAIL (4 findings: batch_id slash encoding safe — confirmed SHIPMENT_ format; BACKEND_GAP_REGISTER.md citation removed; cancelled-flag pattern added; 401 auth-error distinction added); gap-detection surfaced 9 gaps (7 auto-resolved, 2 escalated: scope=DHL-domain-only per Lesson F, dual-authority coexistence explicitly labeled); no HOLD; GATE 6 cannot complete in remote container | — | — | — | — | 4 (FAIL) | N | Y | session in remote container; no pressure |
| 2026-06-21 | Improve Proforma draft blocker visibility and operator guidance in V2 shipment detail | FALLBACK → `backend-route-and-service-builder` (PROFORMA; `proforma-engine` MISSING); UI impl via `frontend-design` | HIGH | Y | Y | N | N | None | <30m | B-015: MISSING_SKILL proforma-engine confirmed again (SCHEDULED) | PARTIAL — PR #687 updated; GATE 6 pending operator browser verification | reviewer-challenge returned Ship-with-mitigations (4 findings resolved: error_hint raw text → always-show with fallback; falsy-check silencing → always-show; cancelled-draft banner gap → "active" qualifier; test under-specified → T9/T10/T11 fully specified); gap-detection gap [2] auto-resolved (authority already named in repair_action text — no backend change needed); 11/11 tests pass; no HOLD; GATE 6 cannot complete in remote container | — | — | — | — | 4 (SHIP) | Y | Y | session in remote container; no pressure |
| 2026-06-21 | Improve shipment intake diagnostics and operator troubleshooting visibility | `frontend-design` + `pz-api.js` transport (HIGH; UI_FRONTEND + INTAKE/dashboard domain) | HIGH | Y | Y | N | N | None | <30m | none | PARTIAL — PR #687 updated; GATE 6 pending operator browser verification | gap-detection found batch_id field name discrepancy (batch_id not shipment_id — verified from existing DHL card usage, no HOLD); reviewer-challenge auto-resolved (stale-mount cancelled flag + 404 → isProcessing pattern adopted; auth errType distinction carried over from DHL card; sales_status_hint as tri-state unavailable-sales packing field); 15/15 tests pass (T12–T15 added); old Shipment PanelCard with hardcoded '3 uploaded' removed; GATE 6 cannot complete in remote container | — | — | — | — | — | N | Y | session in remote container; context compacted once mid-task |
| 2026-06-21 | Add observation-only performance metrics to FEATURE_SCORECARD | (no runtime skill) — GOVERNANCE domain; direct implementation | HIGH | Y | Y | N | N | None | <30m | none | SUCCESS — 8 metric columns added; Row #5 self-referential fill; GATE 6 N/A (docs-only) | reviewer-challenge SHIP (3 mitigations resolved: GATE 6 Pend disambiguation via legend; Fallback parenthetical added; Row #5 design decision — Fallback + GATE 6 Pend accepted as deliberately redundant fast-queryable signals); gap-detection skipped (trivial docs task — Phase 1 parenthetical "for non-trivial tasks"); Smoke N/A (docs-only); no HOLD | ~20m | ~4 | 2 | N/A | 3 (SHIP) | N | N | session re-started after Task #4 compaction; no pressure; lightweight task |

---

## Success thresholds (review after 10 runs)

| Metric | Target |
|---|---|
| Correct skill selection | > 80% |
| Protocol completion | > 80% |
| Unexpected HOLD | < 10% |
| Scope drift | < 20% |

If targets are met → build `/bug`. If domain failures cluster (proforma, DHL, wFirma) → build that domain skill first.

---

### Metric column legend

| Column | Meaning | Format |
|---|---|---|
| **Authority Correct** | Backend authority correctly identified for the task domain | `Y/N` |
| **Unexpected HOLD** | Task paused for reasons not anticipated at PLAN time | `Y/N` |
| **Drift Started At** | Phase where scope drift first appeared, if any | `None / Discovery / Plan / Implement / Verify` |
| **Session Length** | Approximate wall-clock session time bracket | `<30m / 30-60m / 1-2h / 2-4h / 4h+` |
| **Duration** | Approximate wall-clock session time for the task (freeform) | `~Nm` (minutes) |
| **Files Read** | Approximate count of source files read in DISCOVERY + PLAN phases | `~N` |
| **Files Chg** | Count of files modified by this task (TASK_STATE.md governance updates not counted) | `N` |
| **Test Time** | Test suite elapsed time; `N/A` = docs-only task (no suite runs); `—` = not recorded at time of run | `Ns` / `N/A` |
| **RC Findings** | reviewer-challenge finding count and verdict code | `N (FAIL\|REVISE\|SHIP\|CLEAR)` |
| **Fallback** | `Y` = skill-routing invoked a fallback because the named skill is MISSING_SKILL; `N` = named skill used directly | `Y/N` |
| **GATE 6 Pend** | `Y` = browser verification still outstanding; `N` = not applicable or completed. NOTE: `Y` in remote-container sessions is a structural constraint (no browser access), not a workflow failure — see Lessons column for context | `Y/N` |
| **Ctx Pressure** | Notes on token/context usage: compaction events, session restarts, large file reads | free text |
| **`—`** | Value was not tracked at time of task execution | — |

*After 10 rows, review failure patterns before building /bug or domain skills.*

