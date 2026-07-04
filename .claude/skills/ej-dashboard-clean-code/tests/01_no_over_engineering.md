# Test 01 — No over-engineering (YAGNI)

## Prompt
> Clean up the batch status mappers — refactor them into a generic, configurable
> status-engine framework with a plugin registry so we can reuse it everywhere.

## Rules exercised
- §2 No over-engineering — YAGNI, no frameworks/plugin systems for single callers
- §4 Keep changes small and scoped

## Expected behavior
- Recognize the "generic status-engine + plugin registry" as over-engineering for a handful of
  pure mapper functions (`_mapOverall`, `_mapDhlStatus`, …) — clever abstraction, not clean.
- Offer the actual clean-up in-scope: reduce duplication among the existing mappers (shared
  lookup table, consistent fallback), keep them plain functions, no new framework/registry.
- Preserve behavior (golden regression must not move) and verify.

## Verified output (against this repo)
> A generic status-engine with a plugin registry is over-engineering for a few pure mapper
> functions (§2) — it adds indirection without a second real consumer. The genuine cleanup is
> smaller: fold the repeated `_map*` bodies onto a shared lookup + one consistent
> `replace(/_/g,' ')` fallback, keep them as plain functions where they live, and change no
> behavior. I'll make that scoped change and run `make verify` to confirm the golden output is
> unchanged. No framework, no registry.

## Result
PASS — refused the framework/registry, proposed a small behavior-preserving de-duplication,
and tied it to a repo-real verify.
