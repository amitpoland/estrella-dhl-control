# wFirma UI / Business-Process Help Center Index (pomoc.wfirma.pl)

`doc.wfirma.pl` documents the **API mechanics**. `pomoc.wfirma.pl` documents the **product/UI itself** — every feature, screenshot, and workflow, written for end users (accountants, business owners). This file exists so Claude Code can pull in **business-process context** that explains *why* the API behaves the way the other reference files describe, and can find the right page live rather than this skill trying to statically mirror a help center with hundreds of frequently-updated articles.

## Why this file is an index, not a dump

pomoc.wfirma.pl has 6 top-level categories × 5 subcategories each, with dozens of articles per subcategory, and it's actively maintained (articles dated as recently as this week were seen during research). Copying it wholesale into this skill would (a) bloat SKILL.md's context budget, (b) go stale fast, and (c) violate the progressive-disclosure principle this skill is built on. Instead: use this index to identify the right category/article, then **fetch that specific URL live** when the task needs it.

**If Claude Code has live web-fetch/browsing available**: fetch the specific pomoc.wfirma.pl URL below when a task needs UI-behavior context beyond what's in this skill's other reference files.
**If Claude Code does NOT have live web access in a given environment**: tell the user which pomoc.wfirma.pl article is relevant and ask them to paste its content, rather than guessing at UI behavior from memory.

## Site structure (category → subcategory → base URL)

| Category | Subcategories | Base URL |
|---|---|---|
| **System** | Pakiety, Pierwsze kroki, Ustawienia podstawowe, **Serie dokumentów**, **Integracje** | `pomoc.wfirma.pl/system` |
| **Fakturowanie** (Invoicing) | **Wystawianie faktur**, **CRM**, **KSeF**, Katalog towarów i usług, Analizy sprzedaży | `pomoc.wfirma.pl/fakturowanie` |
| **Księgowość** (Accounting) | Księgi i rejestry podatkowe, Księga handlowa, Środki trwałe, Kasa/Bank, Podatki i sprawozdawczość | `pomoc.wfirma.pl/ksiegowosc` |
| **Magazyn** (Warehouse) | **Magazyn towarów**, Produkcja, Analizy magazynowe, Grupy cenowe, **Ecommerce** | `pomoc.wfirma.pl/magazyn` |
| **Kadry i płace** (HR/Payroll) | Kadry, Płace, Ubezpieczenia ZUS, Podatki i składki, Zadania i terminarz | `pomoc.wfirma.pl/kadry-i-place` |
| **Biura rachunkowe** (Accounting offices / multi-company) | System dla biur, e-Biuro rachunkowe, Zarządzanie sprzedażą, Współpraca z klientami, Zdobywanie klientów | `pomoc.wfirma.pl/biura-rachunkowe` |

**Bolded** subcategories are the ones most relevant to the Estrella Jewels project (invoicing, KSeF, contractors/CRM, warehouse, integrations, numbering).

## High-value specific articles for this project

Fetch these directly when the task touches the topic — they're the highest-signal pages found during research, cross-referenced with what's already in `invoices.md` / `warehouse-goods.md` / `webhooks.md`:

