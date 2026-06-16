# ADR-029: Proforma Workspace as an orchestration shell (authority-preserving) — bounded amendment to V2 domain isolation

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-16 |
| **Deciders** | Operator (Amit) |
| **Implements operator decision** | Option A — orchestration-shell + ADR (session 2026-06-16) |
| **Amends** | `docs/v2-architecture-plan.md` §2 / §9 (domain-isolation reviewer-challenge blocker) — bounded exception only |
| **Extends** | ADR-022 (cached snapshot for pre-gate detection), ADR-021 (detect-before-gate invariant), ADR-026 (outbound DHL label / carrier scaffold) |
| **Honors (does not amend)** | ADR-025 (soft validation), ADR-023 (master-data SSOT), ADR-024 (product-master authority), ADR-027 (VAT from master), ADR-028 (V2 shell tracks), ADR-010/018 (default-OFF flags) |
| **Related plan** | `docs/proforma-workspace-consolidation-plan.md` |

## Context

The operator directive is to consolidate the fragmented `Shipment → Mapping → Draft → Edit → AWB → Post` flow into a single **Proforma Workspace** for packing intake, document configuration, inventory reservation, AWB generation, conflict detection, and wFirma posting.

This directly contradicts a **LOCKED** architectural decision: `docs/v2-architecture-plan.md` §9 lists *"a component in `proforma-v2.html` calling `/api/v1/dhl/` or `/api/v1/warehouse/`"* as a reviewer-challenge **blocker**, and Lesson F mandates *"ONE PAGE = ONE DOMAIN AUTHORITY / NO PAGE MAY OWN ANOTHER PAGE'S BUSINESS LOGIC."* A workspace that drives inventory + AWB + wFirma appears to violate this.

The contradiction is, however, only about **frontend geography**. The brief's own Phase 9 *preserves* every backend authority owner (Inventory, AWB/DHL, wFirma, Customer, Product). Phase-1 inspection (`docs/proforma-workspace-consolidation-plan.md` §1) confirmed the backend primitives already exist and are authority-clean. The open question is whether one frontend surface may *orchestrate* several services without *owning* their logic.

## Decision

**The Proforma Workspace is an orchestration shell: it delegates every cross-domain action to the owning service's existing public API and never re-implements domain logic.** A bounded exception to the V2 domain-isolation rule is granted to this single designated surface, fenced by the layer rules and invariants below.

### 1. Delegation (no logic duplication)

| Workspace action | Delegates to (authority owner) | Mechanism |
|---|---|---|
| Reserve inventory | Inventory / Reservation Service | existing reservation routes (per operator choice to **activate** `routes_reservations.py`, OQ-NEW-14 = Option A) — never a UI-side stock mutation |
| Generate AWB | Carrier subsystem (`carrier/coordinator.py`) | per ADR-026 Path-LIVE/Path-DOC; coordinator idempotency + `dispatch_record` |
| Post / convert | wFirma (`wfirma_client.py`) | existing `/post` + `/to-invoice`, behind existing write-flags + confirm token |
| VAT | `vat_resolver` (ADR-027) | read-only resolve; **no per-line VAT editor** |
| Valuation | `dual_valuation` (frozen) | read-only |

### 2. Frontend layer rules (extend Lesson F, do not abandon it)

- `pz-api.js` — transport only (fetch + error shape). No business logic.
- `pz-state.js` — normalize / cache / derive view state only. **No** local legality compute (no `ready = blocking_reasons.length===0`, no VAT, no postability).
- `pz-components.js` — domain-aware components (`WorkflowStepper`, `ConflictBadge`, `ConflictPanel`) live here.
- `dashboard-shared.js` — visual atoms only; **MUST NEVER gain domain knowledge** (Lesson F Rule 1; reinforced by ADR-028). The workspace stays on **Track-1 `/dashboard/proforma-v2.html`**; it does NOT pull the Track-2 `/v2/` shell into scope (ADR-028 keeps the tracks separate).

### 3. Conflict detection conforms to ADR-025 soft validation

Conflict detection is **advisory by default**: detect → surface as inbox/proposal → operator **approves / overrides / regenerates / accepts / reverts**. It **reuses** the existing soft-validation infrastructure (the Rule-Based Reverification Layer / action-proposal inbox from ADR-025) — the `proforma_conflicts` store is a **typed extension** of that model, not a parallel authority. No workflow gate becomes a hard block.

### 4. Master-drift detection reuses ADR-022 + honors ADR-021 invariant

Drift checks (customer VAT/address/terms changed, product HS/origin/UOM changed, service-charge defaults changed) compare the **cached snapshot in the draft row** (ADR-022 pattern, extended with the fields each check needs) against the current masters (local reads). **No wFirma read or write may occur before the write-enable gate** (ADR-021 invariant). All pre-gate detection is zero-wFirma-I/O.

### 5. One hard gate only — the wFirma write boundary

