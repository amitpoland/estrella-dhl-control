# Atlas Pro Forma — Drilldown Redesign (wFirma-style)

**Scope**: Pro Forma surface inside the Shipment detail page only. Visual rebuild + two surgical data fixes. Do not touch other pages in this task.

**Reference UX**: wFirma invoice detail view (`Widok szczegółowy faktury WDT 87/2026`). Calm three-card top region (Sprzedawca / Nabywca / Odbiorca), single horizontal action toolbar, tab strip (Podstawowe informacje / KSeF / Ewidencje / Płatności / Podgląd wydruku / Dokumenty), flat key-value grid for invoice metadata. Reproduce that hierarchy in our component vocabulary — do not import wFirma styles, match the *structure* not the chrome.

---

## 1. The problem we are fixing

The current Pro Forma surface stacks everything into one scroll:

1. Stepper (Intake → wFirma Booked)
2. Next Action banner
3. Cached audit stale banner
4. Document Suite gold/green header with drafts count
5. Local Proforma Drafts list (Diamond Point, Verhoeven, Dream Ring, Panakas)
6. One expanded draft card (Panakas) with CUSTOMER MAPPING + History/Visibility/AI/Close buttons
7. "Advanced / legacy reservation preview" accordion
8. "wFirma Reservation Preview" — Capability & Summary + Reservation BLOCKED + per-draft cards with Create Reservation / View Proforma / Convert Proforma to Invoice
9. A duplicate ghost row at the top of the reservation preview: `—` / `Not ready` / `Doc: —` / `client_name is empty` / `customer '' not matched` — this is a data bug, not a real draft

Result: every region competes for attention, no information hierarchy, the operator cannot tell where to look first.

---

## 2. Target architecture

### 2.1 Navigation model: drilldown

**Two screens, not one.**

**Screen A — Drafts List** (lives where the current Document Suite section is):

- Replaces the current expanded-card-inside-list pattern
- One row per draft, identical row shape, no inline expansion
- Clicking a row navigates to Screen B
- Keep the stepper, Next Action, and stale-audit banner above this list (they are shipment-level, not draft-level)

**Screen B — Draft Detail** (new route, full-page):

- Route: `/shipments/:shipmentId/proforma/:draftId`
- wFirma-style layout: action toolbar → party cards → tab strip → tab body
- Tab strip: `Overview` · `Lines` · `Customer Mapping` · `Reservation` · `History`
- Default tab: `Overview`
- Back link top-left: `← Shipment EJL26-27013` (or whatever the AWB/shipment label is)

The "Advanced / legacy reservation preview" and "wFirma Reservation Preview" sections collapse into a single `Reservation` tab inside Screen B. Delete the standalone sections from the Pro Forma scroll entirely.

### 2.2 Screen A — Drafts List spec

Container: same width as current Document Suite card. Header strip stays (green/gold band, `ESTRELLA JEWELS · DOCUMENT SUITE / Pro Forma · Faktura proforma`, draft count on right) — that branding works, keep it.

Row anatomy (left → right, single horizontal line, ~56px tall):

| Region | Content | Notes |
|---|---|---|
| Status pill | `DRAFT` or `READY` or `BLOCKED` | one pill only, see §4 for chip rules |
| Client name | bold, primary text | e.g. `Diamond Point`, `Verhoeven Joaillier` |
| Doc number | muted | `draft #18 · v1` or `— · v1` if not yet numbered |
| Sync chip | small muted chip | `packing synced` (current behaviour, keep) |
| Total | right-aligned, monospaced numerals | `0,00 USD` |
| Updated | right-aligned, muted | `2026-05-18 10:34:02` |
| Chevron | `›` | indicates navigation |

Row is fully clickable. Hover: subtle background tint (use existing `--surface-hover` token). No per-row action buttons on this screen. All actions (History, Visibility, AI, Close, Convert, Create Reservation) live on Screen B.

### 2.3 Screen B — Draft Detail spec

