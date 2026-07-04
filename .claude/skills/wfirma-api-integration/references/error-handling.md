# Error Handling

Read `request-response-conventions.md` first — this file assumes you already know the `status.code` + module-branch response shape.

## Where errors show up

wFirma reports errors at **two different levels** — your error-handling code must check both:

1. **Top-level `status.code`** — general request-level status (e.g. overall success/failure, or scope/auth-level errors like `DENIED_SCOPE_REQUESTED`).
2. **Nested per-field `errors`/`error` branches** inside individual records and sub-records (e.g. inside `invoice`, inside `contractor`, inside each `invoicecontent`) — these represent field-level validation failures on a write request. See the worked example in `request-response-conventions.md`.

**A response can have `status.code = OK` at the top level while still containing nested field errors on sub-records** (e.g. one invoicecontent line failed validation while the rest of the invoice was otherwise processed, or a partial-success scenario) — don't treat a top-level OK as "everything succeeded" without also walking the response for nested error branches.

## Known error codes / conditions

- **`DENIED_SCOPE_REQUESTED`** — the API key/OAuth token doesn't have the scope required for the action attempted (e.g. calling `/invoices/add` without `invoices-write`). Handle this explicitly in application code — surface a clear "missing scope: X" error rather than a generic failure, since the fix (re-authorize with the right scope, or generate a new API key with the right permissions) is different from a data/validation problem.
- **Generic `Internal server error` / 500 on `/invoices/add`** — has been documented (wFirma forum) as arising from:
  - Missing JSON numbering on nested repeatable collections (see `request-response-conventions.md`) — check this first if a payload that looks structurally correct still 500s.
  - contractor-id-only references occasionally triggering this in specific circumstances (see `invoices.md`) — try the full-object contractor form as a diagnostic.
  - When you hit an unexplained 500 with a payload that "looks right," re-verify JSON structure (numbering, root wrapper presence/absence between XML and JSON) before assuming it's a data problem.
- **Negative stock rejection** — an expected, by-design rejection when a write would drive stock below zero (see `warehouse-goods.md`). Handle as an expected business-logic case, not an unexpected error.
- **KSeF authorization block** — invoices via API fail if the API-key-owning user hasn't personally completed KSeF authorization in the wFirma UI, even if the company overall has KSeF enabled (see `invoices.md`). Surface this distinctly from generic validation errors since the remediation is a manual UI step by a specific user, not a code fix.

## Defensive coding pattern (recommended)

```
1. Parse status.code — if not OK/success, surface the top-level error clearly.
2. Recursively walk the response body for any `errors`/`error` branches at any nesting level,
   regardless of top-level status — collect them into a structured, field-attributed error list.
3. If both are empty, treat as success.
4. Log the raw response on any unexpected shape (missing status branch, unfamiliar error code)
   rather than trying to force-parse it — wFirma's documented error surface isn't
   exhaustive, and unlisted variants can appear.
```

## Rate limits

wFirma applies request rate limits (exact numbers vary by account/plan and aren't reliably documented publicly at a fixed figure — don't hardcode an assumed limit). Build in:
- Exponential backoff on repeated failures from the same endpoint.
- Batching/pagination for bulk operations rather than firing large numbers of parallel requests.
- If bulk-loading many records (e.g. ~1000 invoices/month, a scenario explicitly discussed on the wFirma forum), wFirma's own guidance is to write a script that adds records **one at a time on a schedule/interval**, not in a single burst — there's no documented bulk-add endpoint for invoices.
