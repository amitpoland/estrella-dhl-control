# DHL Express Operator UI Review Pass

**Mode:** PRE-IMPLEMENTATION
**Scope:** walk the five DHL Express UI surfaces an operator now
sees on the dashboard's `DHL Express` tab, and surface friction,
safety concerns, and copy bugs before the next UI phase opens.
**Baseline:** `1a8b46d` (UI-GAP-1.3 closed)
**Coordinator pass:** in-context (Opus); reviewers
(UI/UX Planner, Operator Safety Reviewer, QA Lead, Gap Hunter)
executed as Coordinator-simulated parallel reads. Backend
Architect + Security NOT activated — no backend or security
surface in scope.

---

## 0. Pre-flight

| Gate | Result |
|---|---|
| `git status --short` | clean |
| DHL Express surface tests (4 files) | **245 / 245** pass |
| Full dashboard suite at HEAD | 1336 / 1336 pass |
| `make verify` | 160 / 160 pass |

---

## 1. The five surfaces under review

| # | Surface | Testid landmark | Lines |
|---|---|---|---|
| S-1 | Tab container + overview list (W-2.1 + W-2.1a) | `carrier-actions-tab` + `carrier-shipment-panel` | 4246 – ~4365 |
| S-2 | Shipment drill-down + timeline + label evidence (W-2.2) | `carrier-shipment-detail` (selection-gated) | 4367 – 4490 |
| S-3 | Action proposals listing (W-2.3 read side) | `carrier-proposals-panel` | 4493 – 4625 |
| S-4 | Confirmation drawer for 3 simple actions (W-2.3 write side) | `carrier-confirm-drawer` (drawer-state-gated) | 4644 – 4745 |
| S-5 | Shadow log review (UI-GAP-1.3) | `carrier-shadow-panel` | 4749 – ~4915 |

All five live inside the same `activeTab === 'DHL Express'` block.

---

## 2. Operator journey checklist

The end-to-end walkthrough a real operator performs today on a
batch with one or more DHL Express shipments:

| Step | Operator action | What they see | Friction |
|---|---|---|---|
| J-1 | Click "DHL Express" tab on batch detail page | Tab activates; useEffects fire `loadCarrierShipments` + `loadCarrierProposals` + `loadCarrierShadow` in parallel | none |
| J-2 | Scan overview list | `carrier-shipment-panel` shows row per shipment (carrier="DHL Express", AWB, state badge, label sha first 12 chars + "…", manifest "✓ on disk" / "—", created/updated timestamps) | **F-1 — stale mode-note copy** (see §5) |
| J-3 | Click a shipment row | Row highlights; `carrier-shipment-detail` block appears inline below; transitions + label-evidence card render | **F-2** — selection state can scroll out of view; no sticky "selected: AWB X" indicator |
| J-4 | Read transitions timeline | Each transition shows `from_state → to_state`, actor, reason, created_at | low — readable |
| J-5 | Click "Open label" link | New tab → GET `/api/v1/carrier/labels/{sha256}` → label PDF (or ZPL) | low — works |
| J-6 | Scroll back, review proposals panel | One card per proposal; review button on enabled simple actions; disabled badge or W-2.3b info-note on create_shipment | **F-3 — operator-confusing W-2.3b reference** (see §5) |
| J-7 | Click "Review action" on `mark_label_printed` (or `mark_handed_to_carrier` or `cancel_shipment`) | `carrier-confirm-drawer` opens with action / AWB / current state / proposal_id; operator-name input required; reason optional | low — clear |
| J-8 | Read cancel warning | Red bold "⚠ Irreversible: cancelling a DHL Express shipment voids the AWB…" | none — strong |
| J-9 | Read handover note | Blue "📦 DHL Express handover — once confirmed, the shipment is recorded as handed to DHL Express. Track via the standard MyDHL API channel." | low — accurate |
| J-10 | Type operator name + reason; click Confirm | POST fires; drawer closes; success banner; Promise.all refresh fires (proposals + shipments + selected-shipment timeline) | none |
| J-11 | Scroll to shadow log panel | Summary + recent rows; "match" / "shape_mismatch" / "live_only_error" / "stub_only_error" / "both_error" diff badges | **F-4** — diff_outcome jargon; **F-5** — no operator next-action hint when a non-match diff appears |
| J-12 | Want to refresh everything? | Each card has its own ↺ Refresh button (5 separate buttons on tab) | **F-6** — no single "Refresh all" |

