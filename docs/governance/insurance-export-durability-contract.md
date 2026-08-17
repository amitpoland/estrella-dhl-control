# Insurance Export — durability contract

**Status:** binding · **Recorded:** 2026-08-17 · **Baseline release:** `2f04ae1c20ae17cfa72765df76ea3db59268f415`

The Insurance Export statement took five releases to reach its current figures
(#1256, #1258, #1259, #1262/#1263, #1264). Only some of that was application
defect. This document exists so the same ground is not re-walked: it names what
is now pinned by tests, what is a completed migration that must never re-run,
and what the release procedure must prove before a statement release can be
called closed.

Nothing here is new machinery. It is a contract over machinery that already
exists.

---

## 1. The authority map (read this before any fix)

```
issued wFirma document
        │
        ▼
CommercialChargeAuthority ──► commercial_charges.db      (recovered premium)
        │
        │        india_official_fx ──┐
        │        nbp_rate_service ───┴──► insurance_fx_provider   (FX)
        ▼                                        │
        └────────────► insurance_export_statement.py ◄┘
                                 │  canonical projection
                    ┌────────────┴────────────┐
                    ▼                         ▼
   insurance_export_pdf_renderer.py    insurance-export-tab.jsx
```

Four rules follow from the picture, and every one of them is a test:

1. **`insurance_export_statement.py` is the only place a monetary value is
   produced.** Both renderers print strings the projection already resolved.
2. **`insurance_fx_provider` is the only FX authority.** The statement service,
   the routes and the PDF renderer may not reach NBP; the JSX may not derive a
   cross rate. PLN is `INR/PLN = INR/USD ÷ PLN/USD` — India official leg over
   the NBP USD bridge leg, both disclosed in `fx_provenance`.
3. **Calculation value and display value are different fields.** `fx_rate` is
   the arithmetic authority (a PLN cross rate carries 26 fractional digits);
   `fx_rate_display` is serialization-only at 4 dp. **`fx_rate_display` is never
   an arithmetic input.** `sum_insured_inr = sum_insured × fx_rate`.
4. **A recovered premium comes only from an issued document.** A draft or
   proforma is pre-issue intent and may never be a fallback source. A recorded
   `0.00` is a *proven* answer (`charge_authority_on_record: true`); *no record*
   is an unknown, counted by `insurance_recovered_rows_without_authority`.

---

## 2. What is pinned, and where

| Invariant | Pinned by |
|---|---|
| Whole-report projection: reason present on every `needs_review` row; 4-dp display rate on every rated row; no INR value derivable from the display rate; four-way total identity; missing rate disclosed, never folded in as zero; `rows_without_authority` counts exactly the unconverged rows; recovered totals are per-currency | `service/tests/test_insurance_export_projection_contract.py` |
| Display/arithmetic separation at the field level | `service/tests/test_insurance_export_presentation.py` |
| Renderers never do money maths: no `*` `/` `float` `round` on Decimal in the PDF; the PDF's one aggregation is `+` over already-quantized `sum_insured_inr`; the three footer totals read `declaration_totals`; exactly one money formatter per renderer, no locale formatting; no FX arithmetic or cross-rate derivation in the JSX; NBP reachable from the FX boundary only | `service/tests/test_insurance_export_no_recomputation.py` |
| A draft is never a second source for the premium | `test_the_draft_is_never_a_second_source_for_the_premium` |
| The published production figures themselves | `service/tests/test_insurance_export_production_smoke.py` + `service/tests/fixtures/insurance_export_production_pins.json` |

**The four-way identity**, stated once so it is not re-derived:

```
Σ row.sum_insured_inr  ==  Σ contractor.subtotals.sum_insured_inr_documents
                       ==  report_totals.sum_insured_inr_documents
                       ==  kpi.gross_insured_inr
```

and the grand line likewise ties group subtotals to
`report_totals.sum_insured_inr_grand` and `kpi.net_insured_inr`.

**Why the PDF's group subtotals are not the report's.** The PDF renders an
operator *declaration selection*, not the whole report; adjustments enter it
through `_totals_for(automatic=False)`, while report group subtotals are
filtered by `_AUTOMATIC_EFFECTS`. The two are different questions and are
*supposed* to differ. Asserting them equal would pin a falsehood — so what is
pinned instead is that the PDF only sums authority-quantized strings and takes
its footer totals from the backend.

### The production pins are a closure gate, not unit coverage

`insurance_export_production_pins.json` holds figures **measured** from
production on 2026-08-17, including the three rows that cost the most to get
right: WDT 153/2026 = EUR 56.98, WDT 156/2026 = USD 10.00, and WDT 155/2026 =
USD **0.00 proven** (`no_insurance_charged`, authority on record — the value
that must never regress to unknown). `362.39` is listed as a forbidden
recovered amount: it was draft-derived and no issued document supports it.

A pin changes **only when the underlying business fact changes** — a corrected
invoice, a newly converged premium. Editing a pin so a run goes green is the
exact failure the file exists to prevent.

---

## 3. Completed migration — do not re-run

The historical commercial-charge convergence (2020–2026 backbill) is **COMPLETE**.

- **Applied:** 2026-08-17, operator-authorized, Jan–Aug scope.
- **Result:** 202 CommercialChargeAuthority records; `rows_without_authority`
  202 → 0; recovered EUR 1879.09 / USD 778.36; period totals unmoved.
- **Idempotency proven:** second run inserted 0, left 202 unchanged.
- **Tool:** `service/app/tools/converge_commercial_charges.py` — an explicit
  operator CLI, never a startup or scheduler path.

Three properties keep it from re-running by itself, and they are code, not
convention:

1. `commercial_charge_convergence.run_scheduler_tick()` returns `None`
   immediately when `settings.commercial_charge_convergence_apply_enabled` is
   false — no unattended run at all, not even a dry pass.
2. That setting **must not exist** in `.env`, Process, User, Machine or NSSM
   environment. It is a per-invocation, process-scoped arming flag for the CLI
   and nothing else. It never becomes a persistent production setting.
3. When the flag *is* armed, the scheduler window is two months with a 6h
   cooldown (`wfirma_webhook_scheduler._run_charge_convergence_tick`): "a
   scheduler never re-reads six years of documents."

**No further CommercialChargeAuthority financial write is authorized.** A new
historical apply needs a fresh, explicit financial-write approval. The existing
202 records are not rewritten by refactors, tests, or durability work.

The UI states this rather than hiding it: the convergence panel reads
*"Automatic — off · authority populated"*. Off is the correct steady state, and
the operator is told why.

---

## 4. Human-only boundaries — classify at campaign start

Two controls in this repository are operator-only by design, both fail-closed
in the deploy guard:

| Boundary | Guard rule | Who |
|---|---|---|
| GitHub merge (`gh pr merge`) | `gh-pr-merge` | operator |
| Production release (`Deploy-PZ.ps1`, `-WhatIf` included) | `deploy-script-invocation` | operator |

These are not friction to route around. `PZ_AUTONOMOUS_MERGE_ENABLED` is not
armed, and signed autonomous merge governance does not exist yet.

**The procedure.** Classify the campaign at its start, before any code is
written, using the operating mode already defined in `CLAUDE.md`:

- **Mode 2 (test-only / docs-only)** — one boundary: the merge. No gate, no
  deploy. *This document's own PR is mode 2.*
- **Mode 1 (runtime change)** — two boundaries: merge, then release. Plus the
  seven-agent gate before either.

State the boundaries in the opening message of the campaign. When one is
reached, hand the operator **one consolidated command** — not a checklist, not
a running commentary — and then continue the rest of the campaign
automatically. Re-running phases that were already solved because the session
paused at an operator boundary is the failure this rule exists to stop.

---

## 5. Post-production acceptance — mandatory closure

A deployment is not closed when the sync finishes. It is closed when these pass,
in order:

1. **Identity** — `C:\PZ\version.txt` == deploy `HEAD` == `origin/main`.
   (Post-merge SHA, not the gated head: `Invoke-ReleaseFlow` resolves its target
   from `origin/main`.)
2. **Parity (Lesson P)** — content hash diff between `C:\PZ\app` and the source
   `service/app`: missing 0 / extra 0 / content 0. robocopy's copied-file count
   is not the blast radius; content is.
3. **Health** — local `http://127.0.0.1:47213/api/v1/health` 200 and public
   `https://pz.estrellajewels.eu/api/v1/health` 200. *A 403 on the public probe
   from `Python-urllib` is Cloudflare blocking the UA — send a browser
   User-Agent + `X-API-Key`. It is not a deploy defect.*
4. **Startup logs** — clean; no import error, no scheduler exception.
5. **Business smoke** — the step that makes the rest mean something:

```
set PZ_SMOKE_BASE_URL=http://127.0.0.1:47213
set PZ_SMOKE_API_KEY=<service API key from C:\PZ\.env — never printed, never committed>
pytest service/tests/test_insurance_export_production_smoke.py -v
```

Read-only: one GET per pinned period, no writes, no convergence. Steps 1–4 prove
the right bytes are running. Step 5 proves the statement still publishes the
figures the business signed off. **A release that skips step 5 is not closed** —
generic unit tests passing on a refactor is precisely the case this catches.

---

## 6. On failure — no additive patch

When a pin breaks, the reflex to add a compensating adjustment is wrong. The
symptoms this surface produced — a PLN row with no rate, a recovery that
appeared and vanished, a "needs review" with no reason, a 26-digit rate on
screen — were **five different authority gaps**, and every one of them would
have accepted a patch that made the symptom go away.

The order is fixed:

1. **Read §1 first.** Which authority owns the broken value?
2. **Fix it at that authority.** Not at the renderer, not at the caller, not
   with a fallback. If the PDF and the screen disagree, one of them acquired a
   second monetary authority — remove it; do not reconcile it.
3. **A fallback that substitutes one authority for another is the defect**, not
   the fix. Draft-for-issued, display-rate-for-full-rate, NBP-for-India: each is
   a duplicate authority wearing a fallback's clothes.
4. **If duplicate authority has genuinely returned, stop patching and open a
   replacement/convergence campaign.** Converging the data and deleting the
   second authority is the smaller total change than maintaining both.

Financial scope, unchanged and binding: no wFirma POST/edit/delete; customs,
warehouse, inventory, AWB and accounting ledgers off-limits; no historical apply
without new explicit financial-write approval.

---

## Reference

- `service/app/services/insurance_export_statement.py` — the projection
- `service/app/services/insurance_fx_provider.py` — the FX boundary
- `service/app/services/commercial_charge_convergence.py` — the disarmed gate
- `docs/governance/AUTHORITY_MAP.md` — repository-wide authority registry
- `CLAUDE.md` § OPERATING MODEL — operating modes, the seven-agent gate, Lesson P
- PRs #1256, #1258, #1259, #1262, #1263, #1264 — how each invariant was learned
