# ADR-017: Carrier label store — retention policy

Status: Accepted
Date:   2026-05-10
Phase:  W-1 (governance debt D-3)

## Context

The carrier campaign introduced an on-disk content-addressed
store for outbound carrier labels and per-AWB manifests
(`service/app/services/carrier/carrier_label_store.py`). The
store layout is:

```
<store_root>/
  _index.json                       map: awb -> manifest path
  _attachments/<sha256>.<ext>       content-addressed label artefacts
  _by_awb/<awb>/manifest.json       per-AWB manifest (atomic write)
  _by_awb/<awb>/messages/<id>.json  per-AWB append-only message log
```

Since the store landed (DL-A through DL-F3.5), nothing in code
or in any prior ADR has stated:

- whether artefacts may be deleted (and under what conditions),
- how long manifests must be retained,
- how the store interacts with rollback,
- what evidence the store guarantees for audit.

The retention policy was therefore implicit. Per program-board
debt **D-3**, the policy needs codification.

## Decision

**Append-only by default.** No code path inside the carrier
service deletes from the label store. Manifests are written
atomically; messages are append-only; attachments are
content-addressed (same sha256 → same path; second write is a
no-op).

**Retention boundaries.**

| Class | Retention | Justification |
|---|---|---|
| Label attachments (`_attachments/<sha256>.<ext>`) | indefinite | Duplicate writes collapse by sha256; storage cost is bounded by distinct labels, not by call count. Required for replay and audit reconstruction. |
| Per-AWB manifests (`_by_awb/<awb>/manifest.json`) | indefinite | Manifest is the canonical record of what the carrier issued, in what state, at what timestamps. Required for live-AWB invariant verification (ADR-005) and for idempotent replay (DL-F3.5a). |
| Per-AWB message log (`_by_awb/<awb>/messages/<id>.json`) | indefinite | Append-only; carries the audit trail of state transitions for the AWB. |
| `_index.json` | indefinite | Singleton; rebuilt on init. |

**Deletion rules.** Inside the running service, **none**.

The service has no delete code path. Manual operator deletion
(filesystem-level), if ever performed, is treated as an
out-of-band administrative action and must be paired with:

- a written reason recorded outside the service (operator
  decision log),
- preservation of the corresponding row in
  `carrier_shipments.db` so the registry retains the AWB
  reference and idempotency lookups remain consistent,
- a follow-up ADR documenting the operational reason.

**Rollback expectations.**

- Reverting a code commit MUST NOT delete artefacts. If a
  commit added a new message type or manifest field, reverting
  it leaves the existing on-disk records untouched; the
  reverted code simply ignores the unknown field on read.
- The store is forward-compatible with reverted code: writers
  may add fields; readers tolerate unknown fields.

**Audit expectations.**

- Every label issued (live or stub) has a manifest entry.
- Every state transition logged via `append_message` is
  permanent.
- The hash chain (sha256 of attachment + sha256 of manifest at
  read time) is the integrity surface; ADR-006 forbids inlining
  bytes into evidence stores, so the hash is what audit relies
  on.

**Evidence-preservation invariant.**

> The label store is treated as **immutable evidence**. The
> service does not delete from it; rollback does not delete
> from it; tests do not assert deletion behaviour. Any future
> requirement for deletion (GDPR erasure, regulatory purge)
> requires a successor ADR specifying the boundary, the audit
> mechanism, and the operator approval gate.

## Rejected alternatives

- **Time-based pruning (e.g., delete manifests older than 12
  months).** Rejected — invalidates replay against historical
  audits, breaks idempotency lookups, and moves a deletion
  decision out of operator authority and into an automated
  schedule.
- **Size-bounded LRU eviction.** Rejected — same reasons; also
  introduces a cache-eviction model into what is a permanent
  evidence store.
- **Manual delete API exposed by the service.** Rejected — adds
  a destructive write surface the security review would have to
  re-audit; out-of-band operator action remains the escape
  hatch.

## Risks

- **Disk growth.** Storage is unbounded in principle. Mitigation:
  attachments are content-addressed (deduplication by sha256);
  manifest growth is per-AWB, not per-call. Operator monitors
  filesystem usage on the host; this ADR does not codify a
  threshold.
- **GDPR / regulatory erasure requests.** Such a request would
  require a successor ADR before any code change.
- **Label format obsolescence.** Old PDFs / ZPLs in
  `_attachments/` may become unreadable years later. Mitigation:
  out of scope here; the store guarantees byte preservation, not
  rendering compatibility.

## Rollback

This ADR does not introduce code; rollback means superseding
this ADR with a new one. The on-disk artefacts written before
supersession remain in place.

## Future impact

- Any future code that wants to delete from the store must
  reference this ADR and propose a supersession.
- Any future migration of the store (e.g., S3-backed, object
  storage) inherits the immutable-evidence invariant.
- Tests asserting on the store must not assert *absence* of
  files except in fresh-test-directory contexts; deletion is
  not part of the runtime contract.

## Related

- ADR-005 (no live AWB persistence — discipline transfer)
- ADR-006 (no PDF bytes / credentials in evidence stores; the
  store holds bytes, but evidence emitted *from* it is hashes)
- DL-F3.5a (idempotency by `(batch_id, reference)` reads
  manifests, never deletes them)
- `service/app/services/carrier/carrier_label_store.py`
  (the store under policy)
