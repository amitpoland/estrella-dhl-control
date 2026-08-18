# Enterprise Ledger presentation - findings register (PR A)

Findings surfaced while building the enterprise ledger presentation layer that
are NOT fixed in PR A, with the reason each was left alone. One entry per
finding: what it is, where it lives, what it costs, and what happens next.

A finding is recorded here rather than fixed when fixing it would either widen
PR A past presentation, or require changing a financial authority. The campaign
brief is explicit on the second case: "If presentation appears wrong because an
upstream fact is wrong: STOP THAT PARTICULAR UI PATCH. Do not add a frontend
filter or alternate calculation. Escalate with the exact source fact."

---

## E-1  ESCALATION - the client statement has no local fact path

**Severity:** blocks two acceptance categories. Not a defect in anything PR A
changed; a pre-existing asymmetry in the route layer.

**The fact.** Every ledger surface except one reads the corrected LOCAL
projection by default:

| Route | Function | `source` default |
|---|---|---|
| `GET /clients` | `list_client_balances` (routes_ledgers.py:1060) | `"local"` |
| `GET /management-analysis.json` | `get_management_analysis` (:1385) | `"local"` |
| `GET /payables-analysis.json` | `get_payables_analysis` (:1516) | `"local"` |
| `GET /suppliers/{id}/statement.json` | `get_supplier_statement` (:1757) | `"local"` |
| `GET /clients/{id}/statement.json` | `get_client_statement` (:590) | **no parameter** |
| `GET /clients/{id}/statement.pdf` | `get_client_statement_pdf` (:657) | **no parameter** |

The client statement builder `_build_statement_dict` (:446) accepts no `source`
argument at all. It preflights the counterparty LIVE through
`lookup_wfirma_contractor` (:498), loads `load_ar_fact_universe` (:541 - the
LIVE universe, not `local_fact_universe`), and pins `body["source"] = "wfirma"`
(:572). There is no code path by which a caller can ask it for local facts.

**Why this is not patched in PR A.** Giving the client statement a local fact
path is a change to which fact universe a financial surface reads. That is a
source-authority change, not presentation. It also touches `load_ar_fact_universe`
call sites, which sit inside the off-limits list for this campaign. A frontend
workaround - reading the roster row and re-deriving the statement client-side -
would make React a second accounting authority, which the brief forbids outright
and which `test_no_arithmetic_on_financial_fields_in_the_ledger_jsx` pins against.

**What it costs, stated honestly.** Two acceptance categories cannot be
browser-verified in the isolated review environment, because the review server
has no live wFirma credentials and the client statement will only read live:

- **Status Conflict** (fixture customer 700007) - source says paid, economic
  remaining > 0.
- **Unapplied payment** (fixture 800004) - cash with nothing to apply against.

Both remain covered by the contract suite (sections 2 and 7 of
`service/tests/test_ledger_presentation_contract.py`), and both are visible on
the supplier side, which does read local. This is an acceptance gap, not a
verification pass: the client-side rendering of those two states has unit
coverage and no browser evidence.

**Next step.** Hand to the financial-authority workstream as a scoped question:
should `_build_statement_dict` take `source` and read `local_fact_universe`
like its four siblings? That decision belongs with the owner of the AR fact
universe, not with a presentation release.

---

## B-1  BACKLOG - the v2 fetch shim rethrows raw response bodies

`service/app/static/v2/index.html:82-85`. On any non-2xx, the shared `apiFetch`
throws `new Error('HTTP ' + res.status + ': ' + t.slice(0, 200))`, where `t` is
the raw response body. For a FastAPI validation error that is a JSON blob; for
an unhandled 500 behind a proxy it can be an HTML error page. Whatever it is
gets rendered into the operator's error toast.

Affects every v2 page, not the ledgers. The ledger pages route their errors
through `formatAccUpstreamError`, so PR A's surfaces are not the exposure. Fixing
the shim changes error handling for ~20 pages and belongs in its own change.

**Severity:** LOW - cosmetic leak of upstream text, no financial consequence.

---

## B-2  BACKLOG - three cross-file global collisions in the v2 bundle

`text/babel` scripts share one global scope, so a later file's top-level `const`
silently overwrites an earlier file's same-named declaration rather than
shadowing it. Three names are declared in more than one v2 file:
`CapChip`, `CarrierKpi`, `StatTile`.

None is used by the ledger pages, so none is a PR A exposure - but each is a
component that renders whichever definition happened to load last, which is a
load-order dependency nobody wrote down. Rename per owning page.

**Severity:** LOW - latent, currently benign.

---

## D-1  DEFERRED TO PR B - raw ISO timestamps in the primary hierarchy

The brief's PDF redesign asks for "no raw ISO timestamps in primary hierarchy";
small print in the page footer is explicitly permitted. Three sites still print
a raw timestamp above the footer:

- supplier statement header, "Issued"
- management analysis header, "Report date"
- management analysis footer, "Aging: Due date - <ISO>Z"

These are inside the enterprise PDF redesign scope (PR B step 19), where the
whole header block is rebuilt. Changing them in PR A would mean touching the
same paragraphs twice and reviewing the layout twice.

**Severity:** LOW - presentation polish, no figure affected.