**Top action toolbar** (mirrors wFirma's Modyfikuj/Usuń/Powiel/Koryguj/Rozlicz/Drukuj/Wyślij/Generuj row):

```
[Edit] [Delete] [Duplicate] [Post to wFirma] [Convert to Invoice] [Print] [Send] [Generate ▾]    [⋯]
```

- Single horizontal row, icon + label, no dropdowns except `Generate ▾`
- Disabled buttons are visibly disabled, not hidden — same as wFirma
- Right side: overflow `⋯` for rarely-used actions (Hide, AI, Visibility — moved out of the row)

**Party cards** (mirrors Sprzedawca / Nabywca / Odbiorca):

Three cards in a row on desktop, stack on mobile.

- `Seller` — always Estrella Jewels, pulled from config
- `Buyer` — from the draft's customer mapping
- `Recipient` — usually same as Buyer; show only if different, otherwise hide this card

Each card: title in muted small caps, then plain-text address block (name, street, city, country, NIP/VAT UE). No icons, no badges inside the card body. If Buyer is unmatched, show a single inline warning row at the bottom of the Buyer card: `⚠ Not mapped to wFirma customer — [Open Customer Master]`.

**Tab strip** under the cards:

```
Overview | Lines | Customer Mapping | Reservation | History
```

Active tab: underline + bold, matches wFirma's style.

**Overview tab body** — flat key-value grid, four columns on desktop (mirrors wFirma's Numer / Zamówienie / Numer KSeF / Metoda płatności row):

| Numer | Zamówienie | Numer KSeF | Metoda płatności |
| Data wystawienia | Termin płatności | Data sprzedaży | Zapłacono |
| Do zapłacenia | Schemat księgowy | Kody w JPK_V7 | Razem |
| Magazyn | | | |

Adapt labels to our domain. Suggested mapping:

- `Numer` → draft number (`#18 · v1`)
- `Zamówienie` → linked AWB / shipment ID (clickable link)
- `Numer KSeF` → wFirma invoice ID once posted, else `—`
- `Metoda płatności` → from packing list
- `Data wystawienia` → draft created date
- `Termin płatności` → payment due
- `Data sprzedaży` → sale date
- `Zapłacono` → paid amount
- `Do zapłacenia` → outstanding
- `Schemat księgowy` → accounting scheme (`Zwykły` etc.)
- `Kody w JPK_V7` → JPK codes
- `Razem` → total + FX rate display `405,00 EUR (Kurs: 4.2284 PLN)`
- `Magazyn` → warehouse

Label = muted small text on row 1, value = bold larger text on row 2. Exactly wFirma's pattern.

**Lines tab body** — line items table. Use the existing table component, no redesign needed for this task, just move it under this tab.

**Customer Mapping tab body** — the current CUSTOMER MAPPING block (Sales client name / wFirma customer ID / wFirma stored name / Match strategy / Open Customer Master) moves here verbatim. No redesign needed in this task.

**Reservation tab body** — see §3.

**History tab body** — the current History dropdown content moves here as a full timeline list.

---

## 3. Reservation tab — consolidating the two preview surfaces

The current page has TWO reservation surfaces fighting each other: "Advanced / legacy reservation preview" (collapsed accordion, calls itself legacy) and "wFirma Reservation Preview" (the canonical one). This is exactly the kind of duplicate surface ADR-018 was meant to prevent.

**Decision**: keep one. Delete `Advanced / legacy reservation preview` from the DOM entirely. The "wFirma Reservation Preview" block becomes the body of the `Reservation` tab.

Inside the Reservation tab:

1. **Capability strip** — top row, three chips: `wFirma configured` ✓ · `Audit clean` (state-dependent) · `Reservation supported` (state-dependent). Same chips as today.
2. **Summary line** — `Ready: 0 / 5 · Currency: USD` aligned right of the capability strip.
3. **Blocking reasons card** (only if blocked) — yellow surface, bulleted list of reasons. Same content as today (`30 packing line(s) not yet scanned into warehouse`, `wFirma warehouse module not enabled (…)`).
4. **Action footer** — right-aligned: `[Create Reservation]` (disabled if blocked) · `[Convert Proforma to Invoice]`. Drop `[View Proforma]` from here — we are already viewing the proforma.

The per-document cards inside the current reservation preview (Diamond Point / Verhoeven / etc.) **do not appear in this tab** because this tab is scoped to one draft. They were only there because the old surface was unscoped. Single-draft = no list.

---

## 4. Surgical data fixes (the two non-visual changes)

### 4.1 Remove the duplicate empty-name row

The "wFirma Reservation Preview" currently renders a phantom row at the top:

```
— Not ready
Doc: —
✗ No customer name | No wFirma customer
• client_name is empty
• customer '' not matched in wfirma_customers (register via PUT /api/v1/wfirma/customers/<name>)
```

This is a row produced by the resolver when `client_name` is empty string. Fix at the data layer: in the reservation preview resolver, **filter out rows where `client_name` is empty/whitespace AND there is no `doc_number`**. Those are not real drafts — they are stub rows the resolver produces during sync.

Add a unit test: resolver fed `[{client_name: "", doc_number: null, ...}, {client_name: "Diamond Point", ...}]` returns only the Diamond Point row.

If the empty-name row turns out to represent a real draft that just hasn't had a customer assigned yet (check by joining against `proforma_drafts` table), then keep it but render it with the draft's *internal ID* as the name (e.g. `Draft #18 (unassigned)`) instead of `—`. Verify which case applies before implementing — this determines whether the fix is filter-out or render-different.

### 4.2 Fix INVOICE BLOCKED chip semantics

Current state: the Panakas draft card shows `DRAFT` + `INVOICE BLOCKED` simultaneously. These are not orthogonal — a draft cannot be both "draft" and "invoice blocked" because a draft has not been converted to an invoice yet. The chip is overloaded to mean "conversion to invoice is blocked".

Replace the chip vocabulary with a single status that follows draft lifecycle:

| State | Chip | Meaning |
|---|---|---|
| Newly synced from packing | `DRAFT` (muted) | exists locally, not yet posted |
| Posted to wFirma as proforma | `PROFORMA POSTED` (blue) | linked to wFirma proforma ID |
| Conversion to invoice blocked | `CONVERT BLOCKED` (amber) | with tooltip listing reasons |
| Converted to invoice | `INVOICED` (green) | linked to wFirma WDT/Faktura ID |

Only one chip per draft, ever. The previous `INVOICE BLOCKED` becomes `CONVERT BLOCKED` and is mutually exclusive with `DRAFT`.

Migration: any row currently emitting `INVOICE BLOCKED` should emit `CONVERT BLOCKED` if it has a posted proforma, otherwise just `DRAFT` (the blocking reasons surface in the Reservation tab, not in the chip).

---

## 5. What to delete

After this work lands, the following should be **gone** from the Pro Forma surface:

- The inline expanded-draft card inside the drafts list (replaced by drilldown)
- The `Advanced / legacy reservation preview` accordion (gone, not migrated)
- The standalone `wFirma Reservation Preview` block at the bottom of the page (moved into Reservation tab)
- The duplicate `—` empty-name row in the reservation preview (filtered at resolver)
- The `INVOICE BLOCKED` chip string (replaced by `CONVERT BLOCKED`)

The stepper, Next Action banner, and Cached audit stale banner stay where they are — they are shipment-level signals, not pro-forma-level.

---

## 6. What stays unchanged in this task

Do not touch in this PR:

- `/shipments` list page
- Stepper component itself (only its position relative to the new layout)
- Inbox, Documents, Accounting, Inventory, Reports, Setup pages
- Customer Master surface (still linked from Buyer card and Customer Mapping tab)
- The packing-list sync logic
- The wFirma API client
- Any backend route except the reservation-preview resolver filter (§4.1) and the chip status emitter (§4.2)

Separately scoped tasks (Atlas Frontend Reality Audit covers them) will handle the other 28 frontend problems.

---

## 7. Implementation order

1. **Add the route** `/shipments/:shipmentId/proforma/:draftId` with placeholder body
2. **Build Screen B shell** — back link, action toolbar (buttons can be no-op stubs initially), party cards, tab strip, empty tab bodies
3. **Wire Overview tab** — flat key-value grid populated from existing draft model
4. **Wire Customer Mapping tab** — move existing block into it
5. **Wire Lines tab** — move existing line items table into it
6. **Wire Reservation tab** — port the wFirma Reservation Preview content, scoped to single draft
7. **Wire History tab** — port the History dropdown content
8. **Rebuild Screen A** — flatten drafts list to row-per-draft, make rows clickable, remove inline expansion
9. **Remove deleted surfaces** — Advanced/legacy preview, standalone reservation preview
10. **Apply §4.1 resolver filter** + unit test
11. **Apply §4.2 chip vocabulary** + migration of existing emit sites
12. **Hook up the action toolbar** — wire Edit, Delete, Duplicate, Post to wFirma, Convert to Invoice, Print, Send, Generate to the same handlers the current buttons use (rename internally if needed, do not change behaviour)
13. **Smoke test on Windows production** — load each tab on each of the four current drafts (Diamond Point / Verhoeven Joaillier / Dream Ring / Panakas), verify no console errors, verify the phantom `—` row is gone

---

## 8. Acceptance criteria

- Pro Forma scroll on the Shipment page shows ONLY: stepper · Next Action · stale-audit banner · Document Suite header · drafts list (clean rows). Nothing else below.
- Clicking any draft row navigates to `/shipments/:id/proforma/:draftId`
- Draft detail page passes side-by-side visual comparison with the wFirma reference: three-card top region, single action toolbar, tab strip, flat key-value grid in Overview
- Reservation tab shows exactly one set of capability chips, one blocking-reasons card (if applicable), and one action footer — no duplication
- The `—` phantom row no longer appears on any shipment, verified by reloading the four current draft shipments
- No draft anywhere shows both `DRAFT` and `INVOICE BLOCKED` chips. Each draft shows exactly one chip from the §4.2 vocabulary
- All existing actions (Create Reservation, Convert to Invoice, History, Visibility, AI, Close, Open Customer Master) remain functional — only their location changes
- No regression in packing-list sync, draft creation, or wFirma posting flows
- Build passes, no new console warnings, no broken keyboard navigation on the tab strip

---

## 9. Out of scope explicitly

- Mobile responsive polish beyond "doesn't break" (separate task)
- Renaming `Sprzedawca/Nabywca/Odbiorca` cards to Polish (we use English; only the structure is borrowed)
- Replacing the green/gold Document Suite header band (it stays)
- Changing the stepper visual (separate item in the Frontend Reality Audit)
- Persisting tab selection across navigation (nice-to-have, not in this task)

---

## 10. Notes for the implementer

- The wFirma layout works because each region has exactly one job. If you find yourself adding a second purpose to any region (e.g. "the party card also shows mapping status"), stop — that's a tab body's job, not a card's job
- The action toolbar should look identical whether the draft is blocked or ready. Disabled state communicates blocking, not absence of the button
- Resist the urge to add a "summary at top" panel inside Screen B. The party cards + Overview grid IS the summary. wFirma does not have a separate summary card and neither should we
- If during implementation a tab body feels empty, that's fine — empty states with a single helpful sentence beat fake density
