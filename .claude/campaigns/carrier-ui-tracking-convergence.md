# UI + tracking convergence checklist (from FedEx Fit + Authority Audit)

Locked by agent reconciliation 2026-08-16. Implement in Release C (after credential authority).

## Enum (one wire set)

| Display | Wire (booking/intake) | CM store |
|---|---|---|
| DHL | DHL | dhl |
| FedEx | FEDEX | fedex |
| UPS | UPS | ups |
| Other | OTHER | other |

## Surfaces

1. `modals.jsx` NewShipmentModal — add UPS; keep Other; intake only.
2. `proforma-detail.jsx` AwbGenerateModal — add Other as external; no second modal.
3. `client-detail.jsx` — rename “DHL Express accounts” → “Carrier accounts”.
4. `EXTERNAL_PROVIDERS` — include OTHER if Other registration allowed.
5. Tracking UI — pass `FedEx` string matching `tracking_service` (`carrier == "FedEx"`).

## Tracking authority

- Atlas track SSOT: `tracking_service` + `tracking_db`.
- FedEx: keep `_call_fedex`; do not add parallel adapter Track until delegate or delete.
- Never infer carrier from AWB shape when `carrier_shipments.provider` exists.

## Account resolution

- Generalize `dhl_account_resolver.py` **in place** for multi-carrier billing accounts.
- Do not create a second resolver module.
