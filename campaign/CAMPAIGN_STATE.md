# CAMPAIGN_STATE.md — CT-MASTER

**Append-only.** Last entry is ground truth. Never resume from memory.

---

## Header

| Field | Value |
|---|---|
| Campaign id | CT-MASTER |
| Charter | `CAMPAIGN_CT_MASTER.md` (operator-supplied, session-scoped; not committed) |
| Status | **W0 COMPLETE — HELD AT TRIP LINE 1** |
| Working tree | `C:\PZ-wt\ct-master` (branch `campaign/ct-master`, cut from `main` @ `9b0d3819`) |
| Read tree | `C:\PZ-main` @ `9b0d3819` (clean, == origin/main) |
| Live evidence source | `http://127.0.0.1:47213` (PZService RUNNING) |
| Open PRs by this campaign | 0 (ceiling 2) |

### PATH GUARD — confirmed
- `C:\PZ-verify` is **occupied**: HEAD `7d27eda4`, branch `fix/description-authority-usable-predicate`, dirty tree. NOT used.
- `C:\PZ-main` @ `9b0d3819`, clean — used **read-only** for source inspection.
- `C:\PZ-wt\ct-master` created for all campaign writes. Single session.

---

## Wave plan status

| Wave | Status |
|---|---|
| W0 CENSUS | ✅ COMPLETE — `campaign/reports/W0-report.md` |
| W1 FRESHNESS | ✅ EVIDENCE COMPLETE — charter hypothesis **overturned**, see below |
| W2 METRIC CORRECTNESS | BLOCKED on Trip Line 1 |
| W3 MANAGEMENT LANGUAGE | NOT STARTED |
| W4 OUTBOUND PAGE | NOT STARTED |
| W5 DHL PUSH INGEST | NOT STARTED |
| W6 DEPLOY | NOT STARTED |

---

## Entry 001 — 2026-08-22 — CHAIR — campaign convened

Charter read. PATH GUARD confirmed (above). Evidence vault created at `campaign/`.
Authority map for the concern under repair, all `C:\PZ-main` @ `9b0d3819`:

| Concern | Authority | Duplicate? |
|---|---|---|
| Control Tower HTTP surface | `service/app/api/routes_dhl_logistics.py` (242 L) | none |
| Row projection / cohort / exclusions | `service/app/services/dhl_logistics_projector.py` (2591 L) | none |
| Stage KPIs / bottleneck / lanes | `service/app/services/dhl_logistics_intelligence.py` (645 L) | none |
| Targets (constants) | `service/app/services/dhl_logistics_targets.py` (81 L) | none |
| PDF export | `service/app/services/dhl_logistics_intelligence_pdf.py` (289 L) | none |
| Page render | `service/app/static/v2/pages-v2.jsx` → `DhlCustomsPage` | none |
| API wrapper | `service/app/static/v2/pz-api.js:1428-1477` | none |

**VERIFIED — single authority holds for every concern in scope.** No duplicate resolver found.
Principal Architect veto not triggered.

---

## Entry 002 — 2026-08-22 — DATA FORENSICS — W0 census complete

Raw artifact: `campaign/evidence/W0/data-forensics/projection_all_2026-08-21T2315Z.json`
(408,422 bytes, `HTTP 200`, `GET /api/v1/dhl/logistics/projection?direction=all&view=all`,
`generated_at_utc = 2026-08-21T23:15:12.336642+00:00`).

Full findings: `campaign/reports/W0-report.md`. Headline verdicts:

1. **Cohort spine is already sound.** For every stage, `N + excluded_n == direction cohort`
   exactly (inbound 40, outbound 22). The "impossible funnel" is a **presentation** defect,
   not an arithmetic one — the six numbers are independent pair-coverage counts, not a funnel.