---

## 3. Safety review

Reviewer: Operator Safety Reviewer (simulated).

### What's working

| ID | Finding | Status |
|---|---|---|
| OS-OK-1 | Three write actions are all gated through `carrier-confirm-drawer` — no direct POST from a list button | ✓ shipped W-2.3 |
| OS-OK-2 | Drawer requires non-empty operator-name (`actor`) input; execute button disabled when empty | ✓ |
| OS-OK-3 | Cancel action carries an "Irreversible" warning naming AWB-void consequence | ✓ |
| OS-OK-4 | Mark-handed action carries a "DHL Express handover" note | ✓ |
| OS-OK-5 | `create_shipment` proposal renders as info-only with explicit disabled badge — cannot reach the drawer | ✓ defense-in-depth (`carrierExecuteEndpointFor` returns null; `openCarrierConfirmDrawer` refuses) |
| OS-OK-6 | Shadow log surface is read-only — no execute path | ✓ |
| OS-OK-7 | Shadow log does NOT expose raw DHL bytes, credentials, label bytes, documentImages (backend allowlist + UI defence-in-depth source-grep) | ✓ pinned by 14 parametrised tests |
| OS-OK-8 | Empty / loading / error states named with `data-testid` for every loader | ✓ |
| OS-OK-9 | Disabled-state messaging discipline holds — proposal-disabled rows show blocking-reasons + Disabled badge | ✓ |

### What's missing (safety gaps)

| ID | Severity | Finding |
|---|---|---|
| **OS-GAP-1** | **P0 for live-prod readiness** | No **mode banner**. The operator cannot tell at a glance whether they're in stub / sandbox-shadow / live-prod. The shadow panel hints (rows imply shadow is recording) but no explicit banner. This is gap G-2 from the gap audit; closes via W-2.6 + ADR-018. |
| OS-GAP-2 | P2 | Reason field on the confirm drawer is optional even for **Cancel** (irreversible). Could be tightened: cancel without a reason is unusual. Tradeoff: forcing a reason may slow valid recoveries. Not a regression — Cancel still requires actor; just an audit-trail enrichment opportunity. |
| OS-GAP-3 | P3 | Shadow log diff-badge colours communicate severity but no legend. New operator may not know that "shape_mismatch" warrants investigation but "match" is normal. |
| OS-GAP-4 | P3 | After successful execute, the success banner is text-only — no link back to the now-updated shipment row or to the new transition the action created. |

---

## 4. Missing information

What an operator *might* want to see today and currently cannot
without leaving the UI:

| ID | Missing info | Recoverable? |
|---|---|---|
| MI-1 | **Mode awareness** (stub/shadow/live) | currently inferable from absence/presence of shadow rows; banner needed (W-2.6) |
| MI-2 | **Last-refresh timestamp** per loader | not displayed; operator can't tell freshness |
| MI-3 | **Click-to-copy AWB / label sha** | operator must hand-copy or use browser select |
| MI-4 | **Tracking-portal deep-link** to DHL Poland's tracking page | not present; would need URL-template config |
| MI-5 | **Pending-proposals count** badge on the DHL Express tab itself | not present; operator must open the tab to know |
| MI-6 | **Per-shipment last action by + when** | available in transitions but not aggregated to a single "last activity" line on the row |
| MI-7 | **Cross-batch carrier list** | gap G-3 — only by-batch view exists |
| MI-8 | **Shadow event → triggering shipment** navigation | shadow rows show `method` + diff but no link back to the shipment that produced the row |

None of these are blockers. They are *enrichment* opportunities
to consider for a future operator-evidence-driven phase.

---

## 5. Confusing copy

Found three operator-confusing copy issues:

### **F-1 (P1) — `carrier-overview-mode-note` is stale**

Line 4260-4263:
```
Read-only view of DHL Express shipments registered for this batch.
Operator actions (create, print, hand over, cancel) are not available here yet.
```

**This is now inaccurate.** Since W-2.3 shipped, three of those four actions (**print, hand over, cancel**) ARE available via the proposal drawer immediately below. Only `create` remains deferred (correctly — W-2.3b).

