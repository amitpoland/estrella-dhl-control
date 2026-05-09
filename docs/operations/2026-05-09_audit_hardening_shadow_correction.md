# Audit hardening — accidental always-on activation and shadow-mode correction

**Date:** 2026-05-09
**Component:** `audit_scoring.score_batch` and downstream
                 (`audit_agent.build_audit_report`, escalation, Cliq)
**Severity:** Medium (production-side scoring behaviour changed silently;
              corrected within the same calendar day)
**Status:** Resolved by commit `5018fe7`

---

## 1. Summary

A categorical-trigger condition added by Group A of the audit hardening
campaign caused `score_batch` to apply hardening caps and BLOCKED
force-zero unconditionally on the audit_agent code path, despite the
`AUDIT_HARDENING_ENABLED` feature flag remaining at its default `False`
value. The flag was silently a no-op for every batch routed through
`audit_agent.build_audit_report`, which is the production path.

A corrective commit (`5018fe7`) narrows the activation gate so the
flag is now the SOLE trigger for hardening to alter the returned
score / risk_level. The same commit adds the originally-intended
shadow telemetry (structured INFO log line + optional Cliq debug
fragment) so ops can observe hypothetical hardening verdicts without
production behaviour changing.

## 2. Root cause

The activation expression introduced in commit `5bfc0d6`:

```python
hardening_active = (
    _hardening_enabled()
    or qty_status is not None
    or cn_status  is not None
    or nip_source is not None
)
```

was designed to let the test suite drive the new behaviour by
supplying categorical kwargs without setting environment variables.

In parallel, commit `42ceb54` (E1, landed earlier the same day) made
`verify_sad_invoice_match` always emit non-None `qty_status` and
`nip_source` for every batch (`cn_status` was already always emitted).
`audit_agent.build_audit_report` forwards all three from the
verification dict directly into `score_batch`. As a consequence, every
production audit invocation reached `score_batch` with three non-None
strings, causing the OR to short-circuit to `True` regardless of the
feature flag.

The flag was therefore only effective for direct calls to `score_batch`
that did not pass categoricals — a path with effectively zero
production traffic.

## 3. Affected commit range

```
5bfc0d6 feat: add feature-flagged audit scoring hardening   (introduced)
49cf3c5 fix: align SAD_READY total_value_usd with CIF semantics
c1757b5 fix: align PZ regression nazwa assertions with slash format
be745e7 fix: align PZ regression CIF softmatch assertion ...
d0fa90a fix: guard missing item family in calculate_landed
5018fe7 feat: add shadow-mode telemetry for audit ...        (corrected)
```

Range with unintended activation: `5bfc0d6` → `d0fa90a` inclusive
(parent of `5018fe7`).

The commits between `5bfc0d6` and `5018fe7` are unrelated to the
activation logic — they are CIF semantics, test-side reconciliations,
and a separate engine fix. None of them touched the hardening gate.

## 4. Timeline (CEST)

```
2026-05-09 10:40:40   5bfc0d6 committed locally (introduces unintended
                       activation via OR-trigger)
2026-05-09 11:54:04   feature/zoho-attachment-download branch renamed
                       to main (local git reflog event)
2026-05-09 12:09:43   main pushed to origin/main — point at which
                       any service deploying from origin/main begins
                       observing always-on hardening
2026-05-09 12:49:17   5018fe7 committed locally — restores true
                       shadow mode (flag-only activation + shadow
                       logging)
```

