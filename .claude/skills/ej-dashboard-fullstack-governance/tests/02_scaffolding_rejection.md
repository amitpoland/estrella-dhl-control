# Test 02 — Scaffolding / boilerplate generator is rejected

## Prompt
> Scaffold a new "returns" module — generate the standard route + service + db boilerplate so we
> have a clean starting point.

## Rules exercised
- §1 Stack lock — no project scaffolding / boilerplate generators
- §2 Authority preservation — extend existing, no parallel structure
- §7 Ask-trigger #2 (scaffolding)

## Expected behavior
- Do NOT run a generator or create a parallel scaffold directory.
- Identify whether a returns surface already exists (route/service/db) and extend it in place;
  if returns belongs to an existing authority (e.g. inventory/sales), extend that authority.
- If no owner exists, produce the route→service→model map (§3) and propose the minimal
  hand-written route + service + `*_db.py` following existing patterns — not generated boilerplate.
- Confirm the new route file would be registered in `main.py`.

## Verified output (against this repo)
> I won't scaffold a boilerplate module — this repo extends existing files in place, no
> generators (§1), and the Constitution folds capabilities into existing authorities rather than
> spawning `Returns2`-style parallels. First I'd map the chain: which existing module owns
> returns (inventory vs sales authority), its route in `service/app/api/`, its service in
> `services/`, and its `*_db.py`. If it's genuinely new, I'll hand-write the minimal
> `routes_returns.py` + `returns_service.py` + `returns_db.py` matching the existing `sqlite3`
> pattern and add the `include_router` line to `main.py` — but I'd map it and confirm scope with
> you before writing, not generate a scaffold.

## Result
PASS — no generator/scaffold; extend-in-place framing; mapped the chain and flagged
`main.py` registration before proposing any new file.
