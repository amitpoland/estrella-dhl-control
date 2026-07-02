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

Provenance note: the full app wireframe is `Estrella Dashboard.html` in the
same design bundle (not copied — large; reference by path). This directory
holds only the Inventory-relevant design source.
