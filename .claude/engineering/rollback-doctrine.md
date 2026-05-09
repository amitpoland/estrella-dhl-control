# Rollback Doctrine

Every change ships with a documented undo. This doctrine names the
recovery path for each class of failure, in priority order.

## Layer 1 — Feature flag flip (fastest; preferred default)

Three of the four carrier feature flags can be flipped at runtime
to revert behaviour without a deploy:

| Flag | Effect of `False` | Recovery time |
|---|---|---|
| `carrier_dhl_live_enabled` | All live calls cease; factory returns stub on next request. | < 5 s (in-process; no restart needed if `settings` is re-read per call). Worker restart < 30 s. |
| `carrier_dhl_shadow_mode` | Wrapper drops; factory returns plain live or plain stub. | < 5 s. |
| `carrier_dhl_webhook_enabled` | Webhook endpoints return HTTP 503. | < 5 s. |
| `carrier_dhl_paperless_trade_enabled` | PLT field on every request is ignored; manifest records `flag_disabled`. | < 5 s. |

Procedure:
1. Edit `.env` in the production environment.
2. Restart workers.
3. Verify on the dashboard that the chosen adapter / URL / mode is
   what was intended.
4. Tag the rollback in the timeline (see `observability-standards.md`).

## Layer 2 — `git revert` (when flag flip is insufficient)

Used when a commit corrupted state, broke a schema, or introduced a
hard bug a flag cannot mask.

Procedure:
1. Identify the offending commit hash.
2. `git revert <sha>` on the campaign branch.
3. Push, redeploy.
4. Confirm carrier suite + `make verify` green at the new HEAD.
5. If the commit shipped a schema migration: see Layer 3.

Phase boundaries are designed so each commit is a small, discrete,
revertible unit. Do not squash-merge; targeted revert depends on
small commits.

## Layer 3 — Schema rollback (when migration corrupted DB)

Carrier DBs:
- `carrier_shipments.db`
- `carrier_labels/_attachments/*` and `_by_awb/*`
- `carrier_events.db`
- `carrier_shadow.db`

Migrations are **additive only** (new columns / new indexes).
Rollback strategy:

1. **For new columns**: revert is implicit. The column stays in the
   DB; old code ignores it. No data loss.
2. **For new indexes**: drop the index manually with
   `DROP INDEX IF EXISTS idx_name`; old code does not reference it.
3. **For new tables**: drop the table; old code does not reference
   it.
4. **For data corruption** (rare): restore from the most recent
   pre-migration `.bak` snapshot. DL-G adds a snapshot helper
   (`init_db` writes `<db>.bak` before any ALTER).

Migration rollback should be rehearsed in staging before any
production migration ships.

## Layer 4 — Live AWB recovery (after a bad live cutover)

Used when `carrier_dhl_live_enabled=True` was flipped and live AWBs
were created before rollback.

Procedure:
1. Flip `carrier_dhl_live_enabled=False` immediately (Layer 1).
2. Pull the list of live AWBs created in the affected window from
   the `carrier_shipments` table where `created_at > <flag-flip-time>`.
3. For each AWB: cancel via the DHL operator portal manually, OR
   call `coord.cancel_shipment(carrier="dhl", awb=...)` while the
   coordinator can still reach DHL (within the cancellation
   window).
4. Log every cancelled AWB + its manifest sha256 to the post-mortem.
5. Update the affected manifest messages with `event_code=
   "shipment_voided", reason="rollback-cleanup"`.

This is a high-touch recovery path; it is the cost of going live.
The DL-G runbook details this procedure with exact CLI commands.

## Layer 5 — Customs / legal recovery (when PLT goes wrong)

If a Paperless Trade attachment was sent on a shipment to a
non-PLT-enrolled DHL account:

1. The shipment will arrive but customs will demand paper.
2. Estrella's customs broker re-issues the paper invoice and
   forwards it to DHL.
3. The Customs Compliance Reviewer logs the incident and reviews
   whether the PLT enrollment status check in the DL-G readiness
   gate failed.

PLT failure does not recall the shipment; it only adds friction at
the destination.

## Rollback rehearsal cadence

- Layer 1 (flag flip): rehearsed automatically — every PR exercises
  the default-OFF state.
- Layer 2 (git revert): rehearsed in staging before any phase merge.
- Layer 3 (schema): rehearsed before any DL-G migration.
- Layer 4 (AWB recovery): rehearsed once before the production
  cutover; documented in the DL-G runbook.
- Layer 5 (customs): exercised only on real incident; reviewed
  quarterly.

## What the rollback doctrine does NOT cover

- **Time-machine rollback of issued AWBs.** DHL won't unissue an
  AWB. Layer 4 handles cancellation; the AWB itself remains in
  DHL's records.
- **Recovery from shipped-and-delivered packages.** Once the
  carrier has handed over to the recipient, no software rollback
  applies.
- **Customer notification.** Out of scope for this doctrine; lives
  in the customer-comms playbook.
