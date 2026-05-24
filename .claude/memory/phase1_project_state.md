# PZ Correction Lifecycle, Phase 1, Project State
**Last updated:** 2026-05-24 (PR A — activation blocker fixes)
**Merge SHA:** 9c45cee (PR #348, squashed to main at 7d8d0c0)
**PR A fixes:** sentinel, suppress route, documentation correctness
**Service:** PZService, port 47213, `https://pz.estrellajewels.eu`

---

### Current State

Phase 1 is complete and deployed. PR A (activation blocker fixes) is applied on top of Phase 1.
Production impact is zero. Both flags are off.

The feature flag `pz_correction_lifecycle_enabled` is `False` in `C:\PZ\.env`. All five lifecycle
endpoints are live, registered, and responding, but they return HTTP 503 before executing any logic.
The wFirma push flag `wfirma_correction_push_allowed` is also `False`. Both flags must be explicitly
set to `True` before any lifecycle operation can run. Neither is set automatically by deployment.

**Recommended explicit .env entries** (add these to `C:\PZ\.env` before any activation attempt):

```
PZ_CORRECTION_LIFECYCLE_ENABLED=false
WFIRMA_CORRECTION_PUSH_ALLOWED=false
```

Currently both values rely on Pydantic defaults. Explicit entries make the disabled state visible
during incident response and survive `.env` regeneration.

PZService is healthy. Local and public health checks return 200. The existing correction routes,
PZ processing, WorkDrive upload, Cliq posting, and wFirma write paths are all unchanged.

The lifecycle module files (`pz_correction_lifecycle.py`, `pz_correction_state.py`) are not present
in `C:\PZ\app\services\` at this time. They were removed during hygiene cleanup on 2026-05-24 and
backed up to `C:\PZ\backups\hygiene_phase10_20260524-092326\services\`. This is safe: the lifecycle
endpoints use lazy imports inside each function body, so a missing file never causes a startup error
or import failure while the flag is off. These files will be redeployed in the normal robocopy
sequence when Phase 2 activation is prepared.

---

### Critical Technical Invariant

The execution ordering chain is non-negotiable. Any refactor must preserve this sequence:

```
stage_option()
  └─► execute_correction_option()          [local write, no wFirma call]
        └─► writes correction_execution_record.json to batch_dir
              └─► on success: state transitions to STAGED
                    └─► execute()
                          └─► push_correction_to_wfirma()
                                └─► Gate 5 checks correction_execution_record.json exists
```

`push_correction_to_wfirma()` has an explicit Gate 5 that checks for `correction_execution_record.json`
on disk before making any wFirma API call. If the file is absent, the push fails at the gate, not at
the wFirma level. This means:

- `stage_option()` must call `execute_correction_option()` before writing the STAGED state. It does.
  The state is only written as STAGED if `execute_correction_option()` returns successfully.
- `execute()` must only be called from STAGED, which guarantees the execution record exists.
- If `execute_correction_option()` fails for any reason, the state remains OPERATOR_REVIEWED and no
  STAGED record is written. The operator can retry.

Do not move the `execute_correction_option()` call out of `stage_option()` into `execute()`, and do
not call `push_correction_to_wfirma()` directly without going through `PZCorrectionLifecycle.execute()`.
Both changes would break Gate 5 reliability.

The EXECUTING state is written to disk before the push call begins. If the process crashes mid-push,
the state on disk is EXECUTING, not STAGED. This prevents a restarted service from treating the push
as not-yet-started and double-submitting to wFirma.

A batch stuck at EXECUTING (service killed mid-push) can be recovered via:
`POST /api/v1/pz/lineage/{batch_id}/correction-suppress` with a reason string.
This transitions to TERMINAL_SUPPRESSED without touching wFirma.

---

### Sentinel Contract

**Canonical location:** `global_pz_push.py`, lines 74-78, `_CONFIRM_SENTINEL`.

**Exact value:**
```
"I confirm this will create a new wFirma PZ document and cannot be undone without manual wFirma intervention"
```

This is Gate 1 of `push_correction_to_wfirma()`. Any `confirm_understanding` value that does not
match this string exactly causes an immediate `status="blocked"` return, which the lifecycle layer
records as FAILED state.

Phase 2 UI must send this exact string. Tests must import `_CONFIRM_SENTINEL` rather than duplicating
the literal. All previous references to `"I UNDERSTAND THE IMPLICATIONS"` in documentation and tests
were wrong and have been corrected in PR A.

---

### Lifecycle State File Atomicity

`pz_correction_lifecycle.json` is written via `write_json_atomic` (tempfile + os.replace). This file
is safe against partial writes and crash-during-write.

`correction_push_record.json` and `audit.json` patches inside `global_pz_push.py` are written via
`_write_json_file` (plain `path.write_text`). These are NOT atomic. A crash between the wFirma API
call returning and the push record write completing leaves wFirma with a document but no idempotency
guard. Fixing this is PR B scope (atomicity hardening), not PR A.

---

### Route Surface (Five Endpoints)

As of PR A, five lifecycle endpoints exist in `routes_pz.py`:

| Method | Path | Gate | Notes |
|--------|------|------|-------|
| GET | `/pz/lineage/{batch_id}/correction-state` | lifecycle flag + global batch | reads or inits state |
| POST | `/pz/lineage/{batch_id}/correction-stage` | lifecycle flag + global batch | stages option, writes execution record |
| DELETE | `/pz/lineage/{batch_id}/correction-stage` | lifecycle flag | resets STAGED to OPERATOR_REVIEWED |
| POST | `/pz/lineage/{batch_id}/correction-commit` | lifecycle flag + push flag + global batch | pushes to wFirma |
| POST | `/pz/lineage/{batch_id}/correction-suppress` | lifecycle flag only | closes workflow without wFirma push |

The suppress endpoint does NOT require global batch detection. This is intentional: an operator
must be able to close a stuck EXECUTING workflow even if source PDFs are unavailable or corrupt.

---

### What Did Not Change

These things were not modified by Phase 1 or PR A and remain exactly as they were:

- **Database schema.** No new SQLite tables, no schema migrations, no changes to existing `.db` files.
- **Storage structure.** Production databases live at `C:\PZ\storage\`. Phase 1 writes only
  `pz_correction_lifecycle.json` inside the existing per-batch output directory when the flag is on.
- **Router registration.** The lifecycle routes are in `routes_pz.py`. No new router file. No
  `main.py` change. The `routes_pz` router was already registered.
- **Existing correction routes.** The pre-Phase 1 correction endpoints are unmodified.
- **wFirma client.** No changes to `global_pz_push.py`, `global_pz_execution.py`, or the wFirma
  API wrapper. Phase 1 and PR A call into them; they do not modify them.
- **Atomicity of push record and audit writes.** `_write_json_file` in `global_pz_push.py` remains
  plain `path.write_text()`. The false "atomic" comment at line 205 is a known documentation defect
  tracked for PR B.
- **wFirma delete or cancel capability.** CANCEL_AND_RECREATE is explicitly blocked.
- **UI.** No dashboard changes. No new frontend pages or components.
- **Automatic activation.** Nothing in the deployment sequence turns the feature flag on.

---

### Readiness for Phase 2

Phase 2 is NOT approved yet. Do not begin Phase 2 work until the operator issues explicit go/no-go.

PR B (atomicity hardening and parallel push route deprecation) is not required before Phase 2 begins,
but must complete before `wfirma_correction_push_allowed` is set to True in production.

PR A fixes that are now resolved:
- Sentinel mismatch: FIXED. Tests import `_CONFIRM_SENTINEL`. Docstrings updated.
- suppress_terminal route: FIXED. Fifth endpoint added, 9 tests passing.
- Documentation sentinel value: FIXED in both phase1 docs.

PR B remaining blockers (required before wfirma flag activation):
- Atomicity: `_write_json_file` in `global_pz_push.py` must use `write_json_atomic`.
- Parallel push path: old `correction-push-wfirma` route needs lifecycle gate or deprecation.

PR C improvements (medium severity, not blocking activation):
- `_is_global_batch()` failure diagnostics.
- KEEP_CURRENT staging guard or explicit documentation of STAGED -> FAILED path.
- Empty contractor/warehouse ID validation in push service.

---

### Recommended Next Steps

**Activation** (when operator decides to enable Phase 1):
1. Run PR B first. Do not activate before PR B is complete.
2. Add explicit entries to `C:\PZ\.env`:
   `PZ_CORRECTION_LIFECYCLE_ENABLED=false` and `WFIRMA_CORRECTION_PUSH_ALLOWED=false`
3. Verify `WFIRMA_SUPPLIER_CONTRACTOR_ID` and `WFIRMA_WAREHOUSE_ID` are non-empty in `.env`
4. Redeploy lifecycle files: robocopy `service\app\services\pz_correction_*.py` to `C:\PZ\app\services\`
5. Set `PZ_CORRECTION_LIFECYCLE_ENABLED=true` in `C:\PZ\.env`
6. Restart PZService
7. Smoke test: `GET /api/v1/pz/lineage/{known_global_batch}/correction-state` should return 200
   with `state: PROPOSED`
8. Only then set `WFIRMA_CORRECTION_PUSH_ALLOWED=true` if the commit path is also being activated

**Phase 2 work** can focus on three areas without touching Phase 1 code:
- Operator workflow UI: state visibility, option selection, stage confirmation, commit confirmation
  with the exact `_CONFIRM_SENTINEL` string from `global_pz_push.py`
- State display: reading `correction-state` and rendering the current state, available transitions,
  and staged option; include the suppress action for EXECUTING and FAILED states
- Reset and re-stage UX: making it easy for operators to back out of a staged option before committing

No Phase 1 architecture decisions need to be revisited before Phase 2 starts. The only prerequisite
is explicit operator approval to begin.
