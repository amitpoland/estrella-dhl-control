# W-2 PRE-IMPLEMENTATION — Carrier-Actions Operator UI

**Mode:** PRE-IMPLEMENTATION
**Scope:** scope and sequence the next implementation campaign
(W-2). Inspection only — no production code edits in this
session.
**Baseline:** `4d598f1` (DL-G1 release-readiness audit closed;
stabilization window active)
**Coordinator pass:** in-context (Opus). Eight reviewer roles
ran as Coordinator-simulated parallel reads — promotion to
parallel sub-agent spawn deferred to W-2.1 implementation
session per the operating system's "reviewer activation"
contract.

---

## 0. Pre-flight gates

| Gate | Result |
|---|---|
| `git status --short` | clean |
| Branch | `feature/dhl-label-workflow-planning` |
| dashboard suite | **875 / 875** pass |
| carrier + DHL suite | **1205 / 1205** pass |
| `make verify` | **160 / 160** pass |
| Active code lane | none |
| Stabilization window | **active** since DL-G1 (`4d598f1`) |

This artifact opens during the stabilization window and produces
no source change. The window's "no implementation campaign opens
without explicit operator decision" clause is satisfied by the
operator's `/context` opening this session.

---

## 1. Current W-2 state

### What exists (carrier subsystem, runtime side)

The carrier subsystem ships a complete API surface. Backend is
"live-capable in shadow mode" today — flags default OFF (ADR-010).

| Surface | Path | Auth | Status |
|---|---|---|---|
| List shipments (cross-batch) | GET `/api/v1/carrier/shipments` | none | read-only, in production |
| Get shipment by id | GET `/api/v1/carrier/shipments/{shipment_id}` | none | read-only |
| List shipments by batch | GET `/api/v1/carrier/shipments/by-batch/{batch_id}` | none | read-only |
| Shipment transitions | GET `/api/v1/carrier/shipments/{shipment_id}/transitions` | none | read-only |
| Download label artifact | GET `/api/v1/carrier/labels/{sha256}` | none | content-addressed, by sha256 |
| List all open proposals | GET `/api/v1/carrier/proposals` | none | read-only |
| Proposals for batch | GET `/api/v1/carrier/proposals/by-batch/{batch_id}` | none | read-only |
| Recent shadow rows | GET `/api/v1/carrier/shadow/recent` | API key | read-only, gated |
| Shadow summary | GET `/api/v1/carrier/shadow/summary` | API key | read-only, gated |
| Create shipment (execute) | POST `/api/v1/carrier/actions/create-shipment/execute` | API key | write; proposal-gated; idempotent (DL-F3.5a) |
| Mark label printed | POST `/api/v1/carrier/actions/mark-label-printed/execute` | API key | write; state-engine gated |
| Mark handed to carrier | POST `/api/v1/carrier/actions/mark-handed-to-carrier/execute` | API key | write; state-engine gated |
| Cancel shipment | POST `/api/v1/carrier/actions/cancel-shipment/execute` | API key | write; state-engine gated |
| Webhook activate (DHL→us) | POST `/api/v1/carrier/webhook/dhl/activate` | DHL-API-Key + IP allowlist | external; gated by `carrier_dhl_webhook_enabled` |
| Webhook events (DHL→us) | POST `/api/v1/carrier/webhook/dhl/events` | DHL-API-Key + IP allowlist | external; gated; DL-F3.5c enforces 503 when allowlist empty under live |

### What is missing (operator-facing UI)

Confirmed via grep over `service/app/static/dashboard.html`:

> **`grep -nE "/api/v1/carrier" dashboard.html` returns ZERO matches.**

The carrier subsystem is **entirely API-only** from the operator's
perspective today. Specifically missing:

1. No carrier shipment list / by-batch panel.
2. No proposal viewer (the API can list proposals; the dashboard cannot).
3. No execute-action button for any of create / mark-printed / mark-handed / cancel.
4. No label-artifact viewer.
5. No transitions timeline.
6. No shadow-log review surface.
7. No safety banner indicating which mode (`live_enabled` / `shadow_mode` / `api_status`) is active.
8. No webhook-event audit surface.

