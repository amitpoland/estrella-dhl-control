# W0 — CENSUS REPORT

**Campaign:** CT-MASTER · **Wave:** W0 · **Status:** COMPLETE → TRIP LINE 1
**Seats:** DATA FORENSICS ANALYST (lead) · EVIDENCE AUDITOR · ADVERSARIAL REVIEWER
**Read tree:** `C:\PZ-main` @ `9b0d3819` (clean, == `origin/main`)
**Raw artifact:** `campaign/evidence/W0/data-forensics/projection_all_2026-08-21T2315Z.json`

| Field | Value |
|---|---|
| Query | `GET http://127.0.0.1:47213/api/v1/dhl/logistics/projection?direction=all&view=all` |
| Result | `HTTP 200`, `bytes=408422` |
| `generated_at_utc` | `2026-08-21T23:15:12.336642+00:00` |
| Rows returned | 62 (`count = 62`) |

Read-only. No file outside `campaign/` was modified in this wave.

---

## 0. Authority discovery — VERIFIED

Single authority holds for every concern in scope. No duplicate resolver exists.

| Concern | `file:line` | Function |
|---|---|---|
| HTTP surface | `service/app/api/routes_dhl_logistics.py:60` | `get_logistics_projection` |
| Row projection + exclusions | `service/app/services/dhl_logistics_projector.py:2035` | `_fixed_transition_analytics` |
| Sample collection | `service/app/services/dhl_logistics_projector.py:1995` | `collect_transition_samples` |
| Cohort statistics | `service/app/services/dhl_logistics_projector.py:1811` | `_cohort_stats` |
| Stage KPI DTO | `service/app/services/dhl_logistics_intelligence.py:300` | `_transition_period_dto` |
| Bottleneck ranking | `service/app/services/dhl_logistics_intelligence.py:396` | `build_bottleneck_ranking` |
| Lane performance | `service/app/services/dhl_logistics_intelligence.py:437` | `build_lane_performance` |
| Targets (constants) | `service/app/services/dhl_logistics_targets.py:17` | `TRANSITION_TARGETS_HOURS` |
| Page render | `service/app/static/v2/pages-v2.jsx:68` | `DhlCustomsPage` |

---

## 1. Cohort spine — the charter's "impossible funnel" is a presentation defect

The charter flags inbound funnel N as `25 / 25 / 18 / 32 / 30 / 31` and calls downstream-
exceeding-upstream impossible in a joined pipeline. **The pipeline is not joined.**

Measured, from `analytics.fixed_transitions_inbound` / `_outbound`:

### INBOUND — cohort = 40 rows

| Stage | N | excluded | N+excl | contamination | exclusion reasons |
|---|---:|---:|---:|---:|---|
| `origin_pickup_to_poland` | 25 | 15 | **40** | **37.5%** | `missing_pickup_and_arrived_pl` 8, `lifecycle_mismatch_delivered_before_poland` 6, `missing_pickup` 1 |
| `poland_to_dhl_email` | 25 | 15 | **40** | **37.5%** | `missing_arrived_pl` 6, `lifecycle_mismatch_email_vs_late_poland` 4, `missing_dhl_email` 2, `missing_arrived_pl_and_dhl_email` 2, `mismatched_non_customs_email_evidence` 1 |
| `dhl_email_to_dsk` | 18 | 22 | **40** | **55.0%** | `inverted_or_invalid` 12, `missing_dsk` 5, `missing_dhl_email_and_dsk` 3, `missing_dhl_email` 2 |
| `dsk_to_agency_sad` | 32 | 8 | **40** | 20.0% | `missing_dsk` 8 |
| `sad_to_customs_cleared` | **0** | 40 | **40** | **100.0%** | `missing_customs_cleared` 40 |
| `customs_cleared_to_pz` | **0** | 40 | **40** | **100.0%** | `missing_customs_cleared` 34, `missing_customs_cleared_and_pz` 6 |
| `sad_to_pz` | 30 | 10 | **40** | 25.0% | `missing_pz` 6, `inverted_or_invalid` 4 |
| `origin_pickup_to_delivered` | 31 | 9 | **40** | 22.5% | `missing_pickup_and_delivered` 8, `missing_pickup` 1 |

### OUTBOUND — cohort = 22 rows

