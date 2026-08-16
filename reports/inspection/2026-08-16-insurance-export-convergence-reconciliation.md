# Insurance Export canonical convergence — dry-run reconciliation

Date: 2026-08-16 · Branch `feat/insurance-fx-and-recovered-convergence`
Worktree `C:\PZ-wt\insurance-fx-convergence` · forked from `origin/main` @ `ea292f71`

Companion to `2026-08-16-insurance-recovered-authority-census.md` (root-cause
classification). This file records the *reconciliation* evidence: what the
convergence capability would write, proven against live wFirma reads, and what
the FX authority resolves for the same documents.

wFirma was **read-only** throughout. Every APPLY below ran against a scratch
sandbox database, never `C:\PZ\storage`.

---

## 1. Window: 2026-01-01 .. 2026-08-31 (August + 7 historical months)

    python -m app.tools.converge_commercial_charges --from 2026-01-01 --to 2026-08-31

    mode=dry_run  scanned=764  in_window=202
    inserted=202  unchanged=0  conflict=0
    with_insurance=110  without_insurance=92
    billed EUR 1879.09 · billed USD 778.36

`inserted=202` is not a discrepancy: production carries **no**
`commercial_charges.db` yet (`C:\PZ\storage` has no such file), so the first
production convergence is a pure create — there is nothing to overwrite, and
`conflict=0` is therefore a measured fact rather than an empty comparison.

Per month (documents / with an insurance line / billed):

| Month | Docs | With insurance | EUR | USD |
|---|---|---|---|---|
| 2026-01 | 28 | 21 | 238.30 | 153.09 |
| 2026-02 | 28 | 8 | 64.52 | 25.08 |
| 2026-03 | 19 | 7 | 60.00 | 10.00 |
| 2026-04 | 26 | 16 | 165.21 | 99.94 |
| 2026-05 | 34 | 20 | 388.47 | 110.59 |
| 2026-06 | 38 | 24 | 845.35 | 234.91 |
| 2026-07 | 17 | 10 | 26.81 | 76.23 |
| 2026-08 | 12 | 8 | 90.43 | 68.52 |

`unattributed_insurance_lines = []` across the whole window: every insurance
line found on an issued document mapped to the canonical insurance product
identity `13102217`.

## 2. August 2026 — the operator's candidate rows, measured

    mode=dry_run  in_window=12  with_insurance=8  without_insurance=4
    billed EUR 90.43 · billed USD 68.52

| Document | Invoice id | Date | Ccy | Insurance billed |
|---|---|---|---|---|
| WDT 153/2026 | 495842723 | 2026-08-04 | EUR | 56.98 |
| WDT 154/2026 | 495844643 | 2026-08-04 | EUR | 13.45 |
| WDT 155/2026 | 495933603 | 2026-08-05 | USD | — (0 lines) |
| WDT 156/2026 | 496002147 | 2026-08-05 | USD | 10.00 |
| FV 15/2026 | 497557795 | 2026-08-11 | USD | — (0 lines) |
| FV 16/2026 | 497608291 | 2026-08-11 | PLN | — (0 lines) |
| WDT 157/2026 | 497743523 | 2026-08-11 | USD | 13.30 |
| WDT 158/2026 | 497747171 | 2026-08-11 | EUR | 10.00 |
| WDT 159/2026 | 498012323 | 2026-08-12 | USD | 35.22 |
| WDT 160/2026 | 498080611 | 2026-08-12 | USD | 10.00 |
| WDT 161/2026 | 498081571 | 2026-08-12 | USD | — (0 lines) |
| WDT 162/2026 | 498723555 | 2026-08-14 | EUR | 10.00 |

EUR 56.98 + 13.45 + 10.00 + 10.00 = **90.43**.
USD 10.00 + 13.30 + 35.22 + 10.00 = **68.52**.

These reproduce the operator's candidate rows exactly, including the two the
operator flagged (WDT 153 is EUR, WDT 156 is USD). Nothing here is a constant
in production code — the numbers come from the census/live read every run.

## 3. WDT 155/2026 and its 362.39 USD — explained from live source

The issued document `495933603` carries **216 lines: 215 goods + 1 "Freight"**.
It contains no line for the insurance product `13102217`, and the string
`362.39` does not occur anywhere in the document XML.

