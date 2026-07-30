# PR #925 production non-writing verification + EOS v1.3 deploy closeout

Date: 2026-07-16 evening · Verifier: Claude Fable 5 session · Record: PROF 160/2026 (draft 67)

## Deployment verification (re-run after operator's corrected sync) — PASS

- origin/main = deployed source SHA **a853503b** (contains #928 `1f02811b` + #925 squash).
- Five-file SHA256: **all MATCH** (routes_proforma 9BA64CD7…, customer_master E390E78D…,
  payload_disclosure A72C5DC6…, proforma_to_invoice 86066A56…, proforma-detail.jsx 458CA6B4…).
- Five campaign markers: **all FOUND** in C:\PZ\app.
- PZService STATE: 4 RUNNING (fresh PID 19584); stderr tail = clean uvicorn startup, no tracebacks.
- Liveness: local + public /api/v1/health respond (401 unauthenticated). **Authenticated**
  health via the operator's logged-in browser session: `GET /api/v1/health → 200` on
  https://pz.estrellajewels.eu (captured in network log).

## Non-writing browser verification — PROF 160/2026, production, operator Chrome session

| Check | Result |
|---|---|
| Canonical V2 page `/v2/proforma_detail?draft=67` loads | ✅ (real data: WDT 0%, VIES IE5455683P, freight 90 + insurance 11.45 saved on draft) |
| Convert modal opens | ✅ |
| Exactly ONE disclose-convert request per open | ✅ `GET /api/v1/proforma/draft/67/disclose-convert → 200` — single request with network tracking armed |
| Five invoice lines | ✅ 3× "pierścionek ze złota próby 18K…RING" (958.00 / 1083.00 / 1231.00) + Freight + Insurance |
| Freight USD 90.00 | ✅ line rendered |
| Insurance USD 11.45 | ✅ line rendered (full Future Generali wording) |
| Grand total USD 3,373.45 | ✅ "Total (USD) 3373.45" |
| Series ID + readable name | ✅ D6-step-3 form: series omitted → "(wFirma contractor default)" readable label + LIVE ADVISORY: "WDT invoice series not configured in Customer Master for 'MICHAEL KENNY LLP'. Set preferred_wdt_invoice_series_id on the customer record." |
| Payment & Ownership Terms | ✅ payment terms visible (transfer · 90 days pre-filled); the full ownership-terms sentence is included in the invoice **description at execute** (unit-pinned: terms present exactly once, back-reference first) — the sentence itself is not rendered as modal text (per ratified Fix-5 scope; optional follow-up: surface description preview in disclosure) |
| Honest lineage wording | ✅ "Creates a new final invoice in wFirma referencing this proforma number. wFirma has no native proforma→invoice conversion; lineage is recorded via the invoice description back-reference and the local conversion link." |
| Browser console errors | ✅ none |
| Final confirmation | ✅ NEVER pressed (checkbox unchecked, button disabled; modal closed via Cancel) |
| No wFirma document touched | ✅ proven: `proforma_invoice_links` rows for 488979043 = **0**; draft 67 `wfirma_invoice_id` = None |

Screenshots: ss_3819gxx8s (modal top: payload preview, honest wording, 3373.45),
ss_33090t9cj / ss_4665igh61 (wFirma preview: 5 line(s), series advisory, audit block,
unchecked confirm). Payment-due row displays the source proforma's date; execute
recomputes from payment_days=90 via compute_payment_due (never before invoice date).

## ⚠ FLAG POSTURE FINDING (the one deviation from the session's stated gates)

`C:\PZ\.env` line: **`WFIRMA_CREATE_INVOICE_ALLOWED=true`** — file last modified
**2026-07-10 17:20**, i.e. PRE-EXISTING since before this campaign; not changed by any
campaign session (this matches the repo memory "all-ON wFirma flags standing posture",
but contradicts this verification's expected "remains false"). Live writes remain
guarded by confirm-token + operator session + checkbox + duplicate-link guard + payload
hash; no write occurred. **Operator decision required**: keep the standing all-ON
posture (documented reality) or set the flag false until Phase-14.

## /deploy-checklist closeout verdict

**DEPLOYED & VERIFIED (non-writing) — PASS with one flagged finding (flag posture, pre-existing).**
Rollback ready: `git revert a853503b --no-edit && git push origin main` + re-sync + restart
(operator-only). Deployed main SHA a853503b; production disk byte-identical for all
changed app files.

## Remaining items

1. Flag posture decision (above) — operator.
2. Customer Master: set `preferred_wdt_invoice_series_id` (e.g. WDT series 15827921) for
   MICHAEL KENNY LLP (and other WDT customers) before Phase-14, else the final invoice
   lands in the wFirma contractor-default series (advisory already fires in the modal).
3. Issue #927 repair (stale V1 test pins) — scheduled, exclusion registered.
4. Optional UX follow-up: render the description/terms preview text in the modal.
5. Phase-14 live single-invoice certification — SEPARATE operator-approved campaign.