### What is API-only

Everything carrier-related. Operator action today requires:
- knowing the proposal_id (derived deterministically by the backend; obtainable via the GET proposals endpoint),
- holding the API key,
- POSTing JSON to the execute endpoint with the correct envelope shape.

This is the program-board debt **D-2** (P2 — release blocker for live-prod).

### What is blocked by release posture

- **W-2.x phases that would touch live behaviour are blocked.** The stabilization window prohibits live-prod rollout. W-2 must not introduce paths that change `carrier_dhl_*` flag defaults or that emit traffic which requires those flags.
- **Webhook-receiver UX is partially blocked.** Webhook events depend on `carrier_dhl_webhook_enabled`. UI for the event log is fine; UI to *enable* the webhook is a flag-flip surface and requires Coordinator + PRR + OSR sign-off (charter authority matrix).

---

## 2. Existing backend capability map

For every prospective UI module, classified by capability:

### Carrier shipment reads (no auth; safe for UI)

| Endpoint | Use case |
|---|---|
| GET `/api/v1/carrier/shipments?status=&carrier=` | Cross-batch shipment list |
| GET `/api/v1/carrier/shipments/{id}` | Drill-down view |
| GET `/api/v1/carrier/shipments/by-batch/{batch_id}` | Per-batch panel |
| GET `/api/v1/carrier/shipments/{id}/transitions` | Timeline rendering |

### Carrier proposals (no auth)

| Endpoint | Use case |
|---|---|
| GET `/api/v1/carrier/proposals` | All open action proposals across batches |
| GET `/api/v1/carrier/proposals/by-batch/{batch_id}` | Per-batch proposals |

### Carrier actions (API key required)

| Endpoint | Use case |
|---|---|
| POST `/api/v1/carrier/actions/create-shipment/execute` | Operator-confirmed create |
| POST `/api/v1/carrier/actions/mark-label-printed/execute` | After printing |
| POST `/api/v1/carrier/actions/mark-handed-to-carrier/execute` | At handover |
| POST `/api/v1/carrier/actions/cancel-shipment/execute` | Pre-handover void |

All four take `{batch_id, request, proposal_id, actor, reason}`-shape envelopes (verify exact shape in implementation phase via existing test files). All four are idempotent or state-machine-gated — duplicate retries return 200 with `idempotent_replay: true` (DL-F3.5a) or 409 if state doesn't permit.

### Shadow logs (API key)

| Endpoint | Use case |
|---|---|
| GET `/api/v1/carrier/shadow/recent` | Diff log for shadow-mode operator review |
| GET `/api/v1/carrier/shadow/summary` | Match-rate / failure-rate aggregates |

### Webhook events (external trust path; UI cannot accept; UI can read events DB)

| Endpoint | Use case |
|---|---|
| POST `/api/v1/carrier/webhook/dhl/activate` | DHL→us; not callable from UI |
| POST `/api/v1/carrier/webhook/dhl/events` | DHL→us; not callable from UI |

UI may render *received* events (via a future read endpoint backed by `carrier_event_db`) — not yet exposed; out of W-2.1 scope.

### Manifests / evidence

The carrier label store (`carrier_label_store.py`, ADR-017) writes to `<storage_root>/carrier_labels/`. Manifests are read indirectly via the shipment-detail GET endpoints (the response includes `manifest_path`, `label_sha256`). Direct label download via `/api/v1/carrier/labels/{sha256}` is content-addressed.

### Auth posture summary

| Class | Auth | Notes |
|---|---|---|
| GET reads (shipments + proposals) | none | safe for UI; matches existing dashboard read-only patterns |
| GET reads (shadow) | API key | dashboard already passes API key on existing `/api/v1/execute/...` calls — pattern transfers |
| POST writes (actions) | API key + proposal_id check | every UI write must call exact corresponding execute route |
| Webhook | external | not UI-reachable |

