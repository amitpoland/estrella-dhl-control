# PZService Silent Crash — 2026-06-03 (#434)
# Root cause, fixes, and canonical service configuration

## Summary

PZService was observed in `STATE 4 RUNNING` (per `sc.exe query`) while uvicorn was not
listening on port 47213. Bare calls to `127.0.0.1:47213` returned `WinError 10061`
(connection refused). The service manager reported healthy; the app was serving nothing.

**Root cause:** uvicorn was running on the Windows IOCP proactor event loop
(`asyncio.ProactorEventLoop`, the Python 3.8+ default on Windows). The proactor loop
has known socket edge-cases with `WinError 64` / `WinError 10054` under high socket
churn (outbound DHL/Zoho API calls). When the error occurred, the uvicorn process exited
or became unresponsive while NSSM's PID-watch reported it alive — the "zombie" state.

---

## Fix A — Health watchdog (detection, ~120s worst-case recovery)

**File:** `C:\PZ\scripts\health-watchdog.ps1`  
**Registered as:** Windows Task Scheduler task `PZService-HealthWatchdog`, every 60s  
**Probe:** `GET http://127.0.0.1:47213/login` (unauthenticated, in `_PUBLIC_PATHS`)  
**Threshold:** 2 consecutive probe failures → `sc.exe stop/start PZService`  
**State persistence:** `C:\PZ\logs\health-watchdog-state.txt` (plain integer counter)

Failure-path test observed 2026-06-03:
```
FAIL [1/2]  HOLD
FAIL [2/2]  ACTION -- restart issued
[scheduler probe during ~10s startup window → FAIL [1/2] HOLD]
RECOVERED  HTTP 200  (cleared 1 consecutive failure(s))
```
Counter resets to 0 on the first successful probe after recovery. A single blip
followed by a success resets to 0 — two unrelated blips only accumulate if no probe
succeeds between them.

**Deploy-lock:** The watchdog is disabled/re-enabled around every deploy per
`service/docs/windows-deploy-runbook-template.md` (task name exact: `PZService-HealthWatchdog`).
ENABLE is the first step in every rollback path so a failed deploy cannot leave the
watchdog silently off.

---

## Fix B — Remove the zombie cause (uvicorn → asyncio selector loop)

**This is the permanent fix.** Fix A is the backstop; Fix B removes the failure class.

### What changed

The `--loop asyncio` flag switches uvicorn from the IOCP proactor loop to the
`asyncio.SelectorEventLoop`. The selector loop does not use IOCP and does not exhibit
the `WinError 64 / WinError 10054` edge case under outbound socket churn.

### Canonical NSSM AppParameters (source of truth)

```
-X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 47213 --log-level info --loop asyncio
```

**Verbatim.** This is the exact string confirmed live on 2026-06-03 by:
1. `nssm get PZService AppParameters` — returned the string above
2. `Get-CimInstance Win32_Process -Filter "ProcessId=7428"` — cmdline of the running
   uvicorn process contained `--loop asyncio`

### To restore on a fresh box or after a reinstall

```powershell
nssm set PZService AppParameters "-X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 47213 --log-level info --loop asyncio"
sc.exe stop PZService
sc.exe start PZService
# Verify: sc.exe query PZService -> STATE 4 RUNNING
#         netstat -ano | Select-String ":47213.*LISTEN" -> port bound
#         GET http://127.0.0.1:47213/login -> 200
```

### NSSM config note

PZService's full configuration currently lives only as machine state in the NSSM
registry on `DESKTOP-IGKI1LF`. This AppParameters string is its only durable record
in source control. If PZService is reinstalled from scratch, this file is the
authoritative reference for the asyncio flag — **do not omit it**.

### Rollback (revert to proactor loop)

If the asyncio selector loop introduces new issues, revert with:
```powershell
nssm set PZService AppParameters "-X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 47213 --log-level info"
sc.exe stop PZService; sc.exe start PZService
# (proactor loop returns; zombie risk also returns; diagnose from here)
```

### Smoke after applying Fix B

After restarting with `--loop asyncio`:
1. `GET http://127.0.0.1:47213/api/v1/inbox` → 401 (enforcement active)
2. `/v2/` loads in browser (cookie path → 200, no lockout)
3. Run the email/monitor path once and confirm DHL/Zoho outbound completes without
   `WinError 64` or a new exception class in `pz_stdout.log`

Fix B applied and smoke-3 (socket-path) confirmed clean on 2026-06-03: 14+ AWBs
ingested via Zoho API, zero `WinError` in logs.

### /login probe under asyncio (watchdog probe target)

```
GET http://127.0.0.1:47213/login → HTTP 200
```
Confirmed on the live asyncio-loop service (2026-06-04). The watchdog will not
false-positive into unnecessary restarts.

---

## Standing ops rule — PowerShell 5.1 / UTF-8 encoding

PowerShell 5.1 (Windows PowerShell) reads files without a BOM as Windows-1252 (CP1252)
by default, not UTF-8. Any `.ps1` script that contains non-ASCII characters (em-dashes,
smart quotes, ł, ę, ó, etc.) will silently misparse on this box.

**Rule: all `.ps1` scripts on this box must be ASCII-only.** Use `--` for em-dash,
straight quotes, and ASCII lookalikes. If a script must embed a non-ASCII string, use
a Unicode escape (`[char]0x2014`) rather than the literal character.

This rule was learned from the `health-watchdog.ps1` authoring session (2026-06-03)
where an em-dash in a comment caused a parse error. The fix was to remove the character;
the lesson is to not introduce it in the first place.

---

## #434 resolution checklist

- [x] Root cause identified: WinError 64 IOCP proactor zombie under socket churn
- [x] Fix A deployed: health watchdog, failure-path observed end-to-end
- [x] Fix B deployed: `--loop asyncio` in AppParameters, socket-path smoke clean
- [x] Canonical AppParameters recorded in this file
- [x] /login under asyncio = 200 (watchdog probe not false-positiving)
- [x] Deploy-lock wired: watchdog disable/enable in deploy template (#435)
- [x] Standing rule recorded: ASCII-only `.ps1` files