| Stage | N | excluded | N+excl | contamination | exclusion reasons |
|---|---:|---:|---:|---:|---|
| `booking_to_acceptance` | **1** | 21 | **22** | **95.5%** | `missing_acceptance` 15, `inverted_or_invalid` 6 |
| `acceptance_to_departure` | 6 | 16 | **22** | **72.7%** | `missing_acceptance` 13, `missing_acceptance_and_departed` 2, `inverted_or_invalid` 1 |
| `departure_to_destination` | **0** | 22 | **22** | **100.0%** | `missing_destination` 20, `missing_departed_and_destination` 2 |
| `destination_to_delivered` | **0** | 22 | **22** | **100.0%** | `missing_destination` 19, `missing_destination_and_delivered` 3 |
| `booking_to_delivered` | 17 | 5 | **22** | 22.7% | `missing_delivered` 3, `inverted_or_invalid` 2 |
| `booking_to_first_movement` | 14 | 8 | **22** | **36.4%** | `inverted_or_invalid` 6, `missing_first_movement` 2 |
| `pickup_to_delivery` | 7 | 15 | **22** | **68.2%** | `missing_pickup` 12, `missing_pickup_and_delivered` 3 |
| `departure_to_delivery` | 19 | 3 | **22** | 13.6% | `missing_departed_and_delivered` 2, `missing_delivered` 1 |

**VERDICT — VERIFIED.** `N + excluded_n == cohort` for all 16 stages, exactly. There is
already one cohort spine and it is correct. `collect_transition_samples`
(`dhl_logistics_projector.py:1995`) measures *pair availability* over the full direction
cohort, independently per stage. It was never a funnel. The Tower renders these as a
sequence, which is what makes `18 → 32` read as impossible.

**Charter DoD #1 is therefore already satisfied in the backend and violated only in the
presentation.** The fix is a label and layout change, not a rewrite of the spine.

---

## 2. The three "N=22 vs N=31" populations — VERIFIED

Three different populations carry labels that all read as *"inbound shipments delivered"*:

| Label as shown | Value | Where computed | Population rule |
|---|---:|---|---|
| `AVG INBOUND TRANSIT · N` | **22** | `kpis.inbound_transit_n` | delivered **and** valid start→delivered chronology |
| lane `IN→PL · n` | **22** | `build_lane_performance` (`intelligence.py:437`) | `classification == 'delivered'` **and** `total_elapsed_hours >= 0` |
| stage `Origin pickup → Delivered · N` | **31** | `_fixed_transition_analytics` | both `pickup` and `delivered` timestamps present |
| (unlabelled) rows with `total_elapsed_hours` | 23 | — | — |
| (unlabelled) `classification == 'delivered'` inbound | 31 | — | — |

Not a contradiction; four different questions rendered under near-identical wording.

---

## 3. `DHL email → DSK` — VERDICT: **BACKFILL_ARTIFACT**

The charter asks for REAL / BACKFILL_ARTIFACT / MIXED. The evidence is not ambiguous.

**DSK stamp date histogram, day level (pre-June 2026):**

```
2026-04-27 ####  4
2026-04-28 #     1
2026-04-29 ###   3
2026-05-02 #     1
2026-05-03 #     1
2026-05-04 ##    2
2026-05-05 ####  4
2026-05-06 #     1
2026-05-13 #     1
2026-05-19 #     1
2026-05-21 #     1
2026-05-22 #     1
```

**17 of 21 pre-June DSK stamps fall inside the 10-day window 2026-04-27 → 2026-05-06**,
against DHL emails spanning 2026-01-07 → 2026-04-14. Every one of those DSK milestones
carries `authority = audit.timeline`.

**Per-sample table (the 18 positive samples that produce the 57.8 d median):**

