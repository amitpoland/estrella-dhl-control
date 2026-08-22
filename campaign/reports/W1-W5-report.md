# W1–W5 — EXECUTION REPORT

**Campaign:** CT-MASTER · **Waves:** W1 freshness · W2 metric correctness · W3 management
language · W4 outbound page · W5 ingest normaliser (part)
**Tree:** `C:\PZ-wt\ct-master` · **Frozen HEAD:** `73cbd658`
**Production at time of writing:** `3748daae` (measured from `C:\PZ\version.txt`)

---

## Headline

The Control Tower's #1 bottleneck was fiction. It reported

> `DHL email → DSK · +1364h excess · 24,558 contribution-hours`

from an all-time median with **zero observations in the last thirty days**, dominated by a DSK
backfill compressed into 2026-04-27 → 05-06. Seven of the twelve ranked entries were stages
*beating* target. One was ranked on a single shipment.

After this work, measured on a replica of production storage:

| # | Stage (business name) | Excess vs target | Recent shipments |
|---|---|---:|---:|
| 1 | Label printed, DHL took the parcel | **+113.8h** | 13 |
| 2 | Label printed, DHL actually collected | **+108.1h** | 13 |
| 3 | Whole export, booking to delivered | **+85.7h** | 12 |
| 4 | Whole import, pickup to delivered | **+17.1h** | 6 |

Three of the four are one finding: **once a booking exists, DHL is not physically collecting for
about five days.** It was underneath the fake number the whole time.

`DHL email → DSK` is now withheld, with `contamination_now = 100%` — every one of its four recent
observations has the DSK stamped *before* the email. That sentence is worth more than a median.

---

## W1 — Freshness

### The charter's hypothesis was wrong, and the evidence says so

Charter §6 W1: *"INFERRED: mixed staleness — different cards have different freshness authorities,
and the page never re-fetches."*

- **Second half VERIFIED.** No `setInterval`, no `EventSource` anywhere in the page. Only a manual
  `↻ Reload`.
- **First half FALSIFIED.** There is exactly **one** page-render freshness authority. Every card
  destructures one `GET /api/v1/dhl/logistics/projection`. The endpoint is `no-store` and the
  projector holds no cache — it recomputes per request.

The two screenshots diverged because of **sample recency, not caching**:
`booking_to_first_movement` has `current_30d.n = 13` so its median drifts;
`dhl_email_to_dsk` has `current_30d.n = 0` and is frozen inside the backfill — arithmetically
incapable of moving. The lane table (all historical) likewise cannot move.

W1 therefore collapsed from "build a per-card freshness matrix" to **one slice**.

### Freshness authority map — two rows, because there are two layers

| Layer | Authority | TTL | Invalidation |
|---|---|---|---|
| Page render (every card) | `GET /api/v1/dhl/logistics/projection` — `routes_dhl_logistics.py:60` | none; `no-store`, recomputed per request | 60 s interval · tab becomes visible · filter change · `↻ Reload` |
| Outbound carrier facts | `storage/outputs/<batch>/tracking_cache.json` — read in `dhl_logistics_projector.py` | set by whatever refreshes tracking | **see W5 — no scheduled refresh exists** |

### A defect the browser pass caught

The first build guarded the interval on `visibilityState === 'visible'` and nothing else. Chrome
reported the backgrounded window as `hidden`, so **no refresh fired for 130 s**. The guard was
right — there is no point refetching for a tab nobody is looking at — but returning to the tab
meant up to a full minute in front of stale numbers. A `visibilitychange` listener now catches up
immediately.

Proven from the server access log, not from page instrumentation: load → 1 request,
`visibilitychange` → 2, after a further 75 s → 3. A delta of exactly **1** across 75 s is one
60-second interval, not a runaway timer. An earlier count via a patched `window.fetch` returned
zero and was discarded rather than trusted.

---

## W2 — Metric correctness

### S1 — the type code the tracker was already sending

Every DHL event carries a two-letter type code in `ev["status"]`. The projector discarded it and
stamped all 306 carrier events with the literal stage id `"event"`, so four fixed transitions were
looking for semantic stage ids that never existed.

Both runs below are the same commit's code against the same storage replica; the normaliser is the
only variable.

| Stage | N before | N after | Contamination |
|---|---:|---:|---|
| `booking_to_acceptance` | **1** | **14** | 95.5% → 36.4% |
| `acceptance_to_departure` | 6 | **20** | 72.7% → 9.1% |
| `departure_to_destination` | **0** | **13** | 100% → 40.9% |
| `destination_to_delivered` | **0** | **13** | 100% → 40.9% |

Two stages that had **never once produced a sample** now have thirteen each. Inbound is
untouched: **+0 on all eight stages.** `booking_to_acceptance` is no longer ranked on one shipment.

