# OPERATOR RUNBOOK — PR #640: Merge → Deploy → Verify (AUTHORITATIVE)

> **This runbook is the authority.** Execute top to bottom. Pass/fail criteria are
> binary; failure actions are prescribed. Inside a 🔒 **NO-EXCEPTIONS** zone there is
> no operator discretion — you do not proceed because "tests passed." All merge /
> deploy / prod-write actions are operator-executed; no agent performs them.
> Remaining risk is execution discipline, not missing controls.

## Document control

| Field | Value |
|---|---|
| Decision on record | 🟢 GO for PR #640 merge (deploy under the five-stage gate) |
| PR #640 | OPEN / MERGEABLE / CLEAN |
| Branch HEAD | `8d49ae7` (docs-only ahead of code) |
| Code SHA (frozen, reviewer-PASS) | `f6c7ec2` |
| Base (`origin/main`) | `4652292` |
| Deploy | NOT executed |
| GATE 2 | At ceiling (3 impl: #643, #640, #630 + 1 docs: #637) |
| Squash SHA | `__________` (captured STAGE 2) |
| Execution chain | STAGE 1 → 2 → 3 → 4 → 4A → 5 → PROJECT_STATE → PR-2 eval |

**Hard dependency (NON-NEGOTIABLE):** STAGE 5 (AWB VERIFIED) **cannot begin** until
**both** STAGE 4 (HASH VERIFIED) **and** STAGE 4A (ROLLBACK ANCHOR VERIFIED) have
passed. AWB verification exercises production logic and may materialize
`vision_invoice` into the audit — it must follow both prior gates.

**Execution log (operator fills):**

| Stage | Entered (UTC) | Exited (UTC) | Verdict |
|---|---|---|---|
| STAGE 1 — Pre-exec validation | | | |
| STAGE 2 — MERGE | | | |
| 7-agent deploy gate | | | |
| STAGE 3 — DEPLOY | | | |
| STAGE 4 — HASH | | | |
| STAGE 4A — ROLLBACK ANCHOR | | | |
| STAGE 5 — AWB | | | |
| PROJECT_STATE close | | | |

---

## Field lock (applies at STAGE 5 — memorize before starting)

| Class | Field(s) | Rule |
|---|---|---|
| **PROTECTED** (change expected) | `vision_invoice` | MUST be written (advisory proposal). Its presence is correct, not a leak. |
| **FORBIDDEN** (no change permitted) | `operator_confirmed`, `rows`, `invoice_totals`, `clearance_decision`, resolved CIF authority | Any change = accounting-authority leak → incident path (STAGE 5 / §A). |

---

## ⛔ HOLD STATEMENT (in force until the full chain closes + PROJECT_STATE updated)
- **No PR-2.** Do not open / implement / combine the confirmation workflow.
- **No PZ / wFirma** for AWB 2315714531 or any image-only shipment.
- **No new implementation campaign** (GATE 2 full; only draining is permitted).

---

# STAGE 1 — PRE-EXECUTION VALIDATION  🔒 NO EXCEPTIONS

**Entry criteria:** none — this is the start. Do not touch any later stage first.

**Execution steps:**
```
V1  gh pr view 640 --json state,mergeable,mergeStateStatus,isDraft
      → OPEN / MERGEABLE / CLEAN / not draft
V2  git log --oneline 4652292..origin/fix/invoice-image-only-lineitem-extraction
      → every commit after f6c7ec2 is docs-only (.md / .claude). A CODE file = FAIL.
V3  git status --short (clean) ; HEAD == origin HEAD (8d49ae7 or newer docs-only)
V4  gh pr list --state open → ≤ 3 implementation PRs (this merge frees a slot)
V5  PROJECT_STATE shows prod = REPORTED (not VERIFIED); PR-2 not open; PZ/wFirma blocked-by-design
V6  grep -rn "vision_invoice" service/app → writer only in vision_extractor;
      only a status-flag read in routes_dashboard; NO PZ/wFirma/customs/landed-cost consumer
```

**Binary exit:** ✅ PASS = V1–V6 all true. ❌ FAIL = any line false.

**Failure action:**
- V2 shows a code file → STOP; re-run reviewer-challenge on the new code SHA; restart STAGE 1.
- Any other FAIL → STOP; reconcile the failing line; re-run STAGE 1. Do **not** enter STAGE 2.

---

# STAGE 2 — MERGE VERIFIED

**Entry criteria:** STAGE 1 PASS.

**Execution steps:**
1. `gh pr view 640` — re-confirm OPEN / MERGEABLE / CLEAN.
2. `gh pr merge 640 --squash` (operator).
3. `git fetch origin main && git rev-parse --short origin/main` — record the **real**
   squash SHA in Document control. Do **not** assume or reuse a prior value.

**Binary exit:** ✅ PASS = PR #640 = MERGED **and** real squash SHA recorded.
❌ FAIL = merge conflict / non-clean / SHA not captured.

**Failure action:** STOP → resolve/rebase → re-review (STAGE 1) → re-run STAGE 2.

> **7-AGENT DEPLOY GATE (between STAGE 2 and STAGE 3 — GO required):**
> Run `/deploy` against `4652292 → <squash SHA>`. Six reviewers in parallel
> (git-diff, backend-impact, persistence-storage, security, qa, release-manager)
> → **deploy-lead-coordinator decides last**. release-manager **must emit the exact
> rollback command for this squash SHA** (required input to STAGE 4A).
> Hard blockers (any = NO-GO): QA test failure; HIGH/CRITICAL security; forbidden-path
> or schema finding; missing router/auth guard. NO-GO → STOP, gate stays OPEN.
> (Backend-only diff, no root-engine file → standard robocopy; Lesson J N/A.)

---

# STAGE 3 — DEPLOY VERIFIED

**Entry criteria:** STAGE 2 PASS **and** 7-agent gate GO.

**Execution steps:**

**3A — Capture rollback-anchor inputs BEFORE any overwrite 🔒 NO EXCEPTIONS**
(once prod is overwritten these cannot be reconstructed)
1. **PROD_BASELINE_MANIFEST** — LF-normalized SHA256 of every live file the deploy
   will overwrite:
   ```powershell
   Get-ChildItem -Recurse C:\PZ\app -File | ForEach-Object {
     $lf = (Get-Content $_.FullName -Raw) -replace "`r`n","`n"
     $h  = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().
            ComputeHash([Text.Encoding]::UTF8.GetBytes($lf))).Replace("-","")
     "$h  $($_.FullName)"
   } | Set-Content C:\PZ-backups\pr640\PROD_BASELINE_MANIFEST.txt
   ```
2. **Backup** the overwrite set **+ the AWB 2315714531 batch audit/state files** to a
   path **outside** the overwrite target:
   ```powershell
   robocopy C:\PZ\app C:\PZ-backups\pr640\app /MIR /COPY:DAT
   robocopy C:\PZ\<batch-store>\2315714531 C:\PZ-backups\pr640\audit /E /COPY:DAT
   ```
3. **Record** the release-manager rollback command verbatim in Document control.

**3B — Sync + restart (operator-only prod write):**
```powershell
robocopy <repo>\service\app C:\PZ\app /MIR /COPY:DAT
sc.exe stop PZService ; sc.exe start PZService
```

**Binary exit:** ✅ PASS = 3A complete (manifest stored + backup readable + rollback cmd
recorded) **and** 3B clean (sync ok + service healthy). ❌ FAIL = any of those missing.

**Failure action:**
- 3A incomplete → STOP **before** sync (no recoverable rollback target).
- 3B fails → execute the recorded rollback command; restore from backup; do not verify.

---

# STAGE 4 — HASH VERIFIED  🔒 gates STAGE 4A and STAGE 5

**Entry criteria:** STAGE 3 PASS.

**Execution steps:**
```powershell
git -C C:\PZ-verify fetch origin ; git -C C:\PZ-verify checkout <squash SHA>
# Hash the live tree (as in 3A.1) and compare LF-normalized digests to C:\PZ-verify.
# Record both raw-CRLF (transfer) and LF-normalized (authority) hashes.
```

**Binary exit:** ✅ PASS = LF-normalized live hash == verification clone @ squash SHA.
❌ FAIL = any mismatch.

**Failure action:** deployed tree ≠ squash SHA. Re-sync, re-restart, re-hash.
**STAGE 4A and STAGE 5 must NOT begin. "Deployed" stays REPORTED, never VERIFIED.**

---

# STAGE 4A — ROLLBACK ANCHOR VERIFIED  🔒 gates STAGE 5

**Entry criteria:** STAGE 4 PASS. Purpose: lock an executable rollback **before** the
state-mutating AWB recheck.

**Execution steps — verify all six anchor artifacts:**
```
A1  Squash SHA recorded (Document control)
A2  PROD_BASELINE_MANIFEST present AND matches the pre-deploy live tree (3A.1)
A3  Backup exists, READABLE/RESTORABLE, covers overwrite set + AWB audit, stored
    OUTSIDE the overwrite target (open one app file + one audit file to confirm)