**Recommended fix** (one-line copy update, single commit, doc-only ergonomics):

```
Read-only summary of DHL Express shipments registered for this batch.
Print / hand-over / cancel actions live in the Proposals panel below.
Creating a new shipment is not yet available from the dashboard.
```

### **F-3 (P1) — operator-confusing W-2.3b reference**

Two places in the proposal panel mention internal phase code:
- Line ~4577: `data-testid="carrier-proposal-create-info-note"` content: *"Create shipment requires shipper, recipient, package, value, and service data. Data-entry form lands in W-2.3b."*
- Line ~4584: `data-testid="carrier-proposal-create-disabled-badge"` content: *"Awaiting W-2.3b"*

Operators don't know what "W-2.3b" means — that's a campaign-internal phase identifier. Surface-friendly rewording:

```
info-note:   "Creating a new DHL Express shipment requires shipper,
              recipient, package, value, and service data. A
              dedicated form is planned; until then this proposal is
              informational only."
badge:       "Form pending"
```

### **F-4 (P2) — shadow log diff jargon**

Operator-visible diff outcome values:
- `match` — clear
- `shape_mismatch` — operator-clear-enough
- `live_only_error` — slightly cryptic
- `stub_only_error` — same
- `both_error` — same

Could be replaced with operator-friendly labels (e.g., `live response error`, `stub response error`, `both responses errored`) while preserving the technical `diff_outcome` value for source-grep tests and for any downstream filter. **Lowest priority** — operators familiar with shadow-mode terminology will read these correctly.

---

## 6. Other friction notes (lower priority)

| ID | Note | Priority |
|---|---|---|
| F-2 | Selected-shipment context (drill-down) can scroll out of view. Sticky breadcrumb / "selected: AWB X" indicator would help long-batch workflows. | P3 |
| F-5 | Shadow log shows diffs but no operator next-action hint for non-match outcomes. A small "Investigate" / "Mark reviewed" affordance could land in a future write-surface phase (UI-GAP-2 territory). | P3 |
| F-6 | Five separate refresh buttons on one tab. A single "Refresh all" header button could simplify. Not urgent. | P3 |

---

## 7. UI-GAP-1.1 — can it open?

**Yes.** UI-GAP-1.1 (agency SAD decision read card) targets the
**DHL / Customs** tab, NOT the DHL Express tab. The two surfaces
are unrelated; no overlap with the DHL Express friction found
above.

UI-GAP-1.1 remains operator-approval-ready:
- Single commit, read-only card under `DHL / Customs` tab
- Closes gap G-11 (agency SAD decision read) from the gap audit
- No overlap with DHL Express surfaces under review here
- Lowest-risk remaining gap closure

**Recommendation:** UI-GAP-1.1 is safe to open in a fresh session.
It does NOT depend on the F-1 / F-3 copy fixes being addressed
first.

---

## 8. W-2.3b — remains deferred?

**Yes — W-2.3b remains correctly deferred.**

Rationale (re-confirmed):
- create_shipment payload requires full `_ShipmentRequestPayload`
  (ship_from + ship_to + packages list + service_code + reference
  + optional customs_*) — that's a form, not a confirm drawer.
- The W-2 PRE-IMPL artifact (`34a2691`) and the operator's Option
  A choice (W-2.3 session) recorded this explicitly.
- The gap audit (`0bb10d3`) confirms W-2.3b as its own future
  campaign, NOT a sub-phase of UI-GAP-1.x.

No operational evidence collected since UI-GAP-1.3 changes this.
Sandbox shadow has not opened yet; the carrier UI's actual use
under operator scrutiny is not yet known.

**W-2.3b opens only when:**
- Either the gap audit's UI-GAP-3.6 phase opens explicitly, OR
- Operator decides shipment-creation-from-dashboard is the
  blocking workflow gap based on real evidence.

Until then: existing batch-creation flow remains the
shipment-creation path. The proposal panel correctly surfaces
this as info-only.

---

## 9. Recommended micro-phase before next gap closure

The two **P1** copy fixes (F-1 + F-3) are a single tiny commit
that takes operator-confusing text out of the UI before more
features pile on top. Lower priority than UI-GAP-1.1 in
mechanical terms, but higher priority operator-experience-wise.

