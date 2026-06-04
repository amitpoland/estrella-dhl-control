# Atlas Pro Forma — Add Draft Proforma + Manual Convert to Invoice (wFirma-style)

**Two-phase task.** Phase 1 is investigation only, no code. Phase 2 fires only after Amit approves the Phase 1 report.

**Scope**: Pro Forma surface inside the Shipment detail page. Builds on the drilldown redesign already specified in `ATLAS_PROFORMA_DRILLDOWN_REDESIGN.md` — that redesign is the layout baseline this task extends.

**Reference UX**: wFirma invoice detail view. Calm three-card top region, single action toolbar, tab strip, flat key-value grid. Borrow the structure, not the chrome.

---

# PHASE 1 — Investigation Report

**Task type**: investigation only. No code changes. No PRs. No file edits. Output is a single markdown report.

## 1.1 What to investigate

Read and report on the following files. For each, extract the relevant routes, models, services, and current behaviour. Use file:line citations for every claim.

### Backend

- `service/app/api/routes_proforma.py` — proforma draft lifecycle endpoints
- `service/app/api/routes_wfirma*.py` — all wFirma write routes (proforma create, customer create, product create, convert-to-invoice)
- `service/app/services/wfirma_proforma_*.py` — proforma writer service (live + shadow if present)
- `service/app/services/wfirma_invoice_*.py` — invoice writer / converter (if exists as separate module)
- `service/app/db/models/proforma_draft*.py` or wherever the `proforma_drafts` table is defined — full schema, all columns, all foreign keys
- `service/app/db/models/wfirma_write_audit*.py` — audit row schema
- Any migration files that touch `proforma_drafts` or `wfirma_write_audit`
- Tests under `service/tests/` matching `*proforma*`, `*wfirma_proforma*`, `*convert*invoice*`

### Frontend

- `service/app/static/dashboard.html` — current Pro Forma surface (search for `Pro Forma`, `proforma`, `Convert Proforma to Invoice`, `Create Reservation`)
- Any React/JSX component files under `service/app/static/components/` or equivalent that render the Pro Forma surface — there may be both legacy HTML and newer React; report which is currently rendered in production
- Wire layer: where does the frontend call to create/post/convert? Document the fetch/axios calls and their endpoints

## 1.2 Questions Phase 1 must answer

Answer each with VERIFIED (file:line) / INFERRED (reasoning) / NO EVIDENCE. Do not guess.

### A. Draft proforma creation — current state

1. Is there a "create blank draft" endpoint, or are drafts only auto-synced from packing list?
2. If a clone-from-source endpoint exists, what's the route and what does it accept as input (shipment_id, packing_list_id, existing_draft_id)?
3. What columns does `proforma_drafts` have? List every column with type and nullable status. Specifically confirm presence/absence of: `id`, `shipment_id`, `client_name`, `wfirma_customer_id`, `doc_number`, `version`, `status`, `source_type` (auto/clone/manual), `source_ref_id`, `currency`, `lines` (JSON or separate table?), `created_at`, `updated_at`, `created_by`, `last_post_error`, `wfirma_proforma_id`, `wfirma_invoice_id`, `idempotency_key`.
4. Are line items stored as JSON inside `proforma_drafts`, or in a separate `proforma_draft_lines` table? If separate, full schema.
5. What "source" entities could a clone-from-source draft pull from? Candidates: another `proforma_draft`, a packing-list row, a previous wFirma proforma fetched into cache, a previous wFirma invoice. Report which exist in the DB and which currently power any draft creation logic.

### B. Convert proforma to invoice — current state

