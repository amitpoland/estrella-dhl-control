# Expenses Module (`expenses` / wydatki / koszty)

⚠️ **This module's API write-support status is genuinely uncertain from public sources — read the caveats below before building automation on it.** Unlike invoices/contractors/goods, the evidence here is thinner and partly contradictory across sources of different ages, so treat this file as "what's known" plus explicit flags on what to verify, not a fully confirmed reference like the other files in this skill.

## What's relevant to Estrella Jewels

The `expenses` module covers the **purchase side** — recording costs, including purchase invoices from Indian suppliers (Estrella Jewels LLP and others) into the Poland entity's books. This is the wydatki (expenses)/księgowanie wydatków (booking expenses) area of wFirma, distinct from `invoices` (the sales side already covered in `invoices.md`).

## Reading expenses via API — confirmed

The community SDK (`webit/w-firma-api`) exposes an `expensesApi()` with `find`/`get`-style querying (confirmed pattern: filtering expenses by date range with `Conditions::and(Conditions::ge('date', ...), Conditions::le('date', ...))`, same `Parameters`/`Conditions`/`Order`/`Pagination` pattern as every other module — see `query-syntax.md`). Reading/listing existing expense records is workable.

## Writing (adding) expenses via API — NOT reliably confirmed, verify before relying on it

Evidence is mixed:
- A wFirma-forum thread has a user requesting the ability to **add** cost/expense invoices via API, with wFirma support's reply being that they'd **pass the suggestion along to the technical department** — phrasing that implies write support did **not** exist at the time of that thread, and was only a feature request, not a confirmation of existing capability.
- Separately, a community SDK page lists "Basic support for the following modules: expenses (details)" alongside full support for invoices/contractors/etc. — "Basic support" suggests more limited functionality than the fully-modeled modules, consistent with read-heavy/write-limited support.

**Action for this project**: before designing any automated expense-booking flow (e.g. auto-recording Indian supplier purchase invoices into wFirma), explicitly test `POST /expenses/add` (or the equivalent current action name — verify against doc.wfirma.pl, since this file cannot confirm the exact endpoint/payload shape) against `test.api2.wfirma.pl` first. If it's unsupported or has changed since these sources were gathered, the fallback is: expenses get entered in the wFirma UI by Izabela/Tejal (finance/accounts) rather than automated, and the integration's role is limited to surfacing what needs to be entered (e.g. a report of supplier invoices pending booking) rather than writing the expense itself.

## The UI-side expense workflow (for context / to know what any automation would need to replicate)

Booking a cost in wFirma (WYDATKI » KSIĘGOWANIE » DODAJ) requires choosing a document type:
- For VAT-registered accounts: **faktura** (VAT invoice), **faktura (bez VAT)** (non-VAT invoice), or **dowód wewnętrzny** (internal proof/voucher).
- For VAT-exempt accounts: **wydatek** (expense) or **dowód wewnętrzny**.

Each requires selecting the correct **RODZAJ WYDATKU** (expense category/type — e.g. "koszty prowadzenia działalności," "zakup samochodu osobowego" with its own KŚT classification code, "wydatki związane z użytkowaniem pojazdu," etc.) for correct KPiR (Księga Przychodów i Rozchodów) column placement. This categorization is a meaningful business decision, not just metadata — if expenses are ever automated, the category mapping from "what kind of cost is this" (e.g. jewelry purchase from an Indian supplier = zakup towarów handlowych, goods for resale) to the correct RODZAJ WYDATKU needs to be explicit and reviewed by Izabela/finance, not inferred.

## Foreign-currency purchase invoices — dual exchange rate mechanism (UI-confirmed)

Directly relevant since Indian-supplier purchases are foreign-currency: wFirma's expense booking UI supports **two separate exchange rates** for a single foreign-currency purchase document:
- One rate for **income-tax purposes** (the default/standard conversion).
- A **separate rate specifically for VAT purposes**, enabled via a checkbox ("VAT w PLN") under the IMPORT Z ZAGRANICY I INNE / ZAAWANSOWANE tab, where you either pick an NBP-published date or enter a manual rate matching what's on the actual purchase invoice.

