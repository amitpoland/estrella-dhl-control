# PRE-IMPLEMENTATION Dry-Run — 2026-05-10

**Mode:** PRE-IMPLEMENTATION
**Scope:** project-wide audit; output an execution plan for the
next campaign
**Baseline commit:** `25fff3b` (governance scaffold)
**Coordinator pass:** in-context (Opus 4.7); reviewer roles
sampled by Coordinator simulation, not parallel-spawned

This is the first real test of whether the operating system is
useful or bureaucratic. The brief from the operator: "evaluate it
on its own merits — if useful, freeze; if heavy, simplify."

---

## 1. Current state (program board snapshot)

Read from `program_board.md` at baseline:

| ID | Workstream | State | Tests | Telem | UI |
|---|---|---|---|---|---|
| W-1 | DHL carrier label workflow | `pre-release` | green | green | partial |
| W-2 | Operator dashboard | `impl-ongoing` | partial | gap | partial |
| W-3 | Customs / PZ engine | `live` | green | gap | partial |
| W-4 | wFirma PZ + invoice | `closed` | green | green | partial |
| W-5 | DSK forward + DHL self-clearance | `pre-impl` | partial | gap | none |
| W-6 | Cowork action runner | `live` | green | green | partial |
| W-7 | Pre-existing dashboard test failures | `pre-impl` | red | n/a | n/a |
| W-8 | Newsletter classification | `live` | partial | green | n/a |

**Headline:** W-1 is the highest-readiness candidate for the next
campaign. It already has green tests and green telemetry; what
blocks it from `release` is a non-code gate (Production Readiness
Reviewer pass + Operator Safety Reviewer pass + IP allowlist
populated + DHL sandbox handshake passed).

---

## 2. Blockers

Hard blockers (red on board):
- **W-7** — pre-existing dashboard test failures, predate F3.5
  baseline. Not blocking W-1 because they're orthogonal, but
  they will block W-2's release readiness when that workstream
  enters its own RELEASE.

Soft blockers (gaps that compound):
- **W-1 UI gap** — operator dashboard has no carrier-actions
  surface. Today, `/api/v1/carrier/actions/create-shipment/execute`
  is API-only. Operator drives carrier ops from API tooling, not
  from the dashboard. This means the dashboard's D-2 debt is
  *also* a W-1 release dependency.
