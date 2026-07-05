# CP3 Recognition Set — Integrity Audit (2026-07-05)

**Objective:** make the CP3 side-by-side set a trustworthy review instrument — every composite = correct HTML (left) vs correct React (right), same page/route/viewport, no mispairs.

## Audited
- 41 paired composites + `INDEX.md` + wireframe-only/live-only sets, at 1440×900.
- Harness pairing logic (`scripts/cp3_capture.py` STATIC_PAIRS / ACC_RAIL_IDS / ACC_WF_TO_LIVE_IDX).

## Defects found + repaired
1. **Accounting sub-tabs mispaired/stale (pairs 30–38, old set).** The harness mapped wireframe accounting tabs to the *old* live rail indices; the FULL HTML PORT rebuilt AccountingHub to a 15-item document-type rail, so the mapping no longer matched (4 tabs — Invoice/Credit Note/Client Balance/Supplier Ledger — were wireframe-only). **Repair:** `ACC_RAIL_IDS` realigned to the new rail; `ACC_WF_TO_LIVE_IDX` made 1:1 with `WF_ACC_TAB_TEXTS`. Now **13 accounting sub-tabs pair correctly** (pair-29…41). Validated: `pair-31-accounting_tab_invoice` = wireframe Invoice ↔ live Invoice grid.
2. **`shipment_detail` list-vs-detail mispair (old pair-04).** The wireframe has no reachable shipment-detail screen distinct from the shipments list, so the side-by-side put a wireframe *list* beside a live *detail*. **Repair:** removed the `shipment_detail` static pair; the live shipment detail is now recorded **live-only** (no HTML counterpart — consistent with the accepted "no wireframe detail screen" finding).

## Result
- **41 correctly-paired composites** (all top-level pages + 9 setup + 11 inventory tabs + 13 accounting tabs); left=wireframe screen X, right=live screen X, same route + viewport; 0 WF errors, 0 live errors.
- **Wireframe-only (1):** shipment_detail (no live-pair created — see defect 2).
- **Live-only (5):** dhl_customs, proforma_search, shipping_ops, proforma_detail, shipment_detail — live screens with no HTML counterpart (documented, not mispaired).
- No duplicate pairs; no missing pairs; no route/viewport mismatch; stale numbering swept (41 orphans removed).

**CP3 recognition package: TRUSTWORTHY (ready for operator recognition review).**
