# OPERATOR RUNBOOK — PR #640: Merge → Deploy → Verify (AUTHORITATIVE)

> This is the **single authoritative operator guide** for executing the PR #640
> rollout. Execute top to bottom. Where a decision tree is given, follow it
> exactly — **no operator discretion** is permitted inside a "NO EXCEPTIONS"
> zone. All merge / deploy / prod-write actions are **operator-executed**; no
> agent performs them.

## Document control

| Field | Value |
|---|---|
| Decision on record | 🟢 GO for PR #640 merge (deploy under the gate below) |
| Snapshot validated at | **2026-06-17T14:50:33Z** (re-validate per §1 before starting) |
| Base (`origin/main`) | `4652292` |
| Code SHA (frozen, reviewer-PASS) | `f6c7ec2` |
| Branch HEAD (docs-only delta) | `69c6758` |
| Squash SHA | `__________` (captured §STAGE 1) |
| Five-stage gate | `MERGE → DEPLOY → HASH → ROLLBACK ANCHOR → AWB` |

**Execution log (operator fills timestamps):**

| Stage | Entered (UTC) | Exited (UTC) | Verdict |
|---|---|---|---|
| Pre-exec validation | | | |
| STAGE 1 — MERGE | | | |
| 7-agent deploy gate | | | |
| STAGE 2 — DEPLOY | | | |
| STAGE 3 — HASH | | | |
| STAGE 4 — ROLLBACK ANCHOR | | | |
| STAGE 5 — AWB | | | |
| PROJECT_STATE close | | | |

---

## §0 — Governance state snapshot (validate before proceeding)

This is the state the rollout assumes. **If any line is false at execution time,
STOP and reconcile before starting.**

