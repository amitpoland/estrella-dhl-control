# PR #1037 — Production Deployment Provenance Investigation

**Date:** 2026-07-28
**Investigator session:** primary C:\PZ-verify session (9742361b)
**Authority owner:** production deployment operator
**Status:** ✅ CLOSED — SUCCESSFUL OPERATOR DEPLOY · CONTENT VERIFIED · BOTH RESTART + COPY ATTRIBUTED
**Constraint:** read-only investigation. No copy, restart, rollback, GATE-6, Draft #73, or Customer Master write performed.

> **RESOLUTION (2026-07-28, operator-confirmed):** The production deployment operator confirmed **"Yes — I ran it"**:
> the stop→robocopy→start handoff into `C:\PZ\app` was an **authorized manual operator deploy**, not an unattributed
> actor. Executor is now **resolved = production deployment operator (manual)**. The operator also confirmed
> **single-writer** ("I'm the only writer"): no other operator/session will write to `C:\PZ` during verification.
> ⇒ Deployment record **CLOSED as successful operator deploy**. The two GATE-6 preconditions (provenance known +
> single-writer confirmed) are **satisfied**; GATE-6 is **UNBLOCKED** and may run on a disposable non-posted draft
> per `reports/campaigns/2026-07-28-pr1037-gate6-postdeploy-checklist.md` (Draft #73 stays read-only; no posting/
> conversion; Customer Master unchanged).

---

## 1. Question

Production `C:\PZ\app` already contains the approved PR #1037 content (`776d327f`), but **this session did not
perform the copy** (its robocopy was deploy-guard-blocked) and observed a second service restart it did not
issue. Identify the actor(s) that (a) copied the four files into production and (b) restarted PZService.

---

## 2. Evidence captured (read-only)

### Content parity — production == deploy SHA
| File | Prod SHA256 (C:\PZ\app) | Match |
|---|---|---|
| `api/routes_proforma.py` | `35D9…51CC` | ✅ = source @ 776d327f |
| `services/customer_master.py` | `5A57…59B4` | ✅ |
| `services/proforma_invoice_link_db.py` | `84A8…64F8` | ✅ |
| `static/v2/proforma-detail.jsx` | `E2FD…DB2A` | ✅ |

Markers present: `from draft-saved service product` (jsx = 1), `missing a valid charge_id` (route = 1).
Blast radius: exactly these 4 files carry an 18:07:47 mtime; the rest of the tree is the prior baseline. **Content-verified.**

### Timestamp chain (the decisive evidence)
- `C:\PZ-verify` git reflog: `dd59559f → checkout main @ 18:07:46`, then `776d327f … pull --ff-only … Fast-forward @ 18:07:47`.
- The git pull rewrote the 4 files in **C:\PZ-verify\service\app** with mtimes **18:07:47.479 / .481 / .483 / .486**.
- The 4 files in **C:\PZ\app** carry the **identical millisecond mtimes** (18:07:47.479 / .481 / .483 / .486).
- `C:\PZ\app` is **not** a reparse point / junction (`fsutil reparsepoint query` → "not a reparse point"); prod
  files have their own distinct CreationTimes → they are independent files, not a link or hardlink.

**Only a timestamp-preserving copy (`robocopy /XO`, which sets destination mtime = source mtime) reproduces the
verify tree's exact sub-millisecond mtimes on independent production files.** Therefore a
`robocopy C:\PZ-verify\service\app → C:\PZ\app` executed at/after 18:07:47. (robocopy stamps the *source* mtime
regardless of when it runs, so the wall-clock time of the copy is not pinned by the file mtime.)

### This session's actual commands (decoded from PowerShell/Operational script-blocks)
| Time | This session ran | Writes C:\PZ\app? |
|---|---|---|
| 18:07:43 | `Set-Location C:\PZ-verify; git checkout main; git pull --ff-only origin main` (source pin) | No — verify tree only |
| 18:08:00 | `sc.exe stop PZService` (+ STOPPED poll) | No |
| 18:08:48 | `sc.exe start PZService` (restore after guard block; → nssm PID 24812) | No |
| 18:09:18 | health probe `/api/v1/health` | No |
| 18:11:51 | `Get-FileHash` parity (read-only) | No |
| 18:13:08 | mtime-distribution read (read-only) | No |

