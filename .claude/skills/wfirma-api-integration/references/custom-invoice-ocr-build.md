# Building Your Own Invoice-OCR Feature (to replace wFirma's OCR for foreign supplier invoices)

**This file is NOT about the wFirma API** — it's general engineering guidance, included in this skill because it directly answers the gap identified in `expenses.md`: wFirma's own OCR-in-the-cloud feature explicitly excludes foreign-language/foreign-currency invoices, which rules it out for Estrella Jewels' Indian-supplier documents (Estrella Jewels LLP, etc.). If Atlas/PZ needs an equivalent "upload a scan → get structured data → save the document" experience for those invoices, that has to be built independently and then, where relevant, the extracted data can feed into a wFirma `/invoices/add` (for the eventual sales side) or into a manually-reviewed expense entry (since expense write-via-API is unconfirmed — see `expenses.md`).

## What wFirma's OCR UX actually does (the experience to replicate)

1. User uploads/drops a PDF/PNG/JPG (manually, or via a synced Dropbox/Google Drive folder).
2. System OCRs it and extracts: contractor/supplier info, invoice number, dates, line items, amounts, VAT.
3. A **draft** record is created for human review (not committed automatically).
4. User reviews the draft side-by-side with the source image, corrects any misreads, and confirms/saves.
5. The source file stays permanently attached to the resulting record for later reference.

This five-step pattern (upload → extract → draft → review-with-source-visible → confirm-and-attach) is the right UX to replicate regardless of which extraction engine you use underneath — the review step matters as much as the extraction accuracy, especially for foreign-language documents where automated extraction will be less reliable.

## Extraction engine options (as of current landscape)