| # | Asserted state | Source of truth |
|---|---|---|
| 0.1 | PR #640 `OPEN / MERGEABLE / CLEAN`, not draft | `gh pr view 640` |
| 0.2 | Code frozen at `f6c7ec2`; HEAD `69c6758` is docs-only ahead | `git log f6c7ec2..origin/<branch>` = docs only |
| 0.3 | GATE 2 queue FULL: 3 impl (#643, #640, #630) + 1 docs (#637) | `gh pr list --state open` |
| 0.4 | PZ / wFirma blocked **by design** (layer 3 empty; no confirmed path) | ADR-030; handoff doc |
| 0.5 | PR-2 **not open** (separate, later PR) | `gh pr list` |
| 0.6 | Production "deployed at `4652292`" is REPORTED, **not** hash-verified | PROJECT_STATE FACTS |
| 0.7 | Authority chain clean: sole `vision_invoice` writer, no consumer, no daemon | code grep (verified) |

---

## §1 — PRE-EXECUTION VALIDATION (all must PASS — gate before STAGE 1)

> 🔒 **NO EXCEPTIONS.** If any check fails, do not enter STAGE 1.

```
[ ] V1  PR status      : gh pr view 640 → state=OPEN, mergeable=MERGEABLE, mergeStateStatus=CLEAN, isDraft=false
[ ] V2  Code SHA       : git log --oneline 4652292..origin/fix/invoice-image-only-lineitem-extraction
                         → every commit AFTER f6c7ec2 is docs-only (.md / .claude). If a CODE file appears → FAIL.
[ ] V3  Docs sync      : working tree clean (git status --short empty); HEAD == origin HEAD (69c6758 or newer docs-only)
[ ] V4  Queue capacity : gh pr list --state open → ≤ 3 implementation PRs. #640 merge is slot-FREEING, allowed.
[ ] V5  Blockers honest: PROJECT_STATE shows prod=REPORTED (not VERIFIED); PR-2 not open; PZ/wFirma blocked-by-design
[ ] V6  Authority chain: grep -rn "vision_invoice" service/app  → writer only in vision_extractor; only status-flag
                         read in routes_dashboard; no PZ/wFirma/customs/landed-cost consumer
```

**Decision:**
```
All V1–V6 PASS ──────────────► proceed to STAGE 1
Any V2 shows a code file ────► STOP; re-run reviewer-challenge on the new code SHA
Any other FAIL ──────────────► STOP; reconcile the failing line; re-run §1
```

---

## ⛔ HOLD STATEMENT & NO-EXCEPTIONS ZONES

**HOLD (in force until the full five-stage sequence closes + PROJECT_STATE updated):**
- **No PR-2.** Do not open / implement / combine the confirmation workflow.
- **No PZ / wFirma** for AWB 2315714531 or any image-only shipment.
- **No new implementation campaign** (GATE 2 full; only draining is allowed).

**NO-EXCEPTIONS zones (operator discretion forbidden):**
1. §1 pre-execution validation.
2. Gate ordering `HASH → ROLLBACK ANCHOR → AWB`.
3. The forbidden-field incident protocol (§STAGE 5 / §6).
4. "Deployed" stays REPORTED until HASH VERIFIED (STAGE 3) passes.

---

## §2 — FIVE-STAGE GATE (overview + gating chain)

```
STAGE 1  MERGE VERIFIED ──┐
STAGE … 7-agent gate ─────┤ (GO required before STAGE 2)
STAGE 2  DEPLOY VERIFIED ─┤
STAGE 3  HASH VERIFIED ───┤ gates ▼
STAGE 4  ROLLBACK ANCHOR VERIFIED ─ gates ▼
STAGE 5  AWB VERIFIED
```
Rationale for the order: AWB recheck (STAGE 5) **mutates production state** (writes
`vision_invoice` to the batch audit). Rollback safety (STAGE 4) must be locked
**before** any mutation, against a tree already proven correct by HASH (STAGE 3).

---

## STAGE 1 — MERGE  →  exit: **MERGE VERIFIED**

**Entry:** §1 all PASS.
**Execute:**
1. `gh pr view 640` — re-confirm OPEN/MERGEABLE/CLEAN.
2. `gh pr merge 640 --squash` (operator).
3. `git fetch origin main && git rev-parse --short origin/main` — record the
   **real** squash SHA in Document control. **Do not assume/reuse a prior value.**

**Exit verification (pass/fail):**
- ✅ PASS: PR #640 = MERGED **and** squash SHA recorded.
- ❌ FAIL (conflict/non-clean): STOP → resolve/rebase → re-review → re-run STAGE 1.

---

## 7-AGENT DEPLOY GATE  (between STAGE 1 and STAGE 2 — GO required)

Run `/deploy` against `4652292 → <squash SHA>`. Sequencing & dependencies:

```
        ┌─ deploy_git_diff_reviewer ──────────┐
        ├─ deploy_backend_impact_reviewer ─────┤
(parallel) deploy_persistence_storage_reviewer ┼─► deploy_lead_coordinator ─► GO / NO-GO
        ├─ deploy_security_reviewer ───────────┤        (final authority)
        ├─ deploy_qa_reviewer ─────────────────┤
        └─ deploy_release_manager ─────────────┘
```
- All 6 reviewers run in parallel; **lead-coordinator decides last** and only after
  all 6 verdicts are in.
- **release_manager must emit the exact rollback command for this squash SHA** —
  it is a required input to STAGE 4. No rollback command → gate cannot reach GO.
- **Hard blockers (any one = NO-GO):** QA test failure (unconditional);
  HIGH/CRITICAL security finding (cannot be overridden); forbidden-path or schema
  finding; missing router registration / auth guard.

**Decision:**
```
lead-coordinator GO + rollback cmd present ─► STAGE 2
Any hard blocker ──────────────────────────► STOP; resolve inline or escalate; gate stays OPEN
```
> Diff is backend-only (`service/app/**` + `service/tests/**`), no root-engine file → standard robocopy; Lesson J N/A.

---

## STAGE 2 — DEPLOY  →  exit: **DEPLOY VERIFIED**

**Entry:** 7-agent GO.

### Step 2A — Capture rollback-anchor inputs **BEFORE any overwrite** 🔒 NO EXCEPTIONS
> Once prod is overwritten these cannot be reconstructed.
1. **PROD_BASELINE_MANIFEST** — LF-normalized SHA256 of every live file the deploy
   will overwrite. Example:
   ```powershell
   Get-ChildItem -Recurse C:\PZ\app -File | ForEach-Object {
     $lf = (Get-Content $_.FullName -Raw) -replace "`r`n","`n"
     $h  = [System.BitConverter]::ToString(
             [System.Security.Cryptography.SHA256]::Create().ComputeHash(
               [Text.Encoding]::UTF8.GetBytes($lf))).Replace("-","")
     "$h  $($_.FullName)"
   } | Set-Content C:\PZ-backups\pr640\PROD_BASELINE_MANIFEST.txt
   ```
2. **Backup** the overwrite set **+ the AWB 2315714531 batch audit/state files**
   (STAGE 5 mutates the audit) to a path **outside** the overwrite target:
   ```powershell
   robocopy C:\PZ\app C:\PZ-backups\pr640\app /MIR /COPY:DAT
   robocopy C:\PZ\<batch-store>\2315714531 C:\PZ-backups\pr640\audit /E /COPY:DAT
   ```
3. **Record** the release_manager **rollback command** verbatim in Document control.

### Step 2B — Sync + restart (operator-only prod write)
```powershell
robocopy <repo>\service\app C:\PZ\app /MIR /COPY:DAT
sc.exe stop PZService ; sc.exe start PZService
```

**Exit verification (pass/fail):**
- ✅ PASS: manifest stored + backup readable + rollback cmd recorded (2A) **and**
  sync clean + service healthy (2B).
- ❌ FAIL (2A incomplete): STOP **before** sync — no recoverable rollback target.
- ❌ FAIL (2B): execute rollback command; restore from backup; do not verify.

---

## STAGE 3 — HASH  →  exit: **HASH VERIFIED**  🔒 gates STAGE 4

**Entry:** DEPLOY VERIFIED.
**Execute:** LF-normalized SHA256 of live prod files vs the verification clone
checked out at the **squash SHA**; record raw-CRLF (transfer) + LF (authority) hashes.
```powershell
git -C C:\PZ-verify fetch origin ; git -C C:\PZ-verify checkout <squash SHA>
# hash live tree (as in 2A) and compare LF-normalized digests to C:\PZ-verify
```
**Exit verification (pass/fail):**
- ✅ PASS: LF-normalized live == clone @ squash SHA. Promote prod REPORTED→**VERIFIED** allowed.
- ❌ FAIL: deployed tree ≠ squash SHA. Re-sync, re-restart, re-hash.
  **STAGE 4 must NOT begin. "Deployed" stays REPORTED.**

---

## STAGE 4 — ROLLBACK ANCHOR  →  exit: **ROLLBACK ANCHOR VERIFIED**  🔒 gates STAGE 5

**Entry:** HASH VERIFIED. **Purpose:** lock executable rollback BEFORE the
state-mutating AWB recheck.

**Rollback-anchor package — all six artifacts required:**
```
[ ] A1  Squash SHA recorded (Document control)
[ ] A2  PROD_BASELINE_MANIFEST present AND matches the pre-deploy live tree (2A.1)
[ ] A3  Backup exists, is READABLE/RESTORABLE, covers overwrite set + AWB audit,
        and is stored OUTSIDE the overwrite target (2A.2)
