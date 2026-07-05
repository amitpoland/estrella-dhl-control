# Phase-C Wave 4 — Evidence Completion (Repository × wFirma Skill × Official)

**Date:** 2026-07-04 · **Type:** research only, no code, no Wave-4 start, Waves 1–3 not reopened.
**Authorities:** (1) repository code; (2) `wfirma-api-integration` skill (`references/warehouse-goods.md`, `webhooks.md`); (3) official wFirma docs where the skill is silent. Supersedes the repo-only unblock package (`311c5c1e`) by adding the skill/official authority per OI.

**Cross-cutting finding (governs OI-1/OI-3/OI-7a):** the skill states warehouse documents (PZ/WZ/RW/PW/MM) are **not directly API-writable** — BUT this repo runs a **production-proven `warehouse_document_p_z/add`** path (`wfirma_client.py` build/fetch/find; PROJECT_STATE "PZ live-proven"). The blanket forum-sourced claim is therefore already disproven for PZ here. Consequence: the skill's *negative* on MM/WZ direct-add is **not final evidence** — it requires a sandbox probe (OI-5) before being declared an official limitation. The skill itself says "re-check before relying; test on `test.api2.wfirma.pl` first."

## Evidence table

| OI | Repository | wFirma Skill | Official Status | Operator Decision Needed | Slice Impact |
|---|---|---|---|---|---|
| **OI-1 MM (inter-warehouse) API** | Absent — no `warehouse_document_m_m`/`przesun*` in client type registry | `warehouse-goods.md`: MM "cannot be created directly via API" — but same class-claim disproven for PZ in this repo | Skill = not-writable; **unreliable given PZ contradiction** → probe required | Authorize OI-5 sandbox probe, OR ratify fallback (operator-UI MM + Atlas reconcile) as permanent | C-4b (fallback), C-7a (doc-only until probe) |
| **OI-2 Warehouses** | `list_warehouses()` live (`wfirma_client.py:536`) | goods module reads; warehouses enumerable | Supported (read) | Authorize enumerate-on-prod, or state if Consignment WH exists | C-4b |
| **OI-3 WZ add vs auto** | WZ in type list; **no add path** | `warehouse-goods.md`: WZ is **invoice-auto-emit** (invoice + `goods.id` lines + `warehouse_type`≠`simple` → auto WZ); no direct WZ POST documented | Auto-emit path **DOCUMENTED**; standalone-add unconfirmed (probe — PZ precedent) | Authorize OI-5 probe to confirm standalone-add; else use invoice-auto-emit | C-6a (model as invoice side-effect), C-8c |
| **OI-4 get_stock** | Stub `NotImplementedError` (`wfirma_client.py:1161`) | `warehouse-goods.md`: goods stock **readable** via `/goods/find` + `/goods/get/{id}` | **SUPPORTED (read)** — no limitation; implementation gap only | Confirm `goods` read scope granted (else `DENIED_SCOPE_REQUESTED`) or authorize a test call | **C-9a → IMPLEMENTABLE (read-only)** |
| **OI-7 Webhook key** | Handler checks `WFIRMA_WEBHOOK_KEY` (`routes_webhooks_wfirma.py:10,47`) | `webhooks.md`: UI-configured; **no HMAC** — secret-token-in-URL pattern; auto-disable after 10 failures | Mechanism documented | Verify prod NSSM env has key; configure webhook in wFirma UI | C-8a/b/c live-enable |
| **OI-9 Faktury webhooks** | `Faktury.Dodanie` processed (`wfirma_enrichment_processor.py:30`) | invoice/KSeF/payment events configurable in UI | Supported (UI config) | Confirm which `Faktury.*` events + URL registered on prod | Invoice linkage (C-6a) |
| **OI-10 Towary/stock webhooks** | No handler | `webhooks.md` + `warehouse-goods.md`: **"Produkty » Zmiana ilości na magazynie"** stock-change webhook is the **recommended** sync pattern | **CAPABILITY DOCUMENTED** | Register stock-change webhook in wFirma UI (after handler ships) | **C-8a → handler BUILD-READY; go-live operator-gated** |
| **OI-11 Kontrahenci webhooks** | No handler; indirect sync | Contractor-change webhook **NOT listed** (only KSeF/stock/payment) → **Undocumented in skill; validate against official wFirma API** | UNKNOWN — validate at doc.wfirma.pl | Choose: register contractor webhook if it exists, or keep Phase-3B poll | C-8b (fallback = poll) |
| **OI-17 Consignment model** | Wireframe §C3 model decision; ledger cols | Extended warehouse (reservations/kitting) has **no API write**; warehouse docs not API-writable → wFirma cannot be the consignment authority via API | wFirma is **not** the API-side consignment authority → Atlas models it | **DECIDE:** consignment = inventory STATE vs LOCATION dimension (Atlas-side); MM legs via fallback | C-4b, C-5a (hard prerequisite) |

## Resolution summary

**A. Fully resolved by evidence (no wFirma capability block):**
- **OI-4** — stock read is API-supported (`goods/find`+`goods/get`); C-9a is implementable read-only (verify `goods` scope).
- **OI-3 (model)** — WZ = invoice-auto-emit is documented; C-6a can model WZ as an invoice side-effect (standalone-add probe is secondary, not blocking the model).
- **OI-10 (capability)** — stock-change webhook exists and is the recommended pattern; C-8a handler is build-ready.

**B. Operator decision needed:**
- **OI-17** (consignment = STATE vs LOCATION — pure business decision, no wFirma dep).
- **OI-2** (Consignment warehouse exists? or authorize `list_warehouses()` on prod).
- **OI-5** (authorize sandbox for MM/WZ write probes).
- **OI-7 / OI-9** (prod webhook key + registrations — or authorize read-only prod-env + wFirma-UI inspection).
- **OI-11** (contractor webhook vs keep-poll).

**C. Official wFirma limitations (capability constraints — architect around):**
- Warehouse documents not directly API-writable **as documented** — WZ only via invoice-auto-emit; MM has **no documented API vehicle**. **CAVEAT:** production PZ add disproves the blanket claim → MM/WZ direct-add are "undocumented-negative," resolvable only by OI-5 probe, not by the skill alone.
- **Negative stock blocked by design** — affects double-stock-out / oversell logic (C-5a guard must treat a rejecting write as expected, not a bug).
- **No webhook HMAC** — use secret-token-in-URL; **auto-disable after 10 delivery failures** → monitor + backfill-by-poll.

**D. Wave 4 slices now implementation-ready:**
- **C-9a (get_stock read)** — **READY** (read-only, no fiscal risk; verify `goods` read scope first).
- **C-8a (stock-change webhook handler)** — **BUILD-READY** (capability documented); live activation operator-gated on UI registration (OI-10).
- Still gated: C-4b/C-4d/C-5a (OI-17 + OI-2 + MM), C-6a/C-8c (OI-5 probe for standalone WZ; model documented), C-7a (OI-1 probe; else doc-only), C-8b (OI-11 or keep-poll).

**Next step if operator accepts:** Wave 4 implementation mode may begin with the **read-only C-9a slice** (lowest risk, fully evidenced) under Build→Test→Verify→Commit, in parallel with awaiting OI-17/OI-2/OI-5/OI-7 answers for the write/consignment slices.