This distinction (income-tax rate vs VAT rate on the same document) is a real Polish accounting requirement, not a UI quirk — if expense automation is ever built, both rates need to be handled, not just one. This is a UI-only confirmed mechanism as of the sources gathered here; whether both rate fields are exposed on API write (if API write exists at all — see above) is unverified.

## Automatic/recurring internal vouchers (dowody wewnętrzne automatyczne)

The UI supports defining recurring internal vouchers issued automatically on a set day each month (WYDATKI » AUTOMATYCZNE » DODAJ DOWÓD AUTOMATYCZNY), with configurable payment method and numbering series, but **cannot backdate** — automatic vouchers only generate forward from the day they're configured. This is a UI-scheduling feature; no evidence of an API equivalent was found in the sources gathered for this skill.

## Attaching the source file to an expense (scan/PDF of the purchase invoice) — UI-only, and NOT usable for Estrella Jewels' Indian supplier invoices

wFirma has a well-developed feature for attaching/reading purchase-invoice files, but it is **entirely UI/cloud-integration based, with no evidence of an API upload endpoint**:

- **OCR-based booking** (Program do odczytywania faktur w chmurze): upload a PDF/PNG/JPG scan of a purchase invoice, either via WYDATKI » KSIĘGOWANIE » DODAJ » NA PODSTAWIE PLIKU (manual, one at a time or bulk), or automatically by dropping files into a synced **Dropbox or Google Drive** folder (configured under USTAWIENIA » INTEGRACJE » DYSK W CHMURZE). The system OCRs the file, pre-fills expense fields, and creates a **draft expense** (wersja robocza wydatku) for review before booking.
- The image/PDF file itself becomes permanently attached to the resulting expense record and is viewable later (PODGLĄD DOKUMENTÓW sub-tab) — this is how "the file is saved with the expense document" works in wFirma: it's inherent to the OCR-based creation flow, not a separate upload step.
- ⚠️ **Critical limitation confirmed directly in wFirma's own documentation: this OCR feature does NOT work for foreign-language or foreign-currency invoices, corrections, or advance/prepayment invoices** ("Funkcja ta nie dotyczy faktur zagranicznych (obcojęzycznych oraz walutowych), faktur korygujących oraz faktur zaliczkowych"). **This directly rules out using OCR for Estrella Jewels' Indian-supplier purchase invoices** (Estrella Jewels LLP and others) — those are foreign-language and foreign-currency by definition. For those, expenses would need to be entered manually (with the source file attached manually, if that's supported outside the OCR flow — not separately confirmed) rather than via the OCR/cloud-folder shortcut.
- No API endpoint for uploading a file to attach to an expense record (via OCR or otherwise) was found in any source gathered for this skill. Combined with the uncertainty around `/expenses/add` itself (see above), file-attached expense automation for foreign supplier invoices looks, on current evidence, **not achievable via the API at all** — it would need to remain a manual UI step for Izabela/Tejal, with the integration's role limited to (a) flagging which supplier invoices need booking, and (b) possibly pre-computing the dual exchange rate (VAT rate vs income-tax rate — see `currency.md`) so the person booking it manually has the numbers ready.
- **If the goal is to replicate wFirma's OCR experience yourself** (upload a foreign-language/foreign-currency Indian-supplier invoice → get structured data → review → save) since wFirma's own version won't handle these documents, see `custom-invoice-ocr-build.md` for engine options and an architecture pattern matching this project's stack.



Given the uncertainty here, if expenses/wydatki automation becomes a real requirement for this project:
1. First confirm current write capability by testing directly against `test.api2.wfirma.pl` (see `auth.md`) rather than trusting either source above, since they may be outdated.
2. If write is unsupported, scope the integration to **read-only reconciliation** (matching what's already booked in wFirma against what the external system expects) rather than promising automated booking.
3. Escalate to the user (Amit) explicitly if a stakeholder requests automated expense booking and testing confirms it's not API-writable — this is exactly the kind of "not currently possible" finding that should be flagged rather than worked around silently, per this skill's general philosophy (see `warehouse-goods.md` for the same pattern applied to warehouse documents).