Per ADR-025 ("soft workflow gates + hard write gates"), the **only** hard gate is the wFirma write flag (`wfirma_create_proforma_allowed` / `_invoice_allowed`, default OFF). The opt-in `conflict_posting_blocker` flag (default OFF → ON before production) elevates **ERROR-severity** conflicts to block the **wFirma write specifically** (not workflow advancement) at that existing boundary. **Warnings proceed only if acknowledged + logged.** Upload never triggers a wFirma write.

### 6. Workflow state is additive

A new nullable `workflow_stage` column (`draft → reserved → awb_generated → ready_to_post`) gates *reaching* the existing posting states; it does **not** overload `draft_state` (whose post idempotency guard is frozen). Reversible via reservation release. `Posted`/`Converted` remain read-only except allowed outputs.

### 7. Flags default OFF (ADR-010/018)

`consolidated_workflow`, `conflict_detection_enabled`, `toolbar_v2`, `shipping_summary` default `false`; `conflict_ui_mode=panel`; `conflict_posting_blocker` false → true before prod; `conflict_resolution_auto_use_defaults` false.

### The bounded amendment (precise scope)

`docs/v2-architecture-plan.md` §9's blocker — *"proforma page calling `/api/v1/dhl/` or `/api/v1/warehouse/`"* — is amended **for the designated orchestration surface only**: that surface MAY call multiple services' read + gated-write APIs **provided** (a) it calls each service's public API only — never its DB and never a re-implemented copy of its logic; (b) the backend stays the sole authority for legality, readiness, VAT, valuation, and idempotency; (c) the §2 layer rules hold; (d) it is gated by `consolidated_workflow` (default off). This exception does **not** generalize to other domain pages, which remain strictly single-authority.

## Rejected alternatives

- **Option B — separate pages + workflow rail.** Lesson-F-pure (zero amendment), but keeps the multi-page navigation the directive exists to eliminate. Rejected by operator in favor of the single workspace.
- **Option C — full V2 re-architecture around workflows.** Largest blast radius; re-opens a closed, working architecture. Deferred.
- **Parallel conflict authority (new inbox).** Rejected — would duplicate ADR-025's soft-validation/inbox layer and split authority. Conflicts extend the existing model.
- **Overload `draft_state` with Reserved/AWB.** Rejected — risks the frozen post idempotency guard. Orthogonal `workflow_stage` instead.

## Invariants

1. No automatic wFirma write from upload; writes stay behind their flags + confirm token.
2. No UI-only inventory mutation — reservation goes through the Inventory/Reservation Service.
3. No duplicate AWB (proforma-scoped key extending the coordinator's batch-scoped key, ADR-026) and no duplicate post (existing state guard).
4. All conflict detections and resolutions are auditable via `master_audit` (before/after/actor/reason).
5. Masters remain SSOT (ADR-023/024); VAT stays backend-resolved (ADR-027) — no per-line VAT editor; discount via effective unit price unless a separate approved schema campaign.
6. `dashboard-shared.js` never gains domain knowledge (Lesson F Rule 1 / ADR-028).
7. No wFirma read or write before the write-enable gate (ADR-021).

## Risks

| Risk | Mitigation |
|---|---|
| Orchestration shell drifts into a V1-style god-page | Layer rules §2 + reviewer-challenge fires on every workspace PR + exception scoped to one surface |
| Soft-vs-hard validation confusion | Explicit reconciliation §3/§5 anchored to ADR-025; default advisory, blocker opt-in at write boundary only |
| Two reservation systems (operator chose Activate) | Reconcile `routes_reservations.py` + `wfirma_reservation_drafts` in the reservation PR; one canonical intent record |
| Live DHL not implemented (Phase D) | Workspace integrates shadow + Path-DOC now; Path-LIVE remains operator-gated (ADR-026), unaffected |
| Snapshot drift vs live wFirma | Live XML remains authoritative post-gate (ADR-022 reconciliation clause) |

## Rollback

Flip `consolidated_workflow`, `conflict_detection_enabled`, `conflict_posting_blocker` OFF (in that order) → workspace reverts to the current Track-1 proforma surface; `workflow_stage` column is nullable and inert when unused; remove V2 workspace file additions. Existing Proforma and Shipment flows remain reachable throughout. First migration uses nullable columns only (no NOT NULL).

## Future impact

Establishes the **orchestration-surface pattern** (delegate, don't own) for future workflow consolidations; fixes the conflict-store-as-typed-extension model; and sets proforma-scoped AWB keying as the extension point on top of ADR-026's carrier scaffold. Any second orchestration surface requires its own ADR citing this one — the exception is not a general license.

## References

- `docs/proforma-workspace-consolidation-plan.md` — the file-backed implementation plan this ADR governs
- `docs/v2-architecture-plan.md` §2/§9 — the amended domain-isolation rule
- `.claude/adr/ADR-021`, `ADR-022`, `ADR-025`, `ADR-026`, `ADR-027`, `ADR-028`
- CLAUDE.md Lesson F (V2 authority isolation); Lesson M (capability visibility)
- `docs/ATLAS_WORKFLOW_MAP.md` — canonical workflow build order
