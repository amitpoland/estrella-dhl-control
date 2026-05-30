# Sprint 24 — Proforma V2 Drilldown + Convert to Invoice

**Campaign:** Atlas-V2
**Sprint:** 24
**Branch:** `atlas-v2/sprint-24-proforma-v2-drilldown`
**Dependency:** Sprint 05 merged
**New file:** extends `service/app/static/proforma-v2.html` OR new `service/app/static/proforma-detail-v2.html`

## Summary

Two screens and two write features:
- Screen A: Drafts list (existing proforma-v2.html, with nav to Screen B)
- Screen B: Drilldown detail — wFirma-style toolbar → party cards → tab strip
- Feature 1: New Proforma Draft modal (clone-from-source)
- Feature 2: ⚠ Convert Proforma → Invoice (irreversible, §7 gated)

## Routes

- Screen A: existing `/dashboard/proforma-v2.html?batch_id=<ID>`
- Screen B: `/shipments/:id/proforma/:draftId` (new route or query-param approach)

## Status Chip Semantics (corrected)

| State | Chip |
|---|---|
| Draft, not posted | `DRAFT` (neutral) |
| Posted to wFirma as proforma | `PROFORMA POSTED` (blue) |
| Conversion blocked | `CONVERT BLOCKED` (amber) |
| Converted | `INVOICED` (green) |

Old chip `INVOICE BLOCKED` → deprecated; migrate to `CONVERT BLOCKED` if proforma posted, else `DRAFT`.

## Screen B — Toolbar buttons

| Button | Endpoint | Gate |
|---|---|---|
| Edit | draft update (discover) | editable only while not INVOICED |
| Delete | draft delete (discover) | GATED confirm |
| Post to wFirma | wFirma proforma post (discover) | GATED; disabled if already posted |
| **Convert to Invoice ⚠** | POST /api/v1/proforma/{id}/convert-to-invoice OR /wfirma/invoices/convert (confirm real route) | GATED + payload-disclosure modal |
| Print | PDF render (discover) | safe |
| Send | send (discover) | GATED (external) |

## Feature 2 — Convert to Invoice (irreversible)

- ⚠ stays in label always
- Disabled if: wfirma_proforma_id null · Reservation blockers · wfirma_customer_id null
- Payload-disclosure modal required (§7): irreversibility sentence first, exact JSON values shown
- Endpoint ambiguity: confirm real route (routes_proforma.py vs routes_wfirma*.py)

## Backend Data Fixes (discover phase)

- §4.1 Phantom empty-name row: filter rows where client_name empty AND doc_number absent
- §4.2 Chip migration: stop emitting INVOICE BLOCKED

## Build Order

1. Screen A nav to Screen B (row click)
2. Screen B shell (back link, toolbar stubs, party cards, tab strip)
3-7. Wire tabs: Overview → Customer Mapping → Lines → Reservation → History
8. [+ New Draft] modal (Feature 1)
9. Convert modal + payload disclosure (Feature 2)
10. Data fixes §4.1/§4.2
11. Hook toolbar to confirmed endpoints
12. Contract-verify every element
13. Render-verify on real drafts (Diamond Point / Verhoeven / Dream Ring / Panakas)

## Source specs

From operator session 2026-05-30:
- `ATLAS_PROFORMA_NEW_DRAFT_AND_CONVERT.md` (not yet written — spec lives in this file for now)
- `ATLAS_PROFORMA_DRILLDOWN_REDESIGN.md` (not yet written)
