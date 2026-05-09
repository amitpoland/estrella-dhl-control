# ADR-006: No PDF bytes / credentials in evidence stores

Status: Accepted
Date:   2026-05-09
Phase:  DL-F2 / DL-F3

## Context

The carrier campaign produces multiple evidence artefacts:

- `carrier_label_store/_by_awb/<awb>/manifest.json` — per-AWB manifest.
- `carrier_label_store/_by_awb/<awb>/messages/` — per-event log.
- `carrier_shadow_log` SQLite table — stub vs live diff records.
- `RawShipmentResponse.raw` — adapter's full response dict.
- `CarrierEvent.raw` — webhook event's full payload.

DHL responses can echo our credentials (Basic Auth, account number,
PLT signature) in error bodies. PLT customs invoices contain PII
(addresses, declared values). DHL push events carry recipient
addresses. If any of those land verbatim in the stores above, the
evidence layer becomes a parallel PII / credential store.

## Decision

Persisted records carry **metadata only**:

- sha256 hash of file content (where applicable).
- file size in bytes.
- boolean attached / not attached / accepted flags.
- error class name (allowlisted: `CarrierAuthError`,
  `CarrierResponseError`, `CarrierRateLimitError`,
  `CarrierTransportError`, `CarrierAdapterError`, `Exception`).
- error summary truncated to ≤ 200 chars.
- ISO-8601 timestamps.

Persisted records DO NOT carry:

- Raw PDF bytes (PLT invoices, labels).
- Base64-encoded `documentImages[].content`.
- DHL Basic-auth header value.
- DHL account number in operator-facing error messages.
- Full DHL response JSON (only the operator-relevant subset).
- Webhook payload's full shipment dict (only the parsed fields).

Source-grep tests pin the absence of `print(`, `log.`, `logger.`
near `Authorization`, `documentImages`, `password`, `secret`. Every
ADR-006-relevant file has a corresponding source-grep guard.

## Rejected alternatives

- **Persist for diagnostics; redact via review.** Manual redaction
  doesn't survive contributor turnover.
- **Encrypt at rest.** Adds key management; doesn't solve the leak
  surface (debugging access still decrypts).
- **Persist with TTL.** Reduces blast radius but doesn't change the
  category of data we hold.

## Risks

- Debugging a live DHL incident requires the response body that we
  intentionally don't persist. Mitigated by:
  (a) shadow-log row carries enough metadata (status, duration,
      error class) to localise the issue;
  (b) DHL operator portal is the source of truth for live AWBs;
  (c) the live adapter's retry telemetry surfaces transient vs
      persistent failures distinctly.

## Rollback

This invariant has no rollback — it's a contract we never reverse.
A future contributor who needs more diagnostic data writes a new
ADR proposing a redacted-diagnostics store; the new store inherits
the same metadata-only constraint at a different granularity.

## Future impact

This invariant generalises beyond DHL. wfirma invoice attachments,
Zoho Cliq message bodies, customer email contents — none of them
land verbatim in evidence stores. The principle is: persist *that*
something happened, not the contents of what happened.
