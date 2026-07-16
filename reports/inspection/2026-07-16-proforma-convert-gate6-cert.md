# GATE-6 Browser Certification — Proforma→Invoice Convert Modal (non-writing)

Campaign: wFirma Proforma→Invoice Conversion Certification & Repair (2026-07-16)
Branch: `fix/proforma-convert-certification` (off `28784270`)
Certifier: Claude Fable 5 session (operator-approved plan `campaign-breezy-stream.md`)

## Environment (disclosed test doubles)

Local uvicorn (port 8600) running the REAL app from the branch working tree, with
exactly TWO cert-only patches applied in an external launcher (never in repo code):

1. `wfirma_client.fetch_invoice_xml` → returns a canned PROF 160/2026-shaped
   proforma XML (5 invoicecontents: 958.00 + 1083.00 + 1231.00 merchandise,
   Freight 90.00, Insurance 11.45 = 3373.45 USD; contractor 199226787; series
   15827088 = proforma series; paymentmethod przelew). No live wFirma call was
   made at any point; no credentials were loaded.
2. `routes_proforma._derive_draft_readiness` → returns ready (the readiness gate
   is UNTOUCHED by this campaign and separately pinned by its own tests; the
   full sales/product-master chain it requires is out of campaign scope).

Seeded local data (dev storage, gitignored): customer_master row 199226787
(MICHAEL KENNY LLP, IE, VAT-EU set, preferred_wdt_invoice_series_id=15827921,
transfer/90 days) via `customer_master_db.upsert_customer`; proforma_drafts row
id=3 (SHIPMENT_CERT_160, status=issued, draft_state=posted, vat_context=wdt,
wfirma_proforma_id=88800160). `WFIRMA_CREATE_INVOICE_ALLOWED=false` throughout.

Production browser verification (Business Completeness requirement 6, real
production data) remains the operator's post-deploy step, as in every campaign.

## Verified in browser (`/v2/proforma_detail?draft=3` → Convert to Invoice modal)

| Check | Result |
|---|---|
| Merchandise lines | 3 (RG-2201 958.00, ER-1145 1083.00, PN-3310 1231.00) ✅ |
| Freight | 90.00 USD rendered as invoice line ✅ |
| Insurance | 11.45 USD rendered as invoice line ✅ |
| Total lines | "5 line(s)" (`data-testid=convert-line-count`) ✅ (was "0 line(s)" before RC-1 fix) |
| Grand total | 3373.45 USD (`data-testid=convert-grand-total`, server-sourced) ✅ (was 3272.00) |
| Series | 15827921 — WDT invoice series, in BOTH modal sections ✅ (was 15827088 proforma series) |
| Series name | empty + graceful note (local dictionary cache is baseline — documented R-5 path) |
| Payment method | transfer ✅ |
| Payment terms | 90 days pre-filled ✅ |
| Payment due | 2026-10-07 shown ✅ |
| Sale date | "—" (blank surfaced, not hidden) ✅ |
| FX rate | 3.6521 PLN shown ✅ |
| Honest labeling | "Creates a new final invoice in wFirma referencing this proforma number. wFirma has no native proforma→invoice conversion; lineage is recorded via the invoice description back-reference and the local conversion link." ✅ |
| Flag disclosure | WFIRMA_CREATE_INVOICE_ALLOWED shown as required ✅ |
| Console errors | none ✅ |
| disclose-convert requests on modal open | exactly ONE (duplicate fetch eliminated) ✅ |
| Final confirm | NOT pressed (per plan; live Phase-14 certification is a separate operator-gated step) |

Evidence: full modal text dump + JS assertions captured in session transcript
(pixel screenshots timed out under the in-browser Babel renderer; all checks
made via accessibility tree, page text, and DOM queries).

## Endpoint evidence (curl, same server)

`GET /api/v1/proforma/draft/3/disclose-convert` →
`series_id=15827921`, `line_count=5`, `grand_total=3373.450000 USD`,
`payload_core_hash` present (64-hex), `payment_resolved.method=transfer`,
`payment_days=90`, `series_advisories=[]`, `due_date_advisories=[]`.

## Defects found DURING certification (fixed on branch before this record)

1. **Opus review D-1 (CRITICAL)**: disclosure used a falsy `final_series_id or
   snap.series_id` fallback → hash asymmetry vs execute for validly-empty series.
   Fixed with a `None`-sentinel signature + regression tests
   (`test_empty_resolved_series_hashes_empty_not_snap_series`).
2. **Pre-existing latent bug**: `disclose_proforma_convert` locally imported a
   non-existent `customer_master_db.get_customer_master` (ImportError silently
   swallowed since introduction) → Customer Master payment defaults AND series
   never loaded in disclosure. Fixed to use the module-level alias
   (routes_proforma.py top-level `get_customer as get_customer_master`).

## Test verdict at certification time

- Six touched suites: **178 passed, 1 failed** — the failure is
  `test_dashboard_renders_two_step_convert_flow`, red on origin/main `28784270`
  before any change (V1 shipment-detail.html strings) — pre-existing baseline.
- Smoke: **63 passed, 1 skipped**. Golden: **160/160**.
