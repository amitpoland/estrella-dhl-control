# Design authority — Inventory (parity source)

`inventory-page.design.jsx` is the operator's wireframe Inventory page, copied
verbatim 2026-07-03 from the design bundle at
`Downloads/estrella-dashboard/project/inventory-page.jsx` (Claude Design
project 019dcc53-…, "Estrella Dashboard"). It is the **UI authority** for the
Phase-B Inventory parity work (operator standing rule: *Wireframe = UI
authority; existing V2 Inventory = code authority; no duplicate page*).

It is a REFERENCE artifact, NOT a shipped file — it is not loaded by index.html
and uses mock data throughout. Parity slices port its STRUCTURE and VISUAL
LANGUAGE into the live `service/app/static/v2/inventory-page.jsx`, wired to real
backend authorities, never faking data (Lesson M five-state honesty).

## Canonical wireframe of record

`estrella-dashboard-wireframe.html` (1.67 MB, compiled standalone) is the
operator's canonical dropped authority file (2026-07-03). It is the SAME
design bundle as `inventory-page.design.jsx` — same 11-tab Inventory model
(Temp Purchase/Warehouse/Sale · Consignment · Final Stock · Sample Out/Return
· Client/Producer returns · Identity/Mapping), same Move Stock modal, same
`stock_unit_id` / `trace_barcode` truth model — just compiled to one HTML.
The `.design.jsx` is the readable extract used for element-level parity
citation; the `.html` is the authority-of-record the operator handed over.

The Inventory mapping gate
(`reports/inspection/2026-07-03T150000Z-inventory-mapping-gate.md`, commit
af397e27) was produced against the `.jsx` extract and STANDS unchanged against
this canonical HTML (verified same design signatures on copy-in).
