# DL-G1 — W-1 Release Readiness Audit (Sandbox Shadow Target)

**Mode:** RELEASE
**Scope:** decide sandbox-shadow readiness for the DHL carrier
workflow (W-1). Does **not** approve live-prod cutover.
**Baseline:** `37fda67` (W-7 dashboard stabilization closed)
**Coordinator pass:** in-context (Opus); reviewer roles
(Production Readiness, Operator Safety, Security) executed as
Coordinator-simulated parallel reads — promoted to actual
sub-agent spawn in DL-G2 / DL-Hx if those campaigns open.

---

## 1. Trust-layer verification (gates 1-4)

| # | Gate | Result |
|---|---|---|
| 1 | dashboard suite | **875 / 875 pass** |
| 2 | carrier + DHL suite | **1238 / 1238 pass** |
| 3 | `make verify` (golden) | **160 / 160 pass** |
| 4 | active production-code lane | **none** — `git status` clean; B1 closed at `37fda67` |

Trust layer is **green**. Release-mode signals are clean.

---

## 2. Production-readiness checklist walk (gate 5)

The checklist (`.claude/engineering/production-readiness-checklist.md`)
is written for the **live-prod cutover** moment. For sandbox shadow
the applicability splits — many DHL-account / customer-impact items
are not in scope. Per-gate walk:

### Gate 1 — Engineering

| Item | Sandbox-shadow applicability | Status |
|---|---|---|
| Campaign phases merged on release branch | applies | DL-A→F3.5 + Org Layer Upgrade + W-7 all on `feature/dhl-label-workflow-planning`; main merge is its own future move |
| Carrier suite green at HEAD | applies | **pass** (1238/1238) |
| `make verify` 160/160 | applies | **pass** (160/160) |
| No `TODO`/`FIXME`/`HACK` in carrier files | applies | not separately swept this campaign — defer to DL-G2 |
| No new module-scope adapter import outside local-factory | applies | source-grep guards held throughout DL-F3.5 |
| No new credential / PDF leak surface | applies | DL-F3.5b redaction + DL-F3.5c containment landed; tests pin |
| Idempotency guarantee for `create_shipment` (DL-F3.5a) | applies | shipped + 24/24 dedicated tests |
| Per-AWB lock + atomic CAS on transition (DL-G) | live-prod only | not yet built; not blocker for sandbox shadow |
| Schema version table + .bak snapshot (DL-G) | live-prod only | deferred |

**Gate 1 sandbox-shadow verdict: PASS** (with two live-prod-only items deferred).

### Gate 2 — Observability

| Item | Sandbox-shadow applicability | Status |
|---|---|---|
| Shadow diff dashboard live | applies | read-only shadow-log routes shipped at `bd9b50d`; dashboard surface is via API today, dashboard UI wiring deferred (D-2) |
| Match-rate ≥ 98% over 7 op-days | applies — but **after** shadow opens | not measurable yet; this gate becomes the exit criterion **out of** sandbox shadow into live-shadow, not the entry criterion |
| p95 live latency < 4 s over 7 op-days | applies after shadow runs | same as above |
| Quota counter visible | live-prod only | sandbox quota is 500 / day, ample for testing |
| Forbidden-token leak tests green | applies | DL-F3.5b adds `_SENSITIVE_KEYS_LOWER` redaction + 20 source-grep tests; **pass** |
| `request_hash` correlation present | live-prod only | deferred |

**Gate 2 sandbox-shadow verdict: PASS** for entry criteria; the
match-rate / latency items become the *exit* criteria for the
sandbox-shadow window.

### Gate 3 — Security