The code vocabulary is censused from this account's own cache — 962 events, 21 distinct codes — so
it is the carrier contract as received, not a mapping taken from documentation. An unrecognised
code stays `"event"` and stays excluded; guessing a plausible neighbour would silently close a
duration against the wrong milestone.

`AF` (sort facility) is deliberately **not** `AR` (delivery facility). Collapsing them would
report the Leipzig hop as the whole destination leg.

### S2 — coverage is not contamination

They were one undifferentiated `excluded_n`. They are different defects:

- **Coverage** — an endpoint was never recorded. The sample is smaller than the cohort, but every
  sample in it is true.
- **Contamination** — the two stamps we hold describe a sequence that cannot have happened. Those
  samples are not absent, they are *wrong*, and they are what bends a median.

Only contamination blocks publication. Exclusion reasons now name the defect —
`dsk_before_dhl_email`, `acceptance_before_booked`, `pz_before_sad` — instead of
`inverted_or_invalid`.

Neither number was published anywhere before this change: the frontend rendered **no**
exclusion data at all, so DoD #2's "published in-product" was entirely unmet.

### S3 — the ranking, and three defects found while building it

A stage now answers four questions before it earns a rank: is it measurable, is it slow *now*
rather than once, is it actually over target, and are there at least five recent shipments behind
the claim. Everything excluded is published with its reason — a list that silently drops two
thirds of the stages reads as "these are the only stages", and that is how a broken stage stops
being looked at.

**Defect A — the charter's prescribed fix was necessary but not sufficient.** The charter predicted
a prev-N≥3 gate would kill the Δ7380%. Measured: `booking_to_delivered` had **prev-N = 4**. The
gate would not have fired. The real cause was the *value*: `previous_30d.typical = 2.30h` for
booking→delivered on an international lane.

**Defect B — a backfilled booking is not a time anchor.** The three fastest samples were:

| AWB | booked | delivered | reported | carrier had it since |
|---|---|---|---:|---|
| AWB-33 | 2026-07-14 13:12 | 2026-07-14 15:44 | 0.52h | 2026-07-11 16:33 |
| AWB-34 | 2026-07-14 11:33 | 2026-07-14 15:44 | 2.17h | 2026-07-11 16:33 |
| AWB-35 | 2026-07-14 11:17 | 2026-07-14 15:44 | 2.44h | 2026-07-11 16:33 |

Those were not measuring booking→delivery. They were measuring how long after the parcel was
already in flight somebody typed it into EJ. The rule that catches it needs no invented threshold
— it is the same shape as the lifecycle checks already in the module.

**Defect C — my own gate measured the wrong population.** Contamination was computed over the
all-time cohort and then used to block a **current-window** statistic. Six backfilled bookings, all
around 38 days old, suppressed three stages whose recent samples were entirely clean — and those
three carried the only real finding in the dataset. A gate that judges one population and blocks
another is a second way to be wrong, not a safeguard. Caught before commit by re-reading the
ranking output rather than by a test.

### S4 — rendering

`+{excess}h` was a hardcoded plus in front of a possibly-negative number — the `+-2.98h` in the
charter. Now sign-aware, and the ranking cannot contain a negative anyway. Blocked steps render
`INSUFFICIENT CLEAN DATA` with a plain-language reason and the counts behind it.

### The "impossible funnel" was never impossible

`N + excluded_n == direction cohort` on **all sixteen stages**, exactly. The six numbers
`25/25/18/32/30/31` are independent pair-coverage counts drawn in a row, not a funnel. DoD #1 was
already satisfied in the backend and violated only in the drawing.

---

## W3 — Management language

The page now opens on five sentences instead of six statistics. Rendered live:

```
NEEDS ACTION NOW      1        1 shipment needs attention today
MOVING NORMALLY       1        1 shipment moving normally
WHERE WE LOSE DAYS    4d 17h 49m
                               Label printed, DHL took the parcel is taking 4d 17h 49m
                               longer than target, on 13 recent shipments
                               5 step(s) cannot be measured yet — see Analyst view
IMPORT SPEED          5d 17h 7m
                               Typical import is taking 5d 17h 7m against a target of
                               5d 0h 0m, over 6 recent shipments
DAYS LOST THIS MONTH  7.4      7.4 days lost this month across 5 completed imports
```

**Jargon audit — PASS.** Searched the rendered management view for `P90`, `median`, `Δ`, `N=`,
`DSK`, `SAD`, `percentile`, `contamination`, `cohort`, `p75`: **zero matches**. All of it is one
click away under Analyst view.

**Days lost counts only overruns.** An import that beat target does not earn back somebody else's
delay, and netting them off would hide both.

**Lesson M satisfied without a cancellation record.** Every statistic previously on the front page
is still present under Analyst view — relocated, not removed. Verified by toggling in a browser.

