# Operator Runbook — PR #640: Merge → Deploy → Verification

**Decision on record:** 🟢 **GO** for PR #640 merge. Shipment accounting (AWB
2315714531) stays blocked **by design**. PR-2 is a separate, later PR.

**Scope of this runbook:** the complete operator sequence from squash-merge
through PROJECT_STATE update. Every step states what success looks like, what
blocks progression, and what to do on failure. All merge / deploy / prod-write
steps are **operator-executed** — no agent performs them.

**Non-negotiable gate ordering:** the post-merge gate has **four** conditions.
They are strict and sequential. **`HASH VERIFIED` must occur before
`AWB VERIFIED`.** This corrects an earlier ambiguity and is not negotiable —
AWB recheck against an unverified production tree is meaningless.

---

## ⛔ HOLD STATEMENT (in force until this sequence closes)

Until all four gate conditions are VERIFIED and PROJECT_STATE is updated:

- **No PR-2.** Do not open, implement, or combine the confirmation workflow.
- **No PZ / wFirma.** Do not generate a PZ or post to wFirma for AWB 2315714531
  or any image-only shipment.
- **No new implementation campaign.** The GATE 2 queue is at ceiling (3 impl +
  1 docs). The only permitted queue action is draining it via this merge.

Violating the hold re-introduces the exact audit hole this sequence prevents.

---

## Reference SHAs (fill the squash SHA at Phase 1)

| Name | Value | Meaning |
|---|---|---|
| Base | `4652292` | `origin/main` the deploy gate diffs against |
| Last code SHA | `f6c7ec2` | reviewer-challenge PASS; code frozen here |
| Branch HEAD | `a92e4a0` | docs-only delta since `f6c7ec2` |
| **Squash SHA** | `__________` | **captured at Phase 1, step 2 — the deploy target** |

---

## Phase 1 — Merge

### Step 1.1 — Pre-merge review
- **Do:** Confirm PR #640 is `OPEN / MERGEABLE / CLEAN`. Confirm the code SHA is
  still `f6c7ec2` (delta to HEAD `a92e4a0` is docs-only).
- **Success:** mergeable + clean + code SHA unchanged.
- **Blocks progression:** any code SHA other than `f6c7ec2`.
- **On failure:** re-run reviewer-challenge against the new code SHA before any
  merge. Do not proceed on an unreviewed code change.

### Step 1.2 — Squash merge
- **Do:** Squash-merge PR #640 into `main` (operator action: `gh pr merge --squash`).
- **Success:** PR #640 shows `MERGED`.
- **Blocks progression:** merge conflict or non-clean state.
- **On failure:** stop. Rebase/resolve, re-review, restart Phase 1.

### Step 1.3 — Capture the real squash SHA
- **Do:** Read the **actual** new `origin/main` tip SHA. Record it in the table
  above. Do **not** assume or reuse a prior value.
- **Success:** a concrete squash SHA is written down and used by every later step.
- **Blocks progression:** proceeding without the real SHA.
- **On failure:** re-fetch `origin/main`; capture the tip before continuing.

> **MERGE VERIFIED** ✅ is satisfied when 1.2 + 1.3 are complete.

---

## Phase 2 — 7-Agent Deploy Gate

### Step 2.1 — Run the gate
- **Do:** Run the full 7-agent gate (`/deploy`) against `4652292 → <squash SHA>`:
  lead-coordinator, git-diff-reviewer, backend-impact-reviewer,
  persistence-storage-reviewer, security-reviewer, qa-reviewer, release-manager.
- **Success:** every agent returns a verdict block; lead-coordinator issues GO.
- **Blocks progression:** any HIGH/CRITICAL finding; any test failure (QA is an
  unconditional blocker); any forbidden-path or schema finding.
- **On failure:** resolve the finding inline or escalate. Do **not** deploy on a
  partial gate. The gate **cannot close** until all four conditions (Phase 5) are met.

> Diff is backend-only (`service/app/**` + `service/tests/**`), no root-engine
> file → standard robocopy; Lesson J is N/A here.

---

## Phase 3 — Deployment

### Step 3.1 — Deploy on GO only
- **Do:** Only after a GO at 2.1, perform the standard sync (`service/app →
  prod app dir`) and restart the service (operator-only prod write).
