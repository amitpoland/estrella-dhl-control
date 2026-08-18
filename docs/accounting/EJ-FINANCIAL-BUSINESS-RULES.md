# EJ Financial Presentation Rules

**Status:** active · **Scope:** presentation only · **Owner:** Finance (policy) + EJ Dashboard accounting module (implementation)

This document records how corrected financial facts are **presented** to an
operator, a CFO, a CA/CS reviewer, or a counterparty. It is a *presentation*
policy. It changes no accounting formula, no eligibility predicate, and no
stored value.

## 0. What this document is not

This file does **not** define, alter, or duplicate any of the following. They
are financial authorities and are out of scope for every presentation change:

`classify_expense_lifecycle` · payment lifecycle / tombstone logic ·
`list_payments_as_of` eligibility · `remaining_after_payments` ·
`match_payments_to_invoices` · `match_payments_to_expenses` · AR/AP projection
sync · `payment_state` DB semantics · `financial_reporting` DB semantics ·
opening/closing arithmetic · currency conversion / FX authority · AP
eligibility rules · the aging bucket formula.

If a screen looks wrong because an upstream fact is wrong, the UI patch stops
and the source fact is escalated. A frontend filter or an alternate frontend
calculation is never the remedy.

## 1. The single presentation identity

The canonical identity lives in `accounting_analytics.py:545-546` and is
restated — never recomputed — by the presentation layer:

```
credit_balance = Σ −remaining   where remaining < 0     (never aged)
net_position   = gross_exposure − credit_balance
```

**GROSS EXPOSURE − CUSTOMER/SUPPLIER CREDITS = NET POSITION.**

Consequences that are binding on every screen and every PDF:

- Aging buckets are built from **positive remainings only**. Credit notes and
  over-settled documents are therefore *not* in the buckets. The buckets are
  **gross, before credits**.
- Because of that, `Overdue` and `Not due` are **gross** figures and must be
  labelled as such. The statement carries `aging_basis = "gross_before_credits"`
  so a renderer cannot silently present a gross overdue figure as a net one.
- A gross overdue figure may **never** be displayed without the credit that
  offsets it standing in the same block. The operator must never see
  `Net 0` beside `Overdue 52,940` with no visible 52,940 credit explaining
  the difference.
- The caption belongs **on the aging surface itself**, not only in the
  payload. A reader takes in one card at a time: an aging card headed
  `Aging` and showing `91-180  2,000.00` reads as a supplier 2,000 overdue,
  even when the offsetting 2,000 credit sits on the card beside it. Every
  aging block -- client statement card, supplier statement card, management
  analysis grid -- carries the words **gross · before credits** in its own
  heading. Pinned by `test_every_aging_surface_says_the_split_is_before_credits`.

## 2. Position vs Activity — two different questions

| | POSITION | ACTIVITY |
|---|---|---|
| Question | What is owed **as of** a date | What moved **inside** a period |
| Figures | Gross exposure, Credits/offsets, Net position, Overdue, Not due, Due date unavailable | Opening / B-F, period debits, period credits, Closing |
| Identity | `net = gross − credits` | `opening + debits − credits = closing` |
| Payload | `position_per_currency` | `entries_per_currency` + opening/closing |

A period closing balance is **not** the current portfolio position and the two
are never substituted for one another. Both are rendered in distinct, labelled
blocks.

Distinct means **separately headed**, not merely separated by a rule. A single
card holding opening/debits/credits/closing *and* gross/credits/outstanding/net
leaves the reader to guess which question each row answers, and when closing
balance happens to equal net position -- as it does whenever nothing moved in
the window -- the conflation is invisible in the numbers. The statements carry
**Period activity** (`movement inside the period`) and **Position**
(`gross less credits · as of <date>`) as two cards.

Substitution is also forbidden in the *fallback* direction, and here the two
statements differ, so the rule is about the figure rather than the key. A
renderer filling in for a missing `closing_balance` may read another **period**
figure and may never read a **position** figure. On the supplier statement both
candidates are position -- `outstanding` is gross open, `net_payable` is that
less credits (`ledger_aggregator.py:1043-1045`) -- so neither may stand in. On
the client statement `outstanding` is the aggregator's explicit legacy alias
for the closing itself (`:1583`), so reading it substitutes nothing and keeps an
older-shaped payload printing its real number instead of a confident `0.00`.

The blanket version of this rule was written first and was wrong in the
direction that matters: it would have replaced a correct figure with zero.
Pinned by `test_activity_card_holds_no_position_figure` and
`test_closing_balance_never_falls_back_to_a_position_figure`, the second of
which scopes its check to the supplier block.

## 3. Presentation state vocabulary