[ ] A4  Release worktree SHA == squash SHA  AND  worktree CLEAN (no local mods)
[ ] A5  Hash-comparison artifacts (STAGE 3 raw + LF digests) stored
[ ] A6  Rollback command recorded AND parseable (release_manager, 7-agent gate)
```
**Verification procedure:** confirm A1–A6 individually; for A3, open one backed-up
file and one backed-up audit file to confirm readability; for A4 run
`git -C <release-worktree> status --porcelain` (empty) + `rev-parse HEAD` (==squash SHA).

**Exit verification (pass/fail):**
- ✅ PASS: A1–A6 all confirmed → rollback is executable on demand.
- ❌ FAIL: **AWB recheck (STAGE 5) must NOT begin.** Re-capture the missing artifact.
  If a backup is missing and prod already overwritten → deploy-integrity incident:
  re-sync from clone @ squash SHA and re-anchor.

---

## STAGE 5 — AWB  →  exit: **AWB VERIFIED**

**Entry:** ROLLBACK ANCHOR VERIFIED.

### What AWB verification actually does in production (state-mutating)
Running the recheck on AWB 2315714531 invokes `run_image_only_invoice_extraction`,
which **writes** `audit["vision_invoice"]` — supplier, USD-only `fob_usd`, line
items, `confidence`, `operator_confirmed=false` — into the batch audit JSON
(`_merge_vision_invoice`, merge-not-replace, sticky, TOCTOU-guarded). This is the
**only** intended mutation. It must **not** touch CIF / `invoice_totals` / `rows` /
`clearance_decision`. The dashboard surfaces a status flag + "review and confirm"
warning; nothing reads the proposal into accounting.

### State-invariance sub-checklist (all must hold for AWB VERIFIED)
```
[ ] vision_invoice ........ WRITTEN   (intended materialization)
[ ] operator_confirmed .... false     (NO True-writer exists yet)
[ ] rows .................. UNCHANGED
[ ] invoice_totals ........ UNCHANGED
[ ] clearance_decision .... UNCHANGED
[ ] CIF .................... 732 (RESOLVED)
```
Detection: diff the batch audit JSON against the STAGE-2A backup; assert the four
accounting/customs keys are byte-identical and `operator_confirmed==false`.

**Exit verification (pass/fail):**
- ✅ PASS: `vision_invoice` written **and** all six sub-checklist lines hold.
- ❌ FAIL — `vision_invoice` missing: functional failure → investigate extractor; not a leak.
- ❌ FAIL — any protected field changed: **ACCOUNTING-AUTHORITY LEAK** → §6 protocol.

---

## §6 — FORBIDDEN-FIELD INCIDENT PROTOCOL  🔒 NO EXCEPTIONS

**Trigger:** at STAGE 5, `operator_confirmed` becomes `true`, OR `rows` /
`invoice_totals` / `clearance_decision` / resolved CIF (732) change at all.

**Detection mechanism per field (diff vs STAGE-2A audit backup):**

| Field | Detection | Expected |
|---|---|---|
| `operator_confirmed` | JSON value compare | `false` |
| `rows` | array deep-equal vs backup | unchanged (empty for this AWB) |
| `invoice_totals` | object deep-equal vs backup | unchanged |
| `clearance_decision` | object deep-equal vs backup | unchanged |
| resolved CIF | `resolve_cif(audit)` value+source | `RESOLVED`, `732`, `awb_customs.value_usd` |

**Protocol — execute in order, no deviation:**
```
HALT ──► ROLLBACK ──► RE-VERIFY ──► INCIDENT RECORD ──► GATE REMAINS OPEN
```
1. **HALT** — do not confirm the proposal, do not generate PZ, do not post wFirma.
2. **ROLLBACK** — run the recorded rollback command; restore backup / PROD_BASELINE_MANIFEST.
3. **RE-VERIFY** — protected fields back to baseline; `operator_confirmed=false`.
4. **INCIDENT RECORD** — file per Lesson I. Workflow class: "advisory proposal layer
   reached accounting/customs state." Fix at class level, not this shipment.
5. **GATE REMAINS OPEN** — "deployed" never promotes to VERIFIED; HOLD stays in force.

> `vision_invoice` *must exist* (intended write). Its presence is NOT a leak; a
> *changed accounting/customs field* is.

---

## §7 — PROJECT_STATE CLOSE  →  sequence closed

**Execute:** flow-context-keeper (sole PROJECT_STATE owner, RULE 3) records: squash
SHA, LF hash result, rollback-anchor artifacts, all five VERIFIED conditions.
Promote prod REPORTED→VERIFIED only after STAGE 3 passed.
> Optional in-pattern: one Cliq `#PZ` post on this same event path (no daemon, no second state owner).