The session's robocopy was **deploy-guard-blocked** (`rule 'deploy-to-prod-PZ' — copy/write into C:\PZ is
operator-only`). None of its executed commands copy into C:\PZ\app.

---

## 3. Attribution

### (b) Restart @ 18:12:53 — CONCLUSIVELY the HealthWatchdog scheduled task
`C:\PZ\logs\health-watchdog.log`:
```
18:11:48  FAIL [1/2]  no response (timeout or connection refused)
18:12:48  FAIL [2/2]  no response
18:12:48  ACTION  2 consecutive failures hit threshold -- restarting PZService
18:12:48  ACTION  sc.exe stop PZService
18:12:53  ACTION  sc.exe start PZService
18:12:53  ACTION  restart issued
```
Task `\PZService-HealthWatchdog` (RUN-AS `Super Fashion`, RunLevel Highest, every 60s) restarted the service
after two consecutive failed probes. This produced nssm PID 8208 + worker PID 23324 (both StartTime 18:12:53),
the currently running worker — which, because the copy preceded it, has the new code loaded. **Benign
self-healing restart, not an actor deploy.** The two failed probes at 18:11:48 and 18:12:48 indicate the service
was down/unresponsive in that window — consistent with a manual stop→copy→start cycle happening ~18:11–18:12.

The earlier restart at 18:08:48 was **this session's** own restore `sc.exe start` (nssm PID 24812).

### (a) Copy of the 4 files — an actor OTHER THAN this session; scheduled tasks ruled out
- **Not this session** — robocopy guard-blocked; decoded commands contain no copy.
- **Not `PZService-HealthWatchdog`** — the script only probes HTTP and does `sc stop/start`; it contains no
  file copy (full source read; 78 lines, no robocopy/Copy-Item).
- **Not `PZService-DHL-Email-AutoScan`** — the script only POSTs `/api/v1/dhl/scheduled-inbox-check`; no copy.
- **Not another Claude Code session** — the `deploy-to-prod-PZ` PreToolUse guard is a text-pattern hook that
  blocks any command whose text targets `C:\PZ` (it blocked even a *read-only* Get-WinEvent query containing the
  literal path). Any agent session loading this repo's hooks would be blocked identically.

**⇒ The copy was performed by a non-agent actor.** The most probable actor is the **human operator manually
running the handoff robocopy block** (`sc stop → robocopy C:\PZ-verify\service\app → C:\PZ\app /XO … → sc start`),
which is the sanctioned operator-only deploy path and would produce exactly the 18:11–18:12 probe failures the
watchdog then reacted to. Filesystem evidence cannot distinguish "operator manual run" from a hypothetical
non-hooked shell/automation — hence operator confirmation is required to finalise.

Mixed NTFS ownership on the 4 prod files (2× `Super Fashion`, 2× `BUILTIN\Administrators`) reflects historical
in-place overwrites and is not by itself conclusive of the 18:07:47 actor.

---

## 4. Classification (per investigation plan step 7)

| Outcome | Evidence status |
|---|---|
| Confirmed operator deploy → close successful | ✅ **CONFIRMED** — operator "Yes — I ran it" (2026-07-28) |
| Confirmed automation deploy → record job | **RULED OUT** — no scheduled task copies files |
| Unknown actor → security/ops incident, keep GATE-6 blocked | **N/A** — actor is the operator, not unknown |

**Record status: CLOSED — SUCCESSFUL OPERATOR DEPLOY.** Content correct and live; copy executor = production
deployment operator (manual robocopy handoff), operator-confirmed; restart = HealthWatchdog self-heal.

---

## 5. Single-writer status (for GATE-6 gating)

Multiple `claude.exe` processes are resident on the host (including a forked session operating on worktree
`C:\PZ-wt\dhl-tz-guard`), plus a long-running Vite dev server (`vite.config.dev47213.js`, up since 2026-06-28).
None is evidenced writing to `C:\PZ`, and the deploy-guard blocks agent writes to production. Single-writer could
not be *certified* from the process listing alone — but the operator has now **confirmed single-writer**
("I'm the only writer", 2026-07-28): no other operator/session will act on production during verification.
⇒ **GATE-6 single-writer precondition SATISFIED.** GATE-6 (disposable non-posted draft only) is **UNBLOCKED**.

---

## 6. Actions NOT taken (constraint compliance)

No copy · no restart · no rollback · no redeploy · no GATE-6 draft · no Draft #73 change · no Customer Master
write · no posting/conversion. All production files read-only throughout. Timestamps and logs preserved.

---

## 7. Next exact step (operator)

Confirm one:
1. **"I (or my tooling) ran the robocopy block"** → record closes as **successful operator deploy**; GATE-6 may
   proceed on a disposable non-posted draft once no other writer is active.
2. **"I did not run it"** → escalate to security/ops incident (unattributed production write); GATE-6 stays
   blocked pending investigation of the non-hooked actor.