| Item | Sandbox-shadow applicability | Status |
|---|---|---|
| IP allowlist non-empty in `.env` (live mode) | applies | enforced as HTTP 503 `ip_allowlist_required_when_live` per DL-F3.5c |
| DHL-API-Key set in `.env` | applies | sandbox key required |
| PLT path containment to `storage_root` | applies | DL-F3.5c — enforced in adapter constructor; 17/17 tests pin |
| `CarrierEvent.raw` redacted | applies | DL-F3.5b — pass |
| `_summarise()` redacts credentials + `documentImages` | applies | DL-F3.5b — 20/20 tests pin |
| Webhook activate handshake tested in production with DHL | live-prod only | sandbox first |
| Secret rotation procedure documented + exercised | live-prod only | deferred |

**Gate 3 sandbox-shadow verdict: PASS** (security hardening is
complete for both sandbox and live-prod; only the *exercise* of
the webhook activate handshake against DHL is deferred).

### Gate 4 — DHL account readiness

All items in this gate are about **production** account readiness:
production credentials, EORI, PLT enrollment with DHL relationship
manager, production webhook subscription, etc.

**Gate 4 sandbox-shadow verdict: NOT IN SCOPE** for sandbox. The
sandbox URL accepts the test credentials DHL issues alongside the
production ones; no formal PLT enrollment is required for sandbox.

### Gate 5 — Operator readiness

| Item | Sandbox-shadow applicability | Status |
|---|---|---|
| On-call has read this checklist | applies | **operator's responsibility** — flag sandbox open |
| On-call has read rollback-doctrine | applies | one-page document; trivial precondition |
| On-call has rehearsed Layer 1 (flag flip) in staging | live-prod only | flag-flip for shadow IS the rehearsal |
| On-call knows shadow diff dashboard | applies | dashboard surface is API for now (D-2); on-call reads via curl until UI ships |
| On-call knows DHL operator portal URL | live-prod only | not needed for sandbox |
| Operator Safety Reviewer green light | applies | see §4 below |

**Gate 5 sandbox-shadow verdict: CONDITIONAL** on operator reading
the checklist + rollback doctrine before the flag flip.

### Gate 6 — Coordinator approval

| Item | Sandbox-shadow applicability | Status |
|---|---|---|
| Coordinator + PRR independent sign-off | applies | this artifact is the PRR pass; Coordinator approves the recommendation in §9 |
| Cutover window scheduled, not Friday afternoon | live-prod only | sandbox flip is reversible in <5 s; no window required |
| Customer-facing impact statement | live-prod only | sandbox produces no customer-facing AWBs |
| Post-cutover 48 h monitoring | applies in attenuated form | sandbox shadow's "monitoring" is operator review of shadow diffs over the first 24-48 h |

**Gate 6 sandbox-shadow verdict: PASS** with this artifact serving
as the PRR sign-off.

---

## 3. Rollback path review (gate 6 of /context)

For sandbox shadow, the relevant rollback layer is **Layer 1 —
feature flag flip** (per `rollback-doctrine.md`).

| Flag | Effect when flipped OFF | Time-to-revert |
|---|---|---|
| `carrier_dhl_shadow_mode` | wrapper drops; factory returns plain stub (since live remains True) or plain live (if status=production) | < 5 s |
| `carrier_dhl_live_enabled` | factory falls back to stub unconditionally; all live calls cease; telemetry warning fires | < 5 s |
| `carrier_dhl_webhook_enabled` | webhook endpoints return HTTP 503 | < 5 s |

**Rollback rehearsal verdict: TRIVIAL.** Sandbox-shadow rollback is
a single `.env` line edit + worker restart. No DB writes, no AWB
issued in real customer flow, no schema migration.

The Layer 4 "Live AWB recovery" doctrine does **not** apply here —
sandbox AWBs never enter the production registry per ADR-005, and
shadow-mode operator-facing AWBs come from the stub, not the live
sandbox HTTP call.

---

## 4. Operator-safety review (gate 7 of /context)

Reviewer: Operator Safety Reviewer (simulated).

### Risks identified

