# Webhooks / Notifications

Webhooks are wFirma's push mechanism — an alternative to polling the API. They send a **POST request to a URL you configure** immediately after a defined action happens in wFirma, rather than requiring your app to poll on a schedule.

## Configuring a webhook

Configured entirely in the wFirma UI (not via API, as of last check):
- Ustawienia (Settings) » Inne (Other) » Webhooks » Dodaj (Add)
- You select the **triggering event** and provide the **destination URL**.
- Common events relevant to this project:
  - **KSeF status/result** (after invoice processing completes, success or error) — see `invoices.md` for why this matters more than polling for KSeF-enabled invoices.
  - **Produkty » Zmiana ilości na magazynie** (Products » Stock quantity change) — the recommended way to keep an external system's stock numbers in sync without polling `/goods/find` repeatedly.
  - Payment-related events (e.g. payment added against an invoice) — useful for reconciling paid/unpaid status without polling.

## Reliability characteristics — design your receiver defensively

- **Auto-disable after repeated failures**: if 10 consecutive delivery attempts fail, wFirma **automatically disables the webhook**. It must be manually re-enabled in the UI — there's no automatic retry-forever or automatic re-enable. **Implication:** monitor webhook health; if your receiving endpoint has extended downtime, assume the webhook will silently stop firing and you'll need to re-enable it manually (and probably backfill via polling for the gap).
- **Delivery logs are visible in the UI** — clicking the icon next to a sent webhook request shows any error logs, useful for debugging delivery failures without needing server-side logging on your end (though you should still log server-side).
- **No documented signature/HMAC verification scheme in the base wFirma webhook mechanism** (unlike some other providers, e.g. Tpay's JWS-signed webhooks). Treat the receiving endpoint like any other public unauthenticated inbound webhook:
  - Use HTTPS.
  - Consider putting a secret token in the URL path/query string itself as a lightweight verification mechanism (a pattern used by third-party wFirma integrations like the WooCommerce plugin, which defines a per-integration Token embedded in the webhook URL) since there's no separate header-based signature to check.
  - Validate the payload shape defensively (same envelope conventions as regular API responses — see `request-response-conventions.md`) before acting on it.
- **Idempotency**: design the receiver to be safe against duplicate/out-of-order delivery (general webhook best practice — wFirma doesn't document strong duplicate-suppression guarantees). Don't perform non-idempotent side effects (e.g., decrementing stock again) purely because a webhook fired again for the same event — key your processing off the underlying record's ID/state, not "a webhook arrived."

## Data format

Webhooks can typically be configured to POST JSON (confirmed via third-party integration docs, e.g. WooCommerce plugin config selects "Typ danych: JSON"). Parse the payload using the same module/branch conventions as the rest of the API (`request-response-conventions.md`).

## When to prefer webhook over polling in this project

| Need | Preferred approach |
|---|---|
| KSeF status/number after issuing an invoice | Webhook (avoids polling delay/rate limit exposure) |
| Stock level changes for external sync | Webhook (`Produkty » Zmiana ilości na magazynie`) |
| One-off lookup / user-triggered action | Direct API call (`get`/`find`) — no need for a webhook |
| Bulk historical reconciliation | Polling via `find` with date-range conditions, not webhooks (webhooks only fire for events after they're configured) |
