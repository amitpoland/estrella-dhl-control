---
name: wfirma-api-integration
description: "Deep reference and implementation guide for integrating with wFirma.pl — both the developer API (doc.wfirma.pl — invoices/faktury, contractors/kontrahenci, warehouse/magazyn stock, expenses/koszty, webhooks/notifications, KSeF, auth) and the underlying product/UI behavior (pomoc.wfirma.pl help center) that explains why the API behaves the way it does. Use this skill whenever the user is building, debugging, or extending any integration with wFirma — Estrella Jewels accounting/DHL system, e-commerce sync, invoice automation, stock sync, or any custom app talking to api2.wfirma.pl. Trigger this proactively any time wFirma, 'W firma', 'wfirma API', faktury/kontrahenci/magazyn/webhooks in a wFirma context, KSeF integration, or api2.wfirma.pl / pomoc.wfirma.pl comes up — even if the user doesn't say 'skill' or 'API docs' explicitly. Also use when reviewing existing wFirma integration code, diagnosing wFirma API errors, or deciding where in the wFirma data model (or product UI) a piece of functionality belongs."
---

# wFirma API Integration Skill

Deep, project-oriented knowledge base for wFirma.pl's REST-ish API (`api2.wfirma.pl`, documented at doc.wfirma.pl). This skill exists so Claude never "gets stuck" building against wFirma — every request/response convention, every known gotcha, and every module's real-world behavior (not just the happy path) is captured here, sourced from the official docs, the wFirma forum, and real integrator experience.

**Do not re-derive wFirma conventions from first principles or guess field names.** Read the relevant reference file below before writing any request payload, query, or webhook handler. wFirma's API has several non-obvious behaviors (see `references/gotchas.md`) that silently produce wrong data or 500 errors if skipped.

## How to use this skill

1. **Identify which wFirma module(s) the task touches** — invoices, contractors, warehouse/goods, expenses, webhooks, or auth — and read the matching reference file(s) before writing code.
2. **Always read `references/gotchas.md` first** for any task that isn't a pure read. It is short and prevents the most common "why is this failing" loops.
3. **Confirm auth method** before writing request code: this project uses **API Key** (accessKey + secretKey + appKey) — see `references/auth.md`. Never invent OAuth code unless the user explicitly asks for OAuth.
4. **Never fabricate field names, endpoints, or error codes.** If something isn't covered in the reference files and you're not certain, say so explicitly and either (a) recommend a test call against `test.api2.wfirma.pl` first, or (b) ask the user to check doc.wfirma.pl for that specific module — do not guess and silently ship it.
5. **When something looks wrong or a request fails**, check `references/gotchas.md` and `references/error-handling.md` before assuming it's a bug in the user's code — many wFirma "bugs" are documented quirks (numbering of nested branches, contractor vs contractor_detail id, negative stock blocked, etc).
6. **When a question is about business/UI behavior rather than API mechanics** ("why does this work this way," "is this even possible in wFirma," "what does the UI equivalent look like"), consult `references/ui-help-center-index.md` — it indexes wFirma's full product help center (pomoc.wfirma.pl) and points to the specific article to fetch live, rather than this skill trying to statically mirror a help center that changes weekly.

## Reference files

| File | Read this when... |
|---|---|
| `references/auth.md` | Setting up or debugging authentication (API Key headers, company_id, scopes) |
| `references/request-response-conventions.md` | Building ANY request/response — the envelope structure, module branch naming, JSON numbering quirk |
| `references/query-syntax.md` | Writing `find` queries — conditions, operators, sorting, pagination, fields |
| `references/invoices.md` | Creating/editing/reading invoices, invoice drafts, KSeF, warehouse_type |
| `references/proforma-reservations-flow.md` | **Read this for the full reservation → proforma → invoice sales flow** (the actual Estrella Jewels document lifecycle). Covers what's API-writable at each stage and the fact that "converting" a proforma to an invoice is NOT a single API call |
| `references/currency.md` | Multi-currency invoices, the `currency`/`currency_exchange` fields, and the WDT-specific NBP-rate rule (critical for Estrella Jewels' EU sales) |
| `references/series-and-numbering.md` | Invoice/proforma numbering fields (`fullnumber`, `number`, `series.id`), why numbering is locked by default, and why series aren't shared across document types |
| `references/payment-and-contractor-master.md` | Payment method/terms fields (`paymentmethod`, `paymentdate`, `paymentstate`), computing payment due dates, and the full contractor master field set (bank details, discount, the undocumented `contractor_id` query field) |
| `references/expenses.md` | The wydatki/expenses (purchase-side) module — **write support is unconfirmed, read this before promising any expense-automation feature** — also covers why file-attached OCR expense booking doesn't work for foreign (Indian supplier) invoices |
| `references/document-output.md` | Downloading documents as PDF, emailing documents, printing WZ/PZ warehouse documents, and customizing the `description`/notes field — read this for any "get the document out" or "put this text on the printout" task |
| `references/custom-invoice-ocr-build.md` | **Not wFirma-specific** — how to build your own invoice-OCR upload/review feature in Atlas/PZ, since wFirma's own OCR doesn't work for foreign-language/foreign-currency invoices (see `expenses.md`). Covers extraction-engine options and an architecture pattern matching this project's FastAPI + SQLite stack |
| `references/contractors.md` | Contractor CRUD, the Contractor vs ContractorDetail id trap |
| `references/warehouse-goods.md` | Stock levels, goods module — and the hard limit: **no warehouse document API** |
| `references/webhooks.md` | Setting up/consuming webhooks (KSeF status, stock changes, payments) |
| `references/error-handling.md` | Error response shapes, DENIED_SCOPE_REQUESTED, per-field validation errors |
| `references/gotchas.md` | **Read this before writing non-trivial code.** Curated list of things that silently break integrations |
| `references/ui-help-center-index.md` | You need business-process/UI context beyond raw API mechanics — e.g. "why does the API behave this way," "is this even possible without the API," or "what's the UI-side equivalent of this field." Indexes pomoc.wfirma.pl (wFirma's full product help center) and tells you which specific article to fetch live rather than trying to memorize a help center that changes weekly |

## Project context (Estrella Jewels)

This skill is being used for the Estrella Jewels accounting/DHL/inventory integration. Keep in mind:
- Estrella Jewels operates across India (Stella Jewels / Antalia Jewellery) and Poland (Super Fashion) — if the wFirma company in question is VAT-registered in Poland, KSeF (Krajowy System e-Faktur) behavior in `references/invoices.md` and `references/webhooks.md` is directly relevant to any invoice-issuing code path.
- Auth = API Key. Store `accessKey`, `secretKey`, `appKey`, and the numeric `company_id` as config/secrets, never hardcoded.
- If the integration needs to reflect stock movements from wFirma's warehouse module, read `references/warehouse-goods.md` **before** designing that part of the system — the warehouse *documents* (PZ/WZ/RW/PW/MM) are not directly API-writable, which materially affects architecture (see gotchas).

## When you're not sure

wFirma's official docs at doc.wfirma.pl are sometimes incomplete for edge cases (documented in the forum by multiple integrators). If a reference file doesn't answer the question:
1. Say explicitly: "doc.wfirma.pl doesn't fully specify this — recommend testing against test.api2.wfirma.pl first."
2. Suggest the safest fallback (e.g., testing on the sandbox company, or wrapping the call defensively and logging the raw response).
3. Do not present a guess as documented fact.