A4  Release worktree CLEAN and at squash SHA:
      git -C <release-worktree> status --porcelain  (empty)
      git -C <release-worktree> rev-parse HEAD       (== squash SHA)
A5  Hash-comparison artifacts (STAGE 4 raw + LF digests) stored
A6  Rollback command recorded AND parseable (release-manager output)
```

**Binary exit:** ✅ PASS = A1–A6 all confirmed (rollback executable on demand).
❌ FAIL = any artifact missing/inconsistent.

**Failure action:** **STAGE 5 must NOT begin.** Re-capture the missing artifact. If a
backup is missing and prod already overwritten → deploy-integrity incident: re-sync
from clone @ squash SHA and re-anchor before continuing.

---

# STAGE 5 — AWB VERIFIED

**Entry criteria (HARD DEPENDENCY):** STAGE 4 PASS **AND** STAGE 4A PASS. If either is
not green, do not start. No exceptions.

**What this stage does in production (state-mutating):** the recheck on AWB
2315714531 invokes `run_image_only_invoice_extraction`, which **writes**
`audit["vision_invoice"]` (supplier, USD-only `fob_usd`, line items, `confidence`,
`operator_confirmed=false`) via `_merge_vision_invoice` (merge-not-replace, sticky,
TOCTOU-guarded). This is the **only** intended mutation; it must not touch any
FORBIDDEN field. The dashboard shows a status flag + "review and confirm" warning.

**Execution steps:**
1. Run the recheck/recovery on AWB 2315714531 through the deployed path.
2. Diff the resulting batch audit JSON against the STAGE-3A audit backup.
3. Evaluate the field lock:
```
[ ] vision_invoice ........ WRITTEN   (PROTECTED — intended)
[ ] operator_confirmed .... false     (FORBIDDEN to change)
[ ] rows .................. UNCHANGED (FORBIDDEN)
[ ] invoice_totals ........ UNCHANGED (FORBIDDEN)
[ ] clearance_decision .... UNCHANGED (FORBIDDEN)
[ ] resolved CIF .......... 732 / RESOLVED / awb_customs.value_usd (FORBIDDEN to change)
```

**Binary exit:** ✅ PASS = `vision_invoice` WRITTEN **and** all FORBIDDEN fields unchanged.
❌ FAIL.

**Failure action:**
- `vision_invoice` missing → functional failure; investigate extractor; not a leak.
- **Any FORBIDDEN field changed → §A incident path. No discretionary judgment. Do not
  proceed because tests passed.**

---

## §A — FORBIDDEN-FIELD INCIDENT PATH  🔒 NO EXCEPTIONS

**Trigger:** at STAGE 5, `operator_confirmed` becomes `true`, OR `rows` /
`invoice_totals` / `clearance_decision` / resolved CIF (732) changes.

**Detection (diff vs STAGE-3A audit backup):**

| Field | Detection | Expected |
|---|---|---|
| `operator_confirmed` | value compare | `false` |
| `rows` | deep-equal vs backup | unchanged |
| `invoice_totals` | deep-equal vs backup | unchanged |
| `clearance_decision` | deep-equal vs backup | unchanged |
| resolved CIF | `resolve_cif(audit)` value+source | `RESOLVED`, `732`, `awb_customs.value_usd` |

**Path — execute in order, no deviation:**
```
HALT ──► ROLLBACK ──► RE-VERIFY ──► INCIDENT RECORD ──► GATE REMAINS OPEN
```
1. **HALT** — no proposal confirm, no PZ, no wFirma.
2. **ROLLBACK** — run the recorded rollback command; restore backup / PROD_BASELINE_MANIFEST.
3. **RE-VERIFY** — FORBIDDEN fields back to baseline; `operator_confirmed=false`.
4. **INCIDENT RECORD** — file per Lesson I. Workflow class: "advisory proposal layer
   reached accounting/customs state." Fix at class level, not this shipment.
5. **GATE REMAINS OPEN** — "deployed" never promotes to VERIFIED; HOLD stays in force.

---

## PROJECT_STATE CLOSE

**Entry:** all five stages PASS (1 → 2 → 3 → 4 → 4A → 5, in order; 4 and 4A both before 5).

**Steps:** flow-context-keeper (sole PROJECT_STATE owner, RULE 3) records: squash SHA,
LF hash result, rollback-anchor artifacts, all five VERIFIED. Promote prod
REPORTED→VERIFIED only after STAGE 4 passed.
> Optional in-pattern: one Cliq `#PZ` post on this same event path (no daemon, no second state owner).

