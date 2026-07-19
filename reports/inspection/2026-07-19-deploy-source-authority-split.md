# Inspection — Deploy-source authority split (PZ-verify / PZ-main / PZ)

**Date:** 2026-07-19
**Type:** Read-only inspection + governance/config reconciliation
**Trigger:** Operator observed that `C:\PZ-main` is the canonical `main` checkout but the
repository `.git` still lives under `C:\PZ-verify`, and asked whether deployment is broken.
**Verdict:** Deployment was **not** broken by the git split. A different, real defect was
found: the deploy **source** was declared three incompatible ways.

---

## 1. Evidence — production runtime

`PZService` does not run from any git tree.

| Fact | Value | Source |
|---|---|---|
| Service | `PZService` — Running, StartMode Auto | `Get-CimInstance Win32_Service` |
| `PathName` | NSSM shim (`nssm.exe`) — hides the real target | same |
| `Application` | `…\AppData\Local\Programs\Python\Python39\python.exe` | `HKLM:\SYSTEM\CurrentControlSet\Services\PZService\Parameters` |
| **`AppDirectory`** | **`C:\PZ`** | same |
| `AppParameters` | `-X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 47213 --log-level info --loop asyncio` | same |
| `AppStdout` / `AppStderr` | `C:\PZ\logs\pz_stdout.log` / `pz_stderr.log` | same |
| `C:\PZ\.git` | **absent** | filesystem |

`C:\PZ` is a pure robocopy target. The location of `.git` therefore has **zero** effect on
runtime. This is the answer to the operator's question: the split is technical debt in the
*process*, not a production fault.

Reading `PathName` alone is insufficient on this host — it returns only the NSSM shim. The
real deploy target is in the `Parameters` registry key.

## 2. Evidence — git topology

```
C:\PZ-main  →  .git file: "gitdir: C:/PZ-verify/.git/worktrees/PZ-sales-campaign"
               git rev-parse --git-common-dir → C:/PZ-verify/.git
               branch main, HEAD == origin/main, clean
               (9d65395f #953 at inspection start; ff-pulled to afd308ac #954 mid-session
                by another session — exactly PZ-main's declared ff-only role)
C:\PZ-verify → owns .git; detached HEAD b8196590 (pre-#953); dirty
```

