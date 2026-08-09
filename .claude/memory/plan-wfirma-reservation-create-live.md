# PLAN — fix/wfirma-reservation-create-live (base 0fe20d3f)
# Locked 2026-08-09 by operator GO.

## Chain
UI Reservation tab (proforma-detail.jsx)
  → PzApi.getReservationPreview / createReservation / (new) dryRunReservation
  → routes_wfirma_reservation.py
  → wfirma_reservation.py (resolve + optional persist)
  → wfirma_reservation_create.py (gates + write)
  → wfirma_client.create_reservation / _build_reservation_xml
  → wfirma_db drafts/lines + proforma_draft_events audit

## Changes
1. Resolver: Draft lines = commercial rows (1 row per editable line).
   Fallback sales path: design_no lookup; invoice-style product_code never UNMATCHED if already a product_code.
2. Currency/qty/price from Draft document snapshot.
3. Persistence: line_index so same product_code can appear with distinct prices; replace_reservation_lines.
4. Pure build_reservation_plan() + dry-run endpoint (zero HTTP, zero persist).
5. Create: reconcile-idempotent on created+id; audit event after persist id.
6. Hard-disable POST /reservations/process-pending mode=live.
7. UI: honest blockers when preview loaded but not ready; surface dry-run summary.
8. Stock gate unchanged (SALES stock_ok / dispatched). Warehouse receipt stays advisory.
9. Post/Convert untouched.

## Rollback
git revert <merge-sha>; redeploy app tree (no engine files).