2. **`DHL email → DSK` = BACKFILL_ARTIFACT.** 17 of 21 pre-June DSK stamps land inside the
   10-day window 2026-04-27 → 2026-05-06 against DHL emails spanning 2026-01-07 → 2026-04-14.
   Every DSK stamped after that window measures **≤ 2.96 h**. The 57.8 d headline is the
   backfill, entirely. Current-30d N = 0.
3. **Zombie/genuine split: 35 ZOMBIE (56%) / 19 GENUINE (31%) / 8 SUSPECT (13%).**
   Structural cause: **inbound has no carrier tracking authority at all** — 28 of 31 inbound
   `delivered_at_utc` come from `audit.timeline` only.
4. **Bottleneck ranking: 7 of 12 rendered entries have negative excess** (stages beating
   target), one is ranked on N=1, and Δ is computed against prev-N as low as 1.
5. Contamination ≥ 40% on **6 stages**, four of them at **100%** (never once measurable).

**Veto:** DATA FORENSICS holds a veto on any metric built on an unmeasured population.
Exercised against `sad_to_customs_cleared`, `customs_cleared_to_pz`,
`departure_to_destination`, `destination_to_delivered` — all N=0, all currently rendered.

---

## Entry 003 — 2026-08-22 — PRINCIPAL ARCHITECT + SR FRONTEND — W1 freshness

**The charter's W1 hypothesis is overturned by direct evidence.**

Charter §6 W1 states: *"INFERRED: mixed staleness — different cards have different freshness
authorities, and the page never re-fetches."*

- **Second half VERIFIED.** `pages-v2.jsx:111` — `React.useEffect(() => { if (mainTab ===
  'logistics') loadProjection(); }, [loadProjection, mainTab])`. No `setInterval`, no
  `EventSource` anywhere in the file (grep returned nothing). Only the manual `↻ Reload`
  button at `pages-v2.jsx:206`.
- **First half FALSIFIED.** There is exactly **one** page-render freshness authority. Every
  logistics card — KPIs, transit performance, bottlenecks, lanes, ops-now — renders from the
  single `data` object returned by one `GET /projection`. `pages-v2.jsx:120-124` destructures
  all of them off that one response. The endpoint sets `no-store` and the projector holds no
  memo/lru cache; it recomputes per request.

**Corrected explanation of the two screenshots.** `Booking→first movement` moved while
`email→DSK` and the lane table were byte-identical because the two cards have *different
sample recency*, not different caches: `booking_to_first_movement` has `current_30d.n = 13`
(live samples still arriving, so its all-time median drifts); `dhl_email_to_dsk` has
`current_30d.n = 0` and its median is frozen inside the April/May backfill — it is arithmetically
incapable of moving. The lane table (n=22, all historical) likewise cannot move.

**Consequence for W1 scope.** The freshness authority map is two rows, not a matrix:

| Layer | Authority | TTL | Invalidation trigger |
|---|---|---|---|
| Page render (every card) | `GET /api/v1/dhl/logistics/projection` — `routes_dhl_logistics.py:60` | none; `no-store`, recomputed per request | user clicks `↻ Reload`, or changes view/direction/q/stage/date filter |
| Outbound carrier facts | `storage/outputs/<batch>/tracking_cache.json` — read at `dhl_logistics_projector.py:1106-1122` | set by the tracking poller, outside this page | poller run |

W1 therefore reduces to a **single slice**: add auto-refresh to the one existing fetch, and
surface `generated_at_utc` (already in the payload, currently unrendered) as the page's
freshness stamp. No per-card authority work is needed because no per-card authority exists.

---

## Entry 004 — 2026-08-22 — CHAIR — HELD AT TRIP LINE 1

Charter §5 Trip Line 1 fires after W0 census. Contamination exceeds 40% on 6 of 16 stages
(4 at 100%), and the census produced a strategic finding the charter did not anticipate:
the inbound pipeline has **no carrier tracking authority**, so inbound stage durations
measure internal paperwork stamps, not physical movement.

Presented to Operator. Awaiting path decision. No file outside `campaign/` has been modified.