6. What is the exact endpoint that converts a proforma draft to a wFirma invoice? (PR #78 / spec audit suggests it exists as "Detail Sales → Convert" but the rollback path was flagged "unclear — escalate to manual".)
7. Is this endpoint currently wired to a UI button? Find the call site in the frontend.
8. Does the conversion currently call wFirma directly, or does it post a proforma first then convert? Document the exact wFirma API call(s) the server makes.
9. Does an `idempotency_key` get generated and stored before the call? Where?
10. Does the audit row write to `wfirma_write_audit` happen pre-call (with a `pending` status) or post-call only? This determines crash-recovery behaviour.
11. What does wFirma return on success, and what gets stored locally (`wfirma_invoice_id`, KSeF number, WDT number)?
12. What is the current behaviour on failure? Is `proforma_drafts.last_post_error` populated? Does an action proposal of type `wfirma_post_retry` get created?
13. Is there any existing "preview payload before posting" capability, or does the server just send and hope?

### C. Existing UI affordances

14. Does any current button anywhere in dashboard.html or React components allow creating a draft proforma from scratch or by clone? Find every candidate and report what each actually does on click.
15. Does the current "Convert Proforma to Invoice" button perform the conversion synchronously, async, or is it currently a no-op / disabled / wired to a stub?
16. Is there an existing confirmation modal of any kind in the codebase that displays a JSON/structured payload before submission? (Reusing one beats building one.)

### D. Guard rails and known landmines

17. The capability table notes "rollback path unclear (wFirma may not allow cancel) — escalate to manual." What does the current wFirma client do on a partial-success scenario (e.g. invoice created in wFirma but local DB write fails after)? Search for try/except patterns around the convert call.
18. wFirma rate limits — does the client enforce any throttle on conversion calls?
19. Are there any existing tests for the convert path? Report each test file:line, what it asserts, and whether it covers (a) happy path, (b) wFirma rejects, (c) network timeout, (d) partial success.

### E. Architectural fit with the drilldown redesign

20. The drilldown redesign moves all draft actions to Screen B's action toolbar. The new toolbar will need: `Edit`, `Delete`, `Duplicate`, `Post to wFirma`, `Convert to Invoice`, `Print`, `Send`, `Generate ▾`. For each, what backend endpoint exists today, and what's missing?
21. The new "Add Draft Proforma" entry point — where should it live? The drilldown design has a drafts list (Screen A) with no per-row buttons. The natural place is a primary action button in the Document Suite header strip. Confirm the header strip is currently a passive render or if it already hosts actions.

## 1.3 Phase 1 output format

Single markdown file: `ATLAS_PROFORMA_PHASE1_INVESTIGATION.md`. Sections mirror §1.2 (A through E). Every claim cited. Conclude with three tables:

**Table 1 — Endpoint inventory**:
| Capability | Endpoint | Method | File:line | Status (live/stub/missing) | Has audit | Has idempotency |

**Table 2 — `proforma_drafts` schema**:
| Column | Type | Nullable | Default | Notes |

**Table 3 — Gap analysis for new functionality**:
| New capability needed | Endpoint exists? | UI exists? | Audit wired? | Test coverage | Estimated work |

Two new capabilities:
1. Clone-from-source draft creation
2. Manual convert with payload-disclosure modal

Phase 1 ends. Wait for Amit's approval before Phase 2.

---

# PHASE 2 — Design + Implementation

**Do not start Phase 2 until Amit has reviewed the Phase 1 report and given explicit go-ahead in writing.** Phase 2 may need spec adjustments based on what Phase 1 reveals; do not assume the design below survives contact with the codebase unchanged.

## 2.1 Feature 1 — Add Draft Proforma (clone-from-source)

### Entry point

Primary action button in the Document Suite header strip on Screen A (drafts list):

```
┌────────────────────────────────────────────────────────┐
│ EJ  ESTRELLA JEWELS · DOCUMENT SUITE                   │
│     Pro Forma · Faktura proforma          [+ New Draft]│
└────────────────────────────────────────────────────────┘
```

The `[+ New Draft]` button is the only action on Screen A. No per-row buttons. Disabled state if the shipment has no packing list to clone from (with tooltip explaining why).

### Modal: "New Proforma Draft"

Modal title: `New Proforma Draft`. Single column, no tabs, three steps stacked vertically (not multi-step wizard — all visible at once, scroll if needed).

**Step 1 — Pick source**:

Radio list of source candidates, grouped:

```
SOURCE TYPE
  ◯ Packing list on this shipment           (lists the N packing lines on this shipment, each selectable)
  ◯ Existing draft on this shipment         (lists current drafts: Diamond Point, Verhoeven, Dream Ring, Panakas)
  ◯ Prior proforma from wFirma cache        (search input — type to filter wFirma proforma cache)
  ◯ Prior invoice from wFirma cache         (search input — type to filter wFirma invoice cache)
```

Each option shows a count badge `(N available)`. Disabled with explanation if N=0. Default: `Packing list on this shipment` if any packing line exists, else `Existing draft on this shipment`.

**Step 2 — Edit metadata** (revealed once a source is picked):

Flat key-value grid, same as Overview tab in the drilldown design:

| Client name | Currency | Sale date | Payment terms |
| Lines (preview, read-only count + total) | | | |

Fields pre-fill from the source. Client name is editable as free text but warns "Will not auto-map to wFirma customer" if the typed value doesn't match an existing wFirma customer (debounced lookup). All other fields editable.

**Step 3 — Confirm**:

Single button at the bottom right of the modal:

```
[Cancel]  [Create draft]
```

Click `Create draft`:
1. POSTs to the clone endpoint identified in Phase 1 (or new endpoint if missing — Phase 1 says which)
2. Server creates a row in `proforma_drafts` with `source_type` and `source_ref_id` populated
3. Modal closes
4. Drafts list refreshes
5. Navigate to the new draft's detail page automatically (`/shipments/:id/proforma/:newDraftId`)

### Acceptance — Feature 1

- Operator can create a new draft on any shipment that has at least one cloneable source
- The new draft appears in the drafts list with a `DRAFT` chip and `source: clone` indicator in the row (small muted text under the client name: `cloned from packing line #3`)
- Source provenance is queryable: `GET /api/v1/proforma/drafts/:id` returns `source_type` and `source_ref_id`
- Cancel from the modal makes no DB changes (verify with a "cancel after picking source" test)

## 2.2 Feature 2 — ⚠ Convert Proforma to Invoice (manual, payload-disclosed)

### Where it lives

The `Convert to Invoice` button in the Screen B action toolbar. Per the drilldown spec, the toolbar is:

```
[Edit] [Delete] [Duplicate] [Post to wFirma] [Convert to Invoice ⚠] [Print] [Send] [Generate ▾]
```

The `⚠` glyph stays in the label always — not just when blocked. It signals to the operator that this is the irreversible action, every time, not only when something is wrong. (wFirma uses subtle warning iconography on irreversible actions in their UI; mirror that.)

Button disabled if:
- Draft not yet posted to wFirma as a proforma (`wfirma_proforma_id` is null)
- Reservation tab shows blocking reasons
- Customer Mapping shows `wFirma customer ID` is null
- Any line is missing required fields (Phase 1 names the fields)

Tooltip on disabled state lists the specific blockers, not a generic "not ready".

### Modal: "Convert Proforma → Invoice"

Modal title: `Convert Proforma → Invoice` with the `⚠` glyph in the title bar.

Layout:

```
┌─────────────────────────────────────────────────────────┐
│ ⚠ Convert Proforma → Invoice                       [×]  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ This will create a wFirma invoice and link it to        │
│ this proforma. The invoice cannot be cancelled in       │
│ wFirma after creation — only corrected (Korekta).       │
│                                                         │
│ ─── PAYLOAD ─────────────────────────────────────────── │
│                                                         │
│ Endpoint:     POST /wfirma/invoices/convert             │
│ Source:       PROF 95/2026 (wFirma proforma 18-xyz)     │
│ Customer:     Anastazia Panakova — Zlatnictvo Panaks    │
│                VAT UE: SK1020315978                     │
│ Currency:     EUR                                       │
│ FX rate:      4.2284 PLN (NBP table date 2026-05-10)    │
│ Sale date:    2026-05-11                                │
│ Payment:      przelew, 7 days                           │
│ Total:        405.00 EUR (1712.50 PLN)                  │
│                                                         │
│ LINES (3)                                               │
│   1. Diamond ring 0.5ct — 1 pc — 250.00 EUR            │
│   2. Sapphire pendant — 2 pc — 65.00 EUR each          │
│   3. Gold chain 18k — 1 pc — 25.00 EUR                 │
│                                                         │
│ ─── AUDIT ───────────────────────────────────────────── │
│                                                         │
│ Idempotency key:  prof-95-conv-7a3c (already reserved)  │
│ Audit row:        will be written pre-call as 'pending' │
│ Actor:            Amit Saniya (admin)                   │
│                                                         │
│                                                         │
│              [Cancel]    [⚠ Convert to Invoice]         │
└─────────────────────────────────────────────────────────┘
```

Key properties of this modal:

1. **No "are you sure?"** — the modal *is* the confirmation. The payload disclosure is what makes the operator sure, not a redundant checkbox.
2. **Exact field values, not summaries** — render the actual JSON-equivalent values that will be sent. The operator sees what wFirma will see.
3. **Irreversibility line is sentence one, not buried** — "cannot be cancelled in wFirma" appears above the payload, not as a footnote.
4. **Idempotency key shown** — the operator sees it has been reserved client-side before the call. If they retry after a network failure, this key is reused.
5. **Single confirm button** — labelled `⚠ Convert to Invoice` (same text + glyph as the toolbar button). Not `Confirm`, not `Yes`, not `OK`.

### Behaviour on click

1. Frontend reserves idempotency key (already shown in modal, this is a no-op if the key was pre-reserved)
2. Frontend writes audit row as `pending` with the full payload hash
3. Frontend POSTs to the convert endpoint
4. Server makes the wFirma call
5. **On success**: server updates audit row to `success`, populates `proforma_drafts.wfirma_invoice_id`, returns invoice ID + KSeF number. Modal closes, page refreshes, Overview tab now shows the wFirma invoice ID and KSeF number in the flat key-value grid, chip changes from `PROFORMA POSTED` to `INVOICED`.
6. **On wFirma rejection** (4xx from wFirma): server updates audit row to `failed`, populates `proforma_drafts.last_post_error` with verbatim wFirma response, creates `wfirma_post_retry` proposal in Inbox. Modal closes with a non-blocking toast: `Conversion failed — see Inbox for retry options`. Reservation tab now shows the failure under blocking reasons.
7. **On network timeout / 5xx**: same as wFirma rejection but with the error string `network/server error — wFirma may or may not have accepted`. The operator is instructed in the modal *before* clicking that "if this happens, do not retry — check the Inbox proposal and either confirm with wFirma support or use Adopt Existing".
8. **On partial success** (invoice created in wFirma but local DB write fails after): audit row already has the wFirma response; reconciliation cron picks it up on next pass; operator sees an "Adopt existing wFirma invoice" proposal in Inbox.

This is the "automation fails → manual takeover" contract applied to convert-to-invoice, exactly as the spec mandates for every wFirma write.

### Acceptance — Feature 2

- The button is disabled with a specific tooltip whenever any precondition fails
- The modal shows the exact payload the server will send, byte-equivalent (verifiable by comparing modal display against the actual outgoing HTTP body in dev tools)
- Idempotency key is reserved before the modal opens, displayed in the modal, and reused on retry from Inbox
- Audit row is written pre-call as `pending`, updated to `success` or `failed` post-call
- A "convert proforma → invoice" happy path test exists
- A "convert with wFirma 4xx rejection" test exists, asserting audit row state and Inbox proposal creation
- A "convert with network timeout" test exists, asserting no double-submit if operator retries via Inbox proposal (idempotency key reuse)
- The chip on the draft transitions `PROFORMA POSTED` → `INVOICED` on success, never both at once
- The Overview tab's `Numer KSeF` and `wFirma invoice ID` cells populate within one refresh of success

## 2.3 Drilldown design integration points

This task assumes the drilldown redesign (`ATLAS_PROFORMA_DRILLDOWN_REDESIGN.md`) has landed. If it hasn't, Phase 2 must NOT start — the two designs are coupled. Confirmation in the Phase 1 report: which redesign PRs are merged, and what's the current state of the Pro Forma surface.

If drilldown has landed, the integrations are:

- `[+ New Draft]` button → goes in the Document Suite header strip on Screen A
- `Convert to Invoice ⚠` button → goes in the Screen B action toolbar
- `INVOICED` chip → new entry in the chip vocabulary (extends the §4.2 mapping from the drilldown spec)
- Overview tab's flat key-value grid → adds `wFirma invoice ID` and `Numer KSeF` cells (already in the spec, just confirms they populate post-conversion)
- Reservation tab → no changes; the blocking reasons surface unchanged
- History tab → adds two new event types: `draft_cloned_from` (with source link) and `converted_to_invoice` (with idempotency key + wFirma response excerpt)

## 2.4 What to delete or deprecate

Nothing in this task. Add-only. If Phase 1 finds dead UI controls related to draft creation or conversion (stubs, disabled-forever buttons, fake modals), report them in Phase 1 §C — deletion is a follow-up task, not this one.

## 2.5 Out of scope for Phase 2

- Editing line items in the new draft modal — clone preserves source lines, edit happens on Screen B Lines tab in a separate task
- Bulk convert (multiple drafts at once) — single-draft only
- Korekta (invoice correction) flow — separate task
- Re-sending an already-converted invoice to a different customer — explicitly not supported, would require uncoupling from wFirma which the spec forbids
- Mobile responsive polish for the modals beyond "doesn't break"
- Persisting the modal's source-picker state on cancel — discard on close

---

# Workflow

1. Claude Code runs Phase 1, produces `ATLAS_PROFORMA_PHASE1_INVESTIGATION.md`, stops.
2. Amit reviews. Either:
   - Approves → Phase 2 fires as a new task with the report attached as context.
   - Requests adjustments → Phase 2 spec gets revised first, then fires.
   - Discovers blockers → task pauses, adjacent work (e.g. missing audit table migration) happens first.
3. Phase 2 ships as one or more PRs depending on what Phase 1 reveals — Claude Code decides PR granularity, sequenced as:
   - PR-A: any missing backend (endpoints, schema columns, audit wiring)
   - PR-B: New Draft modal + clone endpoint UI wiring
   - PR-C: Convert to Invoice modal + payload disclosure + audit
   - PR-D: chip vocabulary extension (`INVOICED`), History tab event types
4. Each PR ships with its own tests. No PR merges without the failure-recovery test for its surface.

---

# Notes for the implementer

- The whole point of the payload-disclosure modal is that the operator can audit the wFirma call *before* it happens. Do not abbreviate, do not pretty-format in a way that loses information, do not hide fields under "show more". The modal shows everything the server will send. If the JSON is long, the modal scrolls.
- The `⚠` glyph on the Convert button is not decoration. It's an information channel that says "this is the irreversible row of the action toolbar". Keep it on the button always, in the modal title always, on the chip if the action is mid-flight (`CONVERTING ⚠`).
- The "cannot be cancelled in wFirma" sentence is not legal cover — it's operator education. Tejal needs to know what she is about to do, every time, regardless of how many times she has done it before. The modal does not get an "I understand, don't show this again" checkbox. The disclosure is the work.
- If during Phase 2 implementation you find that wFirma's actual API does support cancellation/correction via the Korekta flow, do not change this modal's copy. Cancellation requires a separate Korekta action with its own modal. The convert modal stays single-purpose.
- Resist the urge to add a "draft preview" step between Pick Source and Confirm in the New Draft modal. The drafts list refreshes on create and the operator lands on Screen B for the new draft — that *is* the preview. Adding a preview inside the modal duplicates the destination page.