**Five-condition close (in order — do not check a box until the one above is checked):**
```
[ ] STAGE 2  MERGE VERIFIED
[ ] STAGE 3  DEPLOY VERIFIED
[ ] STAGE 4  HASH VERIFIED
[ ] STAGE 4A ROLLBACK ANCHOR VERIFIED
[ ] STAGE 5  AWB VERIFIED
```

---

## PR-2 EVALUATION (operator action 8)

**PR-2 may begin ONLY when ALL of:**
```
[ ] Five-condition close fully VERIFIED (above), in order
[ ] PROJECT_STATE updated — prod promoted REPORTED → VERIFIED
[ ] A GATE 2 implementation slot is free (this merge frees one)
```
Otherwise PR-2 stays closed (no implementation, no combining with PR-1).

**PZ / wFirma remain BLOCKED until ALL of (needs PR-2 shipped — superset):**
```
[ ] Full five-stage chain closed
[ ] PR-2 merged + deployed (operator-confirm endpoint + gated injection)
[ ] Operator CONFIRMS the proposal (operator_confirmed=true via PR-2 endpoint)
[ ] Engine recompute fills layer 3 (rows + positive invoice_totals)
[ ] PZ preview (read-only) inspected first
```
Completing this runbook produces a reviewable proposal + a clean baseline. It does
**not** unblock PZ/wFirma. Task #15 stays BLOCKED until PR-2 ships.

---

## Operator action sequence (canonical)

```
1. Review PR #640          → STAGE 1
2. Squash merge            → STAGE 2 (step 2)
3. Capture real squash SHA → STAGE 2 (step 3)  🔒 real value, not assumed
4. Run 7-agent deploy gate → between STAGE 2 and 3 (GO required)
5. Deploy                  → STAGE 3 (3A capture BEFORE 3B sync)
6. Pass all five stages    → STAGE 3, 4, 4A, 5 (4 AND 4A before 5)
7. Update PROJECT_STATE    → PROJECT_STATE CLOSE
8. Evaluate PR-2           → PR-2 EVALUATION (conditions above)
```

**Sequence-closed** only when all five conditions are VERIFIED in order (HASH and
ROLLBACK ANCHOR both before AWB) and PROJECT_STATE is updated with squash SHA + hash
result + anchor record. On closure the HOLD lifts and a GATE 2 slot frees; PR-2 may
then be scoped separately. Until then the HOLD statement governs.
