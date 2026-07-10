# ADR — Proforma Detail Wireframe Rebuild (campaign PFW, 2026-07-10)

Status: **Accepted & shipped** (PRs #870, #872, #874, #875 — production `b1caafd4`).
Authority owner: **V2 Proforma Detail page** (`service/app/static/v2/proforma-detail.jsx`),
backed by the existing proforma draft authority (`routes_proforma.py` +
`proforma_invoice_link_db.py`). Certification evidence:
https://claude.ai/code/artifact/a2221cee-fce5-4b67-ac53-fdd22a7eda77

## Problem

The operator supplied an approved wireframe (saved Claude artifact,
`estrella-dashboard-wireframe.html`) for the Pro Forma Draft workspace and
required the live V2 page to match it 1:1 in UI/UX with all functions — while
the live page already carried substantially more capability than the wireframe
(17 toolbar actions, 8 tabs, AWB booking, readiness gating) and the wireframe
displayed fields the draft API did not yet expose (variant identity per line,
VAT code, NBP table number, KUKE insurance).

## Alternatives considered

1. **Frontend-only restyle with mock/fabricated fields** — rejected: violates
   the no-fake-data rule; wireframe fields would render placeholder lies.
2. **New parallel page (proforma-v3)** — rejected outright: FRONTEND AUTHORITY
   CONSTITUTION forbids duplicate pages/renderers.
3. **Backend-first field exposure, then in-place render rebuild in slices**
   — **chosen.** Four PR-sized slices: (1) additive backend field carry-through,
   (2) passive visual primitives, (3) render-layer rebuild, (4) KUKE panel wiring.

## Decision (what shipped)

- **Slice 1 (#870):** variant-identity columns (`client_po, karat, metal,
  metal_color, quality_string, stone_type, size, diamond_weight, color_weight`)
  carried from `sales_packing_lines` into draft `editable_lines` at **all three**
  birth/reset boundaries (pildb birth, pildb reset + route reshape, and
  `routes_intake._auto_create_draft_for_client` — the dominant path, which had
  been silently dropping them through legacy aliases). `_draft_to_full` gained
  `vat_code`, `vat_context`, `wfirma_payment_method`, `nbp_table_number`
  (memoized display-only projection of `fx_rates.table_number`).
- **Slice 2 (#872):** nine `Pf*`-prefixed file-local wireframe primitives.
  The prefix is **load-bearing**: Babel-standalone hoists top-level declarations
  to global scope, so unprefixed names would overwrite
  `shipment-detail-page.jsx`'s `SectionLabel/PanelCard/StatTile` app-wide.
- **Slice 3 (#874):** render layer rebuilt to the wireframe (toolbar eyebrow
  layout, bg-subtle party band + Currency & Payment card, Overview
  StatTiles/PanelCards, wireframe Items columns + charge footer, Logistics
  tiles, Documents card grid, Audit timeline) with every action, gate, modal,
  and pinned data-testid preserved.
- **Slice 4 (#875):** display-only VAT & Insurance (KUKE) panel reading the
  Slice-1 draft keys + Customer Master fields via the **existing**
  `getCustomerMaster` call; fail-visible, never gating.

## Trade-offs accepted

- **Authority pins beat wireframe parity** where they conflicted:
  *Total PLN renders `—`* (Sprint-36 rule: no browser-side FX conversion — the
  PLN total belongs to wFirma at posting) and the edit button is labeled
  *"✎ Edit"*, not the wireframe's "Edit Draft" (Sprint-36 dead-button string
  pin). Visual parity yielded ~5% for authority integrity.
- **HS/Origin columns** moved off the on-screen Items table (wireframe has no
  such columns); they remain in the printable document pipeline.
- **Old drafts show `—`** in variant columns until reset-from-sales-packing or
  a new intake (fields are stored at birth/reset; no retro-backfill was built —
  deliberate: reset is the sanctioned refresh path).
- **Per-line variant editing is not allowed** (`EDITABLE_LINE_FIELDS`
  whitelist rejects variant keys): variant identity is reset-refreshed from
  the packing authority, never hand-edited per line. Pinned by test.
- **Premium is a display-only estimate** (goods total × Customer Master
  `insurance_rate`, labeled "(est.)"), never persisted or consumed by
  readiness — Lesson N advisory class.

## Future implications (what future engineers must know)

- `proforma-detail.jsx` is the **single renderer**; extend it in place. The
  `Pf*` primitives are the styling vocabulary for this page — do not rename
  them to unprefixed forms (global-scope collision) and never pass hex to the
  `accent` prop (CSS custom properties only; pinned).
- **AwbGenerateModal is a protected block** — the wireframe rebuild proved a
  byte-identical modal across a 1,089-line render diff; keep it that way. Its
  known `...payload })` spread-rest regex false-positive is baseline-registered
  and deliberately unfixed.
- The pin suites (`test_proforma_wireframe_layout.py` — self-updating
  prefix-aware testid inventory; `test_proforma_wireframe_primitives.py` —
  boundary-self-checking block scan) are the drop-can't-return guards for this
  page. A failing inventory pin after a UI change means a test-pinned testid
  was removed — that is a Lesson M event, not a test to reconcile silently.
- Deep-link format is `/v2/proforma_detail?batch_id=<b>&draft=<id>` — the page
  slug is a **path segment**, not a query param.