Suggested phase identifier: **UI-2c-copy** (a copy-only micro-phase,
not in the original UI-GAP roadmap because the bug only surfaces
now that W-2.3 has shipped).

| Field | Value |
|---|---|
| Mode | IMPLEMENTATION (single code lane) |
| Scope | UI-2c-copy — fix stale carrier-overview-mode-note + soften W-2.3b operator-facing references |
| Touches | `service/app/static/dashboard.html` (~6 lines) + 1 new test file |
| Forbidden | every other surface |
| Effect | F-1 + F-3 closed; operator copy aligned with reality |

**This phase is OPTIONAL** — UI-GAP-1.1 can open first. The
operator decides priority.

---

## 10. Final recommendation

```
═══════════════════════════════════════════════════════════════════
  DHL EXPRESS OPERATOR UI REVIEW — recommendation
  Date:     2026-05-10
  Baseline: 1a8b46d
═══════════════════════════════════════════════════════════════════

  DHL Express UI surfaces in scope:           5
    S-1  overview (W-2.1 + W-2.1a)
    S-2  shipment drill-down (W-2.2)
    S-3  proposals panel (W-2.3 read)
    S-4  confirm drawer (W-2.3 write)
    S-5  shadow log (UI-GAP-1.3)

  Tests pinning these surfaces at HEAD:        245 / 245 green
  Full dashboard suite at HEAD:                1336 / 1336 green
  make verify at HEAD:                         160 / 160 green

  Safety review:
    9 things working (OS-OK-1..9)
    4 gaps (OS-GAP-1..4); only OS-GAP-1 is P0 — mode banner
                          (G-2 / W-2.6 territory)

  Confusing copy found:
    F-1  P1  stale carrier-overview-mode-note (says actions
              not available; W-2.3 shipped them)
    F-3  P1  proposal-create info-note + disabled-badge reference
              internal "W-2.3b" phase code
    F-4  P2  shadow log diff-outcome jargon (low impact)

  Missing information:    8 enrichment opportunities catalogued
                          (MI-1..8); none blocking.

  UI-GAP-1.1 readiness:   YES — can open in a fresh session.
                          Different tab (DHL / Customs); no
                          overlap with the DHL Express surfaces
                          under review here.

  W-2.3b deferral:        REMAINS DEFERRED — correct.
                          Re-confirmed by gap audit (P3) and by
                          the W-2 PRE-IMPL artifact's Option A
                          rationale.

  Recommended next phases (operator picks):

  α  UI-2c-copy (copy-only micro-phase)        — closes F-1 + F-3
        single tiny commit; ~6 lines of copy; one new test file;
        highest operator-experience impact for least risk.
        Recommended FIRST.

  β  UI-GAP-1.1 — agency SAD decision read     — closes G-11
        single commit; new read-only card under DHL / Customs
        tab; lowest-risk remaining gap closure.

  γ  Pause for real operator evidence on the DHL Express tab.
        Five surfaces just landed in fast succession (overview,
        timeline, label evidence, proposal drawer, shadow log).
        Real operator review may surface friction not
        captured here.

  δ  UI-GAP-1.2 / 1.4 (DSK audit log / wFirma capabilities) —
        lower-priority read-only gap closures.

  ε  ADR-018 draft (Lane-A doc-only) — required only before
        UI-GAP-3.7 (mode banner / W-2.6). Independent of
        everything above.

  Stabilization-window posture
  ----------------------------
  Cell remains at rest at 1a8b46d. The DHL Express tab now has
  enough functional surface that real operator review can
  produce meaningful evidence. Recommendation: open α (the
  copy micro-phase, ~6 lines) only if the friction matters in
  the next operator review session; otherwise pause and
  collect evidence first.

═══════════════════════════════════════════════════════════════════
```

## Self-review

- **What this review catches:** one P0 finding already on the
  roadmap (mode banner = G-2 / W-2.6) and two P1 copy bugs that
  only became visible after W-2.3 shipped. The stale mode-note
  copy is a *regression of accuracy* — the dashboard tells the
  operator actions don't exist that DO exist. That's worth
  fixing before more surfaces add to the noise.
- **What this review deliberately does not decide:** whether
  the operator's next session should open α, β, γ, or none.
  Five surfaces just landed in five commits over four weeks of
  campaign work. The next move is **operator's choice** based on
  what they want to validate first.