---

## 3. Operator journey map

Eight named operator journeys — covering everything the carrier
subsystem supports today:

### J-1: Create shipment (most-used, highest-risk)

```
1. Operator opens batch detail page
2. Reviews customs status (already shown)
3. Sees "Carrier" tab / panel (NEW)
4. Sees "Create Shipment" proposal card if state permits
5. Reviews shipment request fields: ship_from, ship_to, packages, service, reference
6. Operator confirms (prompt for operator name; same pattern as closure-confirm)
7. POST /api/v1/carrier/actions/create-shipment/execute
8. Sees: AWB issued, label sha256, manifest path, shadow notice (if shadow_mode)
9. On idempotent_replay=true: sees explicit "already created" notice with same AWB
```

### J-2: View shipment state (read-only)

```
1. Operator opens carrier panel
2. Sees current shipment row(s) for the batch
3. Sees state badge (created / label_created / label_printed / handed / voided)
4. Sees AWB, carrier, label_sha256 (truncated), state, last transition timestamp
5. Click → drill-down (J-3)
```

### J-3: Drill-down + timeline

```
1. Operator clicks shipment row
2. Sees timeline (transitions list, chronological)
3. Sees label artifact link (download via /api/v1/carrier/labels/{sha256})
4. Sees raw response collapsed (operator-friendly redaction; no credentials)
5. Sees pending proposals for this shipment (if any)
```

### J-4: Approve / execute action

Any of mark-label-printed / mark-handed-to-carrier / cancel-shipment.

```
1. Operator sees a proposal card (e.g., "Mark Label Printed")
2. Card shows: action name, target state, current state, prerequisites
3. Disabled state shows reason ("waiting for previous state X")
4. Operator confirms (prompt-style — consistent with closure-confirm pattern)
5. POST corresponding /api/v1/carrier/actions/.../execute
6. Sees state transition + new shipment state badge
7. On 409 (state_engine_rejected): sees clear error with suggested next step
```

### J-5: Print / label review

```
1. Operator on shipment drill-down
2. Clicks "View label" → opens label artifact in new tab via /api/v1/carrier/labels/{sha256}
3. Prints from the browser
4. Returns to dashboard, executes J-4 (mark-label-printed)
```

### J-6: Inspect shadow results (sandbox-shadow only)

```
1. Operator opens "Shadow" panel (NEW; only visible when shadow_mode=True)
2. Sees recent diffs from /api/v1/carrier/shadow/recent
3. Sees summary stats from /api/v1/carrier/shadow/summary
4. Can filter by method / diff status
5. Read-only — no actions
```

### J-7: Inspect webhook events

```
1. Operator opens "Carrier Events" subpanel
2. Sees recent inbound DHL events (from carrier_event_db)
3. Read-only
4. (Currently no read endpoint for events — listed as gap below)
```

### J-8: Rollback / disable live behavior

```
1. Operator does NOT do this from the UI
2. Operator edits .env, restarts workers
3. UI shows the new mode after refresh (via a "current mode" banner)
```

W-2 must **not** introduce a UI button that flips a feature flag. ADR-010 + the charter authority matrix forbid that.

---

## 4. UI module proposal (no code; module contracts only)

Eight UI modules, named by data-testid for future test pinning:

### M-1: `carrier-actions-tab`
Container for all carrier-side operator surfaces. Lives inside the BatchDetailPage tab strip alongside `DHL / Customs`, `PZ`, etc.

### M-2: `carrier-shipment-panel`
Per-batch shipment list. Renders rows from `/api/v1/carrier/shipments/by-batch/{batch_id}`. Each row shows AWB, carrier, state badge, last transition.

### M-3: `carrier-proposal-panel`
Renders open proposals from `/api/v1/carrier/proposals/by-batch/{batch_id}`. One card per proposal. Disabled-state messages pulled from proposal `blocking_reasons`.

