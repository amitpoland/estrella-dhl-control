# Browser verification — W1 auto-refresh, W2-S4 rendering, W3 management view

**Campaign:** CT-MASTER · **Date:** 2026-08-22
**Instance:** local uvicorn `127.0.0.1:8099`, code = `campaign/ct-master`, storage = a replica of
production storage in the session scratchpad. Not production. Server stopped after the run
(verified: port 8099 returns `000`, zero matching processes remain).
**Auth:** a throwaway admin account created **in the replica only**
(`ctmaster.local@example.invalid`). No production credential was used, and no password was
typed into any field — the session token was minted server-side on the local instance.

---

## 1. Auto-refresh — VERIFIED server-side

Counted from the uvicorn access log, which is independent of any page instrumentation.
An earlier attempt to count via a patched `window.fetch` returned zero and was **not** trusted;
the server log is the authority.

| Event | `GET /api/v1/dhl/logistics/projection` count |
|---|---|
| page load | 1 |
| `visibilitychange` → visible | 2 |
| after a further 75 s | 3 |

Delta of exactly **1** across 75 s confirms a single 60 s interval — not a runaway loop and not
a duplicated timer. Raw log lines: `campaign/evidence/W1/architect/uvicorn_projection_hits.txt`.

### A real defect this pass caught
The first build guarded the interval on `document.visibilityState === 'visible'` and nothing
else. Chrome reported the backgrounded window as `hidden`, so **no refresh fired at all** for
130 s. The guard was right; the gap was that returning to the tab meant waiting up to a full
minute in front of stale numbers with no catch-up. A `visibilitychange` listener now refreshes
immediately on return. Both paths are counted above.

## 2. Freshness stamp — VERIFIED

```
Updated 2:00:36 AM · refreshes every 60s · projection built 02:00:36
```

`generated_at_warsaw` was already in the payload and was never rendered before.

## 3. Management view — VERIFIED

Rendered live against replica data:

```
NEEDS ACTION NOW      1        1 shipment needs attention today            See which ones →
MOVING NORMALLY       1        1 shipment moving normally                  See the list →
WHERE WE LOSE DAYS    4d 17h 49m
                               Label printed, DHL took the parcel is taking 4d 17h 49m
                               longer than target, on 13 recent shipments
                               5 step(s) cannot be measured yet — see Analyst view
                                                                           See the steps →
IMPORT SPEED          5d 17h 7m
                               Typical import is taking 5d 17h 7m against a target of
                               5d 0h 0m, over 6 recent shipments            See every step →
DAYS LOST THIS MONTH  7.4      7.4 days lost this month across 5 completed imports
                               Time past the 5d 0h 0m import target, added up. Imports that
                               beat target are not netted off.
```

### Jargon audit — PASS

Searched the management view's rendered text for `P90`, `median`, `Δ`, `N=`, `DSK`, `SAD`,
`percentile`, `contamination`, `cohort`, `p75`. **Zero matches.** Every one of those terms is
still present in the Analyst view.

## 4. Analyst view — VERIFIED, nothing removed (Lesson M)

Toggling to Analyst restores every element that was on the page before: the six StatTiles, the
data-quality panel, the view tabs, Operations Now / Intervention / Performance / Cost
Intelligence, the filter row and the table. Capability was **relocated, not removed**, so no
PROJECT_STATE cancellation record is required.

`Top Bottleneck` tile now reads `+113.8h vs target · N=13 · last 30d` — the hardcoded `+` in
front of a possibly-negative number is gone, and the tile states how many shipments it rests on.

## 5. Bottleneck ranking — VERIFIED

```
OUTBOUND  Label printed, DHL took the parcel   +113.8h  Typical 5d 5h 49m vs target 12h · N=13
OUTBOUND  Label printed, DHL actually collected +108.1h  Typical 5d 12h 6m vs target 24h · N=13
OUTBOUND  Whole export, booking to delivered    +85.7h   Typical 7d 13h 41m vs target 96h · N=12
INBOUND   Whole import, pickup to delivered     +17.1h   Typical 5d 17h 7m vs target 120h · N=6
          12 step(s) not ranked — and why
```

Three of the four carry `Δ withheld — previous window too small to compare` instead of a
percentage. The fourth shows `Δ vs previous 30d 27.6%`, which has a previous window above the
floor. No entry has negative excess.

## 6. Contamination block — VERIFIED

Steps failing the gate render `INSUFFICIENT CLEAN DATA` with a plain-language reason and the
counts behind it, e.g. inbound *Waiting for DHL clearance paperwork*. Steps that pass render
their statistics plus `Contamination x% of the last 30 days`.

## 7. Console — clean

Six errors captured across the session, all six identical and pre-existing:

```
[BABEL] Note: The code generator has deoptimised the styling of
        .../v2/proforma-detail.jsx as it exceeds the max of 500KB.
```

`proforma-detail.jsx` is untouched by this campaign. **No message originates from
`pages-v2.jsx`.**

## 8. Layout

`document.documentElement.scrollWidth === clientWidth` — the page body does not scroll
horizontally. The management grid resolves to five columns of 285.9 px inside 1477 px at a
1745 px viewport. An earlier reading of "cards cut off" came from the screenshot capture being
narrower than the real viewport and was withdrawn after measuring.

---

## Not verified here

- Behaviour at narrow/mobile viewports was not exercised. The grid uses
  `repeat(auto-fit, minmax(240px, 1fr))`, which wraps by construction, but that is **INFERRED**,
  not measured.
- The page was verified against a replica, not against production data at deploy time. W6
  re-runs the three live checks against production.
