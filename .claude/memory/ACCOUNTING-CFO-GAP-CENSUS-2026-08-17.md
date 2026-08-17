# Accounting / CFO MIS — Production Gap Census

**Baseline:** production `6bc90bd61cf20a5c029cdefc8fe2cb64fafa0ae7` (2026-08-17)
**Visual reference:** Claude artifact `e12c2132-b5f4-4ae0-9226-620f43a41524` timed out.
**Fallback:** Stage A hub `docs/atlas/design-handoff/2026-05-30/design-bundle/estrella-dashboard/project/accounting-hub.jsx` + live V2 `service/app/static/v2/accounting-hub.jsx` / `ledgers-page.jsx`.

Closed invariants from PR #1269 are **out of scope**. Known limitations (2 unapplied payments, sentinel-0, advisory cross-contractor) are **not reopen triggers**.

| Surface | Verdict | Notes |
|---|---|---|
| Overview | PARTIAL | Live PI count + AR KPI. Sales Overdue / Supplier Payable still pending tiles. |
| Proforma | PARTIAL | Live drafts; status-only filter, not shared ARF. |
| Invoice | MATCH UI / PARTIAL API | `AccountingRegisterFilter` in AccDocGrid; search/ccy/status client-side. |
| Credit Note | MATCH UI / PARTIAL API | Same as Invoice. |
| WZ | PARTIAL | ARF without Currency/Status (warehouse semantics). AWB authority preserved. |
| PZ | PARTIAL | Same; AWB authority preserved. |
| PW | PARTIAL | Live empty ≠ failure; HTML sanitized. |
| RW | PARTIAL | Same as PW. |
| MM | INTENTIONALLY DIFFERENT | Honest unsupported (no wFirma MM controller). |
| Client Balance | PARTIAL | Hub uses activity quarter `from/to`, not as-of position. |
| Client Ledger | MATCH | Tally opening→period→closing. Reference model. |
| Supplier Balance | MISSING as dedicated rail | Nested in Supplier Ledger roster (acceptable if labelled). |
| Supplier Ledger | PARTIAL | Window dump; running from 0; no opening/closing; `as_of` ignored vs `filters.as_of`. |
| Insurance Export | PARTIAL / INTENTIONALLY DIFFERENT filter | Private month-step + declaration composer; not a document register. |
| Treasury | INTENTIONALLY DIFFERENT | As-of snapshot (correct). No trend series. No PDF. |
| CFO / Management Analysis | MATCH hierarchy | Liquidity→…→Exceptions. Page-level source/freshness, not per-KPI. |
| Receivables Analysis | MATCH | Inside MA; per-currency; no FX merge. |
| Payables Analysis | MATCH | Inside MA. |
| Liquidity | MATCH | Treasury.sqlite per currency. |
| Working Capital | MATCH | Per-currency AR−AP. |
| Currency Exposure | MISSING | Needs inventory valuation feed — not invented. |
| Data Quality / Exceptions | PARTIAL | Raw `data_quality` keys; aging buckets exist but not a worklist. |
| wFirma Sync | PARTIAL | Status API richer (dead letters, WH-009) than UI. |
| Master Data | MATCH | Navigate. |
| Audit Trail | MATCH | Live audit. |

**Filters:** Shared `AccountingRegisterFilter` used by AccDocGrid only. Ledgers use `LdgPeriodBar`. Insurance keeps composer-specific month-step (semantic reason).

**PDFs:** Same builders as JSON. Supplier PDF has no opening/closing. Windows Unicode fonts missing on statement renderer (Insurance has them). Source/freshness missing. Footer `Page n` not `X of Y`. `generated_at` = as-of, not clock. Treasury PDF missing.

**Webhooks:** WH-006 MATCH; WH-007 API MATCH / UI PARTIAL; WH-008 PARTIAL; WH-009 API MATCH / UI MISSING. WH-002/003/invoice round-trip need genuine events. WH-004 inventory mutation stays blocked (OI-10).
