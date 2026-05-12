# DHL Self-Clearance Program — Planning Artifacts

This directory holds the planning artifacts for W-5 (DHL self-clearance) phases P0 through P5.
Each phase has a self-contained execution instruction that a future Claude Code session can fire without needing to re-read the master plan first.

**Status:** DESIGNED (not yet implemented). P0 ready to fire in the next focused session.
**Designed:** 2026-05-12
**Wall-clock estimate:** 3 weeks minimum, 4-5 weeks realistic
**Source-of-truth ADRs:** ADR-012 (umbrella) + ADR-013..016 (per-phase decisions)

## Firing order (strict serial)

```
P0 → P2 → P3 → P4 → P5
```

P0 is a prerequisite scaffolding phase. P2-P5 each ship independently behind default-OFF flags with their own shadow window.

## Files

| File | Purpose |
|---|---|
| [`00_MASTER_PLAN.md`](00_MASTER_PLAN.md) | Phase dependencies, blast radius, sequencing, shared infrastructure, risk matrix |
| [`01_P0_FOUNDATION.md`](01_P0_FOUNDATION.md) | P0 scaffolding instruction — state engine + coordinator + manifest + flags + classifier + admin runtime-flags endpoint |
| [`02_P2_PROACTIVE_DISPATCH.md`](02_P2_PROACTIVE_DISPATCH.md) | P2 instruction — proactive customs dispatch (ADR-013) |
| [`03_P3_TRACKING_WATCHER.md`](03_P3_TRACKING_WATCHER.md) | P3 instruction — tracking watcher + arrival-driven follow-up scheduler (ADR-014) |
| [`04_P4_CLARIFICATION_REPLY.md`](04_P4_CLARIFICATION_REPLY.md) | P4 instruction — thread-based clarification reply (ADR-015) |
| [`05_P5_SAD_PZ_TRIGGER.md`](05_P5_SAD_PZ_TRIGGER.md) | P5 instruction — SAD/PZC unlock + PZ trigger (ADR-016) |

## Named operator decisions (locked 2026-05-12)

| Item | Resolution |
|---|---|
| **Reviewer (primary / backup)** | Tejal (primary) / Amit (backup for P5 specifically) |
| **Corpus labelling owner** | Tejal labels ≥200 historical DHL emails; Amit spot-checks 10–15% |
| **Kill-switch mechanism** | Admin runtime-flags endpoint: `POST /api/v1/admin/runtime-flags/self-clearance` with `X-API-Key` auth (no UI) |
| **UI commitment** | Read-only state pill on Mac dashboard. **Full operator UI deferred to Windows Atlas.** No writable controls, no phase toggles, no approval UI, no override UI on Mac. |
| **`dhl_followup_sla.py` policy** | NOT rewritten in place. New `dhl_selfclearance_followup_v2.py` created alongside; coordinator routes by `clearance_path`. Legacy stays for Path B until operational evidence justifies deprecation. |

## Mandatory invariants (from ADR-012)

- **HL1** never PZ before SAD link
- **HL2** never inventory mutation before customs complete
- **HL3** never agency-forward on self-clearance path
- **HL4** one AWB = one thread (engine side; DHL-initiated fresh threads handled via `thread_id_aliases[]`)

## Single point of catastrophic failure

The P4/P5 intent classifier. Historical-corpus shadow validation (P0 work item) must complete before any state-advancing code uses the classifier.
