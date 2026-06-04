# ATLAS FRONTEND — RECOVERED P-LIST (Part 1 anchor for Part 2 verdicts)

> Persisted on the Windows host 2026-05-30 from the operator's recovered problem-collection session.
> P1–P26 recovered. NOT recovered: P16, P27, P28, P29 (count drifted 26→28→29) — backfill from the
> Mac `REALITY_AUDIT.md` (authoritative numbering). The Part 2 first-pass Coverage Matrix false-LIVE
> finding is NOT in the recovered numbered list — likely one of the missing P#s; capture on backfill.

## P-LIST (P1–P26, by group)

**Group 1 — Dashboard**
- P1  Progress bar static — not driven by real backend events
- P2  Pipeline lanes decorative — not live
- P3  Cached audit stale — overrides fresh status

**Group 2 — Intelligence & Timeline**
- P4  Intelligence tab shows raw signals — not operator actions
- P5  Timeline raw event log — no grouping, no workflow

**Group 3 — PZ / Accounting**
- P6  Everything locked even for ADMIN
- P7  Product-creation pipeline not visible or actionable
- P8  5 duplicate/redundant panels

**Group 4 — Sales**
- P9  Sales tab empty — no bridge to client packing files

**Group 5 — Documents**
- P24 Documents tab passive file dump — no controls

**Group 6 — Packing & Documents**
- P10 Duplicate packing-list rows — no detection/guidance
- P18 SUOKKO uploaded 4× — no dedup
- P19 Poland purchase packing lists silent failure — fields=0
- P20 Purchase invoices extracted but fields=0
- P21 Inconsistent row-count visibility
- P22 Document Registry stuck at pending — no retry
- P23 AWB document state ambiguous

**Group 7 — Action Proposals**
- P11 Action Proposals empty even when actions exist

**Group 8 — UI/UX Architecture**
- P12 UI is a security wall, not an operations dashboard
- P13 No role-based permission model
- P17 Frontend replacement needed — Atlas migration
- P25 Overview tab — 8 conflicting panels, no canonical next action

**Group 9 — Inbox**
- P26 Inbox controls not persisted — decoration only

**Group 10 — Wave 2 / DHL Shadow**
- P14 Attachment integrity guard untested under real flow
- P15 Wave 2 clock not started — no shadow dispatch evidence

## VERDICT VOCABULARY (canonical)
Every visible control resolves to one of: **LIVE / WIRE / BUILD / HIDE / DELETE / FAKE.**
Rule: **no "BACKEND PENDING" in primary production UI.**

## CALIBRATION (verdict each with the RIGHT evidence)
- **Render-confirmable (render decides):** P1, P2, P26, false-LIVE badges.
- **Data/backend quality (needs data + endpoint evidence, not render alone):** P10, P18, P19, P20, P21, P22, P23.
- **Architectural / strategic (judgment, not pass/fail):** P8, P12, P13, P17, P25.
- **Separate workstream (out of Part 2 render scope):** P14, P15 (DHL Wave 2 shadow).

## 19 AUDIT PAGES
Dashboard · Inbox · Shipment Overview · Documents · DHL/Customs · Warehouse · Sales · PZ/Accounting ·
Timeline · Intelligence · Proposals · Inventory · Accounting · Carriers · wFirma · API Status ·
Diagnostics · Admin/Settings · Master Data. (Plus discovered `atlas/` subdir + possible duplicate
`documents-v2` renderer — note pages outside this list as additive findings.)
