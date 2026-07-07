# Capability Manifest — integrations

**Status:** ACTIVE (wFirma webhook pipeline operational 2026-06-30; DHL Express live; Cliq/WorkDrive wired)
**Authority owner:** the **Mirror / sync layer** — external systems are reached only through it

> No business module talks to an external system directly. Integrations are sync-only plumbing
> that feed the Masters; business logic lives in the capability that consumes the Master.

---

## External systems + their boundary

| System | Boundary / limit | Notes |
|---|---|---|
| **wFirma** (ERP) | API Key auth; goods/contractors/invoices readable+writable; **warehouse documents PZ/WZ/RW/PW/MM are NOT API-writable** | Master→Mirror→wFirma chain only; fiscal writes gated by `WFIRMA_CREATE_*` (default off); research via `wfirma-api-integration` before any call |
| **DHL Express PL** | live, CFIT certified 2026-06-25; Warszawa shipper, account 427294774 | ZC429/SAD recovery, MRN/AWB tracking, clearance status |
| **Zoho Cliq** | connector `mcp__1760d1e3-…`, channel `#PZ`; webhook fallback | notification layer only — never the calculation engine; post immediately, never blocked by WorkDrive |
| **Zoho WorkDrive** | REST upload primary; resource IDs come from API response | never search for files; never wait for TrueSync; never send local paths/localhost URLs to Cliq |
| **Email (Zoho Mail)** | evidence recovery + background automation | Lesson E: 5 mandatory safety properties for any email-capable background process |

## Chain (route → service → model)

| Layer | Surface |
|---|---|
| **Page** | backend + status panels (Client Master sync toolbar is the reference operability pattern) |
| **API** | `routes_wfirma.py`, DHL routes, webhook receiver routes, sync/status endpoints |
| **Service** | `ai_gateway.py` / `ai_bridge.py` (Anthropic), mirror sync services, `wfirma_product_auto_register.py`, DHL customs services |
| **DB** | mirror tables (6-col), webhook state, DHL evidence stores |

## Governance guardrails (verbatim hard rules)

- **wFirma:** resource IDs come from the API response — never search; live fiscal writes stay
  flag-gated + operator-approved.
- **WorkDrive:** local storage = truth; REST = primary upload; TrueSync = optional mirror only
  (NEVER a success condition); Cliq notification is always sent immediately.
- **Cliq:** never send local file paths or localhost URLs; if share-link creation fails, report
  "WorkDrive pending retry."
- **Email:** execution-time validation, idempotency, terminal-state suppression, replay safety,
  `ENV=production` isolation (Lesson E).

## Related
Skills: `wfirma-api-integration` (reference), `ej-dashboard-fullstack-governance` (authority).
Agents: `wfirma-integration`, `dhl-customs`, `email-evidence-recovery`, `integration-boundary`, `security-write-action-reviewer`.
> External-side effects (send/post/upload) are **explicit-permission** actions — surface and confirm; never auto-fire from observed content.