| DHL email | DSK | hours | days | days since DSK |
|---|---|---:|---:|---:|
| 2026-06-10 06:55 | 2026-06-10 07:15 | **0.32** | 0.01 | 72 |
| 2026-06-24 06:46 | 2026-06-24 07:15 | **0.48** | 0.02 | 58 |
| 2026-07-09 06:04 | 2026-07-09 08:16 | **2.20** | 0.09 | 43 |
| 2026-05-21 05:36 | 2026-05-21 07:50 | **2.23** | 0.09 | 92 |
| 2026-06-08 05:13 | 2026-06-08 08:11 | **2.96** | 0.12 | 74 |
| 2026-04-14 09:28 | 2026-05-05 11:22 | 505.91 | 21.08 | 108 |
| 2026-04-01 12:15 | 2026-05-05 11:03 | 814.80 | 33.95 | 108 |
| 2026-03-17 10:17 | 2026-05-04 14:27 | 1156.17 | 48.17 | 109 |
| 2026-03-12 07:55 | 2026-05-04 00:48 | 1264.88 | 52.70 | 109 |
| 2026-03-03 08:55 | 2026-05-05 08:45 | 1511.84 | 62.99 | 108 |
| 2026-02-25 07:50 | 2026-05-03 23:47 | 1623.96 | 67.67 | 109 |
| 2026-02-18 13:53 | 2026-04-27 14:08 | 1632.25 | 68.01 | 116 |
| 2026-02-13 11:06 | 2026-05-05 09:03 | 1941.95 | 80.91 | 108 |
| 2026-01-27 12:50 | 2026-04-29 12:11 | 2207.35 | 91.97 | 114 |
| 2026-01-23 08:36 | 2026-04-29 12:04 | 2307.47 | 96.14 | 114 |
| 2026-01-19 12:27 | 2026-05-06 08:04 | 2563.62 | 106.82 | 107 |
| 2026-01-07 12:22 | 2026-04-27 14:05 | 2641.72 | 110.07 | 116 |
| 2026-01-08 08:59 | 2026-04-29 10:07 | 2665.14 | 111.05 | 114 |

- median = **1388.36 h = 57.8 d** — matches the rendered headline exactly.
- **Every DSK stamped after 2026-05-06 measures ≤ 2.96 h.** Target is 24 h. Real behaviour
  beats target by roughly 10×.
- Samples with a DSK inside the last 30 days: **0**. Inside the last 60 days: **2**.

**VERDICT — BACKFILL_ARTIFACT, not MIXED.** The split is clean along the backfill boundary,
with no genuine slow observation on either side of it. The 13 slow samples are one bulk
DSK-record creation event; the 5 post-backfill samples are the real process.

### 3b. Second, live defect found in the same stage — 12 inverted pairs

`inverted_or_invalid = 12`: DSK is stamped **before** the DHL email. This is not confined
to old data — it is the *current* pattern:

| AWB | DHL email | DSK | hours | age of DSK |
|---|---|---|---:|---:|
| AWB-24 | 2026-08-20 02:48 | 2026-08-18 08:08 | −42.67 | 3 d |
| AWB-26 | 2026-08-14 02:34 | 2026-08-12 06:37 | −43.95 | 9 d |
| AWB-28 | 2026-08-10 05:52 | 2026-08-05 09:36 | −116.26 | 16 d |
| AWB-30 | 2026-07-30 02:52 | 2026-07-27 10:29 | −64.39 | 25 d |
| AWB-32 | 2026-07-21 02:43 | 2026-07-18 12:54 | −61.81 | 34 d |
| AWB-36 | 2026-07-14 02:47 | 2026-07-13 18:37 | −8.16 | 39 d |
| AWB-47 | 2026-06-05 07:51 | 2026-06-02 09:14 | −70.62 | 80 d |
| AWB-49 | 2026-05-25 02:14 | 2026-05-22 00:20 | −73.90 | 91 d |

**Post-backfill, DSK precedes the DHL-email stamp in 8 of 13 measurable rows.** The stage as
defined — *"DHL email → DSK"* — is directionally wrong for how the workflow now runs.

**Corroborating signal, tagged INFERRED:** the inverted rows' DHL-email stamps cluster at
02:34 / 02:43 / 02:47 / 02:48 / 02:52 UTC, while the five clean rows sit at 05:13–06:55 UTC.
A ~02:45 UTC cluster is the signature of a scheduled job stamp, not a human email receipt.
`dhl_email_kpi_at_utc` may be recording a *poll* time rather than a *receipt* time on those
rows. **NO EVIDENCE** either way until the ingestion path is read; flagged for W2, and it is
the reason the Chair is asking about ingestion at Trip Line 1.

---

## 4. Zombie / genuine split — VERIFIED

Definitions used (stated so the number can be reproduced):