| Approach | Strengths | Weaknesses | Fit for India→Poland jewelry invoices |
|---|---|---|---|
| **Claude with vision/PDF input** (you already have Anthropic API access via this project's Claude Code usage) | No new vendor/billing relationship; strong at reasoning over messy/inconsistent layouts and mixed-language documents; can be prompted with your exact target schema (contractor fields, line items, HS/CN codes, currency) and asked to also flag low-confidence fields for review; single API call, no separate OCR-then-parse pipeline needed | Slower per-page than specialized OCR (multimodal LLMs are generally the slowest tier); table/line-item extraction is good but should still be spot-checked against specialized-OCR benchmarks before trusting it blind for line-item-heavy documents | **Strong fit** — your invoices are exactly the "inconsistent layouts, mixed language, needs contextual understanding" case where LLM-vision approaches outperform template-based OCR, and you avoid adding AWS/Azure/GCP as a new dependency for a team already standardized on Claude/Claude Code |
| **AWS Textract (AnalyzeExpense)** | Cheapest at scale for structured extraction; strong line-item/table accuracy on clean documents; fast (1–3s/page) | Weaker on non-English/non-Latin-script content and inconsistent international layouts; you'd own more of the field-mapping logic yourself | Weaker fit unless supplier invoices are consistently English and reasonably standardized |
| **Azure AI Document Intelligence (prebuilt invoice model)** | Strong multilingual support (80+ languages), good accuracy on older/varied invoice formats, reasonable custom-model training time (~30 min) if you need a tuned extractor | Introduces a new cloud vendor/billing relationship; mid-range pricing | Reasonable fit given multilingual need, if you want a dedicated cloud OCR vendor rather than LLM-based |
| **Google Document AI (Invoice Parser)** | Fits well if already GCP-native | Weakest invoice-specific accuracy in independent 2026 benchmarks, notably poor table/line-item parsing (as low as 40% on some structured-table tests) | Not recommended as the primary engine given the accuracy gap on tables |
| **Dedicated invoice-extraction APIs (Mindee, Veryfi, etc.)** | Fastest integration (single REST call, structured JSON out of the box), purpose-built for invoices specifically | Smaller vendor, another billing relationship, generally cost more per page than raw cloud OCR at scale | Worth evaluating if you want an off-the-shelf structured-output API without building your own field-mapping layer |
| **Open-source (Tesseract + custom parsing)** | No per-page cost, fully offline/air-gapped if needed | Weakest raw accuracy of all options tested in 2026 benchmarks; you build 100% of the field-extraction logic yourself on top of raw OCR text | Only worth it if data residency/offline requirements rule out every API-based option — not recommended as a first choice here |

**Recommendation for this project**: given (a) you already operate inside Claude Code with Anthropic API access, (b) the documents are genuinely messy multi-language/multi-currency cross-border invoices (exactly the case where template-based OCR struggles and contextual LLM extraction tends to win), and (c) you don't want another cloud vendor relationship layered onto an already multi-vendor stack (DHL, wFirma, Zoho, Cloudflare) — **start with Claude vision/PDF extraction** for the supplier-invoice reading feature, and only introduce a dedicated OCR vendor later if line-item accuracy on a specific document type proves insufficient after real-world testing.

## Architecture pattern for Atlas/PZ (FastAPI + SQLite + vanilla HTML/Babel JSX)

```
1. Upload endpoint (FastAPI):
   POST /api/supplier-invoices/upload
   - Accept PDF/PNG/JPG, store the raw file (filesystem or blob column), generate a record id.

2. Extraction step (async or synchronous depending on volume):
   - Send the file (as base64/document content) to the extraction engine (e.g. Claude with a
     document/image content block) with a strict prompt: "Extract these exact fields as JSON:
     supplier name, supplier address, invoice number, invoice date, currency, line items
     (description, qty, unit price, HS/CN code if present), total amount, VAT/tax details if any.
     If a field is unclear or absent, return null and add it to a `needs_review` list rather
     than guessing."
   - Store the raw extraction JSON alongside the source file — never discard the raw model
     output, even after a human edits the final record (useful for debugging misreads later).

3. Draft record (SQLite):
   - Insert a draft row with status='pending_review', the extracted fields, a reference to the
     source file, and the `needs_review` flags from the extraction step.

4. Review UI (matches your existing PZ app's operator-gated pattern):
   - Split-pane view: source file image/PDF on one side, editable extracted fields on the other
     (same visual pattern wFirma's own OCR review screen uses, and consistent with this
     project's existing operator-review-before-commit governance model already used for PZ
     clearance stages).
   - Operator corrects any misreads, confirms, and the record moves to status='confirmed'.

5. Downstream action on confirm:
   - If this feeds a wFirma expense: since expense write via API is unconfirmed (see
     `expenses.md`), surface the confirmed, structured data to whoever manually books it in the
     wFirma UI — at minimum this saves the manual data-entry step even though the wFirma write
     itself stays manual.
   - If this feeds something else in Atlas (e.g. a PZ reconciliation record), write directly to
     your own schema — same customs-value-freeze discipline as the rest of the project (source
     document is truth; don't let an OCR misread silently override figures already confirmed
     elsewhere).
```

## Practical cautions specific to this use case

- **Confidence flagging matters more than raw accuracy** for cross-border invoices with inconsistent layouts. Design the extraction prompt/schema to explicitly separate "high confidence" fields from "needs human check" fields, rather than presenting everything as equally certain — this mirrors wFirma's own draft-then-review pattern and fits this project's existing evidence-standard discipline (VERIFIED / INFERRED / NO EVIDENCE).
- **Never let extracted figures silently override source-of-truth documents already in the system** — this project's customs-value-freeze principle (qty, unit price, currency, freight, duty, totals always carried from source documents, never recomputed) applies here too: an OCR extraction is a *convenience for data entry*, not a new source of truth that should overwrite a packing list or invoice PDF already on file.
- **Keep the raw source file and raw model output retained**, not just the final structured record — needed for any future audit trail or re-extraction if the schema/prompt improves later.
- **Test the extraction prompt against a real sample set of actual Indian-supplier invoices early** (a handful of Estrella Jewels LLP documents) rather than assuming generic invoice-extraction performance will transfer — the specific layout quirks of your actual suppliers matter more than any generic benchmark.