---

## W4 — Outbound page

**Removed:** the inbound clearance panel. It fired two extra requests on every render of every
proforma to draw the import workflow on the outbound customer shipment page.

It also could not draw it. Audit timeline events are shaped `{ts, event, trigger_source, actor,
detail}`; the panel looked for a timestamp under `timestamp/time/at/t/date` — **`ts` is not in that
list** — so all **3,142** recorded events rendered a dash for their time, and `detail` is an object,
which its value picker rejected outright. Only the event name ever appeared.

Fixing the key would have produced a correct panel still on the wrong page. The panel is gone,
the authority it belonged to gets a link, and the link renders nothing when the draft has no
import batch rather than offering a dead one. **−2,933 bytes and two round trips per page load.**

**Not built, because it already exists:** the manual weight override.
`routes_proforma.py:10140` accepts net, gross **and** tare; keeps the extracted packing weight as
the historical authority and never overwrites it; snapshots the extracted-weight source revision;
records operator, reason and OCC via `expected_updated_at`. The UI form and the dual-column
display are already wired to it. **DoD #8 was already satisfied before this campaign began.**

---

## W5 — Ingest normaliser (partial)

### Done — and it corrected a duplicate authority I had introduced

W2-S1 added a type-code classifier to the projector without checking what already existed.
`tracking_normalizer` has owned carrier-event classification all along — it classified on the
human description text. Two implementations of one concern, and the second was mine. The
Principal Architect seat holds a veto on exactly this.

The map moved into `tracking_normalizer`; the projector consumes it. The type code stays primary
because the description cannot make a distinction the code makes cleanly:

```
AF "Arrived at DHL Sort Facility LEIPZIG"     -> ARRIVED_ORIGIN_HUB  conf 0.75
AR "Arrived at DHL Delivery Facility ARQUES"  -> ARRIVED_ORIGIN_HUB  conf 0.75
WC "Shipment is out with courier for delivery"-> IN_TRANSIT          conf 0.00
```

`STAGE_ORDER` is deliberately untouched: it drives milestone emission under invariants that module
documents as locked. Two vocabularies remain, but in one file — the file you would open to change
either.

### Not done — and the exit gate cannot be signed

| Component | State |
|---|---|
| One normaliser for push and poll | **DONE** |
| Webhook ingest endpoint | **ALREADY EXISTED** — `routes_carrier_webhook.py`, HMAC-SHA256, dedup, log-safe storage. Its docstring records a deliberate prior decision: no business-state mutation. Receipt is logged; the payload does not reach the tracking pipeline. |
| Poll fallback every 15 min | **DOES NOT EXIST.** The only scheduler registered in the service is `wfirma_webhook_scheduler`. Tracking refreshes on demand only. |

The poll floor the charter calls permanent has never been built. **W5 is unsigned**, and the
Operator narrowed this release to W0–W4 plus the normaliser consolidation.

---

## Test position

| Suite | Passed | Failed | Errors | Floor | Verdict |
|---|---:|---:|---:|---:|---|
| PZ regression `tests/test_pz_*.py` | **296** | 0 | 0 | 260 | OK (+36) |
| Carrier `tests/test_carrier_*.py` | **945** | 3 | 0 | 604 | OK (+341) |
| Targeted Control Tower | **95** | 0 | 0 | — | green |

Counts read from `--junitxml` content, never from pytest summary formatting (Lesson S rule 8).
All three carrier failures are **registered** known-failures in
`.claude/contracts/test-baseline.md`.

One of them, `test_v2_projection_has_no_dhl_fallback`, greps a file this changeset modifies, so it
was checked rather than assumed: my diff adds no `|| 'DHL'`; the single matching line is
`proforma-detail.jsx:1639`, which `git blame` attributes to `f76d8ffb` — the commit the baseline
names; and all three fail identically on clean `C:\PZ-main` at `main`.

## New coverage

| File | Tests | Pins |
|---|---:|---|
| `test_carrier_stage_normalizer.py` | 7 | real cached event shapes; AF≠AR; unknown codes not guessed |
| `test_carrier_stage_single_authority.py` | 7 | the map lives in one module; projector consumes it |
| `test_transition_contamination.py` | 10 | coverage vs contamination; backfilled bookings; window-aware gate |
| `test_outbound_page_authority.py` | 6 | the removed panel stays removed; the link stays present |
| `test_dhl_logistics_intelligence.py` | +6, 1 migrated | ranking gates; Lesson A stub→real-builder migration |

The migrated test is a **Lesson A** case: the original fabricated a KPI dict that never matched
`_transition_period_dto`'s real return shape, so it broke the moment the ranking read fields the
stub had never carried. Rebuilt against the real builder rather than patched.
