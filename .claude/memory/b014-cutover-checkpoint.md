# B-014 — V1→V2 Proforma cutover checkpoint

**Status:** CUTOVER HOLD (operator approval required)  
**Closed as:** FEATURE parity complete for birth-block surfacing; production default unchanged  
**Recorded:** 2026-08-13  
**Baseline SHA:** `ac39bfdd…`

## Prod authority (do not change without approval)

| Surface | Role |
|---|---|
| V1 `shipment-detail.html` ProformaDraftPanel | **Production default** for batch proforma ops |
| V2 `/v2/proforma` + `proforma-detail.jsx` | Available / parity track — **not** the default cutover |

## Parity re-measure (2026-08-13)

| Capability | V1 | V2 |
|---|---|---|
| Ship-to / payment editors | yes | yes (already present — backlog claim stale) |
| Draft line edit / save | yes | yes |
| Birth-block creation panel (`include_advisory=false`) | yes | **added** on `proforma-list.jsx` |
| Advisory contractor_conflict panel | yes | **added** on `proforma-list.jsx` |
| In-page assign resolver | yes | **added** (same assign API) |

## Cutover resume command (operator only)

```text
1. Explicit operator approval to make V2 the default proforma surface.
2. Seven-agent gate on the App payload that changes the default route/entry.
3. Browser verification (V1 + V2) on a real batch with birth-blocks + drafts.
4. Only then flip nav/default — never silent.
```

**Until then:** V1 remains production authority. No router switch in this closure.