### M-4: `carrier-execute-confirmation-drawer`
A consistent confirmation surface for every write action. Same UX shape as the existing closure-confirm flow:
- Modal / drawer
- Action description
- Operator name prompt (defaults `operator`)
- "Reason" free-text (audit field)
- Confirm + Cancel
- Disabled when state-engine prevents the action; reason shown in tooltip

### M-5: `carrier-shipment-timeline`
Renders `/api/v1/carrier/shipments/{id}/transitions`. Chronological. Reuses existing timeline components.

### M-6: `carrier-label-artifact-card`
Shows `label_sha256` (short form), label format, file size; click → opens label via `/api/v1/carrier/labels/{sha256}` in a new tab.

### M-7: `carrier-shadow-status-card`
Shows current mode (live / shadow / stub) inferred from a future read endpoint or from the existing settings surface. NOT a flip control — read-only mode badge.

### M-8: `carrier-mode-banner`
A persistent banner at the top of the carrier-actions-tab announcing the current operational mode. Critical for operator-safety:
- "STUB MODE — no real DHL traffic"
- "SANDBOX SHADOW — real DHL HTTP, AWB returned by stub"
- "LIVE PRODUCTION — real DHL traffic, real customer impact" (red, sticky)

The banner reads from a small read-only status endpoint (does not exist yet — flagged below as backend gap G-2).

---

## 5. Backend readiness assessment per UI module

| Module | Endpoint | Auth | Test coverage | Status |
|---|---|---|---|---|
| M-1 (tab container) | n/a | n/a | n/a | UI-only |
| M-2 (shipment panel) | GET `/shipments/by-batch/{id}` | none | covered (carrier route tests) | **READY** |
| M-3 (proposal panel) | GET `/proposals/by-batch/{id}` | none | covered (proposals route tests) | **READY** |
| M-4 (execute drawer) | POST 4× `/actions/.../execute` | API key | covered (action route + idempotency tests) | **READY** |
| M-5 (timeline) | GET `/shipments/{id}/transitions` | none | covered (transitions test) | **READY** |
| M-6 (label card) | GET `/labels/{sha256}` | none | covered (label-store tests) | **READY** |
| M-7 (shadow status card) | GET `/shadow/summary` | API key | covered (shadow route tests) | **READY** |
| M-8 (mode banner) | **MISSING ENDPOINT** | — | — | **GAP G-2** — needs a small read-only `/api/v1/carrier/mode` endpoint exposing `{live_enabled, shadow_mode, api_status}`. NOT a flag-flip endpoint. |

### Backend gaps surfaced by W-2 PRE-IMPLEMENTATION

| ID | Gap | Severity | Owner | Resolution |
|---|---|---|---|---|
| G-1 | No read endpoint for inbound DHL events from `carrier_event_db` (J-7) | P3 | Backend Architect | optional for W-2.1; can defer to W-2.5 or later |
| G-2 | No mode-status read endpoint for M-8 banner | P2 | Backend Architect + Security | required for W-2.6; small + read-only; one new GET endpoint |

Both gaps are **read-only additions**. Neither is a write surface. Neither flips a flag. Both are low-risk and live within the existing carrier route conventions.

---

## 6. Safety and security findings

### Reviewer: Operator Safety

| ID | Finding | Severity |
|---|---|---|
| OS-1 | The mode banner (M-8) is the **single most important safety surface** for live-prod readiness. Without it, operators cannot tell at a glance whether they are issuing real DHL traffic. Must be prominent, sticky, color-coded by severity, visible above-the-fold on the carrier tab. | **P0** for live-prod readiness; **P1** for sandbox-shadow readiness |
| OS-2 | The execute-confirmation drawer (M-4) must require an *operator name* prompt for every write action — same pattern as closure-confirm. The `actor` field is required and audited per `routes_carrier_actions.py` `_validate_actor` (rejects empty / sentinel-prefixed values). | P1 |
| OS-3 | The Cancel button must show a hard "irreversible (post-handover)" warning if the shipment state is past `LABEL_PRINTED`. Cancel is voidable pre-handover; post-handover it is a recovery operation, not a UI action. Backend already returns 409 in that case; UI must surface the reason clearly. | P1 |
| OS-4 | Disabled-state messaging must explain *why* every disabled button is disabled (mirror the closure-eval pattern). No silent grayed-out buttons. | P2 |
| OS-5 | The "current mode" inference must come from a backend read, not from JS-side flag inspection. Browser-side computation is a trust hole. | P1 |

