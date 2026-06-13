# Stabilization Program — Authority Layer (Campaign 02.75-FINAL)

**Status:** PREPARED — window opens only after Deploy #1 lands the authority layer in production.
**Window definition (campaign rule):** ≥ 7 calendar days **OR** ≥ 100 shipments processed post-Deploy-#1, whichever the operator elects as the closing trigger. Calendar clock cannot be advanced by the agent.
**Drift authority:** `authority_drift_service.py` (R2 `check_authority_drift`, Phase 4 `emit_drift_alert`) against `authority_manifest_pinned.json` — ships in **Deploy #2** (audit-drift branch `feat/c025-authority-audit-drift` @ `2f12830`).

---

## 1. Sequencing dependency

```
Deploy #1 (authority modules, flags OFF)
   → stabilization window opens (modules present, inert)
Deploy #2 (audit + drift layer)
   → drift detection becomes active; manifest pin enforced at startup (R1)
```

The window may open on Deploy #1 (modules in place), but **drift monitoring is only mechanized after Deploy #2**. Until Deploy #2, drift is checked manually via `authority_audit.py` CLI (C1–C6 contracts) on demand.

## 2. What to track (4 authority surfaces)

| Authority | Module | Pinned SHA-256 | Drift signal |
|---|---|---|---|
| NameNormalization | `name_normalization.py` | `815111e4…` | manifest hash mismatch; any delegate host re-growing a private normalizer |
| FollowUpAuthority | `dhl_followup_authority.py` | `adb94aec…` | manifest hash mismatch; projector computing state outside the authority |
| Tracking | `tracking_db.py` | `429fd3d8…` | manifest hash mismatch; outbound registration bypassing the authority |
| Address | `awb_address_authority.py` | `0e7a60e3…` | manifest hash mismatch; carrier route reading raw recipient_address when flag ON |

## 3. Monitoring checklist (daily during window)

- [ ] `authority_audit.py` C1–C6 contracts EXIT=0 (run against `C:\PZ-verify` tracking origin/main).
- [ ] Startup manifest check (R1) clean in service logs — no manifest-mismatch warning on `PZService` start.
- [ ] Drift service (R2, post-Deploy-#2) audit-log shows no `emit_drift_alert` entries.
- [ ] No new private `_normalize_name` / `normalise_name` / direction-deriving helper reintroduced in delegate hosts (grep sweep).
- [ ] Flag posture unchanged from deploy (all OFF unless an explicit flag-flip change is approved + deployed).
- [ ] Error rate / 5xx on `/api/v1/pz/process` and carrier routes at or below pre-deploy baseline.

## 4. Flag-enablement policy during stabilization

- Deploy #1 lands flags **OFF**. Enabling any authority flag in production is a **separate change** (config/`.env`), not part of stabilization-by-default.
- Recommended: keep flags OFF for the full window to prove the modules are inert and import-safe, then enable one flag at a time in a later controlled change with its own smoke. This isolates any behavior delta to a single authority.
- If the operator elects to enable a flag during the window, that flag's authority restarts its own observation sub-window.

## 5. Rollback criteria (trip any → roll back authority layer)

- Manifest hash mismatch at startup that is NOT explained by an approved deploy.
- Drift alert (`emit_drift_alert`) for any of the 4 modules.
- PZ batch totals/notes diverge from pre-deploy golden output (B5 parity break).
- Carrier AWB recipient block changes with the AWB flag OFF (unexpected activation).
- Any 5xx attributable to an authority module import or call.
- Rollback = re-sync `C:\PZ\app` from pre-Deploy-#1 SHA (`62810c2`) + PYCACHE purge + restart; or, for a single authority, revert that squash + redeploy.

## 6. Escalation criteria (escalate to operator, do not auto-act)

- Any rollback-criteria trip (operator decides revert vs flag-OFF neutralize).
- Manifest needs re-pinning because an approved change legitimately altered a module hash (re-run `authority_audit.py` to regenerate `authority_manifest_pinned.json`, commit via PR branch).
- Shipment volume reaches ≥100 OR 7 days elapse → operator decides window closure → triggers Campaign 03 readiness re-evaluation.

## 7. Window-close evidence (required to close stabilization)

- [ ] ≥7 days OR ≥100 shipments recorded (state which trigger).
- [ ] Zero unexplained drift alerts across the window.
- [ ] Daily monitoring checklist green for the full window.
- [ ] B5 parity intact (sample PZ batch matches golden).
- [ ] Final `authority_audit.py` C1–C6 EXIT=0.
- → feeds the Campaign 03 Readiness Package stabilization gate.
