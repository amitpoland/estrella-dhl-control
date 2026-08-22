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

---

## Entry 005 — 2026-08-22 — CHAIR — TRIP LINE 1 cleared, W1–W4 executed

Operator decision at Trip Line 1:
- **W2 path:** presentation-first + two ingestion carve-outs.
- **Inbound tracking:** accept and label it. W5 narrows to outbound.

**Council dispatch — disclosed substitution (charter §2, Lesson B/K).** Seats were run in the
main thread rather than as dispatched subagents. Subagents do not share context, so each would
have re-read the charter and re-derived the census, and the operator's standing performance rule
prohibits background agents by default. The protocol's substance was preserved — propose,
challenge, revise, ratify, verify — with the Evidence Auditor's and Architect's vetoes both
exercised against my own work. Disclosed here rather than applied silently.

### Commits on `campaign/ct-master`

| SHA | Wave | What |
|---|---|---|
| `533f25d0` | W0 | census + evidence vault + re-runnable script |
| `1b1d77ce` | W2-S1 | carrier type-code normaliser — four dead stages repaired |
| `c20428e9` | W2-S2/S3 | contamination split, backfilled-booking rule, ranking gates |
| `d292e1b5` | W1+W3 | auto-refresh + freshness stamp; management / analyst views |
| `885d15cd` | W4 | inbound clearance panel removed from the outbound page |
| `b9425025` | W5 (part) | carrier-stage authority consolidated into `tracking_normalizer` |

### Runtime payload — 6 files, all under `service/app`

```
service/app/services/dhl_logistics_intelligence.py  +286
service/app/services/dhl_logistics_projector.py     +244
service/app/services/dhl_logistics_targets.py        +16
service/app/services/tracking_normalizer.py          +65
service/app/static/v2/pages-v2.jsx                  +251
service/app/static/v2/proforma-detail.jsx           +115
```

**No root-level engine file is touched — Lesson J's separate sync does not apply.**
Tests and `campaign/` are outside the runtime payload.

### Working-tree line endings — checked, because a deploy copies bytes, not commits

`core.autocrlf=true`, no `.gitattributes`, production files are CRLF. A Python rewrite can
convert a working file to LF in a way `git diff` cannot show, which would make every touched
file differ from production by more than its actual change. Verified after normalising: three
**unchanged** control files are SHA256-identical between this tree and `C:\PZ`
(`routes_dhl_logistics.py`, `dhl_logistics_intelligence_pdf.py`, `pz-api.js`), so the tree's
convention is deploy-consistent and the changed files differ only by their edits.

### Self-caught defects — recorded because each was wrong-in-my-favour (Lesson Q rule 6)

1. **Wrong-revision baseline.** The first before/after compared the live service against my
   tree. Production is `3748daae`, not the `a4a7c227` the memory index carried — CLAUDE.md's own
   rule is to re-measure `C:\PZ\version.txt` every time. Re-baselined: one revision, one variable.
2. **Incomplete replica.** A "copy artifact" explanation for an inbound delta was asserted and
   then disproved. The real cause was 11 `email_evidence` files not copied. After copying, the
   replica reproduced the live projection exactly (inbound `25/25/18/32/0/0/30/31`).
3. **A gate measuring the wrong population.** Contamination was computed over the all-time
   cohort and used to block a current-window statistic. Six ~38-day-old backfilled bookings
   suppressed the only three real bottlenecks in the dataset.
4. **Duplicate authority, mine.** W2-S1 added a second carrier-event classifier without checking
   that `tracking_normalizer` already owned the concern. Consolidated in `b9425025`.

### Backlog — LOW/MEDIUM, never a deploy blocker per the operating model

- `test_dhl_logistics_resolution.py::test_admin_resolve_requires_comment_and_does_not_touch_tracking`
  fails identically on clean `main` — a textbook **Lesson O** stale test. The route was tightened
  to `require_dhl_resolve`; the test still sends `X-API-Key` and gets 401 instead of 422.
  Canonical fix: `app.dependency_overrides[require_dhl_resolve]`, popped in a `finally`.
- `normalize_tracking_event` cannot separate `AF` (sort facility) from `AR` (delivery facility)
  — both score `ARRIVED_ORIGIN_HUB` at 0.75 — and `WC` returns a stage at confidence **0.0**.
  Deliberately not touched: `STAGE_ORDER` drives milestone emission under invariants the module
  documents as locked.
- Three pre-existing failures in the wider `-k normaliz` sweep, identical on clean `main`.
- **Deploy-guard false positive:** `cat >> campaign/CAMPAIGN_STATE.md` run from
  `C:\PZ-wt\ct-master` was blocked as `redirect-into-prod`, because the path prefix `/c/PZ-wt`
  matches `/c/PZ`. Per CLAUDE.md's guard semantics this is a usability defect to fix in
  `classify_command`, not friction to normalise. Not routed around — the Write tool was used.

