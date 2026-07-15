# ADR: Proforma integrates the PZ NBP service (supersedes the display-only prohibition)

Status: Accepted (operator decision, Proforma Review campaign PR-4, 2026-07-15).
Decision: **REVERSE** the earlier "Proforma FX is display-only; no NBP fetch" constraint. Proforma now has an explicit, audited NBP rate-fetch command that **reuses the sole PZ NBP authority** — it does **not** add a second NBP client or rate calculator.

## Context

An earlier proforma FX slice was deliberately display-only. Two tests in
`service/tests/test_proforma_warnings_and_dedup.py` pinned that constraint:

- `test_no_new_nbp_api_method_invented` — forbade any
  `fetchNbp|fetchFxRate|getNbpRate|nbpFetch|fetchExchangeRate` method on `PzApi`,
  with the rationale *"no backend for this exists."*
- an inline guard inside `test_warn_fix_buttons_call_onEditRequest_not_a_new_save_path`
  asserting no NBP/FX fetch method was added to `PzApi` (*"Slice 4 is display-only"*).

As a result the Proforma summary showed `NBP Table: —`, `USD/PLN rate: —`,
`Rate date: —` and the operator had to hand-type every rate, with no link to the
NBP authority the PZ landed-cost workflow already uses
(`pz_import_processor.get_nbp_rate`).

The rationale that "no backend exists" no longer holds: the PZ engine's NBP
service is production code and is the project's single rate-fetch authority.
Keeping Proforma display-only forced manual re-entry and invited drift from the
PZ accounting date rule.

## Decision

Proforma gains an explicit **Fetch NBP rate** command that reuses the existing PZ
NBP authority through a thin, server-safe adapter. The prohibition is retired and
**replaced** (not merely deleted) by a new authority contract test.

Guarantees (pinned by the replacement tests):

1. **One authority.** The rate value comes only from
   `pz_import_processor.get_nbp_rate`, wrapped by
   `service/app/services/nbp_rate_service.py`. No second NBP HTTP client and no
   second rate calculator is introduced.
2. **Server-safe.** The adapter neutralises the engine's interactive `input()`
   fallback and converts `RuntimeError`/`SystemExit`/network/malformed/missing-rate
   into a controlled error — it can never block a request or end the process.
3. **No fabricated fallback.** A USD/EUR upstream failure is surfaced (HTTP 502);
   the adapter never returns `1.0` as a fallback. PLN is an honest identity rate
   (`1.0`, source `identity`, no table number) — not a failure fallback.
4. **Manual override preserved.** The existing `edit-exchange-rate` field stays.
   A hand-typed rate is stamped `fx_rate_source = "manual"` and clears the stale
   NBP table metadata; the change is audited (before/after).
5. **Honest dates.** The requested accounting date (proforma issue date, or today
   when blank) and the returned NBP table date are persisted and surfaced
   separately — the engine may select a prior working-day table, and the two are
   not assumed equal.

Currency scope: USD, EUR (fetched), PLN (identity). Any other currency returns a
controlled 422; the PZ engine is not extended in this slice.

Backend: `POST /api/v1/proforma/draft/{id}/fetch-nbp-rate` →
`pildb.set_draft_nbp_rate` (shared optimistic-lock + draft-edit writer), persisting
`exchange_rate`, `fx_accounting_date`, `fx_rate_date` (NBP table date),
`fx_table_number`, `fx_rate_source`, `updated_at`, and recording a
`nbp_rate_fetched` audit event. Two additive draft columns: `fx_accounting_date`,
`fx_table_number`.

## Consequences

- `test_no_new_nbp_api_method_invented` is replaced by an authority-contract test
  asserting: the `PzApi.fetchNbpRate` wrapper exists, the backend route exists,
  the route delegates to the PZ NBP authority via `nbp_rate_service`, no duplicate
  NBP client/calculator is introduced, the manual override remains, and no `1.0`
  fallback exists for USD/EUR failures.
- The inline display-only guard's NBP assertion is removed (its `onEditRequest`
  checks remain).

## Rollback

Additive and reversible. Revert the PR-4 commit: the two columns are additive
(existing rows unaffected), the endpoint/adapter are new, and the manual override
path is unchanged. Restoring the prohibition means reinstating the two guards and
removing the fetch command.