`git worktree list` reports the tree set as `C:\PZ-verify`, `C:\PZ-main`, `C:\PZ-pr7`, a
group nested under `C:\PZ-verify\.claude\worktrees\`, and the campaign trees under
`C:\PZ-wt\`.

**The count is deliberately not pinned here.** The set is live: during this inspection it
moved from 25 to 23 as another session merged **#954** and cleaned up
`C:\PZ-wt\pr-closure-template`. Any fixed number in a governance doc is a snapshot that
starts rotting immediately. The argument in §6 rests on the `gitdir:` pointers being
**absolute**, which is a structural property independent of how many trees exist.

The `PZ-sales-campaign` admin-directory name is a **stale label only** — git resolves it
correctly. Already deferred by prior operator decision; unchanged here.

## 3. The actual defect — deploy source declared four ways

| # | Declares deploy source as | Location | State |
|---|---|---|---|
| 1 | `C:\PZ-verify\service\app` | `.claude/commands/deploy.md:74` (+ `cd` at 12, 57, 63, 120) | **detached, stale, dirty tree** |
| 2 | `C:\Users\Super Fashion\PZ APP\service\app` | `.claude/deploy/windows_prod_v2.json` `source_root` | **folder deleted 2026-07-17** |
| 3 | dedicated clean worktree; *"Never deploy from `C:\PZ-verify`"* | `reports/deploy/2026-07-03-wave12-operator-runbook.md:7` | correct in spirit, not encoded anywhere enforceable |
| 4 | `C:\PZ-verify` / `C:\PZ-verify\service\app` | `service/docs/production_deployment_rule.md:16, 160, 186` | **still stale — OUT OF SCOPE for this PR, see §9** |

The live `/deploy` command (#1) pointed at precisely the tree the most recent runbook (#3)
forbids. #2 pointed at a folder that no longer exists. Nothing asserted source cleanliness.

**#4 was found during PR review, not initial inspection.** It is the canonical rule document
that `/deploy` itself cites, and it is outside this PR's declared edit scope (four files).
It is therefore left unchanged and raised as an open item — fixing it silently would exceed
the approved scope; leaving it unrecorded would recreate the exact drift this PR removes.

### Provenance — Step 0 is not a new invention

The new fail-closed preflight implements rules that already existed in
`service/docs/production_deployment_rule.md` but were never encoded in the runnable command:

- **Post-incident rule 4** (line 65) — "Verify the source BEFORE any robocopy", requiring
  `git branch --show-current` = `main`, `git status --short` empty, and `git rev-parse HEAD`
  recorded.
- **Deployment Identity Gate** (lines 81–97) — "Proceed ONLY if: Branch = `main` · HEAD ==
  origin/main · tree clean. Any mismatch → ABORT."

Both trace to the **2026-07-07 incident**, where a `robocopy /XO` sourced from a
feature-branch worktree left `C:\PZ\app` version-skewed and PZService failed to start on an
`ImportError`. Step 0 makes that written gate executable. This PR adds enforcement, not
policy.

## 4. Fourth finding — Lesson J gap

`.claude/commands/deploy.md` contained **no engine-sync step**. Grep for
`engine|pz_import_processor|polish_description` returned nothing. CLAUDE.md Lesson J
requires a separate robocopy of the root engine files to `C:\PZ\engine\`, since they sit
outside `service/app` and are not carried by the main sync. A deploy run strictly to the
old command would have shipped a backend running against a stale calculation engine.

## 5. Fifth finding — production drift (NOT acted on)

**Status: INFERENCE, not verified fact. Production drift remains UNMEASURED.**

The only evidence gathered is a filesystem timestamp: `C:\PZ\app\main.py` has mtime
`2026-07-18 00:30`, while `main` is at `afd308ac` (#954). From this it is *plausible* that
production predates #953/#954.

That inference is **not** a measurement, and this report does not claim a production SHA:

- `C:\PZ` contains no `.git`, so it has no SHA of its own to read.
- No file hashes were compared between `C:\PZ\app` and any commit.
- mtime reflects the last robocopy write, not commit content — `/XO` skips files it deems
  not-newer, so a timestamp can be older *or* newer than the content it holds.

Establishing the real deployed revision requires hash-comparing `C:\PZ\app` against
candidate commits. That is a **read of production**, which was explicitly out of scope for
this task, so it was not performed. Carried to §9 as an open item.
**Production drift is unconfirmed and must be measured before the next deploy.** Deploying
is a separate 7-agent-gated action and was
explicitly out of scope for this task. Carried forward as an open item for the next deploy
gate.

## 6. Decision recorded

> `C:\PZ-main` is the **sole deployment source**. `C:\PZ-verify` remains the git/admin and
> verification-read authority and is **never** a deploy source. `C:\PZ` remains runtime.
> Three roles, three trees, deliberately distinct.

### Why `.git` was NOT relocated to `C:\PZ-main`

Considered and **rejected**. Every worktree carries an absolute `gitdir:` pointer into
`C:\PZ-verify\.git\worktrees\` — including 6 active `C:\PZ-wt\` campaign trees and
`C:\PZ-pr7`. Relocation breaks every one of them, for **zero runtime benefit**, since
production reads none of them. The conflation of "owns `.git`" with "is the deploy source"
was the bug; separating those two ideas resolves it without touching git plumbing.

## 7. Changes applied (all in `C:\PZ-main`, docs/config only)

1. `.claude/commands/deploy.md` — new **Step 0** fail-closed preflight (source clean, on
   `main`, `HEAD == origin/main`); all `PZ-verify` paths repointed to `PZ-main` (Steps 1,
   4, 5, 8); new **Step 5b** Lesson J engine sync with content-hash verification.
2. `.claude/deploy/windows_prod_v2.json` — `source_root` / `requirements_src` repointed to
   `C:\PZ-main`; added `engine_src` / `engine_dst` / `engine_files`; three `notes` entries
   recording the authority rule, the decommissioned path, and the Lesson J requirement.

   **Engine source is the repo ROOT, not an `engine\` subdirectory.** `C:\PZ-main\engine`
   **does not exist** — verified. Per Lesson J the engine files sit at the repository root
   (`C:\PZ-main\pz_import_processor.py`, `C:\PZ-main\polish_description_generator.py`) and
   are copied INTO `C:\PZ\engine\`. The mapping is therefore
   `C:\PZ-main\<file> → C:\PZ\engine\<file>`, which is why `engine_src` is `C:\PZ-main`
   with an explicit `engine_files` allow-list rather than a directory-to-directory sync.
   No `engine\` directory was created — inventing one would be new architecture, not the
   documented Lesson J layout.
3. `CLAUDE.md` — registry rows for `PZ-main` / `PZ-verify` updated; new "Three roles, three
   trees" paragraph explaining why the split is intentional and must not be "repaired".
4. This report.

**Not changed:** no deploy, no service restart, no robocopy executed, no `.git` moved, no
worktree/branch touched, no `C:\PZ-verify` dirty file or `C:\PZ-wt\*` tree modified.

`scripts/cp3_capture.py:40` and `.claude/verify-slice03/verify_guard.py:43-45` hardcode
`C:/PZ-verify`. These are **verification** tools, so that target is correct under the
subagent reading rule — intentionally left alone, noted here so they are not later
mistaken for drift.

## 8. Verification results

| # | Check | Result |
|---|---|---|
| 1 | No `PZ-verify\service\app` / `PZ APP` source refs remain in deploy.md or windows_prod_v2.json | **PASS** — grep returns no hits (only the two deliberate "must never reappear" notes); `PZ-main\service\app` hits both files |
| 2 | Step 0 preflight passes on `PZ-main`, BLOCKS on `PZ-verify` | **PASS** — see below |
| 3 | Engine files resolve at `C:\PZ-main\` root | **PASS** — `pz_import_processor.py` (177388 B), `polish_description_generator.py` (28242 B) |
| 4 | CLAUDE.md no longer implies `PZ-verify` is a deploy source | **PASS** — all 3 remaining mentions in a deploy context explicitly forbid it |
| 5 | Only intended files touched; `PZ-verify` unchanged; worktrees intact | **PASS** — 4 files in `PZ-main`; `PZ-verify` porcelain byte-identical to session start; `git worktree list` healthy |

Step 0 preflight, executed against both trees:

```
--- C:\PZ-main ---              --- C:\PZ-verify ---
  BLOCK: dirty (4 entries)        BLOCK: dirty (23 entries)
  ok: on main                     BLOCK: not on main (is '')      <- detached
  ok: HEAD == origin/main         BLOCK: HEAD b8196590 != origin/main afd308ac
     (afd308ac)