---

## Entry 006 — 2026-08-22 — CHAIR — W5 exit gate CANNOT be signed

Charter §5.3.1 precondition 1 requires the Evidence Auditor to have signed **every** W2–W5 exit
gate. W5's gate reads: *"webhook receipt logged end-to-end with raw payload; poll fallback proven
on a shipment with no subscription."*

Measured:

| W5 component | State |
|---|---|
| One normaliser for push and poll | **DONE** — `tracking_normalizer.carrier_stage_id`, `b9425025` |
| Webhook ingest endpoint | **EXISTS ALREADY** — `routes_carrier_webhook.py`, HMAC-SHA256, dedup, log-safe storage to `carrier_events.db`. Its docstring records a deliberate prior decision: no business-state mutation, no coordinator calls. So receipt is logged, but the payload does not reach the tracking pipeline. |
| Poll fallback every 15 min | **DOES NOT EXIST** — the only scheduler registered in the service is `wfirma_webhook_scheduler`. Tracking refreshes on demand only. |

The poll floor the charter calls permanent has never been built. **The Evidence Auditor cannot
sign W5, so §5.3's pre-authorisation does not cover a release that claims it** — the charter is
explicit that a failed precondition voids the authority.

Nothing in the W0–W4 runtime payload depends on the poller. Wiring the webhook into the pipeline
would reverse a documented prior design decision, and a scheduled DHL poller carries API-quota
and rate-limit consequences (`rate_limited` / `retry_after` are already in the cache contract).
Both belong in their own slice with their own review, not bolted onto a release at the end of a
long session.

**Held for the Operator: release scope.** This is a scope decision, not a technical one, so the
Chair does not take it alone. Deploy preparation is otherwise complete — window open (00:13
Warsaw, Saturday), no batch in flight, payload identified, 95 targeted tests green.

---

## Entry 007 — 2026-08-22 — CHAIR — seven-agent gate + a PII incident of my own making

Operator narrowed the release to **W0–W4 plus the normaliser consolidation**. W5's poller is a
separate wave. The DSK backfill is treated as a one-time historical event.

### Seven-agent gate — six reviewers on frozen head `73cbd658`

| Seat | Risk | Verdict |
|---|---|---|
| `deploy-git-diff-reviewer` | LOW | **CLEAR** — no forbidden paths, no engine files, no schema, no auth |
| `deploy-backend-impact-reviewer` | LOW | **CLEAR** — import DAG acyclic; every `build_bottleneck_ranking` caller traced |
| `deploy-persistence-storage-reviewer` | LOW | **CLEAR** — read-only; `tracking_normalizer` locked invariants untouched |
| `deploy-security-reviewer` | MEDIUM | **CONDITIONAL** — runtime payload clear; **PII blocker** on the branch |
| `deploy-qa-reviewer` | MEDIUM | **CLEAR** — floors cleared; 3 non-blocking coverage flags |
| `deploy-release-manager` | — | **CONDITIONAL** — Lesson D applies to a worktree deploy; merge-first recommended |

Two independent confirmations worth recording, because both were claims of mine that could have
been wrong in my favour: no root-level engine file is touched (Lesson J's separate sync does not
apply), and the additions to `tracking_normalizer.py` sit *alongside* its write path —
`_MILESTONE_ALLOWLIST`, the dedup key and `apply_workflow_progression` are unchanged.

### PII incident — mine, caught by the gate, contained

`deploy-security-reviewer` raised a **non-overridable** `PII_IN_COMMIT` blocker. The repository is
**PUBLIC** (`gh repo view` → `isPrivate: false`). I had committed five live projection snapshots
carrying **54 real counterparty names, 62 AWBs and 21 declared values**, plus the same identifiers
inside `census_stdout.txt` and both wave reports.

**Nothing leaked.** The branch had never been pushed (`git ls-remote` empty,
`git branch -r --contains HEAD` empty), so this was contained to this machine.

Remediation:
1. **Pseudonymised, not deleted.** Every census figure is aggregate and needs no real name, but the
   per-sample tables need stable identifiers or a reader cannot check that the same shipment sits
   in the same place across two files. 62 AWB, 20 party and 40 batch tokens, shared across every
   evidence file and both reports. Declared values, quoted costs, weights, destination cities and
   milestone locations redacted outright.
2. **Field-level scrubbing was not sufficient** — AWBs also live inside `tracking_url` query
   strings and free-text event lines — so the serialised JSON gets a final sweep, and the script
   exits non-zero if any mapped identifier survives anywhere under `campaign/`.
3. **Stripped from every commit**, not merely replaced at the tip:
   `git filter-branch --index-filter` over `main..HEAD`. Branch went 8 commits → 7 (one pruned as
   empty); sanitised versions re-added in one new commit.
4. **Verified independently of the sanitiser:** a `git cat-file` pass over every blob under
   `campaign/` in all 7 commits finds zero AWB-shaped numbers and zero known party names.