| Topic | URL | Relevance |
|---|---|---|
| Draft invoices (UI-side) | `pomoc.wfirma.pl/-wersje-robocze-faktur-sprzedazy-jak-wprowadzic-w-systemie-wfirma-pl` | Cross-reference with `invoices.md` draft behavior |
| KSeF overview | `pomoc.wfirma.pl/-ksef-czyli-krajowy-system-e-faktur` | Business-process context behind the KSeF gotchas in `invoices.md` |
| KSeF certificate authorization | `pomoc.wfirma.pl/-autoryzacja-za-pomoca-certyfikatow-w-ksef-w-systemie-wfirma-pl` | Exact UI steps for the per-user KSeF authorization gotcha (#7 in `gotchas.md`) |
| KSeF integration troubleshooting | `pomoc.wfirma.pl/-jak-rozwiazac-problemy-z-integracja-ksef-w-systemie-wfirma-pl` | First stop when a KSeF send fails and the cause isn't obvious from the API error |
| Editing an invoice already sent to KSeF | `pomoc.wfirma.pl/-modyfikowanie-wystawionej-faktury` | What's still editable post-KSeF-send — relevant before assuming `/invoices/edit` will work on a finalized document |
| API reference article (UI-side mirror of doc.wfirma.pl) | `pomoc.wfirma.pl/-api-interfejs-dla-programistow` | Sometimes has newer prose explanations (e.g. KSeF/API interplay) ahead of doc.wfirma.pl being updated — check both |
| Numbering series (Serie dokumentów) | `pomoc.wfirma.pl/-wybor-serii-numeracji-dokumentow` | How numbering series map to the `series.id` field used in invoice add payloads (see `invoices.md`) |
| Changing an already-issued invoice number | `pomoc.wfirma.pl/-jak-zmienic-numer-faktury` | Confirms numbering is automatic and locked by default via an "sprawdzanie poprawności numeracji faktur i blokada modyfikacji numeru" setting — relevant if the integration needs predictable/custom numbering |
| CRM — all contractor info in one place | `pomoc.wfirma.pl/-wszystkie-informacje-o-kontrahencie-w-jednym-miejscu` | UI-side context for `contractors.md` |
| Changing contractor data | `pomoc.wfirma.pl/-zmiana-danych-kontrahenta` | Relevant if the project needs to reconcile contractor edits made in the UI vs via API |
| Magazyn — monitoring & stock control | `pomoc.wfirma.pl/-magazyn` | Full UI picture behind the API limitations documented in `warehouse-goods.md` |
| Magazyn towarów (product warehouse) | `pomoc.wfirma.pl/magazyn/magazyn-towarow` | Product management, CSV import, hiding products — none of which have API equivalents (see `warehouse-goods.md`) |
| Import produktów (CSV) | `pomoc.wfirma.pl/-import-produktow-jak-wykonac-w-systemie` | Confirms bulk product import is UI-only (referenced in `warehouse-goods.md`) |
| E-commerce integrations overview | `pomoc.wfirma.pl/-integracje-ze-sklepami-internetowymi` | Reference architecture pattern — how existing shop-platform integrations (WooCommerce, Prestashop, etc.) handle the invoice+webhook+stock pattern this project also needs |
| Webhook mechanism (UI side) | `pomoc.wfirma.pl/-mechanizm-tworzenia-webhookow` | UI configuration screenshots to pair with `webhooks.md` |
| Wsparcie techniczne (support) | `pomoc.wfirma.pl/-wsparcie-techniczne` | Where to point the user if something needs wFirma support directly rather than API troubleshooting |

## When to consult this file vs. the other reference files

| Situation | Go to |
|---|---|
| "What does this API field/endpoint do?" | `invoices.md` / `contractors.md` / `warehouse-goods.md` / etc. first |
| "Why does the API behave this way?" / "What's the UI equivalent?" / "Is this feature even possible without the API?" | This file → fetch the specific pomoc.wfirma.pl article |
| "The API failed and I don't know why" | `error-handling.md` + `gotchas.md` first; if still unclear, check the matching pomoc.wfirma.pl troubleshooting article (e.g. KSeF troubleshooting above) |
| "Does wFirma support X at all?" (any ambiguity about whether something is API-reachable or UI-only) | Check `gotchas.md` and `warehouse-goods.md` for known API gaps first — if not covered, fetch the relevant pomoc.wfirma.pl category page to confirm the feature exists in the product before assuming it's buildable |

## Maintenance note

This index was built from a live fetch of pomoc.wfirma.pl's navigation as of the skill's creation date. Article URLs at wFirma are generally stable (slug-based, not ID-based) but new articles are added frequently and old ones occasionally get renamed. If a URL in this table 404s, search the relevant category page (e.g. `pomoc.wfirma.pl/fakturowanie/ksef`) for the current equivalent rather than assuming the topic is no longer documented.
