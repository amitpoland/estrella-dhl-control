# Status endpoint + sync-screen pattern (canonical contract)

> Authoritative detail for the Business Feature Completeness Standard in CLAUDE.md.
> Extracted 2026-08-19. CLAUDE.md keeps the seven requirements, the lifecycle and the
> four questions; this file keeps the Business Owner registry and the exact contracts.
> Referenced from CLAUDE.md as `docs/patterns/status-endpoint.md`.

---

### Business Owner registry

The Business Owner signs off on requirement 7. Without a named owner, Business
Verification cannot happen.

| Module | Business Owner |
|---|---|
| Customer Master | Operations |
| Accounting | Finance |
| DHL Shipping | Shipping |
| Inventory | Warehouse |
| Product Master | Product Team |
| KSeF | Finance / Compliance |
| Reports | Operations + Finance |
| AI | Operations |

When a feature reaches Business Verified, record: date, Business Owner name, and conditions.

### Canonical status API response shape

`GET /api/v1/.../status` returns JSON with fields: `healthy` (bool), `running` (bool — derived from `last_started_at > last_completed_at`), `last_started_at` (ISO 8601), `last_completed_at` (ISO 8601), `duration_ms` (int), `processed` (total seen), `created` (new inserts), `updated` (COALESCE fills), `skipped` (rejected: bad country/name/etc.), `errors` (exception count), `last_error` (string or null).

### Canonical UI layout (Client Master as reference)

Toolbar row: `+ New Client   ↻ Sync from wFirma   ⇅ Full Contractor Scan`. Status panel below: last automatic scan (timestamp + health icon), last manual scan, contractors imported / updated / skipped / errors counts, `[View Log]` link.