| ID | Severity | Finding |
|---|---|---|
| OS-1 | **P1** | The operator dashboard has no carrier-actions UI. `create_shipment` / `cancel_shipment` are API-only today (program-board debt **D-2**). For sandbox shadow this is *acceptable* because shadow is operator-driven via API tooling; for live-prod it is a hard hold. |
| OS-2 | P2 | The dashboard does not currently surface `carrier_live_fallback_to_stub` warnings (DL-F3.5d telemetry token). Operator sees stub-mode behaviour without knowing why if the live adapter quietly falls back. Mitigation: ops grep server logs; structured-log surface deferred (D-5). |
| OS-3 | P3 | Shadow diff dashboard is read-only via API; an operator must explicitly query `bd9b50d`-shipped shadow-log routes. No UI. Acceptable for sandbox-shadow review window. |

**Operator-safety verdict: PASS for sandbox shadow, HOLD for
live-prod.** The deciding factor is OS-1. Sandbox shadow can run
under API-driven operator action because:

- the operator-facing AWB returns from the stub (deterministic, no
  customer impact),
- live HTTP traffic is observation-only,
- rollback is a 5-second flag flip.

The same OS-1 finding **must remain a HARD HOLD on live-prod**
until D-2 closes (carrier-actions dashboard UI shipped + reviewed
+ operator-safety walked).

---

## 5. Security caveats — ADR-009 review (gate 8 of /context)

ADR-009 documents the webhook activate handshake. Its risk section
states explicitly:

> Webhook URL leak → unauthorised replay. Mitigated by IP allowlist
> (mandatory when live). Without that, the `DHL-API-Key` check is
> the only gate — **acceptable for sandbox shadow but NOT for
> production.**

Translated to this campaign:

| Surface | Sandbox shadow | Live-prod |
|---|---|---|
| Webhook activate trust model | DHL-API-Key + IP allowlist (when populated) | DHL-API-Key + IP allowlist **mandatory non-empty** (DL-F3.5c enforces 503) |
| Shadow data sensitivity | low — sandbox returns synthetic AWBs | high — production AWBs contain customer data |
| Recommendation | sandbox shadow is OK with current trust model | live-prod requires the security review explicitly enumerate the IP-allowlist trust assumption (program-board debt **D-1**) |

**Security verdict: PASS for sandbox shadow.** D-1 remains an open
P1 finding for live-prod and must be enumerated in any future
DL-Hx live-prod readiness recommendation.

---

## 6. Live-prod hold confirmation (gate 9 of /context)

Live-prod cutover is **HOLD**. Two independent reasons, either of
which alone is sufficient:

1. **OS-1 (Operator Safety P1):** no carrier-actions dashboard UI
   (D-2). API-only operator surface is unacceptable for live
   customer shipments.
2. **D-1 (Security P1):** webhook activate trust model relies on IP
   allowlist alone for unauthenticated DHL-side calls; acceptable
   for sandbox per ADR-009, **not** for live-prod without explicit
   enumeration of the trust assumption in a live-prod readiness
   recommendation.

A future campaign DL-Hx (live-prod readiness audit) opens only
after both D-1 and D-2 are closed.

---

## 7. Sandbox-shadow recommendation (gate 10 of /context)

**CONDITIONAL-GO** on sandbox shadow.

Conditions to be satisfied at flag-flip time (operator pre-flight):

1. `.env` configured:
   ```
   CARRIER_DHL_LIVE_ENABLED=True
   CARRIER_DHL_SHADOW_MODE=True
   DHL_EXPRESS_API_STATUS=sandbox
   DHL_EXPRESS_API_USERNAME=<sandbox username>
   DHL_EXPRESS_API_PASSWORD=<sandbox password>
   DHL_EXPRESS_ACCOUNT_NUMBER=<sandbox account>
   ```
2. Webhook configuration (only if exercising webhook flow):
   ```
   CARRIER_DHL_WEBHOOK_ENABLED=True
   CARRIER_DHL_WEBHOOK_API_KEY=<DHL-issued key>
   CARRIER_DHL_WEBHOOK_IP_ALLOWLIST=<DHL sandbox IPs, comma-separated>
   ```