- **Success:** sync completes; service restarts and is healthy.
- **Blocks progression:** any sync error or service failing to start.
- **On failure:** invoke the release-manager rollback command for this squash SHA;
  restore from backup; do not proceed to verification.

> **DEPLOY VERIFIED** ✅ is satisfied when 3.1 completes cleanly.

---

## Phase 4 — Verification (strict order)

### Step 4.1 — Hash-verify (MUST run before 4.2)
- **Do:** Compute LF-normalized SHA256 of the live production files and compare
  against the verification clone checked out at the **squash SHA**. Record both
  the raw-CRLF (transfer) and LF-normalized (authority) hashes.
- **Success:** LF-normalized live hash == verification clone @ squash SHA.
- **Blocks progression:** any mismatch — **AWB recheck (4.2) must NOT run until
  this passes.**
- **On failure:** the deployed tree does not match the intended SHA. Re-sync,
  re-restart, re-hash. Do not promote "deployed" to a fact; do not run 4.2.

> **HASH VERIFIED** ✅ is satisfied here. **This gates 4.2 — non-negotiable.**

### Step 4.2 — Recheck AWB 2315714531
- **Do:** Run the recheck/recovery on AWB 2315714531 through the deployed path.
- **Success:** a `vision_invoice` proposal is written and the state conditions in
  Phase 5 all hold.
- **Blocks progression:** any state condition perturbed (see checklist).
- **On failure:** treat as a deploy regression. Roll back; the proposal layer
  must never touch customs/accounting state.

> **AWB VERIFIED** ✅ is satisfied when 4.2 + the Phase 5 checklist all pass.

---

## Phase 5 — Four-Condition Gate Checklist (work in sequence)

The deploy gate **closes only** when all four are true, **in this order**:

```
[ ] 1. MERGE VERIFIED   — #640 squash-merged; real squash SHA captured (Phase 1)
[ ] 2. DEPLOY VERIFIED  — robocopy + service restart completed (Phase 3)
[ ] 3. HASH VERIFIED    — LF-normalized SHA256 live == C:\PZ-verify @ squash SHA (4.1)
[ ] 4. AWB VERIFIED     — AWB 2315714531 recheck, state unchanged (4.2 + below)
```

**`HASH VERIFIED` (3) gates `AWB VERIFIED` (4).** Do not check box 4 until box 3
is checked.

### AWB 2315714531 state-invariance sub-checklist (all must hold for box 4)
```
[ ] vision_invoice ............ WRITTEN (advisory proposal present)
[ ] operator_confirmed ........ false   (no promotion — no True-writer exists yet)
[ ] rows ...................... UNCHANGED (engine accounting layer untouched)
[ ] invoice_totals ............ UNCHANGED
[ ] clearance_decision ........ UNCHANGED
[ ] CIF ....................... 732 (RESOLVED — customs ladder unaffected)
```

Any unchecked box → gate stays OPEN; "deployed" stays REPORTED; the HOLD remains
in force; PR-2 does not start.

---

## Phase 6 — PROJECT_STATE Update

### Step 6.1 — Record the closed gate
- **Do:** flow-context-keeper (sole PROJECT_STATE owner, RULE 3) records: the
  squash SHA, the LF-normalized hash result, and all four VERIFIED conditions.
  Promote "deployed" from REPORTED → **VERIFIED** only after box 3 (HASH) passed.
- **Success:** PROJECT_STATE FACTS reflect a cryptographically clean baseline at
  the squash SHA.
- **Blocks progression:** none — this is the closing step.
- **On failure:** if any box was not genuinely VERIFIED, do not record closure.
  Re-open the relevant phase.

> Optional, in-pattern: a single Cliq `#PZ` post on this same event path
> (no daemon, no second state owner).

---

## Sequence-closed definition

This sequence is **closed** only when:
1. All four gate conditions are VERIFIED in order (HASH before AWB), and
2. PROJECT_STATE is updated with the squash SHA + hash result.

On closure: the HOLD lifts, a GATE 2 slot is freed, and PR-2 may be scoped as a
separate PR. Until then, the HOLD statement at the top of this runbook governs.
