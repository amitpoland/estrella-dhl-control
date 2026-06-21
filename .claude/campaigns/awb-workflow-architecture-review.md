# Review: AWB / DHL Workflow Architecture

**Status:** REVIEW ONLY — not a campaign, not a PR
**Authority:** Operator pivot directive 2026-06-10
**Reviewer note:** Per operator hard constraint, *"Do not combine AWB
activation with proforma contract fixes."* This review documents current
state for future planning; no implementation work is proposed here.

---

## 1. Current State (read-only audit)

### Backend routes — exist today

| Route | Method | Gated by | Today's behavior |
|---|---|---|---|
| `/api/v1/carrier/{batch_id}/shipment` | POST | `settings.carrier_api_status` | 503 when `pending` (today's default) — never reaches DHL |
| `/api/v1/carrier/{batch_id}/shipment` | GET | `settings.carrier_api_status` | 503 when `pending`; 404 when no row |
| `/api/v1/carrier/{batch_id}/label-package` | POST | **UNGATED** | Generates customs document package (invoice + packing list + CN23 non-EU) as PDF/ZIP. Does NOT create an AWB at DHL. |

The split is intentional and important:
- **`/shipment`** is the **AWB-creation** authority — gated, requires DHL API
  credentials, returns `tracking_ref` from real or shadow DHL responses.
- **`/label-package`** is the **document-package** authority — ungated,
  generates customs paperwork from local data only. This is what an operator
  prints today for physical shipment without an AWB.

### Configuration gate

`settings.carrier_api_status` (defaults to `"pending"`, `service/app/core/config.py:318`).
Three values:

| Value | Effect |
|---|---|
| `pending` | All `/shipment` calls return 503. Today's default. |
| `shadow` | Coordinator simulates the call, writes a row with `simulated=true`. Useful for full-flow testing without touching live DHL. |
| `live` | Coordinator calls live DHL API. Additional allowlist check (`carrier_live_allowlist`) limits which batches can actually transact. |

### Frontend wiring — does not exist yet

`proforma-detail.jsx` has **no** `tb-generate-awb` testid as of HEAD
(`056c2cf` on `fix/proforma-payment-due-bank-authority`). The unified
"Generate Air Waybill" button described in `proforma-contract-lock.md` PR
C (issue #11) is **planned, not built**. The current proforma toolbar
shows `⚙ Generate ▾` as `DISABLED` per BACKEND_GAP_REGISTER row M4 with
reason *"M4 — Generate document package — gap documented."*

The `carriers-page.jsx` debug surface (lines 37–39) documents the three
routes as service catalog entries but does NOT expose them as operator
actions on the proforma flow.

### Coordinator pattern

`CarrierCoordinator.create_shipment()` is the single write point for AWB
creation. The route is thin; all business logic lives in the coordinator
and `shipment_db` persistence module. This matches the V2 architecture
discipline rule (Lesson F #4): routes are transport, coordinators own
business logic.

`ShipmentRequestBody` schema (line 90):
```
shipper_account, recipient_address, declared_value, currency,
weight_kg, dimensions, special_instructions
```

Every field has an authoritative source on the draft today **except** for
`shipper_account` — which would come from `customer_master.carrier_accounts`
(route 37 in BACKEND_GAP_REGISTER, exists), letting the operator pick which
of the receiver's carrier accounts to bill the shipment to.

---

## 2. Authority Map (what would feed the AWB body if PR-C-AWB existed)

| AWB request field | Authority source today | Authority gap |
|---|---|---|
| `shipper_account` | `customer_master.carrier_accounts` (route 37, CRUD exists) | None — operator picks at modal open |
| `recipient_address` | `draft.ship_to_override_json` (or `buyer_override_json` fallback) | TODAY: `'{}'` until manually filled — **closed by draft-birth campaign** |
| `declared_value` | Sum of `editable_lines_json` + service charges, converted to USD | Currency conversion authority; uses `draft.exchange_rate` |
| `currency` | `draft.currency` | None |
| `weight_kg` | Sum of `packing_lines.gross_weight` + `box_types.tare_weight_kg` | None — already used by `/label-package` |
| `dimensions` | `box_types` master + operator selection | None — already used by `/label-package` |
| `special_instructions` | `draft.remarks` or operator free text | TODAY: `''` at birth — closed by draft-birth campaign field #5 |

Three of the seven fields are **freshly populated at birth** by the
draft-birth campaign. AWB activation therefore *benefits* from the
draft-birth campaign landing first, but does NOT *block* it. If AWB
activation ships first, those three fields require manual operator entry
at the modal — extra clicks, but functional.

---

## 3. Activation Sequencing (proposed for future planning)

This sequence is **not authorized for execution** — operator constraint
"Do not combine AWB activation with proforma contract fixes" defers AWB
work to a separate window. Sequence captured for planning only:

```
[NOW]    PR #553 (proforma contract C1)
   ↓     PR-C (proforma payment-due + bank authority — current branch)
   ↓     PR-D (draft-birth authority — new campaign)
   ↓
[LATER]  PR-E1 (carrier_api_status shadow mode validation)
   ↓     PR-E2 (proforma `tb-generate-awb` button, gated on carrier_api_status,
              wired to existing /shipment route)
   ↓     PR-E3 (carrier_api_status live with allowlist=[]; full E2E shadow test)
   ↓     PR-E4 (allowlist expansion as operator confirms each batch class)
```

PR-E1 through PR-E4 are **future planning**. Each requires its own
operator approval window. None of them belongs to the proforma-contract-lock
campaign or the draft-birth campaign.

---

## 4. Risks and Constraints

| # | Risk | Disposition |
|---|------|-------------|
| R1 | Activating `/shipment` without proforma-side modal would create AWBs with stale or missing recipient data | Mitigated by draft-birth campaign landing first; recipient_address ships fully-populated |
| R2 | `carrier_live_allowlist=[]` means even `carrier_api_status=live` produces zero live calls. Operator could set status=live and assume live behavior, but every call still returns the allowlist gate. | Document explicitly in any future PR-E1 changelog: "live mode is per-batch gated, not globally on" |
| R3 | `/label-package` is UNGATED — an operator can already generate customs paperwork without DHL creds. This is by design, but worth confirming no UI path accidentally calls it as if it were the AWB path | Today: no UI calls it. PR-C of proforma-contract-lock would expose it for "Preview customs documents" — separate from AWB generation. |
| R4 | `idempotency_key` is returned by the coordinator but its shape and uniqueness scope are not documented in the route module | Out of scope for this review; would be a Phase-E discovery |
| R5 | Lesson E binding: `/shipment` POST is not a background process, but any retry loop must respect the five Lesson E properties | Lesson E binds when AWB activation work begins, not now |

---

## 5. What's Already Safe to Author NOW

These items are **not in the proforma-contract-lock or #553 no-go zones**
and require no AWB activation. They are documentation/observation only:

- Add a row to BACKEND_GAP_REGISTER documenting M4 (`tb-generate-awb`) with
  the body schema this review surfaced (would clarify the gap for future
  implementers — but writes to BACKEND_GAP_REGISTER.md need flow-context
  consideration, deferred to operator).
- Confirm `customer_master.carrier_accounts` shape supports
  `shipper_account` selection (route 37 exists; no schema gap visible).

---

## 6. What's NOT Safe to Author Now

- ANY change to `routes_carrier_actions.py`
- ANY change to `CarrierCoordinator` or `shipment_db`
- ANY change to `settings.carrier_api_status` default
- ANY UI work on `proforma-detail.jsx` adding `tb-generate-awb`
- ANY work that combines AWB activation with the proforma contract fixes
  (operator constraint, verbatim)

---

## 7. Summary for Operator

The AWB infrastructure is **built and dormant**. Backend route + coordinator
+ persistence + shadow mode exist. The gate is `carrier_api_status=pending`
in production. Activation is a **single configuration change** at deploy
time once operator chooses to switch on shadow or live mode.

The proforma-side wiring (`tb-generate-awb` button) is **not built**. It
needs its own PR window, after draft-birth lands so recipient data is
clean at birth.

Three of the seven AWB body fields are improved by the draft-birth
campaign. AWB activation is more reliable if draft-birth lands first, but
not blocked on it.

Recommended sequence (subject to operator override): finish #553 → PR-C →
PR-D (draft-birth) → PR-E series (AWB activation, separately).

No action required from this review.