### Reviewer: Security

| ID | Finding | Severity |
|---|---|---|
| SEC-1 | Every UI write must call the exact `/api/v1/carrier/actions/.../execute` route. No "/api/v1/execute/..." wrapper. Source-grep guard required in W-2 tests (analogous to existing `test_no_auto_create_product_endpoint_referenced` pattern). | P1 |
| SEC-2 | The mode banner's mode-status endpoint (G-2) MUST NOT expose credentials, account numbers, or any field beyond `{live_enabled: bool, shadow_mode: bool, api_status: str}`. Source-grep guard required against credential exposure on any new mode endpoint. | P1 |
| SEC-3 | UI must never render full DHL response bodies (they may contain undocumented fields). Backend already redacts via DL-F3.5b `_summarise()` and `_SENSITIVE_KEYS_LOWER` — UI must trust the backend's projection and not retain raw responses client-side. | P1 |
| SEC-4 | Proposal_id must be passed verbatim from backend → UI → backend on execute. UI must not synthesize or modify proposal_ids; the deterministic id is the integrity surface. | P1 |
| SEC-5 | The label artifact view opens via `/api/v1/carrier/labels/{sha256}`. The `sha256` is content-addressed; UI must use the value backend returns, not derive its own. | P2 |

### Live-prod blockers — confirmed and re-stated

- **D-1** (Security P1, ADR-009 caveat). NOT closed by W-2; remains a live-prod live blocker on its own.
- **D-2** (Operator UX P2). **W-2 is the campaign that closes D-2.** Closure of D-2 requires (a) W-2.1 through W-2.6 shipped, (b) Operator Safety walk passes against the implemented UI, (c) successor RELEASE artifact updates DL-G1's recommendation.

### Shadow-mode constraints (from DL-G1)

- W-2 must work in stub-mode, sandbox-shadow mode, and live-prod mode without code branching.
- The mode banner (M-8) is the only surface that varies by mode.
- Confirmation copy must be identical across modes (no "this is just shadow, click freely" softening — that builds operator habits that fail in live).

### Webhook trust limitation

- W-2 introduces NO webhook-related write paths.
- W-2 may expose a future read view of received events (G-1) — read-only, gated by API key.

### Operator-confirmation requirements

Every write action requires:
1. Operator name (prompt, defaults `operator`).
2. Free-text reason (audited).
3. Explicit confirm click on the drawer.
4. Visible state-engine prerequisite list (so the operator understands the gating).

### No direct unsafe POST from UI

- Every write must go through `apiFetch` (existing helper) with `credentials: 'include'`.
- No `<form>` submission to write endpoints.
- No `XMLHttpRequest` direct calls.
- API key passes via `X-API-Key` header (existing convention).

---

## 7. Test strategy for W-2 implementation

The W-7 stabilization campaign demonstrated that source-grep
tests on dashboard.html are the trust foundation. W-2 must add
to that foundation, not weaken it.

### Required new test classes