Account-level state (`presentation_state`, emitted per currency leg and rolled
up for the portfolio):

| State | Meaning |
|---|---|
| `open` | Gross > 0 and Net > 0 |
| `offset` | Gross > 0 and Net == 0 — credits fully cover gross. Rendered as **OFFSET / NET ZERO** |
| `credit` | Gross == 0 and Credits > 0 |
| `clear` | Gross == 0 and Credits == 0 |

The portfolio roll-up is the **most-open leg**: a fully offset USD leg does not
clear an open EUR leg.

Row-level status (`presentation_status`) is decided by the backend
(`derive_presentation_status`) and is the only status a renderer may display:

`B/F` · `Not Due` · `Overdue` · `Settled` · `Credit / Offset` · `Applied` ·
`Unapplied` · `Due Date Unavailable` · `Status Conflict`

## 4. Status Conflict — source claim never overrides economics

The wFirma source lifecycle flag (`paid` / `settled`) is **never displayed as
economic truth**. It is only compared against the locally computed economic
remaining.

> Source says *paid* and `economic_remaining > 0` and no correction document
> explains the difference ⇒ **Status Conflict**, never *Paid*.

The correction check is mandatory. Measured against production on 2026-08-18,
47/47 AR and 6/6 AP candidate conflicts were fully explained by a linked
correction document — a correction-blind rule produces 53 false alarms and zero
true ones.

## 5. Multi-currency

Currencies are **never** FX-summed for presentation. EUR, USD, PLN and CHF are
independent legs. Each leg carries its own Gross, Credits, Net, Overdue, Not
due, Opening, Closing and running balance.

The string `multi` is a **backend sentinel meaning "more than one leg"**, not a
currency. Branching on it is correct; displaying it to an operator is a defect.
Where per-leg detail is unavailable the UI names that fact
("Multi-currency — legs unavailable"); it never prints the sentinel and never
adds the legs together.

## 6. Due date

Due date is a first-class column on every ledger and statement row.

- Authority: AR = wFirma `paymentdate`; AP = wFirma `payment_date`.
- Absent ⇒ the row reads **"Due date unavailable"** and its status is
  `Due Date Unavailable`. Such a row is neither overdue nor not-due, and its
  amount is reported in a separate `due_date_unavailable` figure.
- The issue date is **never** substituted for a missing due date.
- Payment rows and the B/F row show an em dash (a due date is not meaningful
  there).

## 7. Unapplied cash

A payment that matches no document is **reported, never netted**. Unapplied
payments do not move the running balance and are not inside the closing figure.
They are listed in their own panel, per currency leg, carrying the `Unapplied`
status. Suppressing them, or folding them into the balance, are both defects.

## 8. Old open items

An item is never hidden, aged out, or written off merely because it is old. A
genuinely open item older than 365 days is shown with a visible review
indicator ("Historical open item 365+ days") and stays in the position.

The visible **activity window** may use the configured history floor. The
**open position** must not discard a genuinely open item solely because its
issue date predates that floor. This campaign introduces no new history floor
and changes no floor policy.

## 9. Screen / PDF parity

The PDF and the screen read **one** model — the statement dict produced by
`ledger_aggregator`. `statement_pdf_renderer` is a pure renderer over that
dict. The PDF may format differently; it performs **no** financial
recalculation. If the screen shows Opening 100 / Debits 50 / Credits 20 /
Closing 130, the PDF shows exactly that, and likewise for Gross, Credits, Net,
aging, due dates and statuses.

## 10. The frontend is not an accounting authority

No financial arithmetic in JSX. The renderer chooses a colour, a label and a
layout; every figure and every status arrives already decided. Fields listed in
`FORBIDDEN_ENTRY_FIELDS` (`payment_state`, `paymentstate`, `remaining`,
`alreadypaid`, `paymentdate`, `paid_date`, `aging`) may never reach an emitted
entry, so a renderer cannot re-derive eligibility or settlement even by
accident.

## 11. Statement of Account vs Balance Confirmation

A monthly **Statement of Account** is a reconciliation document. Its footer
asks the counterparty to review and report discrepancies. It is **not** an
auditor-controlled confirmation, is not labelled ISA 505 / SA 505, and silence
is **never** recorded as agreement.

A **Balance Confirmation** is a separate product with an explicit
Agree / Disagree section, difference amount, comments, name, title and
signature. The Polish year-end distinction between a statutory receivables
confirmation and an ordinary monthly statement is preserved.

## 12. Honesty rule

No presentation change may make a number look better. Where the accounting
relationship is uncomfortable — a large gross overdue offset by a large credit,
a conflict between source and economics, an item open since 2021 — the
presentation exposes it and explains it. It never smooths it away.
