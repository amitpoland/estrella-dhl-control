# Document Numbering & Series (Serie dokumentów)

Covers how wFirma assigns and exposes invoice/proforma/expense numbers, and how numbering series work — directly relevant to reconciling `fullnumber`/`number` fields against Estrella Jewels' own document naming (e.g. `PROF_68_2026`, `Faktura_WDT_63_2026`).

## Numbering-related fields on a document (confirmed from a real invoice response)

```xml
<number>1465</number>
<day>15</day>
<month>10</month>
<year>2017</year>
<day_year>288</day_year>
<fullnumber>FV 1465/2017</fullnumber>
<semitemplatenumber>FV [numer]/2017</semitemplatenumber>
```

- **`number`** — the raw sequential number within its series (an integer).
- **`fullnumber`** — the fully rendered, human-facing document number (e.g. `FV 1465/2017`) — this is what appears on the printed/PDF document and what humans refer to.
- **`semitemplatenumber`** — the numbering *pattern* with the number itself replaced by a `[numer]` placeholder (e.g. `FV [numer]/2017`) — useful for detecting which series/template a document belongs to without parsing the rendered number.
- **`day` / `month` / `year` / `day_year`** — date-decomposed fields, useful for reporting/grouping without re-parsing the `date` field.

## Series (Serie dokumentów) — what they are

A **series** (seria) is a named numbering sequence with its own format template and its own counter. wFirma supports multiple series per document type — e.g. a company can have more than one invoice series (for different sales channels, branches, or purposes), and **proforma invoices always draw from a separate series from normal invoices** (see `proforma-reservations-flow.md`).

- Configured in Ustawienia (Settings) — see `references/ui-help-center-index.md` for the specific pomoc.wfirma.pl article on choosing/configuring series (`wybor-serii-numeracji-dokumentow`).
- On `/invoices/add`, the series is selected via the `series` branch, typically `{"series": {"id": null}}` to use the default series, or `{"series": {"id": "<specific_series_id>"}}` to target a specific one. **Always pass an explicit `series.id`** for anything beyond quick testing — relying on "whatever the default is" is fragile if the default changes in the UI later, and Estrella Jewels needs deterministic mapping between series and document purpose (e.g. a WDT series vs a domestic series vs a proforma series).
- To discover available series and their ids programmatically, use the `series` module's `find`/`get` actions (confirmed to exist via the community SDK's `seriesApi()`) rather than hardcoding ids sourced only from a one-time UI lookup — series ids should still be treated as configuration, not something to infer.

## Numbering is locked by default — don't assume you can set a custom number

By default, wFirma **automatically assigns and validates** invoice numbers, and has a setting that **locks modification of the assigned number** (confirmed via pomoc.wfirma.pl: a checkbox controlling "sprawdzanie poprawności numeracji faktur i blokada modyfikacji numeru" — validity-checking and number-modification lock). Practical implications:

- Don't try to pass a specific `number`/`fullnumber` on `/invoices/add` expecting wFirma to honor it as-is — numbering is normally system-assigned per the series' sequence and template.
- If the project requires custom/predictable numbering (e.g. to match an external order numbering scheme), that has to be solved via **series configuration in the UI** (a dedicated series with the right template), not by passing arbitrary number values on individual API calls.
- If a number ever needs to be corrected post-issue, that's a UI operation with its own constraints — see the "changing an already-issued invoice number" article indexed in `ui-help-center-index.md`; it is not a simple field edit via `/invoices/edit`.

## Draft invoices and numbering (cross-reference)

Draft invoices (see `invoices.md`) **do not consume a number from any series** until they're approved/finalized in the UI — this is the mechanism to use if the integration needs a "reserve this document but don't commit a number yet" workflow, rather than trying to manipulate series/numbering directly.

## Series across document types

Numbering series are **per document type**, not shared:
- Normal invoices have their own series (possibly more than one, if multiple are configured).
- Proforma invoices have their own separate series (see `proforma-reservations-flow.md`).
- Corrections (faktury korygujące) typically have their own series/numbering track as well — if the project ever needs to issue corrections, don't assume the correction shares the parent invoice's series or number sequence; verify against the current module docs (note also: `API wFirma nie obsługuje faktur korygujących` was reported by one third-party integrator as of their integration date — **re-verify whether correction invoices are API-writable at all before building on that assumption**; this may have changed).
- Expense/wydatki documents, if that module is ever automated, will also have their own series concept — see `expenses.md`.

## Practical reconciliation pattern for Estrella Jewels

Since the project's own file-naming (`PROF_68_2026`, `Faktura_WDT_63_2026`) encodes a sequential number and year similarly to wFirma's own `number`/`year` fields, when building any reconciliation or mapping logic:

1. Don't parse Estrella's own filename convention as if it were guaranteed to match wFirma's `fullnumber` — they may diverge (different counters, different formatting).
2. Store the wFirma-assigned `id` (the true unique key) alongside `fullnumber`/`number`/`year` in whatever mapping table the integration keeps, rather than trying to derive the wFirma id from the filename or vice versa.
3. When matching a proforma to its resulting invoice (see `proforma-reservations-flow.md`), key off the mapping YOUR system records at conversion time — not off any numbering pattern, since proforma and invoice numbers come from different series entirely and won't correlate numerically.