| Class | Pattern | Example |
|---|---|---|
| **Module-presence** | `assert "data-testid=\"carrier-shipment-panel\"" in src` | per module M-1..M-8 |
| **Endpoint pinning** | `assert "/api/v1/carrier/shipments/by-batch/" in src` | per endpoint used by W-2 |
| **No-invented-endpoint** | route-audit (existing `test_route_audit_zero_stale`) — must remain green after W-2 | already in place; W-2 must not regress |
| **Write-action guard** | `assert "/api/v1/carrier/actions/" in carrier_panel_snippet` AND `"/api/v1/execute/" not in carrier_panel_snippet` | enforces SEC-1 |
| **Confirmation prompt** | `assert "prompt(" in execute_drawer_snippet` | enforces OS-2 |
| **Disabled-reason testid** | `assert "data-testid=\"carrier-execute-disabled-reason\"" in src` | enforces OS-4 |
| **Mode banner presence** | `assert "data-testid=\"carrier-mode-banner\"" in src` | enforces OS-1 |
| **No credential leak in mode endpoint** | source-grep over backend test (when G-2 lands): `dhl_express_api_password` etc. NOT in mode response | enforces SEC-2 |

### Existing tests that MUST remain green throughout W-2

| Test file | Current count |
|---|---|
| `test_dashboard_*.py` | 875 / 875 |
| `test_carrier_*.py` + `test_dhl_*.py` | 1205 / 1205 |
| `make verify` | 160 / 160 |
| Source-grep guards from DL-F3.5 | all pinning patterns |

### Phase-test gating

Per the lane-serialization rule (b79a9e0), each W-2.N phase ships
a single commit and must:
1. Add new tests covering its module.
2. Run focused → regression → full suite → make verify.
3. Stop hard if any pre-existing test regresses.

---

## 8. Implementation sequencing

Six phases. Each is a single commit. None opens until the
previous closes cleanly. Lane serialization enforced.

### W-2.1 — Read-only carrier overview (smallest, safest first)

| Field | Value |
|---|---|
| **Touches** | `service/app/static/dashboard.html` (new tab section + M-1 + M-2) |
| **Endpoints used** | GET `/api/v1/carrier/shipments/by-batch/{id}` |
| **Tests added** | module-presence (M-1, M-2); endpoint-pinning; no-invented-endpoint regression check |
| **Risk** | low — read-only; no execute path; mirrors existing `closure-eval-card` shape |
| **Rollback** | revert single commit; no DB / config impact |
| **Stop condition** | dashboard suite remains 875+; new tests pass; no carrier+DHL test regression |

### W-2.2 — Per-batch carrier panel + timeline

| Field | Value |
|---|---|
| **Touches** | `dashboard.html` (M-5 timeline; expand M-2) |
| **Endpoints used** | GET `/shipments/{id}/transitions`, GET `/labels/{sha256}` |
| **Tests added** | timeline rendering pinning; label link presence |
| **Risk** | low — read-only |
| **Rollback** | revert |
| **Stop condition** | as W-2.1 |

### W-2.3 — Proposal panel + execute confirmation drawer

| Field | Value |
|---|---|
| **Touches** | `dashboard.html` (M-3 + M-4) |
| **Endpoints used** | GET `/proposals/by-batch/{id}`, all four POST `/actions/.../execute` |
| **Tests added** | confirmation-prompt assertion; write-action guard; disabled-reason testid; per-action testid |
| **Risk** | **medium** — first write surface in the UI for the carrier subsystem. Operator-Safety reviewer activates as parallel sub-agent. |
| **Rollback** | revert |
| **Stop condition** | suite green + Operator Safety sign-off recorded |

### W-2.4 — Label artifact + cancel-irreversible warning

| Field | Value |
|---|---|
| **Touches** | `dashboard.html` (M-6; cancel UX in M-4) |
| **Endpoints used** | GET `/labels/{sha256}`; POST `/actions/cancel-shipment/execute` |
| **Tests added** | irreversible-warning testid; label-link target |
| **Risk** | medium — cancel is destructive |
| **Rollback** | revert |
| **Stop condition** | suite green + Operator Safety sign-off |

### W-2.5 — Shadow-log review panel

| Field | Value |
|---|---|
| **Touches** | `dashboard.html` (M-7) |
| **Endpoints used** | GET `/shadow/recent`, GET `/shadow/summary` |
| **Tests added** | shadow card visible only when shadow_mode (mode-conditional rendering) |
| **Risk** | low — read-only |
| **Rollback** | revert |
| **Stop condition** | suite green |