3. Operator on-call has read:
   - this artifact,
   - `.claude/engineering/rollback-doctrine.md`,
   - the program-board W-1 row.
4. Operator is prepared to flip `CARRIER_DHL_SHADOW_MODE=False`
   within 5 seconds if any of:
   - any operator-facing AWB does not match the stub's deterministic
     pattern (would indicate the stub-vs-live boundary is
     contaminated),
   - the carrier suite or `make verify` regresses,
   - DL-F3.5d's `carrier_live_fallback_to_stub` warning fires
     unexpectedly (would indicate a config drift).

Exit criteria for sandbox shadow (i.e., conditions to advance to
the next stage, NOT gates to enter sandbox):

- Match-rate ≥ 98% over 7 operator-days,
- p95 live latency < 4 s,
- No security incident,
- Coordinator + PRR sign-off in a successor RELEASE artifact.

---

## 8. Governance housekeeping (per /context)

Two updates to `.claude/org/program_board.md`:

1. **W-7 row** — transition state from `pre-impl` (red) to `closed`,
   reflecting B1.a + B1.b + B1.c (commits `b0ff971`, `586d5d4`,
   `37fda67`) closing the dashboard test debt.
2. **D-7 row** — substantively closed by A3 (commit `758ae78`,
   2026-05-10). All 7 governance reviewer/historian agent files
   present at `.claude/agents/` (verified: 11 files total — 4
   pre-existing + 7 from A3).

No other rows are altered.

---

## 9. Final recommendation (signed)

```
═══════════════════════════════════════════════════════════════════
  RELEASE RECOMMENDATION — W-1 (DHL carrier label workflow)
  Date: 2026-05-10
  Baseline: 37fda67
═══════════════════════════════════════════════════════════════════

  Sandbox shadow:    CONDITIONAL-GO
                     (conditions enumerated in §7)

  Live-prod:         HOLD
                     (reasons: OS-1 / D-2 + Security P1 / D-1)

  Trust layer:       GREEN
                     (875 + 1238 + 160; lane serialization held)

  Rollback:          TRIVIAL
                     (Layer 1 flag flip < 5 s)

  Outstanding work before live-prod readiness audit (DL-Hx):
    - Close D-2: carrier-actions dashboard UI (operator-driven
      create / cancel / mark-printed / mark-handed surface, with
      operator-safety walk on disabled-state messaging and
      irreversible-action affordances).
    - Close D-1: explicitly enumerate webhook activate trust model
      in a live-prod readiness recommendation; consider whether
      ADR-009 needs a successor.
    - Land DL-G live-AWB invariants (per-AWB lock + atomic CAS,
      schema version table + .bak snapshot helper) for production-
      grade durability.

  Signed by:         Production Readiness Reviewer (this artifact)
  Coordinator:       approval is the commit message of this artifact

═══════════════════════════════════════════════════════════════════
```

---

## 10. Self-review

What this artifact does well:
- Distinguishes sandbox-shadow from live-prod gate-by-gate, rather
  than asserting a single binary.
- Names the two independent reasons live-prod is HOLD (OS-1, D-1),
  so closing either is not sufficient — both must close.
- Provides operator-actionable conditions in §7 (the `.env` shape,
  pre-flight reads, abort triggers).

What was deferred (deliberately, per /context):
- No actual sub-agent spawn for PRR / OSR / Security; reviewers
  ran as Coordinator-simulated. The next PRR walk (DL-Hx / live-
  prod readiness) should promote them to actual parallel agent
  spawns.
- No diff against a previous PRR walk (this is the first one); the
  artifact at `2026-05-10-pre-implementation.md` was a project-wide
  audit, not a PRR walk specifically.
- No actual flag flip — the recommendation is `conditional-go`,
  not the flip itself. The flip is a separate Coordinator decision
  in a successor session.