5. **The gate verdict still binds:** all six runtime-payload blobs are byte-identical between the
   reviewed `73cbd658` and the post-rewrite HEAD (`git rev-parse 73cbd658:<path>` vs `HEAD:<path>`).

Re-verification was sent back to `deploy-security-reviewer` rather than self-certified — a
security blocker is not the Chair's to clear.

**Lesson for the vault:** the charter's evidence protocol says "RAW stdout only, never edited".
Raw is right for *stdout*; a raw capture of a live production **payload** is a different object,
and on a public repo it needs pseudonymising before it is committed, not after it is caught.

### Release path

`deploy-release-manager` established that deploying directly from this worktree would be a
**LOCAL-COMMIT-ONLY deploy under Lesson D** (non-`main` branch, SHA not on `origin/main`),
requiring a disclosure header and a reconciliation plan. The clean alternative is merge-first:
push → PR → merge to `main` → `ff-only` pull into `C:\PZ-main` → deploy from there. That removes
both the branch-name block and the Lesson D requirement.

Pushing this branch to a **public** remote is an outward-facing, irreversible act, and its content
was PII-contaminated until minutes ago. The Chair does not take that step on standing
authorisation — it goes to the Operator with the security re-verification attached.

---

## Entry 008 — 2026-08-22 — CHAIR — gate GO, pushed, PR open, HELD at operator-only merge

### Seven-agent gate — COMPLETE

`deploy-lead-coordinator` verdict: **READY-TO-DEPLOY**, risk **LOW**.

It concurred that the gate still binds despite the SHA change, on the byte-identical-payload
proof, citing the operating model's runtime-payload rule directly. It resolved the two
outstanding conditions explicitly:

1. The security blocker was **resolved, not overridden** — the reviewer itself re-verified and
   cleared it before coordination. That distinction matters: a non-overridable class stayed
   non-overridable.
2. Release-manager CONDITIONAL is discharged by the **mandatory merge-first path**. Deploying
   directly from `C:\PZ-wt\ct-master` is **FORBIDDEN under this verdict** — it would trigger both
   the branch-not-`main` block and Lesson D LOCAL-COMMIT-ONLY without disclosure.

### Operator authorised the public push

Final pre-push scan before the irreversible step: **81 `campaign/` blobs across all 10 commits,
zero AWB-shaped numbers, zero known party names.**

- Pushed: `campaign/ct-master` → `origin`
- PR: **#1313** → `main`

### HELD — operator-only boundaries

Three controls stopped the Chair, all correctly:

| Boundary | Guard / cause |
|---|---|
| `gh pr merge` | `BLOCK_DEPLOY_OPERATOR_ONLY` — autonomous merge is default-off |
| `Deploy-PZ.ps1` (even `-WhatIf`) | `BLOCK_DEPLOY_OPERATOR_ONLY` — deploy execution is operator-only |
| `PZService` restart | session is not elevated (`IsInRole(Administrator) = False`) |

None was routed around. This is HOLD condition 2 (access the session cannot safely obtain),
combined with an explicit operator-only control.

### Remaining sequence

1. **Operator merges PR #1313** to `main`.
2. **Chair writes** `C:\PZ-secrets\deploy-gate\latest.json` — schema v1, `target_sha` = the merge
   commit, 7 agent entries, `lead_verdict: GO`, 6-hour expiry.
3. **Operator runs** `Deploy-PZ.ps1 -Release` from `C:\PZ-main` in an elevated shell. It resolves
   `origin/main` itself, validates the gate evidence, proves production identity, deploys,
   restarts, validates, and prints one of ALREADY CURRENT / DEPLOYED / ROLLED BACK / FAILED SAFE.

**Pre-deploy live-check baseline** captured against production at `3748daae`
(`campaign/evidence/W6/release/pre-deploy-live-checks.md`) so a post-deploy 200 proves the shape
is unchanged rather than merely that something answered:

| Check | Status | Keys |
|---|---|---|
| `/api/v1/health` | 200 | `status`, `engine`, `environment`, `detail` |
| `/api/v1/dhl/logistics/projection` | 200 | `rows`, `count`, `kpis`, `analytics`, `intelligence` |
| `/api/v1/carrier/status` | 200 | `carrier_api_status`, `carrier_plt_status` |

**Rollback**, pinned to production `3748daae`:
`git revert --no-commit 3748daae..HEAD && git commit` then re-run the sync. `Deploy-PZ.ps1` also
carries its own manifest-validated rollback via `-Rollback -Unit`.

### Campaign hygiene

Temporary verification server (uvicorn :8099) stopped and confirmed down; no orphaned
pytest/uvicorn processes; `PZService` untouched throughout (`STATE: RUNNING`, never stopped).
The storage replica and the throwaway local verifier account exist **only** in the session
scratchpad and were never written to production.
