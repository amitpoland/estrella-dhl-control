# `org/` — operating system

Permanent governance state. Read order at session start:

1. **`program_board.md`** — what's in flight, who owns it, what's
   blocked. The single source of operational truth.
2. **`execution_modes.md`** — declare your mode. PRE-IMPLEMENTATION,
   IMPLEMENTATION, or RELEASE. **No mode = no work.**
3. **`roles.md`** — who edits what. Path-glob allowlists,
   denylists, triggers, review obligations.

Ratified by ADR-011 (2026-05-10). Built on top of
`../engineering/charter.md` (role cosmology) and `../adr/`
(decision history).

## Subdirectories

- **`dry_runs/`** — PRE-IMPLEMENTATION audit artifacts, dated.
  Each file is a snapshot of project reality at the moment a
  campaign was *considered*; the campaign itself ships under
  IMPLEMENTATION mode in a fresh session.
