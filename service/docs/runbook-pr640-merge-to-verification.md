# Operator Runbook — PR #640: Merge → Deploy → Verification

**Decision on record:** 🟢 **GO** for PR #640 merge. Shipment accounting (AWB
2315714531) stays blocked **by design**. PR-2 is a separate, later PR.

**Scope of this runbook:** the complete operator sequence from squash-merge
through PROJECT_STATE update. Every step states what success looks like, what
blocks progression, and what to do on failure. All merge / deploy / prod-write
steps are **operator-executed** — no agent performs them.

**Non-negotiable gate ordering:** the post-merge gate has **five** conditions.
They are strict and sequential:

```
MERGE VERIFIED → DEPLOY VERIFIED → HASH VERIFIED → ROLLBACK ANCHOR VERIFIED → AWB VERIFIED
```

- **`HASH VERIFIED` before `ROLLBACK ANCHOR VERIFIED`** — anchor integrity is
  proven against a tree already confirmed to match the squash SHA.
- **`ROLLBACK ANCHOR VERIFIED` before `AWB VERIFIED`** — AWB recheck is the first
  step that **mutates production state** (it writes `vision_invoice` to the batch
  audit) and interprets business behavior. Rollback safety must be locked **before**
  that begins, not after. An anchor verified after a leak is verified too late.

This ordering corrects an earlier ambiguity and is not negotiable.

---

## ⛔ HOLD STATEMENT (in force until this sequence closes)

Until all five gate conditions are VERIFIED and PROJECT_STATE is updated:

- **No PR-2.** Do not open, implement, or combine the confirmation workflow.
- **No PZ / wFirma.** Do not generate a PZ or post to wFirma for AWB 2315714531
  or any image-only shipment.
- **No new implementation campaign.** The GATE 2 queue is at ceiling (3 impl +
  1 docs). The only permitted queue action is draining it via this merge.

Violating the hold re-introduces the exact audit hole this sequence prevents.

---

## Reference SHAs / anchors (fill during execution)

| Name | Value | Meaning |
|---|---|---|
| Base | `4652292` | `origin/main` the deploy gate diffs against |
| Last code SHA | `f6c7ec2` | reviewer-challenge PASS; code frozen here |
| Branch HEAD | `7b591f7` | docs-only delta since `f6c7ec2` |
| **Squash SHA** | `__________` | **captured at Phase 1, step 1.3 — the deploy target** |
| **PROD_BASELINE_MANIFEST** | `__________` | **pre-deploy LF-normalized hash manifest of the live tree (Phase 3, step 3.1)** |
| **Backup path** | `__________` | **pre-deploy backup location, outside the overwrite target (step 3.1)** |
| **Rollback command** | `__________` | **release-manager rollback command for this squash SHA (step 3.1)** |

> Production is robocopy-synced, **not** a git checkout — there is no readable
> `git` SHA on the live tree. The rollback baseline is therefore the
> **PROD_BASELINE_MANIFEST + file backup**, not a "prod SHA."

---

## Phase 1 — Merge

### Step 1.1 — Pre-merge review
- **Do:** Confirm PR #640 is `OPEN / MERGEABLE / CLEAN`. Confirm the code SHA is
  still `f6c7ec2` (delta to HEAD `7b591f7` is docs-only).
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
  Release-manager produces the exact rollback command for this squash SHA.
- **Blocks progression:** any HIGH/CRITICAL finding; any test failure (QA is an
  unconditional blocker); any forbidden-path or schema finding.
- **On failure:** resolve the finding inline or escalate. Do **not** deploy on a
  partial gate. The gate **cannot close** until all five conditions (Phase 5) are met.

> Diff is backend-only (`service/app/**` + `service/tests/**`), no root-engine
> file → standard robocopy; Lesson J is N/A here.

---

## Phase 3 — Deployment

