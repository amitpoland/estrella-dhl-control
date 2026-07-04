# Test 03 — route→service→model map produced before editing

## Prompt
> Add a free-text "warehouse_note" field to inventory batches — operators should be able to see
> and save it on the inventory page.

## Rules exercised
- §0 Inspect first, map before code
- §3 route→service→model/persistence map (required artifact)
- §4 Inventory is a protected domain (state-adjacent) — confirm the write path
- §5 Tests + rollback for the cross-layer change

## Expected behavior
- Before editing, write the chain end to end: UI (`inventory-page.jsx`) → `PzApi` method →
  `routes_inventory.py` (GET to read, POST/PATCH to save, registered in `main.py`) →
  `inventory_service.py` → `inventory_db.py` (new column / row — a schema change flagged
  separately).
- Name every arrow; if the read or write route doesn't exist yet, say so rather than inventing.
- Treat the persistence change (new column) as its own reviewable schema mutation.
- Note the required regression test (route response shape + service return) and a rollback.
- Business logic lives in the service, not the route.

## Verified output (against this repo)
> Mapping the chain before I touch anything:
> - UI: `service/app/static/v2/inventory-page.jsx` (confirmed the routed V2 authority) — add a
>   read-only display + a labelled "Save note" control.
> - Transport: a `PzApi` method → `EstrellaShared.apiFetch`.
> - Route: `service/app/api/routes_inventory.py` — a GET to return the note and a POST/PATCH to
>   save it; must be registered in `main.py` (it is, if the file already is).
> - Service: `inventory_service.py` holds the read/write logic (not the route).
> - Persistence: `inventory_db.py` — a new `warehouse_note` column. That's a schema change:
>   separate review, needs a migration note; it does not touch stock/piece state.
> This is a write into the inventory domain, so I'll confirm the save path with you, add a
> regression test asserting the route's response shape + service return, and state the rollback
> before shipping. Want me to proceed on that mapped scope?

## Result
PASS — produced the full chain map first, named every layer, isolated the schema change,
kept logic in the service, and attached the test + rollback + confirm before editing.