**Five-condition close (in order — do not check a box until the one above is checked):**
```
[ ] 1. MERGE VERIFIED
[ ] 2. DEPLOY VERIFIED
[ ] 3. HASH VERIFIED
[ ] 4. ROLLBACK ANCHOR VERIFIED
[ ] 5. AWB VERIFIED
```

---

## §8 — WHAT UNBLOCKS WHAT (conditions, explicit)

**PR-2 may be opened ONLY when ALL of:**
```
[ ] Five-condition gate fully VERIFIED (1–5) in order
[ ] PROJECT_STATE updated (§7) — prod promoted to VERIFIED
[ ] A GATE 2 implementation slot is free (this merge frees one)
```
Until then PR-2 stays closed (no implementation, no combining with PR-1).

**PZ / wFirma remain BLOCKED until ALL of (a superset — needs PR-2 shipped):**
```
[ ] Full five-stage sequence closed (above)
[ ] PR-2 merged + deployed (operator-confirm endpoint + gated injection)
[ ] Operator CONFIRMS the AWB 2315714531 proposal (operator_confirmed=true via PR-2 endpoint)
[ ] Engine recompute fills layer 3 (rows + positive invoice_totals)
[ ] PZ preview (read-only) inspected first
```
Completing this runbook alone does **not** unblock PZ/wFirma — it produces a
reviewable proposal and a clean baseline. Task #15 stays BLOCKED until PR-2 ships.

---

## Sequence-closed definition

Closed only when (1) all five conditions VERIFIED in order (HASH → ANCHOR → AWB),
and (2) PROJECT_STATE updated with squash SHA + hash result + anchor record. On
closure the HOLD lifts and a GATE 2 slot frees; PR-2 may then be scoped separately.
Until then the HOLD statement governs.
