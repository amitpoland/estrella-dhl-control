# Authentication (wFirma API)

wFirma supports three auth methods. **This project uses API Key** — default to this unless the user explicitly asks for OAuth.

## API Key (this project's method)

Three keys are required for every request:

- **accessKey** — generated in wFirma UI: Ustawienia (Settings) » Bezpieczeństwo (Security) » Aplikacje (Applications) » Klucze API (API Keys)
- **secretKey** — generated alongside accessKey. **Shown only once at creation time** — must be captured and stored immediately, cannot be retrieved later.
- **appKey** — issued by wFirma individually per registered application (not self-service; you get this from wFirma when registering an app/integration).

⚠️ **Regenerating the key pair in Ustawienia » Bezpieczeństwo » Aplikacje » Klucze always rotates BOTH accessKey and secretKey.** If a downstream system's credentials suddenly stop working, check whether someone regenerated keys in the wFirma UI — this is a common silent-breakage cause.

### Sending the key

Send credentials as headers on every request (exact header names — verify against current doc.wfirma.pl before final implementation, as these are sometimes revised):

```
accessKey: <accessKey>
secretKey: <secretKey>
appKey: <appKey>
```

### company_id

If the wFirma account has multiple companies attached, **every request must specify which company** via the `company_id` parameter, otherwise the request is ambiguous or hits the wrong company's data. Always pass `company_id` explicitly rather than relying on a "default company" assumption — don't hardcode this as a guess; get the real ID from Ustawienia in the target company.

## OAuth 2.0 / OAuth 1.0a (not default for this project)

- OAuth flow issues an `access_token` (Bearer token) after user authorization, sent via the `Authorization: Bearer <token>` header.
- OAuth 1.0a issues `access_token` + `access_token_secret` (varchar(32)) that must be persisted client-side and used on every request, per standard OAuth 1.0a request signing.
- Both require a `scope` parameter during the authorization request — see Scopes below.
- Only build this path if the user explicitly requests OAuth (e.g., building a multi-tenant public app where end users authorize your app against their own wFirma account — API Key is per-account and not suitable for that case).

## Scopes

Every module splits into a **read** and **write** scope:

```
<module>-read    → typically covers find/get methods
<module>-write   → typically covers add/edit/delete methods
```

Example: `invoices-read`, `invoices-write`, `contractors-read`, `contractors-write`.

- Requesting an action outside the granted scope returns error code **`DENIED_SCOPE_REQUESTED`**. Your application code must handle this explicitly (don't let it surface as a generic 500/unknown-error) — see `error-handling.md`.
- When building OAuth authorization URLs, request only the scopes actually needed (least privilege), comma-separated, e.g. `invoices-read,invoices-write,contractors-read,contractors-write`.

## URL / endpoint conventions

Base pattern:

```
https://api2.wfirma.pl/MODULE_NAME/ACTION_NAME
https://api2.wfirma.pl/MODULE_NAME/ACTION_NAME/ID
```

- `MODULE_NAME` — plural, e.g. `invoices`, `contractors`, `goods`.
- `ACTION_NAME` — e.g. `find`, `get`, `add`, `edit`, `delete`. Some modules expose extra non-standard actions (e.g. `/invoices/download`) — check the specific module's doc page, don't assume every module supports the same action set.
- ID is appended directly after the action unless a module's docs specify otherwise.

There is also a **sandbox/test host**: `test.api2.wfirma.pl` — use this for exploratory or destructive testing before hitting production, especially before running bulk add/edit/delete operations for the first time.