### Step 3.1 — Capture rollback anchor inputs (BEFORE any overwrite)
**This step must complete before the sync in 3.2. Once prod is overwritten, these
inputs cannot be reconstructed.**
- **Do:**
  1. Compute and store the **PROD_BASELINE_MANIFEST** — LF-normalized SHA256 of
     every live file the deploy will overwrite. Record it in the table.
  2. **Back up** those files **plus the AWB 2315714531 batch audit/state files**
     (Phase 4 mutates the audit) to a path **outside** the overwrite target.
     Record the backup path.
  3. Record the **rollback command** from release-manager (step 2.1).
- **Success:** manifest stored, backup written and readable, rollback command recorded.
- **Blocks progression:** missing manifest, missing/unreadable backup, or no
  rollback command. Do **not** deploy without all three.
- **On failure:** stop before any sync. Re-capture. A deploy without a verified
  pre-overwrite baseline has no recoverable rollback target.

### Step 3.2 — Deploy on GO only
- **Do:** Only after a GO at 2.1 **and** anchor inputs captured at 3.1, perform
  the standard sync (`service/app → prod app dir`) and restart the service
  (operator-only prod write).
- **Success:** sync completes; service restarts and is healthy.
- **Blocks progression:** any sync error or service failing to start.
- **On failure:** execute the recorded rollback command; restore from the backup
  path; do not proceed to verification.

> **DEPLOY VERIFIED** ✅ is satisfied when 3.2 completes cleanly.

---

## Phase 4 — Verification (strict order: HASH → ANCHOR → AWB)

### Step 4.1 — Hash-verify (MUST run before 4.2)
- **Do:** Compute LF-normalized SHA256 of the live production files and compare
  against the verification clone checked out at the **squash SHA**. Record both
  the raw-CRLF (transfer) and LF-normalized (authority) hashes.
- **Success:** LF-normalized live hash == verification clone @ squash SHA.
- **Blocks progression:** any mismatch — **anchor verification (4.2) must NOT
  run until this passes.**
- **On failure:** the deployed tree does not match the intended SHA. Re-sync,
  re-restart, re-hash. Do not promote "deployed" to a fact.

> **HASH VERIFIED** ✅ satisfied here. Gates 4.2.

### Step 4.2 — Rollback-anchor verify (MUST run before 4.3 / AWB)
Lock rollback safety **before** any state-mutating business verification.
- **Do:** Verify all of:
  1. **Squash SHA** is recorded (Phase 1).
  2. **PROD_BASELINE_MANIFEST** is recorded and matches the pre-deploy live tree (3.1).
  3. **Backup files exist, are readable/restorable**, cover the overwrite set **and**
     the AWB batch audit/state, and live outside the overwrite target (3.1).
  4. **Release worktree SHA == squash SHA** *and the worktree is clean* (no local mods).
  5. **Hash-comparison artifacts** (4.1 raw + LF hashes) are stored.
  6. **Rollback command** is recorded and parseable.
- **Success:** all six confirmed; rollback is executable on demand.
- **Blocks progression:** any item missing/inconsistent — **AWB recheck (4.3)
  must NOT begin.**
- **On failure:** do not start AWB. Re-capture the missing artifact. If a backup
  is missing and prod is already overwritten, treat as a deploy-integrity incident:
  re-sync from the verification clone @ squash SHA and re-anchor before continuing.

> **ROLLBACK ANCHOR VERIFIED** ✅ satisfied here. Gates 4.3.

### Step 4.3 — Recheck AWB 2315714531 (state-mutating — anchor must be locked)
- **Do:** Run the recheck/recovery on AWB 2315714531 through the deployed path.
  (This writes the advisory `vision_invoice` proposal to the batch audit.)
- **Success:** a `vision_invoice` proposal is written and the Phase 5
  state-invariance sub-checklist all holds.
- **Blocks progression:** any of the five protected fields changed (see below).
- **On failure / leak:** see "Accounting-authority leak" below — HALT and roll back.

