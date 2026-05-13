# ADR-007: Paperless Trade safety contract

Status: Accepted
Date:   2026-05-09
Phase:  DL-F3

## Context

DHL Paperless Trade (PLT) lets the shipper attach a digital customs
invoice so the physical paperwork can be skipped. The temptation is
to auto-attach the existing Polish customs description PDF (already
generated and validated by `polish_desc_validator`) on every
shipment. That would be wrong:

- Estrella's DHL Poland account may not be PLT-enrolled. An
  unenrolled account accepts the `documentImages[]` payload but
  still demands paper at the depot, defeating the purpose.
- An auto-attach defeats operator intent; some shipments
  legitimately ship paper (recipient request, customs broker
  preference).
- The PDF carries customs PII; auto-attaching it sends that data
  on every shipment whether the operator wanted it or not.

## Decision

PLT is **opt-in per shipment, gated by feature flag, with strict
file validation**:

1. Operator-supplied path. The action route accepts an optional
   `customs_invoice_pdf_path` field on the create-shipment payload.
   Empty path = no PLT for that shipment. No auto-attach from the
   audit pipeline.
2. Feature-flag gated. The live adapter honours the path only when
   `carrier_dhl_paperless_trade_enabled=True`. Default-OFF
   (ADR-010). Path-supplied + flag-off → manifest records reason
   `flag_disabled`, shipment proceeds without PLT.
3. Validator runs before any base64 encoding:
   - non-empty path,
   - file exists and is a regular file,
   - size > 0,
   - size ≤ 5 MB (DHL's documented PLT cap),
   - first 4 bytes equal `b"%PDF"` (magic check ignores file
     extension),
   - sha256 captured.
4. Validator NEVER raises. All failures suppress the inline
   payload and let the shipment ship without PLT. The manifest's
   `paperless_trade_reason` token names the gate that blocked the
   attachment (`oversize`, `not_pdf`, `file_not_found`, etc.).
5. Bytes never persist. Manifest carries sha256 + filename only.
   Shadow log carries sha256 + size + boolean only. The live
   adapter's `RawShipmentResponse.raw` carries sha256 + size + bool
   — never the bytes, never the base64. Sentinel tests pin the
   invariant.
6. `signatureName` is an account-level constant (`Estrella Jewels`)
   passed at the request-builder layer; per-account override lives
   in the constructor argument, not the per-shipment request.

## Rejected alternatives

- **Auto-attach from polish_desc pipeline.** Removes operator
  intent. Creates surprise billing if account becomes
  PLT-disabled.
- **Persist PDF bytes in shadow log for diff review.** Violates
  ADR-006.
- **Per-shipment signatureName.** Operationally noisy; signature
  is a legal constant per account, not per shipment.

## Risks

- Account-not-PLT-enrolled produces a paper-required shipment
  silently. Mitigated by the DL-G account-readiness checklist:
  PLT enrollment must be confirmed before flipping the flag.
- 5 MB cap is fixed at DHL's documented limit. A shipment with
  many SKUs may approach the cap; operator falls back to paper
  via empty path.
- The `customs_invoice_pdf_path` is operator-supplied via JSON;
  without containment it's an arbitrary-file-read primitive. DL-F3.5
  adds path containment to `settings.storage_root`.

## Rollback

Flip `carrier_dhl_paperless_trade_enabled=False`. Every subsequent
shipment ships without PLT, regardless of operator intent. No
schema migration needed.

## Future impact

DL-F3.5 hardens path containment. DL-F4 surfaces PLT outcomes on
the dashboard so operators see attached / not-attached / reason
without reading the manifest JSON. DL-F5 may expose a future
dashboard upload endpoint, behind operator confirmation.