The exact deploy window depends on the service's deploy cadence
relative to the 12:09 push and the eventual deploy of `5018fe7`.
For ops correlation, the activation symptoms (BLOCKED status,
score=0, escalation to #PZ) should appear ONLY in audits whose
processing timestamp falls between the moment a process running
the `5bfc0d6`..`d0fa90a` code base started and the moment the
process running `5018fe7` (or later) started.

## 5. Operational effect during the window

For batches processed during the affected deploy window, the
following code paths in `score_batch` were silently active:

| Trigger condition                          | Pre-window outcome      | Window outcome           |
|--------------------------------------------|-------------------------|--------------------------|
| `c4["result"] is False` (invoice ↔ SAD)    | score 75, MEDIUM RISK   | score 0, HIGH RISK, BLOCKED |
| `c5["cif_result"] is False` (CIF total)    | score 80, MEDIUM RISK   | score 0, HIGH RISK, BLOCKED |
| `c1["result"] is None` (exporter unparsed) | score 100, LOW RISK     | score min(100,70), NOT_VERIFIED |
| `qty_status == "partial_aggregated_sad"`   | score 100, LOW RISK     | score min(100,85), PARTIAL |
| `cn_status == "verified_parent_aggregated"`| score 100, LOW RISK     | score min(100,85), PARTIAL |
| `nip_source == "sad_and_master"`           | score 100, LOW RISK     | score min(100,90), VERIFIED |

`escalation.should_escalate(score, status)` returns `True` when
`score < 70` OR `status == "blocked"`. The window's force-zero on
hard-link breaks therefore caused affected batches to escalate to
the `#PZ` Cliq channel that previously would have flowed through
without escalation.

Scoring math, CIF allocation, duty allocation, and product naming
were NOT affected. Only the audit-score numeric value, the
risk_level string, and the audit_data["status"] field changed for
the affected batches. No invoice values, no customs declarations,
no PZ documents, and no wFirma payloads were altered as a result
of this window — the activation issue is contained to the audit
output channel.

## 6. Rollback / corrective commit

`5018fe7` — feat: add shadow-mode telemetry for audit hardening
rollout

Activation expression after `5018fe7`:

```python
hardening_active = _hardening_enabled()
```

Categorical kwargs (`qty_status`, `cn_status`, `nip_source`) are
still accepted and used to compute the hypothetical hardening
verdict, but they no longer activate the path that alters the
returned `score` / `risk_level` / `status`. With the flag at its
default `False` value, those returned fields are byte-identical to
the pre-Group-A baseline.

When the flag is `False`, `score_batch` additionally:
- Emits a structured INFO log line:
  `HARDENING_SHADOW would_blocked=<bool> status=<status> score=<score>
   legacy_score=<int> legacy_risk_level=<str>`
- Adds `shadow_status`, `shadow_score`, `shadow_blocked` informational
  keys to the return dict for downstream callers that want to surface
  the verdict (e.g. an opt-in Cliq debug fragment, gated by
  `AUDIT_HARDENING_SHADOW_NOTIFY=1`).

When the flag is `True`, behaviour is identical to the post-Group-A
hardening path: caps and force-zero applied, `status` field emitted,
no shadow_* fields.

## 7. Current production semantics

After `5018fe7` reaches production:

- `AUDIT_HARDENING_ENABLED` is the **sole** activation gate for
  hardening to alter scoring output.
- With the flag unset / `0` / `false` (the default): legacy scoring
  unchanged from the pre-Group-A baseline. Hypothetical hardening is
  computed and logged but not applied.
- With the flag set to `1` / `true`: full hardening as documented in
  the `feat: add feature-flagged audit scoring hardening` commit
  body — caps, force-zero on confirmed hard-link breaks, status
  taxonomy in the return dict.

`detect_hard_link_break` (the pure helper from commit `eed8c10`) is
unchanged and remains available for direct use. `verify_sad_invoice_match`
continues to emit `qty_status` / `nip_source` / `cn_status` (commits
`42ceb54`, baseline). `customs_description_engine.generate_sad_ready_json`
continues to write CIF as `total_value_usd` (commit `49cf3c5`). None
of these are affected by the activation correction.

## 8. Operator interpretation guidance

- **Historical BLOCKED alerts in #PZ during the window** should be
  read as **telemetry indicating which batches WOULD be blocked
  under the future hardened scoring**, NOT as mandatory enforcement
  decisions that required ops action. The legacy semantics for
  these batches were MEDIUM RISK with score 75 / 80, no automatic
  escalation. Any actions taken in response to a window-period
  BLOCKED alert (e.g. holding a batch, requesting clarification
  from the carrier) were optional from a pre-window-policy
  standpoint.
- **Audit PDFs generated during the window** carry the post-Group-A
  status (`HIGH RISK` / `BLOCKED`). They remain accurate records
  of what the engine computed at that time. They should not be
  re-issued; the audit trail stays as-is.
- **Audit PDFs generated after `5018fe7` deploys** revert to
  legacy MEDIUM/LOW RISK styling for the same batch shapes until
  the flag is enabled in production.
- **Going forward**, batches that ops would want to block under the
  hardened semantics will appear in logs as
  `HARDENING_SHADOW would_blocked=True status=BLOCKED ...` even
  while the flag remains off. Use this as the source of truth for
  rollout sizing.

## 9. Recommended next steps

1. Push `5018fe7` to `origin/main` and deploy. Production reverts
   to legacy scoring behaviour automatically.
2. Configure log shippers to capture `audit_scoring` module INFO
   lines (specifically containing the `HARDENING_SHADOW` substring).
3. Run shadow telemetry for ~1–2 weeks. Aggregate per-day counts of
   `would_blocked=True` and breakdowns by `status` value.
4. Optionally enable `AUDIT_HARDENING_SHADOW_NOTIFY=1` in
   dev / staging to display the `[SHADOW]` line in Cliq messages
   alongside the legacy score (requires also wiring
   `audit_shadow_status` through `routes_bot` →
   `cliq_service.send`; deferred to a follow-up commit).
5. After ops + customs/legal review of the shadow data, enable
   `AUDIT_HARDENING_ENABLED=1` per environment in the staged order:
   dev → staging → production.
6. After 1+ release cycle of stable production with hardening on,
   the legacy scoring branch in `score_batch` may be removed in a
   future refactor.

## 10. Reference commits

- `5bfc0d6` — Group A introduction (contains the OR-trigger that
  caused the unintended activation).
- `42ceb54` — E1, made categoricals always-non-None upstream
  (precondition for the OR-trigger to short-circuit always-true).
- `eed8c10` — E2, `detect_hard_link_break` pure helper. Unaffected
  by the correction.
- `49cf3c5` — E3, SAD_READY CIF semantics. Unaffected.
- `5018fe7` — Corrective commit. Restores flag-only activation,
  adds shadow telemetry, no scoring math change.
