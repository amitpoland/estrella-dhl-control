# Observability Standards

Without observability, debugging a live DHL incident is
impossible. This doc defines what every component must emit, how
correlation flows, and what the operator dashboard must show.

## Correlation IDs

Every request that mutates state carries a single `request_hash`
that is consistent across:

- The action route's HTTP request log line.
- The coordinator's manifest message.
- The shadow log row (if shadow mode is on).
- The carrier-event-DB event row (for inbound webhooks).
- The timeline event detail.

`request_hash` is a deterministic sha256 over the canonical seed
(method + identity tuple). Defined in `dhl_shadow_db.compute_request_hash`
and used uniformly. Operators searching for a problem AWB run one
query and see the full lineage.

## Per-event lineage required fields

Every persisted record (shadow log row, manifest message, timeline
event) must carry:

- `request_hash` (str, 64 hex chars)
- `actor` (str, never empty in production; sentinel-prefix
  rejected by the actor validator)
- `created_at` (ISO-8601 UTC)
- `outcome` or `event_code` token (one of the documented enums)
- correlation key — `awb` for per-shipment events, `batch_id` for
  batch-level events

## Metrics surfaced via dashboard

Live cutover requires the following metrics on the operator
dashboard. Until DL-F4 ships them, ops must run the equivalent
SQL by hand.

| Metric | Source | Threshold (alarm if breached) |
|---|---|---|
| Shadow diff rate (mismatch %) | `carrier_shadow_log.diff_outcome` | < 2% over rolling 1 h |
| Stub-vs-live match rate | `carrier_shadow_log` aggregate | ≥ 98% over rolling 24 h |
| Live p95 latency | `carrier_shadow_log.live_duration_ms` | < 4000 ms |
| Live 4xx rate | `carrier_shadow_log.live_http_status` | within 2× of 24 h baseline |
| Daily quota remaining | `DHLDailyQuota.remaining_today()` | > 50 at any point |
| Webhook ingest rate | `carrier_webhook_events` | within 2× of 24 h baseline |
| `outcome=ingest_failed` count | `carrier_webhook_events` | 0 over rolling 1 h |
| Open shipments at non-handed states | `carrier_shipments` count by state | tracked, no hard threshold |
| PLT attached rate | `carrier_shadow_log.live_paperless_trade_attached` | tracked once flag is on |
| PLT validation failures | manifest reason tokens | tracked once flag is on |

## Audit visibility

For every operator action that touches state, the audit chain is:

1. **Action route** logs HTTP method + path + actor + outcome.
2. **Coordinator** writes one transition row + one manifest message.
3. **Shadow log** (if shadow on) writes one row with diff outcome.
4. **Timeline** writes one event with `request_hash` correlation.
5. **Per-AWB messages dir** carries the per-event JSON message.

A future incident-investigation tool joins all five on
`request_hash` to produce a full lineage view. Until that tool
ships, the per-AWB messages dir is the operator's primary view.

## Logging discipline

The codebase uses Python's stdlib `logging` for diagnostic output,
NOT `print`. The following are never logged:

- DHL Basic-auth header value (`Authorization: Basic ...`)
- DHL account number in plaintext (use `acct=****<last4>` if needed)
- Webhook secret (raw or sha256)
- PLT base64 (`documentImages[].content`)
- Operator session cookies / API keys
- Customer addresses, declared values, or AWBs in unstructured
  log lines

Source-grep tests pin the absence of `print(` / `log.` / `logger.`
near each forbidden token in every adapter and route file.

Log levels:
- `DEBUG`: dev only; never enabled in production.
- `INFO`: lifecycle events (service start, lifespan complete).
- `WARNING`: recoverable failures, retries, fallbacks.
- `ERROR`: unrecoverable failures; alarm threshold.

## Telemetry retention

- Manifests + per-AWB messages: indefinite (cheap, audit-relevant).
- Shadow log: 90 days. Older rows archived. Helper added in DL-F4
  or DL-G; until then, ops trim manually.
- Timeline events: tied to the parent batch's audit.json lifetime.
- Webhook events: 90 days; same archival cadence.

## Quarterly observability review

The Observability Engineer runs a quarterly review:
- Are the dashboard thresholds still right?
- Has any new code path landed without correlation IDs?
- Are any logs leaking forbidden tokens (re-run source-grep)?
- Has any persisted store grown beyond expectation?

Findings produce a new ADR if they propose a structural change.