### W-2.6 — Mode banner + new mode-status backend endpoint

| Field | Value |
|---|---|
| **Touches** | `dashboard.html` (M-8); **`service/app/api/routes_carrier.py`** (new GET `/api/v1/carrier/mode`); `service/tests/test_carrier_mode_endpoint.py` (new) |
| **Endpoints used** | new GET `/api/v1/carrier/mode` |
| **Tests added** | mode-banner testid; mode-endpoint shape; **source-grep that mode response does NOT contain credentials**; route-audit zero-stale |
| **Risk** | **medium** — first **backend** addition under W-2; first time we leave the dashboard.html lane in a long while. Backend Architect + Security Reviewer must activate. |
| **Rollback** | revert |
| **Stop condition** | suite green + Backend Architect + Security sign-off |

### Sequencing rationale

W-2.6 is **last** specifically because:
- It's the only phase that adds backend code (the mode-status endpoint, G-2).
- That makes it the highest-risk phase under lane serialization.
- It depends on W-2.1..W-2.5 already shipping the surfaces the banner annotates.

### W-2 closure criterion

After all six phases ship and pass their gates, a **successor RELEASE artifact** (`.claude/org/dry_runs/YYYY-MM-DD-w2-closure-and-dl-h-prep.md`) reviews:
- Operator-Safety walk against the implemented UI
- Whether D-2 closes
- Whether DL-Hx (live-prod readiness audit) becomes opensable
- Whether D-1 (the OTHER live-prod blocker) is now the only remaining gate

W-2 closure does **NOT** flip any feature flag. Live-prod cutover remains a separate, explicit Coordinator decision.

---

## 9. Explicit non-goals

W-2 (and any of its phases) MUST NOT:

- Enable `carrier_dhl_live_enabled`, `carrier_dhl_shadow_mode`, `carrier_dhl_webhook_enabled`, or `carrier_dhl_paperless_trade_enabled` in any code or default.
- Introduce a UI control that flips any feature flag.
- Issue any live DHL HTTP call from this campaign's tests or any new code path.
- Add any new write endpoint beyond what the existing carrier-actions surface provides.
- Merge to `main` (a separate operator-driven release decision).
- Modify any existing ADR (append-only discipline).
- Modify the `program_board.md` strategy columns (only progress columns on touched rows; per execution_modes.md).
- Introduce architecture changes (new services, new orchestration patterns, new agent types).
- Add a new telemetry ecosystem (separate future campaign if/when sandbox shadow surfaces a need).
- Touch `service/app/services/carrier/**` source — the carrier service is not in W-2's edit scope.
- Touch tests outside `service/tests/test_dashboard_*.py` and (in W-2.6 only) the new `test_carrier_mode_endpoint.py`.

---

## 10. Final coordinator recommendation

### Is W-2 ready for implementation?

**Yes — partially.** W-2.1 through W-2.5 are READY. W-2.6 is **conditionally ready** — it requires backend gap G-2 to be drafted as a small ADR (`ADR-018: read-only carrier mode-status endpoint`) before its code lands. ADR-018 is a Lane-A doc-only item that can ship in any session before W-2.6 opens.

### Smallest safe first W-2 implementation phase

**W-2.1 — Read-only carrier overview UI.**

- Single file: `service/app/static/dashboard.html`
- Two new modules: `carrier-actions-tab` (M-1) container + `carrier-shipment-panel` (M-2) row list
- One new endpoint usage: GET `/api/v1/carrier/shipments/by-batch/{id}` (already shipped, already tested, no auth)
- Mirrors existing read-only panel patterns (e.g., the agency docs card just landed in W-7 / B1.c)
- Risk: **low** — read-only; no execute paths; rollback is one revert

### Agents that activate for W-2.1