- **GENUINE** — ≥1 milestone whose `authority` ∈ {`tracking_cache`, `tracking_db`,
  `carrier_shipments`} **and** no invalidating `data_quality` flag.
- **SUSPECT** — carrier evidence present, but an invalidating flag is set.
- **ZOMBIE** — **no** carrier-authority milestone at all; every timestamp is an internal stamp.

Invalidating flags: `invalid_timestamp_order_delivery_before_created`,
`tracking_evidence_missing`, `delivered_claim_without_carrier_terminal`.

| | inbound | outbound | total | share |
|---|---:|---:|---:|---:|
| GENUINE | **1** | 18 | 19 | 31% |
| SUSPECT | 4 | 4 | 8 | 13% |
| **ZOMBIE** | **35** | **0** | **35** | **56%** |
| | 40 | 22 | 62 | |

**The split is not random — it is the direction.** Milestone authority census across all
62 rows:

```
tracking_cache                         312
audit.timeline                         222
audit.dhl_email.received_at             24
carrier_shipments                       22
email_evidence.dhl_request.timestamp    11
tracking_db                              2
```

Inbound `delivered_at_utc` provenance (31 delivered inbound rows):

```
('audit.timeline',)                  28
('audit.timeline','tracking_db')      2
('audit.timeline','tracking_cache')   1
```

**28 of 31 inbound deliveries have no carrier evidence whatsoever.** This is structural, not
a data-quality accident: inbound AWBs are supplier-owned and are not tracked on the Estrella
DHL account. **Every inbound stage duration on the Control Tower measures the interval
between two Estrella paperwork stamps, not physical movement.**

Row-level `data_quality` flag census:

```
invalid_timestamp_order_delivery_before_created   11
tracking_evidence_missing                         10
missing_party_identity                             8
tracking_stale                                     8
mismatched_non_customs_email_evidence              1
mismatched_awb_in_dhl_email_subject                1
delivered_claim_without_carrier_terminal           1
```

---

## 5. Bottleneck ranking defects — VERIFIED against source

`build_bottleneck_ranking` (`dhl_logistics_intelligence.py:396-421`). The only guard is
`if excess is None or n <= 0: continue` (line 403). Rendered output, order preserved:

| # | scope | id | excess h | N | contribution h | Δ% vs prev 30d |
|---:|---|---|---:|---:|---:|---:|
| 1 | inbound | `dhl_email_to_dsk` | 1364.36 | 18 | **24558.48** | — |
| 2 | outbound | `booking_to_first_movement` | 83.77 | 14 | 1172.78 | **1526.8** |
| 3 | outbound | `departure_to_delivery` | 12.55 | 19 | 238.45 | −72.9 |
| 4 | outbound | `booking_to_acceptance` | 181.26 | **1** | 181.26 | — |
| 5 | outbound | `booking_to_delivered` | 0.75 | 17 | 12.75 | **7380.0** |
| 6 | outbound | `pickup_to_delivery` | **−0.75** | 7 | −5.25 | −12.2 |
| 7 | inbound | `poland_to_dhl_email` | **−2.98** | 25 | −74.50 | −9.1 |
| 8 | outbound | `acceptance_to_departure` | **−17.70** | 6 | −106.20 | — |
| 9 | inbound | `origin_pickup_to_poland` | **−9.68** | 25 | −242.00 | −55.6 |
| 10 | inbound | `dsk_to_agency_sad` | **−23.77** | 32 | −760.64 | 177.4 |
| 11 | inbound | `origin_pickup_to_delivered` | **−26.13** | 31 | −810.03 | 27.6 |
| 12 | inbound | `sad_to_pz` | **−47.73** | 30 | −1431.90 | −66.7 |

Four defects, each with its line:

1. **No `excess > 0` filter** — `intelligence.py:403`. Entries 6-12 are stages *beating*
   target, rendered in a list titled "bottlenecks". 7 of 12 rows are noise.
2. **No N floor** — `intelligence.py:403` accepts `n >= 1`. Entry #4 ranks the whole
   `booking_to_acceptance` stage on a **single shipment**.
3. **No prev-N floor on Δ** — `_delta_pct` (`intelligence.py:96`) guards only `previous == 0`.
   Entry #2's Δ 1526.8% compares 13 current samples against **prev N = 1** (8.12 h).