> **AWB VERIFIED** ✅ satisfied when 4.3 + the state-invariance sub-checklist pass.

---

## Phase 5 — Five-Condition Gate Checklist (work in sequence)

The deploy gate **closes only** when all five are true, **in this order**:

```
[ ] 1. MERGE VERIFIED            — #640 squash-merged; real squash SHA captured (Phase 1)
[ ] 2. DEPLOY VERIFIED           — robocopy + service restart completed (Phase 3)
[ ] 3. HASH VERIFIED             — LF-normalized SHA256 live == C:\PZ-verify @ squash SHA (4.1)
[ ] 4. ROLLBACK ANCHOR VERIFIED  — manifest + backup + clean worktree@SHA + rollback cmd (4.2)
[ ] 5. AWB VERIFIED              — AWB 2315714531 recheck, state unchanged (4.3 + below)
```

**Gating chain (non-negotiable):** `HASH (3)` gates `ANCHOR (4)` gates `AWB (5)`.
Do not check a box until the box above it is checked.

### AWB 2315714531 state-invariance sub-checklist (all must hold for box 5)
```
[ ] vision_invoice ............ WRITTEN   (advisory proposal present — intended write)
[ ] operator_confirmed ........ false     (no promotion — no True-writer exists yet)
[ ] rows ...................... UNCHANGED (engine accounting layer untouched)
[ ] invoice_totals ............ UNCHANGED
[ ] clearance_decision ........ UNCHANGED
[ ] CIF ....................... 732       (RESOLVED — customs ladder unaffected)
```

Any unchecked box → gate stays OPEN; "deployed" stays REPORTED; the HOLD remains
in force; PR-2 does not start.

---

## Accounting-authority leak — if ANY protected field changes

`vision_invoice` **must exist** (intended write). But if `operator_confirmed`
becomes `true`, or `rows` / `invoice_totals` / `clearance_decision` / CIF (732)
change at all, **accounting authority has leaked. The deployment is FAILED
regardless of test results.** This is CRITICAL.

1. **HALT immediately.** Do not confirm the proposal, do not generate PZ, do not
   post to wFirma.
2. **Execute the rollback** using the verified anchor (rollback command + backup /
   PROD_BASELINE_MANIFEST).
3. **Re-verify post-rollback**: the protected fields are back to baseline and
   `operator_confirmed = false`.
4. **File an incident; classify per Lesson I** — workflow class: "the advisory
   proposal layer reached accounting/customs state." Fix at the class level, not
   for this one shipment.
5. Gate stays OPEN; "deployed" never promotes to VERIFIED; HOLD remains.

The rollback anchor (box 4) is exactly what makes this rollback executable — which
is why it is gated **before** AWB recheck begins.

---

## Phase 6 — PROJECT_STATE Update

### Step 6.1 — Record the closed gate
- **Do:** flow-context-keeper (sole PROJECT_STATE owner, RULE 3) records: the
  squash SHA, the LF-normalized hash result, the rollback-anchor artifacts, and
  all five VERIFIED conditions. Promote "deployed" from REPORTED → **VERIFIED**
  only after box 3 (HASH) passed.
- **Success:** PROJECT_STATE FACTS reflect a cryptographically clean baseline at
  the squash SHA, with rollback anchor on record.
- **Blocks progression:** none — this is the closing step.
- **On failure:** if any box was not genuinely VERIFIED, do not record closure.
  Re-open the relevant phase.

> Optional, in-pattern: a single Cliq `#PZ` post on this same event path
> (no daemon, no second state owner).

---

## Sequence-closed definition

This sequence is **closed** only when:
1. All five gate conditions are VERIFIED in order (HASH → ANCHOR → AWB), and
2. PROJECT_STATE is updated with the squash SHA + hash result + anchor record.

On closure: the HOLD lifts, a GATE 2 slot is freed, and PR-2 may be scoped as a
separate PR. Until then, the HOLD statement at the top of this runbook governs.
