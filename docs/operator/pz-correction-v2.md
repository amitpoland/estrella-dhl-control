# PZ Correction V2 — Operator Runbook

This page describes the PZ Correction workflow as it appears in the V2
interface. The V2 surface is the single rendering authority for PZ
Correction. The previous in-page card on the shipment detail screen has
been retired.

URL: `/dashboard/pz-correction-v2.html?batch_id=<BATCH_ID>`

The workflow is only available for Global Jewellery batches. For all
other supplier types the page displays "This batch does not have a
correction workflow."

---

## When you would use this page

A Global Jewellery PZ that has already been posted to wFirma may have
structural differences compared to the supplier invoice and packing
authority (mismatched lines, qty divergence, mixed item types). PZ
Correction examines the posted PZ against the authoritative invoice +
packing data and either confirms the existing PZ is acceptable or offers
corrective options.

The page never modifies anything without your explicit action. Every
write button is labelled with what it writes.

---

## The five operator phases

The page renders exactly one of these phases at any given time. The
small badge in the header tells you which.

### 1. "N/A" — Not available

The correction workflow is not available on this environment. This is
a configuration state, not an error. Contact your administrator if you
expected the workflow to be available here.

There are no actions in this phase.

### 2. "Draft" — Review recommendation

The system has analysed your posted PZ and produced a recommendation.
You see:

- The recommended option (with a "Recommended" tag)
- A short explanation of why the system recommends it
- A safety summary (how many lineage links and authority rows were used)
- A list of alternative options you may choose instead

Actions:

- **Record decision** — choose an option, enter a brief reason, click.
  This records your decision in the workflow audit trail. No external
  document is created at this step.
- **Close workflow** — closes the workflow without making any decision.
  You will be asked for a reason.

### 3. "Ready" — Decision recorded

Your decision has been recorded. The workflow now asks you to confirm
you are ready to take the next step.

Actions:

- **Finalize decision** — moves the workflow forward to the posting
  preparation step. The system gathers the data needed to create the
  corrected document.
- **Change decision** — returns you to the Review phase so you can
  choose a different option.

### 4. "Ready to post" / "Held" — Posting step

Once finalized, the workflow shows one of two faces depending on
company policy:

**Ready to post (green):** The system is configured to create
documents in wFirma. You see:

- Your decision in plain text
- A required free-text "Reason for correction" field (10+ characters)
- A required checkbox: "I understand this creates a new accounting
  document."
- **Create document** — clicks when both the reason and the checkbox
  are filled. Creates the new corrected document in wFirma.
- **Change decision** — returns you to the Review phase
- **Cancel** — closes the workflow

**Held (amber):** Posting is currently unavailable by company policy.
This is not an error. You see the message "External posting unavailable.
Your decision is held safely and will post when posting is re-enabled
by the administrator."

In the Held face, the actions are:

- **Change decision** — returns you to the Review phase
- **Close without posting** — closes the workflow; the recorded decision
  is preserved in the audit trail but no external document is created

### 5. Transient outcomes

After clicking **Create document**, the workflow may show one of:

- **Working** — the system is creating the document. The page polls for
  status. If the work takes more than three minutes, a "Still working —
  refresh manually" message appears with a **Refresh now** button.
- **Done** — the corrected document was created successfully. The
  workflow shows the result summary.
- **Needs attention** — the external posting did not complete. Your
  decision is preserved. You can **Retry**, **Change decision**, or
  **Close workflow**.
- **Closed** — the workflow is closed. No more actions are available.

---

## Where the workflow is reached from

The V2 workflow is reachable from the shipment-detail page via the
"PZ Correction" entry on Global Jewellery batches. The URL embeds the
batch id, so a direct link of the form
`/dashboard/pz-correction-v2.html?batch_id=<BATCH_ID>` is safe to share
internally.

---

## Diagnostics accordion

At the bottom of the page there is a collapsed **Diagnostics** section.
This is engineer-facing. It surfaces:

- The internal workflow state name (e.g. `STAGED`, `OPERATOR_REVIEWED`)
- The selected option identifier
- Authority row count, PZ line count, lineage link count
- The lifecycle flag value
- Whether posting was detected as currently disabled
- The current idempotency key
- Timestamps of each transition
- The full list of endpoints the page uses

If something looks wrong and you are asking IT to investigate, expand
Diagnostics and paste the contents into the ticket.

---

## What this page does NOT do without an explicit click

- It does not save anything when you load the page.
- It does not record a decision when you choose a radio button — only
  when you click **Record decision** with a reason filled.
- It does not create a wFirma document when the checkbox is ticked —
  only when **Create document** is clicked.
- It does not retry on its own when posting fails.
- It does not close the workflow when you navigate away — it just
  stops polling.

---

## Engineering reference (appendix)

This section maps operator phases to internal lifecycle states. Operators
do not normally need this; it is included so engineers can correlate
the UI with audit records.

| Operator phase     | Internal state         | Backend action                                       |
| ------------------ | ---------------------- | ---------------------------------------------------- |
| N/A                | (any)                  | `pz_correction_lifecycle_enabled=false` everywhere  |
| Draft              | `PROPOSED` / no record | Page loaded, no decision yet                         |
| Ready              | `OPERATOR_REVIEWED`    | Decision recorded                                    |
| Ready to post      | `STAGED`               | `wfirma_correction_push_allowed=true`               |
| Held               | `STAGED`               | `wfirma_correction_push_allowed=false`              |
| Working            | `EXECUTING`            | wFirma write in progress                             |
| Done               | `COMPLETED`            | wFirma write succeeded                               |
| Needs attention    | `FAILED`               | wFirma write returned a non-200 response             |
| Closed             | `TERMINAL_SUPPRESSED`  | Workflow suppressed (with reason)                    |

Backend authority files:

- HTTP routes: `service/app/api/routes_pz.py` (lines 739–1346)
- Lifecycle state machine: `service/app/services/pz_correction_state.py`
- wFirma write gates: `service/app/services/global_pz_push.py`
- Sentinel string: `global_pz_push._CONFIRM_SENTINEL`

Frontend authority files:

- Single mapper: `pz-state.js correctionUiPhase()`
- Single renderer: `pz-components.js PZCorrectionV2Container` and the
  10 phase components beside it
- Standalone page: `pz-correction-v2.html`
- Transport: `pz-api.js` 8 correction endpoint wrappers + the
  `_CONFIRM_SENTINEL` JS constant + `buildCommitIdempotencyKey`