```

`C:\PZ-verify` fails **all three** assertions — this is precisely the deploy the old
`.claude/commands/deploy.md:74` would have performed, and the reason this change exists.

`C:\PZ-main` fails only the dirty check, and only because of the four uncommitted files of
*this* change. Once they are committed/merged, the gate is green. This is recorded as an
open item rather than worked around — the preflight is doing its job.

## 9. Open items

1. **`service/docs/production_deployment_rule.md` still names `C:\PZ-verify`** (lines 16,
   160, 186) — the fourth stale declaration from §3. It is the canonical rule document this
   PR's command file cites, so leaving it stale means the authority conflict is reduced but
   not eliminated. **Out of scope here** (this PR's edit scope is four files, fixed in
   advance). Needs its own follow-up PR. **GATE 4 disposition: SCHEDULED** — next governance
   session.

2. **Production drift is UNMEASURED** (§5). No production SHA is claimed anywhere in this
   report. Measuring it requires hash-comparing `C:\PZ\app` against candidate commits — a
   production read, out of scope for this task. Must be measured *before*, not during, the
   next deploy. **Operator action.**

3. **Step 5 still uses `/E /XO`** — pre-existing, unchanged by this PR. Post-incident rule 3
   (`production_deployment_rule.md:60-64`) permits `/XO` ONLY for a known-incremental top-up
   where the destination is already a consistent subset of the source; a full or recovery
   sync must overwrite. Given open item 2 (drift unmeasured), the destination's consistency
   is **not** established, so the next deploy should treat `/XO` as unjustified until the
   drift is measured. Flagged, not changed — altering sync semantics is a deploy-behaviour
   change needing its own review. **GATE 4 disposition: SCHEDULED.**

4. **Branch/merge route** — these edits are committed to `fix/deploy-source-authority`, not
   to `main`. `C:\PZ-main` returns to clean on merge, at which point the Step 0 gate goes
   green. Merge is **operator-only**.
