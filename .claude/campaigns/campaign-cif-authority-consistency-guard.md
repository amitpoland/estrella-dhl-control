# Campaign Brief — Single Resolved-CIF Authority Across All Customs/PZ Action Gates

**Status:** Implemented — PR [#643](https://github.com/amitpoland/estrella-dhl-control/pull/643) open (branch `feat/cif-authority-consistency-guard`, HEAD `b6787a1`, impl commit `20d6a0c`)
**Date:** 2026-06-17
**Authority record:** ADR-030 · Scorecard `2026-06-17-cif-authority-consistency-guard.md`
**Scope class:** customs/financial-adjacent · backend gate + governance + tests (no UI refactor, no wFirma/SAD/VAT posting changes)
**Predecessors:** PR #627 (`cif_resolver` tri-state) · PR #631 (upload e2e) · PR #633 (UI + Polish-description gate)

---

## 1. Executive summary

A shipment's customs CIF value can be produced by six different layers (engine-verified invoice CIF, parsed invoice CIF/FOB, DHL pre-check totals, carrier-declared AWB Custom Val). Historically each customs-adjacent endpoint decided independently which field to trust, and several keyed directly off the raw parsed invoice CIF. When invoice parsing failed it collapsed that field to `0`, and the fake zero flowed downstream as if it were a real declared value — falsely blocking shipments that were fully routable from another layer. PR #627 fixed the *resolution* with a tri-state resolver (`resolved` / `declared_zero` / `unknown`, never a fabricated `0.0`) and PR #633 wired the UI and Polish-description gate to it, but DSK generation, the customs package, the agency routing-pending message, and the action-proposal routing gates still made independent or raw-zero decisions. This campaign closes that gap with a single shared action-layer gate — [`cif_authority.py`](service/app/services/cif_authority.py) exposing `get_cif_authority()` (pure read) and `require_resolved_cif()` (the block) — and wires every remaining customs/PZ/DHL action through it, so the resolved CIF is now the one customs-value authority and raw invoice fields are demoted to advisory evidence everywhere.

---

## 2. Architecture map

```
                         audit.json  (shipment record)
                               │
                               ▼
              cif_resolver.resolve_cif(audit)          ◄── PR #627, unchanged
              ──────────────────────────────
              6-layer authority ladder (USD only):
              1 verification.invoice_cif_total_usd
              2 invoice_totals.total_cif_usd
              3 invoice_totals.total_fob_usd
              4 dhl_precheck.invoice_cif_total_usd
              5 dhl_precheck.fob_total_usd
              6 awb_customs.value_usd
              → { cif_usd, cif_state, cif_source,
                  attempts[], extraction_gap }
                               │
                               ▼
        ┌─────────────  cif_authority.py  (NEW — this campaign)  ──────────────┐
        │  get_cif_authority(audit)   → flat decision dict (pure, never raises) │
        │  require_resolved_cif(...)  → returns on RESOLVED, else raises        │
        └───────────────────────────────────┬──────────────────────────────────┘
                                             │
       ┌──────────────────┬──────────────────┼──────────────────┬───────────────────┐
       ▼                  ▼                  ▼                  ▼                   ▼
routes_dhl_clearance   routes_dsk       routes_agency   routes_action_proposals  routes_dashboard
 generate_description  generate_dsk     routing_pending  G6b/G7b routing gate     action_diagnostics
 generate_customs_pkg                   message                                   generate_dsk button
   [require_…]          [require_…]       [get_…]          [get_… + decision]       [get_… is_resolved]
   BLOCK on !RESOLVED   BLOCK / override  honest reason    BLOCK route on           enable iff RESOLVED
                                                            UNKNOWN+DECLARED_ZERO
```

**State → gate behaviour matrix:**

| `cif_state`     | resolver `cif_usd` | `require_resolved_cif` (DHL desc, customs pkg, DSK) | action-proposal routing gate (G6b/G7b) | dashboard DSK button |
|-----------------|--------------------|-----------------------------------------------------|----------------------------------------|----------------------|
| `resolved`      | positive float     | **returns** (action proceeds)                       | **allows** route selection             | **enabled**          |
| `unknown`       | `None`             | **422** `code=cif_unresolved` + extraction gap      | **409** "unresolved … cannot route"    | disabled (gap reason)|
| `declared_zero` | `0.0`              | **422** `code=cif_declared_zero` (operator review)  | **409** "declared zero … review"       | disabled (review)    |
| (resolved but ≤0 — contract violation) | n/a | **500** `cif_resolved_contract_violation` (fail loud) | n/a (decision value used directly) | disabled |

The only authority that may proceed against a customs value is RESOLVED. Both `unknown` and `declared_zero` block, but with *distinct* machine codes so callers branch on the reason, not prose.

---

## 3. Changes by ownership

### `service/app/services/cif_authority.py` — **NEW**
The single deliverable everything else depends on. Two functions over `cif_resolver.resolve_cif`:
- `get_cif_authority(audit)` (L56) — pure, never raises, never mutates. Returns a flat dict mirroring the frontend `getResolvedCifAuthority` field set: `cif_usd`, `cif_state`, `cif_source`, `invoice_cif_parsed`, `invoice_cif_advisory`, `is_resolved`, `is_blocked`, `blocker_reason`, `extraction_gap`. The raw invoice CIF is surfaced for display and flagged `invoice_cif_advisory=True` whenever it is present but not the winning source (L103–106).
- `require_resolved_cif(audit, *, action=...)` (L134) — the gate. Returns the dict on RESOLVED; raises `HTTPException(422)` with `code=cif_declared_zero` or `code=cif_unresolved` otherwise. A RESOLVED state carrying a non-positive value raises **500** (`cif_resolved_contract_violation`, L168–182) rather than silently re-routing to the "unresolved" message — a resolver fault fails loud instead of masquerading as an extraction gap.

### `service/app/api/routes_dhl_clearance.py` — wired
`generate_description` (L3057, `action="a Polish customs description"`) and `generate_customs_package` (L3446, `action="a customs description package"`) now gate through `require_resolved_cif(audit, …)`. Removes the legacy raw-CIF==0 hard block that false-blocked AWB-only-resolved shipments.

### `service/app/api/routes_dsk.py` — wired + audit
`generate_dsk` (L172–192) derives `value_usd` through the full authority ladder via `require_resolved_cif` instead of the two-layer invoice-only check. An explicit payload `value_usd` is respected as the operator's own authority (`value_source="payload"`), but because that path *bypasses* the gate, the override now leaves an audit trace: the `EV_DSK_GENERATED` timeline event records `value_source` and `value_override` (L266–278), making an operator override distinguishable from an authority-derived value.

### `service/app/api/routes_agency.py` — honest message
The `routing_pending` branch (L121–146) previously reported "invoice CIF is 0". It now reads `get_cif_authority`, surfaces the resolver's honest `blocker_reason` and `extraction_gap.next_action`, and raises with `code=clearance_path_unresolved` and the real `cif_state`/`cif_source`. No routing change — only the diagnostic message is corrected.

### `service/app/api/routes_action_proposals.py` — `or 0` silent-zero removed
The G6/G7 value gate (L323–344) now prefers the persisted `clearance_decision.total_value_usd` when present (the routing the operator is bound to), using it directly — **not** `_dec_cif or 0`, which would re-collapse a legitimate `0.0` decision into the silent zero the gate exists to stop. When no decision value exists it derives from `get_cif_authority`. Legacy decision objects predating the `cif_state` field are normalized by inference (L333–340): a positive routed value → `resolved`; a non-positive legacy value → `unknown` (block). The G6b/G7b guard (L352–355) then blocks `carrier_description_reply` and `dhl_dsk_transfer` with a **409** on both `UNKNOWN` and `DECLARED_ZERO`.

### `service/app/api/routes_dashboard.py` — button-state authority
`action_diagnostics` (L1623–1639) computes the `generate_dsk` button's enablement from `get_cif_authority(...).is_resolved`, not raw `invoice_totals.total_cif_usd`. This fixes the mirror-image false-*disable*: a shipment whose CIF resolves only from the AWB Custom Val was incorrectly showing the DSK button greyed out. A `try/except` fallback to the old raw-CIF check (L1633–1639) keeps the diagnostic resilient if the helper ever errors.

### `.claude/adr/ADR-030-*.md` + README index — **NEW**
Records the decision, the four rejected alternatives, the risk that `declared_zero` now blocks previously-slipping shipments (intended), and the rollback (additive helper; revert restores prior inline logic; `cif_resolver`/`clearance_decision` untouched).

---

## 4. Integration boundaries

`cif_authority.py` is the **action-layer companion** to `cif_resolver.py`. The boundary is deliberate and one-directional:

- **`cif_resolver.resolve_cif`** owns *resolution*: "what is the customs CIF and how confident are we?" — pure, the 6-layer ladder, tri-state, never raises. Unchanged by this campaign.
- **`cif_authority`** owns *decision shape*: it turns the resolver's answer into (a) a flat read dict every surface shares and (b) a uniform block contract. It performs **no** audit writes, **no** mutation, and **no** `0.0` fabrication.
- **Each endpoint** keeps what is genuinely its own: HTTP response structure, the `action` label woven into the error, route auth guards, and any non-CIF preconditions (attachment existence, batch-id match, draft validation). What endpoints no longer own is *which field is the customs value* and *what a non-resolved value means*.

**Contract:**
- **Input:** `audit: dict` (the shipment audit record). Tolerates `None`/empty (returns a blocked/unknown decision).
- **States returned:** `resolved` (positive `cif_usd`), `declared_zero` (`cif_usd == 0.0`), `unknown` (`cif_usd is None`).
- **Errors raised** (only by `require_resolved_cif`): `422 cif_unresolved`, `422 cif_declared_zero`, `500 cif_resolved_contract_violation`. `get_cif_authority` never raises.
- **Machine codes** are stable; `cif_unresolved` is byte-identical to the code PR #633 shipped on the Polish-description route, so existing clients/tests are unaffected.

---

## 5. State machine and gate behaviour

The three states and the AWB **2315714531** worked example:

- **RESOLVED** — a positive USD value won at some ladder layer. Every gate proceeds. For 2315714531 the invoice CIF is `0` (parser miss) but layer 6 (`awb_customs.value_usd = 732`) wins → `cif_state=resolved`, `cif_usd=732.0`, `cif_source=awb_customs.value_usd`.
- **UNKNOWN** — no layer produced a positive value and there is no explicit zero signal. `cif_usd=None`, plus an `extraction_gap` naming the first failed layer and the operator's next action. Blocks safely; never a zero.
- **DECLARED_ZERO** — the source *explicitly* declares zero (operator-set `customs_declared_value_zero`, or an AWB Custom Val field that parsed a literal `0` with no gap, USD). `cif_usd=0.0`. Blocks pending explicit operator review — a genuine no-commercial-value shipment is real, but auto-generating a customs/PZ document against zero without review is a compliance hazard.

**The bug, concretely:** the legacy `generate_description` route and the action-proposal gate used `cif = something or 0`. For 2315714531 that produced `0`, which the route hard-blocked as "CIF = 0.00" — directly contradicting the clearance-routing layer, which had already resolved 732 and routed the shipment. The same `or 0` in the proposal gate let *both* routing branches bypass their threshold guards on a fake zero. **The fix:** no surface reads a raw field or applies `or 0`; the value comes from the resolver, `unknown`/`declared_zero` block with distinct codes, and a positive resolved value (732) lets the action through.

---

## 6. Test coverage

Fifteen new test functions; the broad regression filter nets **+13 passing** over the clean baseline (targeted suites: **73 passed**).

**`test_cif_authority.py` (11) — helper + gate + DSK route + source contract:**
1. `test_get_authority_resolved_from_awb` — AWB-only resolution → `is_resolved`, source `awb_customs.value_usd`.
2. `test_get_authority_unknown_is_blocked_with_reason_not_zero` — unknown → blocked, `blocker_reason` set, `cif_usd is None` (never 0).
3. `test_get_authority_declared_zero_is_blocked_pending_review` — declared-zero → blocked with review reason.
4. `test_get_authority_never_raises_on_empty_audit` — purity/`None`-safety.
5. `test_require_returns_on_resolved` — gate passes through on RESOLVED.
6. `test_require_blocks_unknown_with_cif_unresolved_code` — 422 + `cif_unresolved`.
7. `test_require_blocks_declared_zero_with_distinct_review_code` — 422 + `cif_declared_zero` (distinct from unknown).
8. `test_dsk_generate_resolves_from_awb_value` — DSK route end-to-end resolves from AWB.
9. `test_dsk_generate_blocks_unknown_cif` — DSK route blocks unknown.
10. `test_dsk_generate_respects_explicit_payload_override` — operator payload value honoured.
11. `test_customs_routes_use_shared_authority_helper` — **source-grep contract**: asserts the DHL routes reference `require_resolved_cif(audit` (drift guard against a future surface re-deriving the gate).

**`test_action_proposals.py` (2) — routing-gate negative cases:**
12. `test_declared_zero_blocks_routing_dependent_proposal` — `clearance_decision{total_value_usd:0.0, cif_state:"declared_zero"}` → 409, asserts "declared zero" in detail.
13. `test_legacy_decision_without_cif_state_blocks_routing` — a legacy decision object (`total_value_usd:0.0`, **no** `cif_state`) is treated as UNKNOWN → 409. Pins the legacy-missing-`cif_state` normalization decision: a missing tri-state is never an implicit pass.

**`test_dashboard_actions.py` (2) — DSK button regression:**
14. `test_generate_dsk_enabled_when_cif_resolves_from_awb` — the 2315714531 shape (invoice CIF 0, AWB 732) → button `enabled: True`, reason "Ready — CIF value available". This is the regression test for the false-disable.
15. `test_generate_dsk_disabled_when_cif_unresolved` — genuinely unresolved (no invoice total, AWB gap) → `enabled: False`, reason ≠ "Ready …" and always non-empty.

The `test_polish_desc_cif_resolved_gate.py` suite was updated (not added) to assert shared-helper wiring.

---

## 7. Production safety

Guard-rails in place:
- **Read-only helper, pure functions.** `get_cif_authority` and `resolve_cif` never write, never mutate the audit, never fabricate `0.0`. The dashboard button derivation is write-free.
- **Tri-state, not boolean.** `unknown` ≠ `declared_zero` ≠ `0`. The original class of bug — a parser-miss zero treated as a real value — is structurally impossible: a missing value is `None`, and only an *explicit* source signal yields `declared_zero`.
- **Honest blocking with machine codes.** `422 cif_unresolved` (extraction gap + next action) and `422 cif_declared_zero` (operator review) replace silent pass-through and misleading "CIF = 0" prose.
- **Fail-loud on contract violation.** A RESOLVED state with a non-positive value raises `500` rather than degrading to a misleading message — surfaces a resolver fault instead of hiding it.
- **Override auditability.** The DSK payload override leaves a timeline trace (`value_source`/`value_override`), so a human-supplied value is never indistinguishable from an authority-derived one.

**Operational risk reduced:** customs/PZ documents can no longer be generated, and DHL clearance actions can no longer be routed, against a fabricated zero customs value. Both the false-block (resolvable shipment refused) and the silent-bypass (unresolved shipment auto-routed) failure modes are closed by the same single authority. This is customs-adjacent correctness: a wrong customs value on a generated document is a compliance exposure, not a cosmetic defect.

---

## 8. Technical debt and open questions

- **`routes_dhl_documents.py` findings — out of scope, filed.** Two HIGH/MED findings surfaced during review on a file this PR does not touch were filed as separate issues rather than folded into this customs PR (Lesson I — incidents become workflow-class rules, never PR-scope creep): [#641](https://github.com/amitpoland/estrella-dhl-control/issues/641) (server-side path / attachment exfil, HIGH) and [#642](https://github.com/amitpoland/estrella-dhl-control/issues/642) (false `received=True` when all paths missing). Both are genuine; neither is a CIF-authority concern.
- **Dashboard extraction-gap detail wording.** For an unknown CIF the disabled-button reason surfaces the resolver's raw `blocker_reason` (e.g. "AWB Custom Val present but parser flagged an extraction gap"). The test pins only that it is non-empty and not the "ready" text; the exact operator-facing phrasing is left to UI polish and is intentionally not asserted verbatim.
- **`routes_dsk` value derivation `body.value_usd or 0.0`** (L180) treats an explicit payload `0` as absent → derive/block rather than as a declared zero. This is "safe by accident" but the safer behaviour (an explicit 0 is not a usable override) — left as-is by design.
- **Pre-existing repeated-weak flag — `test-coverage-reviewer`** (severity inflation, from the 2026-06-12 scorecard) remains open; this campaign did not dispatch that agent, so the flag carries forward for a future direct dispatch to assess calibration.

---

## 9. Deployment and verification

1. **Merge.** Operator reviews and merges PR #643 (GATE 2 had a free slot at open; concurrent PRs were #637 docs, #630 impl).
2. **Deploy gate.** Production sync runs the full 7-agent deploy gate. The diff is `service/app/**` only (standard robocopy → `C:\PZ\app`); no root-engine files, no schema changes. Prod write is operator-only.
3. **Verify the fix on the canonical fixture.** After deploy, confirm AWB **2315714531** no longer returns `total_value_usd=0.0` on the customs/DSK action surfaces — the DSK button enables, `generate_description`/`generate_customs_package` proceed, and the resolved value reads `732` from `awb_customs.value_usd`.
4. **Confirm no regression for unresolved shipments.** A shipment with no invoice total and no AWB Custom Val must still block with `cif_unresolved` and a visible next action — not silently proceed on a zero.

**Rollback:** revert the PR. The helper is additive; the wired call sites revert to prior inline/raw logic; `cif_resolver` and `clearance_decision` are untouched, so no resolution or routing behaviour changes on rollback. The only consequence is the raw-zero false-block returns for AWB-only-resolved shipments.