- **W-1 D-1** — webhook activate-call has no per-event signature
  (DHL doesn't sign). IP allowlist is the only structural
  mitigation. This is acknowledged in ADR-009 but the live-prod
  gate must enumerate the trust assumption explicitly.
- **W-5 D-6** — DSK forward P2-P5 spec lives in agent memory
  (`dhl_selfclearance_flow.md`) but not as ADRs. If memory is
  lost, design context evaporates.

Governance smells:
- **D-7** — several roles in `roles.md` have no agent definition
  file yet. They execute as Coordinator passes. Acceptable for
  now; promote to standalone agents only when their cadence
  justifies it.

---

## 3. Ownership map (next campaign)

If the next campaign is **W-1 → release readiness**, the touched
files belong to:

| Path | Owner role | Activity |
|---|---|---|
| `service/app/services/carrier/**` (read) | Backend Architect, DB/State Engineer | review only |
| `service/app/api/routes_carrier_*.py` (read) | API/Route Mapper, Execution Guard | review only |
| `service/app/services/carrier/adapters/dhl_express_live.py` (read) | Integration Engineer, Security Reviewer | review only |
| `service/tests/test_carrier_*.py` (read) | QA Lead | regression matrix |
| `.claude/engineering/production-readiness-checklist.md` | Production Readiness Reviewer | edit (audit pass) |
| `.claude/org/program_board.md` | Coordinator | edit (state column) |
| `.env` posture audit | Security Reviewer + Coordinator | review only |

**Implementation Engineer is not activated for this campaign.**
The release-readiness pass is *all* review work. That is itself a
useful signal — it tells us the next campaign is RELEASE mode,
not IMPLEMENTATION mode.

---

## 4. Dependency map

```
W-1 (DHL workflow) ──depends on──> ADR-009 trust model documented
W-1 ──depends on──> non-empty carrier_dhl_webhook_ip_allowlist (env)
W-1 ──depends on──> DHL sandbox credentials (env, externally provided)
W-1 ──depends on──> Production Readiness Reviewer sign-off
W-1 ──depends on──> Operator Safety Reviewer sign-off

W-2 (dashboard) ──blocked by──> W-7 (dashboard tests red)
W-2 carrier-actions UI ──depends on──> W-1 reaching release
W-2 customs UI       ──depends on──> W-3 stable (it is)
W-2 wFirma UI        ──depends on──> W-4 stable (it is)

W-5 (DSK forward) ──depends on──> ADRs for P2-P5 (D-6)

W-7 (test debt) ──independent──; should be a standalone campaign
```

The dependency graph says: **W-1 release readiness, W-7 test
recovery, and W-5 ADR sequestration are mutually independent.**
They can be three separate campaigns in any order.

---

## 5. Rollback impact

If the next campaign is W-1 → release:

- **What ships:** an updated checklist file + a program_board row
  state change (`pre-release` → `release` if go, stays `pre-release`
  if hold).
- **What gets reverted:** the checklist file and the row. No code
  reverts.
- **Live-flag posture:** UNCHANGED. RELEASE mode does not flip
  flags. A separate, subsequent Coordinator decision (gated on
  PRR + OSR sign-off per charter authority matrix) is required
  before `carrier_dhl_live_enabled` can move.

This is the ideal first RELEASE campaign because the rollback
cost is essentially zero — we are validating, not deploying.

---

## 6. Risk matrix (next campaign = W-1 RELEASE)

Sampled per reviewer role:

| Reviewer | Severity | Finding (next campaign scope only) |
|---|---|---|
| **Security Reviewer** | P1 | Webhook activate trust relies on IP allowlist alone (D-1). Release recommendation must enumerate this and require operator-confirmed allowlist before flag flip. |
| **Security Reviewer** | P2 | PLT path containment is enforced; no other arbitrary-file-read primitives identified. |
| **Audit Evidence Reviewer** | P2 | `idempotent_replay=True` events emit `EV_CARRIER_SHIPMENT_CREATED` with `replay=True`. Verify the dashboard / audit reader treats replay markers as informational, not as duplicate creates. |
| **Customs Compliance** | not-in-scope | W-1 doesn't touch customs; clean. |
| **Gap Hunter** | P2 | `_select_carrier_adapter` warning telemetry was never exercised in a live setting because flags are off. RELEASE should pin a DRY observation: with `live_enabled=True` + no creds, the warning fires once per request, not once per process. Verify by reading the test, not the prod logs. |
| **Operator Safety** | P1 | No dashboard UI for carrier actions (D-2). Operator-initiated create/cancel is API-only today. RELEASE recommendation should be `hold` on operator-facing live cutover until this is closed, even if backend itself is `go`. |
| **Production Readiness** | P0 | Cannot give a `go` until `production-readiness-checklist.md` is walked end-to-end against W-1. Today's checklist hasn't been audited since the F3.5 hardening landed. |

**Distillation:** the campaign almost certainly returns `hold`
on full live-prod cutover (because of D-2 dashboard gap), but
can plausibly return `go` on **sandbox shadow** — i.e. flip
`carrier_dhl_shadow_mode=True` against the sandbox URL and
observe diffs, while operator UI remains API-only and
`live_enabled=False` stays put.

---

## 7. Execution plan for next campaign

**Campaign name:** DL-G1 — W-1 release readiness audit (sandbox
shadow target).

**Mode:** RELEASE.

**Phases (each = one commit):**

| Phase | Title | Touched files | Owner | Output |
|---|---|---|---|---|
| G1.1 | Production-readiness checklist walk against current code | `.claude/engineering/production-readiness-checklist.md` (audit notes appended), `.claude/org/dry_runs/2026-05-NN-prr-walk.md` | Production Readiness Reviewer | Walk artifact + go/hold per item |
| G1.2 | Operator-safety walk against current dashboard | `.claude/org/dry_runs/2026-05-NN-osr-walk.md` | Operator Safety Reviewer | Findings; expected `hold` for live-prod, `go` for sandbox shadow |
| G1.3 | Rollback rehearsal: validate revert of `25fff3b..c5ef1e2` cleanly leaves W-1 at the F3 baseline | rehearsal artifact only | Release Manager + Coordinator | Documented revert procedure |
| G1.4 | Release recommendation: signed `hold` on live-prod, `conditional-go` on sandbox shadow | `.claude/org/release_recommendations/2026-05-NN-W1.md` (new dir if first) | Coordinator | Final signed recommendation |

**No phase touches `service/app/**` or `ui/**`.** This is verifiable
by `git diff --stat` at campaign exit.

**Exit criteria for the campaign:**
- W-1 program board row updates to `release` state if all phases
  green.
- D-1 trust assumption explicitly named in the recommendation.
- A *separate* future session, with explicit Coordinator
  authority + the operator's go-ahead, may then flip
  `carrier_dhl_shadow_mode=True` (sandbox only) — that is NOT
  part of this campaign.

**Scoping fence — what this campaign WILL NOT do:**
- Edit any production source.
- Flip any feature flag.
- Implement the carrier-actions dashboard UI (separate workstream).
- Resolve W-7 test debt.
- Sequester DSK forward ADRs.

---

## 8. Operating-system self-review

Per the operator's brief: evaluate the dry-run on its merits.

**Felt useful:**
- Forced me to read the program board row by row, which surfaced
  the D-2 dependency I had glossed over in the campaign report.
- Naming the next campaign as RELEASE (not IMPLEMENTATION) was
  itself the answer — without the three-mode contract, the
  default reflex is "next phase = code phase."
- The risk matrix per reviewer role landed P0/P1/P2 differently
  than my unstructured instinct would have. The Operator Safety
  P1 ("hold even if backend is go") and the Production Readiness
  P0 ("checklist hasn't been audited") are findings the
  unstructured form would have *mentioned* but not *graded*.
- Ownership map made it concrete that Implementation Engineer
  doesn't activate at all in DL-G1 — that's a clean signal.

**Felt heavy:**
- Section 1 duplicates `program_board.md`. The dry-run could just
  say "see board" and skip the table. I'll keep section 1 thin
  in future runs (one paragraph, not a table).
- Sections 4 (deps) and 7 (plan) bleed into each other. Future
  runs can collapse to one "execution plan with deps inline."
- Reviewer simulation in section 6 is honest but limited — the
  reviewers are Coordinator-impersonated. When DL-G1 ships, the
  reviewer roles should actually spawn (parallel sub-agents,
  read-only). That's a freezing-time decision, not a redesign.

**Verdict:** keep the structure. Trim sections 1 and 4 in the
next run. Promote reviewer activation from "Coordinator simulates"
to "parallel sub-agent spawn" in DL-G1's RELEASE pass.

---

## 9. Recommendation to operator

1. **Freeze the operating system at the current scope.** It
   produced a non-trivial finding (the Operator Safety P1
   blocker) within the first dry-run. ROI proven.

2. **Open DL-G1 as a fresh RELEASE-mode session** using the plan
   in §7. Baseline that session at `25fff3b`. Let the reviewer
   roles activate as parallel sub-agents (not Coordinator
   simulation) so the operating system's reviewer-spawn
   trigger fires for real.

3. **Trim the dry-run template** before institutionalising:
   collapse sections 1 + 4 into prose, keep 6 + 7 + 8 + 9 as
   the working surface. Update `execution_modes.md` PRE-IMPL
   "Required outputs" list accordingly when DL-G1 closes.

4. **Do not** open W-2 dashboard work, W-5 DSK ADR sequestration,
   or W-7 test recovery in the same session as DL-G1. Each is
   its own campaign; the operating system would call mixing
   them a mode violation.

End of dry-run.