| Role | Activation | Output |
|---|---|---|
| **Coordinator** | session-header authority | mode declaration, scope fence |
| **Implementation Engineer** | yes | the diff |
| **Backend Architect** | review pass | confirms no inadvertent service/** edits |
| **Route / API Mapper** | review pass | confirms no invented endpoints |
| **QA Lead** | review pass | new tests + no dashboard-suite regression |
| **Dashboard Reviewer** | review pass | reads dashboard.html for hidden actions, broken flow |
| **Operator Safety Reviewer** | **deferred to W-2.3** (first write surface) | not activated for read-only W-2.1 |
| **Security Reviewer** | review pass | confirms no credential / unsafe POST |
| **Gap Hunter** | review pass | confirms no stale-route or silent downgrade |

### Files allowed for W-2.1

```
service/app/static/dashboard.html
service/tests/test_dashboard_carrier_overview.py  (new test file)
```

Forbidden for W-2.1:

```
service/app/**         (no service code change)
service/app/api/**     (no route change)
.claude/**             (governance-frozen; no W-2.1-time edits)
existing service/tests/test_*.py  (no edits to existing tests)
```

### Tests that must gate W-2.1

| Gate | Threshold |
|---|---|
| New W-2.1 tests | all pass |
| Existing dashboard suite | 875 / 875 (no regression) |
| Carrier + DHL suite | 1205 / 1205 (no regression — W-2.1 doesn't touch backend, but verify) |
| `make verify` | 160 / 160 |
| `test_route_audit_zero_stale` | green (no stale frontend calls introduced) |
| Source-grep: no `'/api/v1/execute/'` in carrier panel snippet | new guard test |

### What remains blocked

- **D-1** (Security P1, webhook trust model) — independent of W-2; remains a live-prod blocker. Cleared by ADR-019-style enumeration during DL-Hx, not by W-2.
- **Live-prod cutover** — remains HOLD even after W-2 fully closes. DL-Hx artifact is the next gate.
- **Webhook event read view** (G-1) — out of W-2 scope; future campaign or W-2.7 if operational evidence justifies.

---

## Final report (per /context output schema)

```
Artifact created:
  .claude/org/dry_runs/2026-05-10-w2-preimplementation.md

Agents activated (Coordinator-simulated, single-context this session):
  Lead Coordinator
  Backend Architect
  Route / API Mapper
  Operator Safety Reviewer
  Security Reviewer
  QA Lead
  UI/UX Planner (Claude Design Reviewer)
  Gap Hunter

Key findings:
  1. Carrier subsystem backend is fully ready; UI is missing entirely
     (zero "/api/v1/carrier" references in dashboard.html).
  2. W-2.1 through W-2.5 are READY against existing endpoints; only
     W-2.6 needs a new (small, read-only) backend mode-status endpoint
     plus ADR-018.
  3. Operator-Safety P0 finding: the mode banner (M-8) is the single
     most important safety surface for live-prod readiness.
  4. Sequencing: 6 phases, lane-serialized, smallest first.
  5. W-2 closes D-2 but does NOT close D-1; live-prod remains HOLD.

Implementation readiness:
  W-2.1 — READY
  W-2.2..W-2.5 — READY
  W-2.6 — CONDITIONALLY READY (needs ADR-018 draft first)

Recommended W-2.1 scope:
  Single commit on dashboard.html.
  Two new modules: carrier-actions-tab + carrier-shipment-panel.
  One existing endpoint: GET /api/v1/carrier/shipments/by-batch/{id}.
  One new test file: tests/test_dashboard_carrier_overview.py.
  Rollback: single git revert.

Tests run:
  dashboard suite       875 / 875 pass
  carrier + DHL suite   1205 / 1205 pass
  make verify (golden)  160 / 160 pass
  All green at HEAD 4d598f1.

Commit hash:
  (this artifact's commit, recorded after this dry-run lands)

Next legal lane:
  α  W-2.1 — Read-only carrier overview UI (IMPLEMENTATION mode,
       single code lane, dashboard.html only).
  β  ADR-018 draft — Lane-A doc-only, ahead of W-2.6 (optional now;
       required before W-2.6 opens).
```
