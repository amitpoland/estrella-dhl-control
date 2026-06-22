# REVERSIBILITY_AND_ROLLBACK_FRAMEWORK.md

**Campaign:** EJ PLATFORM CONSOLIDATION DISCOVERY → REVERSIBILITY
**Inspected:** `origin/main @ fb70e15` (read-only)
**Date:** 2026-06-18
**Foundation:** [AUTHORITY_DECISION_FRAMEWORK.md](./AUTHORITY_DECISION_FRAMEWORK.md), [DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md), [MIGRATION_ROADMAP.md](./MIGRATION_ROADMAP.md) (= CONSOLIDATION_WAVE_PLAN).

> **Honesty boundary.** No migration exists yet — there are no feature flags, cutover routes, or wave snapshots to reverse today. This document is therefore a **reusable rollback *design + policy*** that becomes executable the moment a wave is code-scoped. Where a step needs values that only exist once a wave is built (exact SHAs, flag names, snapshot paths), it is marked **`[FILL @ wave scope]`** rather than fabricated. Adopt the template; instantiate per wave.

## 0. Gaps in the governance outputs this framework must close
- The wave plan defines *what* changes per wave but **no rollback point or reversal owner** — added in §1/§3.
- The conflict register identifies divergences but **no production detector** that catches them *recurring* post-cutover — added in §2.
- No mechanism turns a rollback into **learning** that updates the matrices — added in §4.
- No **parallel-run validation** before committing a wave — added in §5 (leveraging the repo's existing shadow-mode pattern, ADR-004/018).

---

## 1. Rollback Checkpoint Design (per-wave template)

A wave is reversible only if a **complete pre-cutover snapshot** exists and the post-cutover delta is **atomically** revertible. For each wave capture:

| Snapshot element | What to capture | Mechanism |
|---|---|---|
| **Code SHA** | `origin/main` SHA at pre-cutover (the rollback target) + the cutover SHA | git tag `rollback/wave-<n>-pre-<sha>` |
| **Schema state** | DDL of every DB the wave touches (`packing.db`, `warehouse.db`, `proforma_links.db`, `wfirma.db`, `documents.db`, `master_data.sqlite`) | `.schema` dump + row counts of authority tables; backup file copy |
| **Authority assignments** | which service owns each calculation entering the wave (snapshot of AUTHORITY_DECISION_FRAMEWORK §2 at that date) | versioned copy of the framework |
| **Shared-library bindings** | which `pz-api.js`/`pz-state.js`/`dashboard-shared.js` each surface loads | manifest of `<script src>` per page (the source-of-truth before MERGE) |
| **Feature-flag positions** | every flag the wave flips (e.g. `WFIRMA_CREATE_*_ALLOWED`, `consolidated_workflow`, ADR-029 conflict flags — all default OFF today) | snapshot the flag store + `dhl_selfclearance_runtime_flags.json` pattern |
| **Cached/derived state** | per-batch `audit.json` projections that the wave's authority change could re-derive differently | copy `storage_root/sessions/*/audit.json` + rely on append-only `timeline.jsonl` as the durable re-derivation source |

**Rollback-point timing:** snapshot is taken **immediately before cutover**; the wave is declared *committed* only **after a stability period** (default **72h** live, or one full operator workflow cycle, whichever is longer) during which §2 detectors stay green. Between cutover and commit, the wave is **rollback-eligible**.

**Atomic rollback unit (must revert together or not at all):** (1) backend authority ownership, (2) frontend surface routing, (3) shared-library bindings, (4) feature-flag positions. Reverting code (3 of these) without reverting flags (4) — or vice-versa — is the failure mode; the runbook (§3) reverts them as one transaction.

**Storage/recovery:** snapshots live outside the deploy tree (operator-held backup, per "prod write is operator-only"); recovery restores V1 surfaces by re-pointing routing + flags to the pre-cutover manifest (V1 files are *frozen, not deleted*, so they remain serveable for rollback throughout Waves 1–5 — this is precisely why Wave 6 decommission is **last**).

---

## 2. Conflict Detection Trigger System (production, tied to real conflicts)

Detectors run continuously during the rollback-eligible window. Each maps to a known conflict.

| Detector | Watches | Threshold → action | Source conflict |
|---|---|---|---|
| **PZ-status divergence reappears** | Shadow-compare `derive_pz_status` vs any other PZ-status producer on every PZ decision | **any** mismatch on a write-path decision → P0 rollback eval immediately | R-5/CA-3 |
| **Duplicate-authority resurfaces** | New code path computing a value the canonical owner already owns (e.g. a new `_compute_*` shadowing `operational_authority`) | CI grep gate + runtime canary; **1** occurrence → P1 eval | DUPLICATE_AUTHORITY_REGISTER |
| **Shared-lib runtime conflict** | Two `apiFetch`/`pz-api` implementations loaded on one page; method-not-found errors | console-error monitor; **>0** on a live page → P1 eval | R-1/CA-2 |
| **Readiness-gate bypass** | proforma post/convert reaching backend without a prior readiness check | endpoint audit log; **any** ungated write → P0 eval | R-2/CA-1 |
| **Authority re-derivation drift** | post-cutover `audit.json` projections differ from `timeline.jsonl` replay beyond tolerance | nightly reconcile; **>0.5%** of batches drift → P1 eval | #570/#652 class |

**Alerting mechanism:** detectors emit to the existing audit/notify layer (the `*_audit.jsonl` + Cliq notification pattern already used for runtime flags). **Decision gate:** detector fires → platform architect assembles §3 evidence → **operator** decides rollback (sole authority). **Threshold to *force* rollback (not just eval):** any **P0** detector firing on a **write path** that is not explained-and-accepted within the SLA. **Response time:** rollback must be *executable* within **1 hour** of a P0 trigger (snapshots pre-staged); decision within the §7-protocol SLA of the decision framework (P0 = 1 business day, but write-path P0 forces immediate rollback if unresolved).

---

## 3. Rollback Execution Runbook (templated — instantiate per wave)

Ordered, reversing the atomic unit. **Exact commands are `[FILL @ wave scope]`** because flag names/routes/SHAs don't exist until the wave is built; the *procedure* is fixed.

```
PRECONDITION: rollback decision recorded (operator); snapshot tag rollback/wave-<n>-pre-<sha> exists.

STEP 1 — Freeze writes on the affected domain (flip the wave's write flag OFF).
         [FILL @ wave scope: flag name(s)]   Verify: write endpoints return gated/no-op.
STEP 2 — Revert feature-flag positions to the pre-cutover snapshot (atomic with STEP 4).
         Restore flag store from snapshot.
STEP 3 — Restore backend authority ownership:
         redeploy the pre-cutover code SHA for the affected service files (operator-executed
         robocopy + service restart, per deploy gate). Canonical authority returns to its
         pre-wave owner.   Verify: §2 PZ-divergence detector green.
STEP 4 — Restore frontend surface routing + shared-library bindings:
         re-point the page's <script src> manifest + route table to the pre-cutover surface
         (V1/Track-1 files are still present — never deleted before Wave 6).
         Verify: the pre-cutover surface loads and renders live data.
STEP 5 — Data reconciliation:
         replay timeline.jsonl to re-derive audit.json projections; run reconcile_from_timeline
         for any batch the wave touched; confirm no orphaned authority pointers
         (PRESERVED_KEYS intact — the #570/#652 guard).   Verify: 0 batches with null external refs.
STEP 6 — Workflow continuity check:
         run one full operator workflow on the restored surface end-to-end (intake → readiness →
         the wave's write action). Confirm resume with no data loss / no manual fixup.
POST: log the rollback in the Discovery Log (§4) BEFORE re-attempting the wave.
```

**Atomicity guard:** STEP 2 (flags) and STEP 3–4 (code/routing) must land together; if STEP 3 fails, re-flip flags forward (STEP 1 reversed) to avoid a half-rolled state where new flags meet old code.

---

## 4. Authority Conflict Discovery Log Format

Every rollback (and every near-miss the detectors catch) appends one entry. This is the mechanism that turns reversibility into *learning* — each entry must drive an update to a governance doc.

```yaml
- entry_id: ROLLBACK-<wave>-<YYYYMMDD>-<n>
  wave: <Wave N — domain>
  date: <YYYY-MM-DD>
  trigger: <which §2 detector fired + the measured value>   # e.g. "PZ-status divergence detector: 1 write-path mismatch on AWB …"
  conflict_observed: <the authority conflict / business-logic nuance missed in discovery>
  differs_from_known: <how this differs from the BACKEND_AUTHORITY_CONFLICT_REPORT entry, or "NEW — not in register">
  blast_radius: <workflows/write-paths affected; batches touched>
  remediation:
    - doc: <AUTHORITY_DECISION_FRAMEWORK | WORKFLOW_AUTHORITY_MATRIX | UI_SURFACE_DECISION_MATRIX | CONSOLIDATION_WAVE_PLAN>
      change: <the specific edit — e.g. "add Path-B as explicit branch in derive_pz_status; add regression test">
  prevention: <how subsequent waves detect/prevent this — new detector, new CI grep, new shadow-compare>
  disposition: <SCHEDULED | ISSUE #nnn | REJECTED>   # GATE-4 vocabulary
  operator_signoff: <name / date>
```

**Rule:** a rollback is not "closed" until its entry names a concrete doc edit and a prevention mechanism. A repeated trigger with no new prevention = governance failure (escalate to operator).

---

## 5. Shadow-Mode Testing Strategy (parallel-run before cutover)

This repo already runs **shadow mode** for carriers (ADR-004/018; `carrier/shadow_log.db`, `shadow_mode` flag) — reuse that established pattern rather than inventing one.

- **What runs shadow vs live:** during a wave's shadow period, the **old authority remains LIVE** (operators act on it); the **consolidated authority runs in shadow** — it computes its decision on the same real inputs but its output is **logged, not acted on**. Applies especially to write-path calculations: PZ status (R-5), proforma readiness (R-2), any merged shared-lib derivation.
- **Real-time comparison:** every decision is dual-computed; old vs consolidated outputs are written to a shadow log keyed by entity (batch_id/draft_id) with the diff. (Mirror `carrier/shadow_log.db`.)
- **Divergence thresholds:**
  - **0 tolerance on write-path authority** (PZ allow/deny, readiness pass/fail): **any** divergence is logged as a **blocker** candidate, investigated before cutover.
  - **Data-quality band** for non-gating/display values: divergences ≤ a small rate (default **0.5%** of entities, none on write paths) are logged as data-quality issues, not blockers.
- **Duration:** shadow runs **minimum 1 full operator workflow cycle or 72h** (whichever longer) with **zero unexplained write-path divergences** before cutover is permitted. Extends if any write-path divergence is open.
- **Rollback/cutover decision criteria from shadow logs:**
  - Cutover **permitted** only when: write-path divergences = 0 (or every one explained + the canonical owner confirmed), data-quality divergences within band, and the §2 detectors would have stayed green.
  - **Do NOT cut over** (and fix discovery first) if: any persistent write-path divergence, OR a divergence reveals an authority the register never documented (→ §4 entry, update matrices, re-plan the wave).

**Why shadow mode is the cheapest reversibility:** it catches the R-5-class divergence *before* it can corrupt a real PZ, so most waves should never need the §3 runbook at all — the runbook is the safety net; shadow mode is the seatbelt.

---

## 6. How this plugs into the waves
| Wave | Highest rollback risk | Primary safety mechanism |
|---|---|---|
| 1 (shared libs + PZ authority) | R-5 write-path divergence | **Shadow-compare PZ status** (0 tolerance) before flipping canonical owner |
| 2 (proforma) | R-2 readiness-gate bypass | Shadow the gate; detector on ungated writes |
| 3 (shipment+DHL) | write-parity regressions | Per-action shadow + continuity check |
| 4 (PZ/wFirma) | correction-chain state loss | Snapshot `wfirma.db`; `reconcile_from_timeline` on rollback |
| 5 (inventory/docs/reporting) | greenfield (no old authority) | Lower risk — no shadow needed for net-new UI; standard checkpoint |
| 6 (V1 decommission) | irreversible by design | **Gated on all prior waves committed**; this is the one wave that ends rollback-eligibility — require explicit operator final sign-off |

**Decommission caveat:** Wave 6 is the point of no return (V1 files removed). It must not start until Waves 1–5 are *committed* (past stability window, detectors green) and operators confirmed on V2. Until then, every V1/Track-1 surface stays serveable precisely to keep rollback possible.