The 362.39 USD lives in the **proforma draft** (`proforma_drafts` id 73,
batch `SHIPMENT_1749271904_2026-07_52887705`, contractor withheld, USD):

    {"charge_type": "insurance", "amount": 362.39, "currency": "USD",
     "resolution": "calculated", "wfirma_service_id": "13102217",
     "formula_basis": {"rate_pct": "0.4500", "minimum_usd": "10",
                       "sales_total": "80530.660"}}

So 362.39 is **calculated intent that was never billed** — the freight charge
from the same draft (28.00 USD) was posted, the insurance charge was not.

Under the repaired authority this is the correct outcome and not a conflict:
the recovered-premium authority is what the *issued* document billed, and the
draft is never a second source (outcome 9, pinned by
`test_the_draft_is_never_a_second_source_for_the_premium`). WDT 155 therefore
contributes **0** to recovered premium, and the August totals stand at
EUR 90.43 / USD 68.52. The unbilled premium is a commercial observation for the
operator, not a report-time correction.

## 4. Determinism and idempotency

- Two consecutive August dry runs produced **byte-identical** artifacts.
- `--apply` without `COMMERCIAL_CHARGE_CONVERGENCE_APPLY_ENABLED`:
  `REFUSED: … dry run is permitted, writing the charge record is not`.
- Sandbox apply, pass 1: `inserted=12 unchanged=0 conflict=0`.
- Sandbox apply, pass 2 (immediate re-run): `inserted=0 unchanged=12
  conflict=0`, totals unchanged. Convergence is idempotent.

## 5. FX authority — live resolution for the same documents

India Official Reference FX Authority (`india_official_fx`), consumed through
the `insurance_fx_provider` abstraction. Date rule: request `invoice_date − 1`,
then the latest publication on-or-before; never forward.

| Invoice date | Ccy | Rate (INR) | Effective | Source |
|---|---|---|---|---|
| 2026-08-04 | USD | 95.2601 | 2026-08-03 | rbi_reference_rate_archive |
| 2026-08-04 | EUR | 109.8247 | 2026-08-03 | rbi_reference_rate_archive |
| 2026-08-05 | USD | 95.3487 | 2026-08-04 | rbi_reference_rate_archive |
| 2026-08-05 | EUR | 109.7165 | 2026-08-04 | rbi_reference_rate_archive |
| 2026-08-11 | USD | 95.2560 | 2026-08-10 | rbi_reference_rate_archive |
| 2026-08-11 | EUR | 110.0600 | 2026-08-10 | rbi_reference_rate_archive |
| 2026-08-12 | USD | 95.4321 | 2026-08-11 | rbi_reference_rate_archive |
| 2026-08-12 | EUR | 110.0882 | 2026-08-11 | rbi_reference_rate_archive |
| 2026-08-14 | USD | 95.4098 | 2026-08-13 | rbi_reference_rate_archive |
| 2026-08-14 | EUR | 109.8784 | 2026-08-13 | rbi_reference_rate_archive |

Historical resolution is by publication date, not by "today":
2026-01-15 USD → 90.2016 eff 2026-01-14 · 2026-03-20 EUR → 106.7616 eff
2026-03-18 (weekend skipped backwards) · 2026-05-10 USD → 94.4365 eff
2026-05-08.

Fail-closed proofs:
- `PLN` → `unsupported_currency` — the authority publishes no PLN, and no
  PLN→EUR→INR or PLN→USD→INR cross is invented. FV 16/2026 (PLN) therefore
  degrades to NEEDS REVIEW with null INR columns rather than a zero.
- A date with no publication window (2026 archive queried for 2030) fails
  closed rather than substituting a nearby or current rate.

## 6. What the two authorities are, and are not

- `commercial_charge_authority` + `commercial_charge_record_db` — the sole
  durable authority for what an issued document billed. The Insurance Export
  statement reads it and performs no wFirma insurance lookup of its own.
- `india_official_fx` behind `insurance_fx_provider` — the sole INR rate
  authority. The statement consumes the abstraction, never the transport.
- Neither repairs, masks, or stands in for the other: an FX gap leaves the
  recovered premium intact, and an unconverged document leaves the INR
  conversion intact. Pinned by
  `service/tests/test_insurance_export_authority_convergence.py`.
