# DHL CFIT Escalation — Error 803 (PL → LT)

**Date:** 2026-06-26  
**Account:** 427294774 (Polish export, Estrella Sp. z o.o. Sp.k., Warszawa PL)  
**Status:** CODE ON HOLD — awaiting DHL confirmation of correct productCode for PL→EU

---

## Error

```
HTTP 422 / DHL Error 803
"Account not allowed for this service"
```

Occurred at: 2026-06-25 22:40:27 UTC  
Endpoint: `POST https://express.api.dhl.com/mydhlapi/shipments`

---

## Payload That Triggered 803

| Field | Value |
|---|---|
| `productCode` | `P` (Express Worldwide WPX) |
| `incoterm` | `DAP` |
| `isCustomsDeclarable` | `true` |
| `valueAddedServices` | none |
| Origin country | `PL` (Warszawa, ul. Sabaly 58, 02-174) |
| Origin account | `427294774` (payer: `shipper`) |
| Destination country | `LT` (Lithuania) |
| Consignee | MB Adagia (VAT: LT100017612018) |
| Weight | ~1.5 kg / 11 pcs (jewellery, 14KT gold / silver) |
| Declared value | USD — jewellery |
| `customerReferences` typeCode | `CU` (corrected from `AAO` in PR #748) |

---

## Context: Certified Routes on This Account (CFIT 2026-06-25)

The following routes were certified in the sandbox CFIT session on 2026-06-25:

| Route | Product | Services | Result |
|---|---|---|---|
| PL → DE (Hamburg) | `U` (Express) | PLT + WY | PASS |
| PL → DE (Hamburg) | `W` (Express Worldwide Doc) | PLT + WY | PASS |
| PL → CH (Basel) | `P` (Express Worldwide WPX) | PLT + WY | PASS |
| PL → US (New York) | `P` (Express Worldwide WPX) | PLT + WY | PASS |
| PL → BR (São Paulo) | `P` (Express Worldwide WPX) | ByPassPLT | PASS |

**Not yet certified:** `PL → LT` — any productCode

---

## DHL Questions for CFIT

1. **Which productCode should be used for PL → LT (EU intra-community, no customs)?**
   - Is it `P` (Express Worldwide WPX) — same as PL→CH/US/BR?
   - Or `U` / `W` (Express / Express Worldwide Document) — same as PL→DE?
   - Or another code entirely for intra-EU B2B jewellery?

2. **Is account 427294774 entitled to `productCode P` for EU destinations (LT, FR, NL, FI, etc.)?**
   - If not, what is the correct product for this account on EU routes?

3. **Should `isCustomsDeclarable` be `false` for EU → EU shipments?**
   - Current code hardcodes `true` for all calls.
   - For PL→LT there is no customs declaration (both EU Schengen).
   - Does this contribute to the 803 error?

4. **Do we need a separate CFIT session for PL → EU routes?**
   - We have non-EU passing (CH, US, BR) and one EU-specific product (U/W for DE).
   - Lithuania is not in our tested matrix.

---

## Code Hold

The following changes are **blocked** until DHL confirms:

- No patch to `productCode` selection logic in `live.py`
- No change to `isCustomsDeclarable` flag
- No PLT/WY/ByPassPLT changes

When DHL confirms the correct product for PL→EU:
1. Implement product selection by destination zone (EU vs non-EU) or by explicit account entitlement config
2. Set `isCustomsDeclarable = False` for EU→EU if DHL confirms it's required
3. Add regression tests for PL→LT and other EU destination cases
4. Re-run CFIT with new product before going live

---

## Other EU Customers on This Account

Other destination countries seen in the customer master (may also need 803 investigation):
`FR`, `BG`, `NL`, `FI`, `SK`, `BE`, `HU`, `DK`

All are EU member states — same issue may apply if `productCode P` is not entitled for EU routes.
