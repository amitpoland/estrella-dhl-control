# Phase-C Inventory Master — Campaign Decisions (DECISIONS.md)

Campaign-local decision ledger. **`.claude/memory/PROJECT_STATE.md # DECISIONS` is the
repo-canonical record** — entries here duplicate (for campaign-context loading) and
cross-reference the canonical entries by dated heading. Every decision affecting campaign
architecture, scope, or wave boundaries is recorded in BOTH places. Append-only.

---

### 2026-07-03 — Launch Ruling (verbatim R4)

OPERATOR RULING (verbatim):
"Launch Master Campaign. Campaign auto-continues through successive waves only
while the validated architecture remains consistent with the next wave. If evidence
invalidates the assumptions of a future wave, the campaign stops, proposes a manifest
amendment, and waits for that architectural decision before proceeding."

Source: FINAL PRE-LAUNCH AMENDMENT (verbatim R4), item 4.
Recorded: MASTER_MANIFEST.md §5 · PROJECT_STATE.md `# DECISIONS` (### 2026-07-03 —
Phase-C Inventory Master Campaign LAUNCHED).
Effect: campaign ACTIVE; Phase 0 → Wave 1 → auto-continue per Architecture Confidence Gate.

---

### 2026-07-03 — ARCHITECTURE CONFIDENCE GATE (verbatim R4)

OPERATOR RULING (verbatim):
"Continue automatically only while the architecture assumptions required for the
next wave remain valid."

Source: FINAL PRE-LAUNCH AMENDMENT (verbatim R4), item 1.
Effect: WAVE ASSUMPTIONS register lives in MASTER_MANIFEST.md §3; gate mechanics in
CAMPAIGN_OS.md §5 (verify NEXT wave's register at every wave boundary and every health
check; INVALIDATED → stop at boundary + manifest-amendment proposal + operator ruling;
mid-wave future-wave invalidation → record immediately, current wave finishes only
unaffected slices).

---

### 2026-07-03 — CAMPAIGN BUDGET (verbatim R4)

BUDGET (operator, initial estimates, amendable): Wave 1: 8h · Wave 2: 11h · Wave 3: 6h ·
Wave 4: 5h. Health checks record Consumed/Remaining/Forecast per wave; >1.5× budget →
self-assessment ledger entry (scope-vs-estimate); >2× → manifest-revision proposal at the
next boundary. Budget overrun alone is never a silent scope cut.

Source: FINAL PRE-LAUNCH AMENDMENT (verbatim R4), item 3.
Effect: MASTER_MANIFEST.md §4 · SELF_ASSESSMENT.md triggers · RUNTIME.md live tracking.

---

### 2026-07-03 — OPERATOR VERDICT: six rulings + stop-line (verbatim R4)

**Ruling 1 — OI-18 resolved = Option (a).** C-1e proceeds as its own slice
(C-1w1/C-1w2 pattern; mirror-first transitional dual-write ×3, Master/passthrough
reads ×5; pin 2 → 1). Sequence: C-1e → Mirror Completeness Proof (grep evidence,
the ratified check) → C-1f (1d proforma fiscal reads, output-equivalence) → C-1d audit.

**Ruling 2 — WAVE STRUCTURE RESTORED (verbatim):**
"Wave 1 Authority · Wave 2 Backend · Wave 3 Entire UI · Wave 4 Synchronization.
UI is never merged into backend. Backend complete first. UI exactly once."
MASTER_MANIFEST amended at the current boundary: Wave 2 = ALL inventory backend
(sample/returns reads, movement, merchandising/batch reads, consignment MODEL where
OI permits, document trails) — ZERO UI; Wave 3 = the complete wireframe UI built once
(CP3 recognition gate); Wave 4 = MM integration + webhook synchronization. Assumption
registers + budgets re-derived; parity/UI items formerly inside Wave 2 moved to Wave 3.

**Ruling 3 — PERMANENT RATIFICATION RULE (verbatim, → CAMPAIGN_OS §5a):**
"Whenever the manifest is authored or materially reconstructed from repository
evidence instead of an already-ratified manifest, the next wave requires operator
ratification before execution."

