# TASK_STATE.md

## Current task

- **Task:** Single-canonical Packing List + CMR document authority — production App deploy + RO artifact verify
- **Status:** `EXECUTION_BLOCKED`
- **HOLD condition:** #2 Missing credentials / access — this session is Linux cloud (`/workspace`); cannot execute `C:\PZ-main\.\.claude\deploy\Deploy-PZ.ps1`
- **Authority owner:** `commercial_packing_list` / `commercial_packing_list_html` + `commercial_cmr` / `commercial_cmr_html` (canonical projection + presentation); `canonical_customer_documents` = thin byte resolver only
- **Do not claim:** `DEPLOYED_SINGLE_CANONICAL_DOCUMENT_AUTHORITY` until post-deploy RO browser/artifact compare closes

### Checkpoint (EXECUTION_BLOCKED)

| Field | Value |
|---|---|
| `suspended_from` | READY_TO_DEPLOY (seven-agent gate CLEAR; merge complete) |
| `blocking_dependency` | Windows Estrella production host (`C:\PZ-main` + `Deploy-PZ.ps1 -Release -Scope App`) |
| `recorded_branch` | `main` |
| `recorded_head` | `d77c16b082c26e1fac0c6637a5a5cc24bc1520c3` |
| `runtime_payload_sha` | `7fb187adda27605c708e88d999e1fb0f89db23f0` (PR #1251 merge; App bytes) |
| `payload_note` | `d77c16b0` = test-only pin on carrier CMR provider (`86012832`); App/runtime payload vs `7fb187ad` is EMPTY |
| `reviewed_implementation_head` | `845c9313dd6be5c32b62c638af32fb65f5404d92` (ancestry into #1251) |
| `merge_sha` | `7fb187adda27605c708e88d999e1fb0f89db23f0` (PR #1251) |
| `pr` | https://github.com/amitpoland/estrella-dhl-control/pull/1251 |
| `persistence` | NONE (no schema/startup migration in App sync) |
| `NO_REPEATED_RETRIES` | true |
| `timestamp` | 2026-08-15T13:45:00Z |
| `resume_attempted_at` | 2026-08-15T13:35:00Z (cloud Linux again — still no `C:\PZ*`) |

**Bounded resume validation (2026-08-15 cloud re-entry — checks 1–4 only):**
1. `git fetch origin main` → `origin/main` == `d77c16b082c26e1fac0c6637a5a5cc24bc1520c3` — PASS
2. App payload `7fb187ad..d77c16b0` — only `service/tests/test_carrier_external_registration.py` — EMPTY for `service/app` + engine — PASS
3. Persistence attributable to target — NONE (unchanged) — PASS
4. Authority owner unchanged — PASS
5. External dependency `C:\PZ-main` / `C:\PZ\version.txt` / `Deploy-PZ.ps1` on Windows host — **FAIL** (this pod is Linux `cursor`; paths absent; 0 self-hosted workers; no alternate deploy permitted)
6. Campaign writer — N/A (deploy not started)

**Preserved facts (do not re-implement):**
- Duplicate-authority census: CLEAN (canonical / thin-delegate / test / retired-unmounted only)
- Security review: no medium/high/critical on document authority surface
- Two-fixture HTML compare: Preview HTML ≡ email/confirmation HTML source (no real SMTP)
- Seven-agent gate @ `/workspace` HEAD `7fb187ad`: CLEAR (QA floors met; Chrome PDF timeouts = Linux env)

**`next_command` (single resume — Windows host only):**

```powershell
cd C:\PZ-main
git pull --ff-only origin main
# Confirm HEAD == d77c16b082c26e1fac0c6637a5a5cc24bc1520c3 (or later ff of main with EMPTY App payload vs 7fb187ad)
.\.claude\deploy\Deploy-PZ.ps1 -Release -Scope App
```

**Post-deploy RO verify (zero SMTP / zero carrier / zero wFirma writes) then close:**
1. `version.txt` matches deploy SHA; `PZService` Running; local+public health 200
2. Proforma → Packing List Preview (canonical iframe)
3. Logistics → CMR Preview (canonical iframe)
4. Materialize prospective packing-list PDF + confirmation CMR PDF via backend **without Send**
5. Compare operator document vs prospective attachment (same exporter / consignee / lines)
6. Confirm no active route still serves old plain/simplified customer Packing/CMR
7. Record rollback unit → verdict **`DEPLOYED_SINGLE_CANONICAL_DOCUMENT_AUTHORITY`**

Handoff detail: `reports/deploy/2026-08-15-canonical-customer-documents-exec-blocked.md`

---

## Prior / paused (not this resume)

- **B-014 HARD CUTOVER** — V1 Sales/Pro Forma entry → V2 — paused; do not resume from this checkpoint