4. **Headline built on an empty current window** — `_transition_period_dto`
   (`intelligence.py:318-321`) computes `excess_vs_target` from the **all-time** `typical`.
   `dhl_email_to_dsk` has `current_30d.n = 0` yet supplies both `top_bottleneck` and
   `top_bottleneck_excess_hours = 1364.36` in the executive summary.

### The Δ7380% entry is a *different* defect from the charter's diagnosis

Charter predicts a prev-N≥3 gate fixes it. Measured: `booking_to_delivered` has
**prev N = 4**, current N = 13. The gate would not fire. The real cause is the value:
`previous_30d.typical = 2.30 h` for booking→**delivered** on an international lane. That is
physically impossible and identifies 4 rows where booking and delivery stamps were written
within hours of each other — the outbound face of the same backfill class.

**The charter's proposed prev-N≥3 gate is necessary but not sufficient.** It kills entry #2
(prev N=1) and leaves entry #5 standing.

---

## 6. Stages that have never once been measurable

| Stage | N | cause |
|---|---:|---|
| `sad_to_customs_cleared` | 0 | `missing_customs_cleared` × 40 — the milestone is never emitted |
| `customs_cleared_to_pz` | 0 | same |
| `departure_to_destination` | 0 | `missing_destination` × 20 |
| `destination_to_delivered` | 0 | `missing_destination` × 19 |

All four are rendered on the Tower with an empty value. `customs_cleared` and `destination`
are milestone ids the projector looks for and nothing ever writes.

**DATA FORENSICS veto exercised** (charter §2.3): a metric built on an unmeasured population
may not ship. These four must either gain an ingestion path or be removed from the view —
they may not continue to render as "no data yet".

---

## 7. `sad_to_pz` typical = 0.27 h — flagged

`typical = 0.27 h` (16 minutes) over N = 30, against a 48 h target, producing
`excess = −47.73` and the "best performing stage" position at rank 12. SAD and PZ are being
stamped essentially simultaneously. That is a bookkeeping event, not a transit duration.
Tagged **INFERRED** — the arithmetic is verified, the interpretation is not yet proven.

---

## 8. Exit gate

| Charter W0 exit-gate requirement | Status |
|---|---|
| Contamination % per stage | ✅ §1, all 16 stages |
| Zombie / genuine split | ✅ §4, 35/19/8 with the structural cause named |
| `email→DSK` verdict with cited evidence line | ✅ §3 — **BACKFILL_ARTIFACT**, `dhl_logistics_projector.py:1995` + per-sample table |

**W0 COMPLETE. → TRIP LINE 1.**

---

## Evidence Auditor sign-off

| Claim class | Tag |
|---|---|
| All N / excluded / contamination figures in §1, §5 | **VERIFIED** — reproduced from the stored 408,422-byte payload |
| Cohort identity `N + excl == cohort` | **VERIFIED** |
| `email→DSK` = BACKFILL_ARTIFACT | **VERIFIED** — day-level histogram + per-sample table |
| Zombie/genuine split | **VERIFIED** — definition stated, reproducible |
| Bottleneck ranking defects 1-4 | **VERIFIED** — each carries a `file:line` |
| `dhl_email_kpi_at_utc` records a poll time, not a receipt time | **NO EVIDENCE** — flagged, not relied upon |
| `sad_to_pz` 0.27 h is a bookkeeping artifact | **INFERRED** — arithmetic verified, interpretation not |
| Inbound has no carrier tracking authority | **VERIFIED** — 28/31 `audit.timeline` only |

No claim in this report is relied upon by a downstream seat while tagged NO EVIDENCE.

## Adversarial Reviewer — what survives this census

1. The census reads the **projection API**, not the underlying DBs. If the projector itself
   drops rows before they reach `rows[]`, the 62-row cohort is not the true population. Not
   yet disproven. *Chair's note: `view=all` is the widest view the route accepts
   (`_VIEW_PATTERN`, `routes_dhl_logistics.py:38`); a DB-level count is owed in W2.*
2. §3's verdict rests on 5 post-backfill samples. Five is a small number to declare a process
   "really ~2 h". The verdict that the 57.8 d figure is **artifact** is safe; the claim that
   real performance **is** ~2 h is weaker and must not be published as a target.
3. Nothing in this census proves the backfill was a one-time event rather than a recurring
   monthly job. If it recurs, fixing presentation alone will let it return.
