# Campaign 03 Readiness Package (Campaign 02.75-FINAL)

**Issued:** 2026-06-13 · **Author:** orchestrator (independent re-verification, no builder trust)
**Verdict:** **NO-GO (provisional)** — engineering complete & green; 0/3 production gates met because the gates are operator-only (merges + 2 deploys + calendar stabilization). Flips to **GO** automatically once the three gates below close. No engineering blocker remains.

---

## 1. Authority deployment status

| Authority | Code state | Tests | In production? |
|---|---|---|---|
| NameNormalization (B5/#577) | merge-ready, MERGEABLE/CLEAN | PZ 221+1known; parity green | **NO** — absent from `C:\PZ` |
| FollowUpAuthority (B6) | merge-ready, clean | PZ 221+1known; 13 authority | **NO** — absent |
| Tracking (Tracking) | merge-ready, clean | own 22; Carrier 412; PZ 221+1known | module exists in prod; **consolidated version NOT deployed** |
| Address (AWB) | merge-ready, clean (config union pending) | 32 authority; Carrier 420; PZ 221+1known | **NO** — absent |

**Status: PREPARED, NOT DEPLOYED.** All four are independently test-green against the enforced baseline. Production = `62810c2`.

## 2. Drift deployment status

- Audit + drift layer (`authority_audit.py`, `authority_manifest_pinned.json`, `authority_startup.py` R1, `authority_drift_service.py` R2/Phase4) lives on `feat/c025-authority-audit-drift` @ `2f12830` (carries the C1 NFD contract fix).
- C1–C6 contracts: 6 passed. Drift detection: 9 passed (verified prior session).
- **Status: PREPARED, NOT DEPLOYED.** This is **Deploy #2**, after Deploy #1 + stabilization-open.

## 3. Stabilization readiness

- Window cannot open until Deploy #1 lands the authority layer. Definition: ≥7 days OR ≥100 shipments.
- Monitoring/rollback/escalation checklists: PREPARED (`stabilization-package.md`).
- **Status: NOT STARTED** (blocked on Deploy #1). Calendar clock is operator-owned; agent cannot advance it.

## 4. Open risks

| Risk | Severity | Mitigation |
|---|---|---|
| Deploy #1 also carries un-deployed B7 backup program (#574) | MEDIUM | 7-agent gate must review B7 surface, not just authority; disclosed in deploy-1-package.md §1 |
| AWB↔Tracking config.py union mis-resolved | LOW | exact union patch pre-written (awb PR body); only one anchor; verified by post-rebase Carrier 420 |
| Authority flags accidentally enabled at deploy | LOW | all default OFF in code; smoke 8b confirms inert; no `.env` entry needed |
| Manifest hash drift after a legitimate later change | LOW | re-pin via `authority_audit.py` + PR-branch commit; escalation path defined |
| B5 parity regression in production | LOW→MED | parity suite green; workflow smoke 8b runs a real PZ batch vs golden |

## 5. Remaining debt

- Flags ship OFF; turning each authority ON is deferred post-stabilization (one-at-a-time, each with its own smoke). This is intentional sequencing, not debt-by-omission.
- Contract-test/drift layer split into Deploy #2 (recorded decision, task #5).
- Dev scripts (`extract_name_corpus.py`, `awb_resolution_audit.py`) intentionally not deployed.
- `wfirma-draft-cancel` branch remains PARKED (out of scope for 02.75; tracked in PROJECT_STATE).

## 6. Campaign 03 recommendation

**NO-GO until all three gates close — then GO:**

```
GATE A: Authority layer live   →  B5+B6+Tracking+AWB merged + Deploy #1 + smoke PASS
GATE B: Drift layer live       →  Deploy #2 (audit-drift) + startup manifest (R1) clean
GATE C: Stabilization complete →  ≥7 days OR ≥100 shipments, zero unexplained drift
```

**Current: 0/3.** All three are operator-gated (merges + deploys + calendar). No remaining engineering work blocks Campaign 03 — the authority program is code-complete, test-green, and merge-ready. Recommendation: proceed through the 2 real operator gates (merge train, then the two deploys), run the stabilization window, then re-issue this package as **GO** with the closed-gate evidence.

## 7. Evidence index

- `deploy-1-package.md` — Deploy #1 content, smoke, rollback, 7-agent gate inputs
- `stabilization-package.md` — window, drift tracking, rollback/escalation criteria
- PR bodies: `pr-body-b5-name-normalization.md`, `pr-body-b6-followup-authority.md`, `pr-body-tracking-direction.md`, `pr-body-awb-address-authority.md`
- `authority_manifest_pinned.json` — 4 pinned SHAs
- Test evidence (this session, isolated re-runs): B5 PZ 221+1known/parity green · B6 PZ 221+1known/13 · Tracking 22/Carrier 412/PZ 221+1known · AWB 32/Carrier 420/PZ 221+1known