**Ruling 4 — GOVERNANCE DURABILITY LESSON (verbatim, → LESSONS_LEARNED.md #1):**
"Problem: Governance prompts never reached disk. Why: Chat transport silently dropped
long prompts. Rule: Every governance change must create a durable artifact. If the
artifact does not exist, the governance change did not happen."
Companion mechanic (→ CAMPAIGN_OS §8a): every governance-bearing order is ACKNOWLEDGED
by naming the artifact + SHA it produced; an order without its artifact is treated as
never received.

**Ruling 5 — DIRTY-TREE PROTECTION (verbatim, → CAMPAIGN_OS §9):**
"Agent must never execute: git stash, git clean, git reset --hard unless explicitly
authorized." Slice pre-flight addition: "Dirty Tree Protection — Record: modified
files, untracked files. Restore verification before commit."
(Paid cost cited: the 46-entry stash incident during C-1w2, recovered by stash pop.)

**Ruling 6 — Continue per the OS:** C-1e now → C-1f → C-1d.

**OPERATOR STOP-LINE (verbatim, binding):**
"After C-1d, STOP for operator ratification of the restored Wave 2-4 plan. Do not
enter Wave 2 automatically because the manifest was reconstructed from repo evidence."
The C-1d CP status presents the full restored Wave 2–4 plan (scope, slices,
assumptions, budgets); the campaign HOLDS there for the operator's word. Hard stops
and silence discipline unchanged.

Source: operator verdict 2026-07-03 (verbatim R4). Recorded also in
PROJECT_STATE.md `# DECISIONS`. Artifacts: this entry · CAMPAIGN_OS §5a/§8a/§9 ·
LESSONS_LEARNED.md · MASTER_MANIFEST restored-wave amendment · OPEN_ITEMS OI-18
ANSWERED (commit SHA named in the acknowledgment per Ruling 4).

---

### 2026-07-03 — WAVE 2 RATIFIED (operator, verbatim, with four amendments)

OPERATOR RULING (verbatim): "RATIFIED. Wave 2 begins."

Amendments to the ratification packet (verbatim):
1. "C-3g (transitional dual-write cleanup + cache-passthrough retirement) is Wave 2
   slice #1 — product pin must reach true 0 before C-3b onward."
2. "Residual-2 census: INSPECTOR verifies each of the 6 files. Sync-layer services ->
   whitelist WITH file:line citation. Any business logic found -> migrate slice,
   propose scope. Dev tools -> exempt-by-purpose, documented."
3. "Residual-3: one batched test-health slice inside Wave 2 — absorb the storage-leak
   fix as its first commit, landed on deploy/latest (single-lane; close any side
   worktree)."
4. "users.db import-time creation -> LESSONS_LEARNED entry + follow-up task
   (fresh-checkout trap), not chased now."

Rules confirmed unchanged (verbatim): "ZERO UI. C-3a migration applies to verify tree
only (prod apply = CP4/deploy, operator ritual). C-4a runs only if OI-17 is answered;
the wave completes without it otherwise. Stop conditions unchanged: hard stops,
Confidence Gate, CP3/CP4."

Effect: CAMPAIGN_OS §5a stop-line satisfied for Wave 2; Wave 2 (Backend) ACTIVE.
Slice order: C-3g → Residual-2 census → Residual-3 test-health → C-3a (verify tree)
→ C-3b → C-3c → C-3d → C-3e → C-3f; C-4a only if OI-17 answered in-wave.
Residual mapping (C-1d audit §Declared residuals): C-3g = residuals 1+2;
census = residual 3 (6 files: services/global_pz_push.py, services/wfirma_reservation.py,
services/wfirma_reservation_create.py, tools/build_pz_batch.py,
tools/send_wfirma_good_live_test.py, tools/send_wfirma_proforma_live_test.py);
test-health = residual 4.

Recorded: MASTER_MANIFEST §2/§6 amendment · RUNTIME.md · LESSONS_LEARNED.md #3 (users.db)
· BACKLOG.md B-017 (users.db follow-up, SCHEDULED) · PROJECT_STATE.md `# DECISIONS`
(canonical). Artifact SHA named in the acknowledgment per §8a.

---

### 2026-07-03 — C-3g slice decisions (Wave 2 slice #1)

Executed under Wave-2 ratification amendment 1 (pin → true 0). Five slice-level
decisions, each a documented default per Anti-HOLD ("technical ambiguity with a
sensible default"):

1. **service_product_registry (new table, pildb / proforma_links.db).** The
   retired wfirma_products cache was the ONLY store of service-charge emission
   metadata (freight label, informational vat_rate, unit); mirror discipline
   forbids business fields, and C-1w1 ruled service charges out of product_master.
   The metadata is PROFORMA-domain line-emission config → it lives in the PROFORMA
   authority's own DB. Identity (wfirma_product_id) deliberately NOT duplicated
   there — the mirror stays the sole identity store. Backfill tool:
   `service/tools/backfill_service_product_registry.py` (deploy-ritual step).
2. **routes_wfirma_capabilities.py added to the PRODUCT pin _SYNC_WHITELIST.**
   Same "wFirma-facing by purpose" ruling the CUSTOMER pin already applies to the
   same file. Its product reads/writes ARE sync management (mapping registry
   listing, adopt-pending — it already calls wfdb.adopt_pending_product directly).
   The transitional rdb.get_cached_* passthroughs it used were retired; it now
   reads wfirma_db directly as a declared sync surface.
3. **Semantic sync-state API** `product_authority_resolver.get_registered_goods_state(_batch)`
   (returns wfirma_product_id + last-synced display name only) replaces raw-cache
   passthrough reads for the two sync operations living in routes_wfirma
   (products/resolve drift check, products/sync-names before-value) and the
   proforma invoice-line-name enrichment. Alternative considered: moving the two
   endpoint bodies wholesale into the sync layer (~400 lines churn in fiscal
   paths) — deferred as a future refinement, recorded here.
4. **DEFECT found & fixed in-slice:** C-1f (`6a781ee4`) removed the
   `prod = wfdb.get_product(ct)` assignment in `_build_service_charge_lines` but
   left `prod.get(...)` references → **NameError on EVERY mapped service charge**
   at proforma build. The C-1f output-equivalence gate missed it because the
   registry suite's mapped-charge tests were already failing (they were in the
   C-1d pre-existing-failure register as capabilities/registry noise). Fixed in
   C-3g; pinned by test_service_product_registry_phase2_3 (source-grep asserts
   no dangling `prod.get`, and the mapped-freight/insurance tests now seed the
   real mirror+registry stores).
5. **Verify-tree data collision surfaced:** cache rows `EJL/26-27/254-1` and
   `EJL/26-27/257-2` both claim wFirma goods id `99`; the mirror's UNIQUE
   invariant keeps 254-1 and reports 257-2 unresolved (honest state). Prod deploy
   ritual must run the mirror backfill and resolve any reported collision before
   going live — `service/docs/ops/c3g-deploy-note.md` is the CP4 payload.

---

### 2026-07-03 — R2-census dispositions (Wave-2 amendment 2, INSPECTOR-verified)

Each of the 6 out-of-pin census files received exactly one disposition
(GATE 4 discipline). INSPECTOR = read-only inspection agent; full report in
the Wave-2 session record; citations recorded in test_master_consumption_rule.py
_SYNC_WHITELIST comments.

| File | Verdict | Basis (citation) |
|---|---|---|
| services/global_pz_push.py | SYNC-LAYER → whitelisted | :235-248 `_build_product_map` reads list_products for wfirma_product_id+product_code only (PZ payload good_id map); no cache/mirror writes |
| services/wfirma_reservation.py | SYNC-LAYER → whitelisted | :362-368 get_product readiness gate (wfirma_product_id, sync_status) pre-reservation-sync; no cache/mirror writes |
| services/wfirma_reservation_create.py | SYNC-LAYER → whitelisted | :143-158 Gate 7 get_product → ReservationLine (wfirma_product_id, product_name_pl, unit); no cache/mirror writes |
| tools/build_pz_batch.py | DEV-TOOL → exempt-by-purpose | :142 get_product_by_code behind explicit `--resolve` flag; CLI only, no production import |
| tools/send_wfirma_good_live_test.py | DEV-TOOL → exempt-by-purpose | :405 duplicate-existence guard; double-confirmation CLI |
| tools/send_wfirma_proforma_live_test.py | DEV-TOOL → exempt-by-purpose | :235 `--bill-to --product-code` line resolution; double-confirmation CLI |

**No BUSINESS-LOGIC verdicts → no migrate slice required.** None of the six
files write wfirma_products or the mirror (writers remain exclusively the
whitelisted sync modules). Census closed.

---

### 2026-07-03 — Platform authored in-session (operator authorization)

DECISION: the eight-document platform was authored fresh in this session from repo
evidence, under explicit operator authorization ("Author the platform here"). The prior
design rounds R1–R3 occurred in a channel with no record on this machine (verified:
working tree, git history all branches, session transcripts, upload channel — all
negative).
BASIS: Constitution §18 (No Creativity) requires operator authorization for structure
creation; granted 2026-07-03 via session question.
SCOPE: platform structure only. All business facts inside the documents cite repo
evidence (integration audit `b9f5664c`+amendment, wireframe inspection 2026-07-02,
PROJECT_STATE DECISIONS, git log). Slices not derivable from evidence are marked
`TBD — populate from Phase 0`, never invented.
