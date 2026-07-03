# Phase-C Inventory Master — Campaign Decisions (DECISIONS.md)

**Platform v1.0 — FROZEN at `e2d69602` (operator ruling 2026-07-03)**

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

### 2026-07-03 — OPERATOR VERDICT: wave order locked; deploy gates Wave 3 (verbatim R4)

OPERATOR VERDICT (verbatim):
"Wave 1 Complete. Wave 2 Complete (development). Production deploy +
verification: Pending. Wave 3 begins only after: (1) Production deploy
(2) Post-deploy verification (3) Mirror collision report clean (4) Wave 3
ratification. This order will not change. Prompt stays stable; only the
eight documents evolve."

Effect: supersedes the earlier same-day "Wave 3 is RATIFIED to start
immediately after deploy verification" reading — Wave-3 ratification is a
SEPARATE step (4) after deploy (1), verification (2), and a CLEAN mirror
collision report (3). Campaign holds at CP4/CP5; deploy itself is
operator-executed (hard stop #7 unchanged). Companion order executed this
session: single operator runbook assembled at
`reports/deploy/2026-07-03-wave12-operator-runbook.md` (backup-first with
EstrellaDBBackup red warning — task confirmed ABSENT on this host; ordered
deploy steps; collision report file + per-product ruling table; post-deploy
verification incl. production output-equivalence and the C-1f
mapped-charge exercise; rollback from the .bak set). Lesson recorded:
LESSONS_LEARNED.md #4 (gate coverage must be proven, not assumed).

---

### 2026-07-03 — Wave-3 gate ruling: DEPLOY FIRST, then Wave 3

OPERATOR RULING (session question, 2026-07-03): "Deploy first, then Wave 3" —
run the production deploy ritual now (7-agent gate + CP4; payload =
service/docs/ops/c3g-deploy-note.md incl. mirror backfill + goods-id-99
collision + registry backfill + returns_events prod apply). Wave 3 is RATIFIED
to start immediately after deploy verification; CP3 then closes against live
backends (clears W3-A1).

Deploy mechanics decided in-session (documented defaults):
- Prod base established by CRLF-normalized fingerprint: C:\PZ = origin/main
  HEAD `c7c0e14e` (#814) — version.txt was stale (aa414d90).
- deploy/latest lacked #809–#814 → merge of origin/main required to avoid
  regressing prod. Operator's uncommitted pz-api.js blocked an in-place merge
  (Ruling 5: no stash) → CLEAN deploy worktree `C:\PZ-deploy-w12`, branch
  `deploy/wave12`, merge `84c292de` (zero conflicts). Worktree doubles as the
  robocopy source so operator-dirty files cannot ship.
- Candidate gates green on the worktree: golden 160/160 · pin 11/11 ·
  smoke 63/1 · carrier suites 100.
- Lesson D applies (83 local commits, no PR): disclosure + reconciliation plan
  + local-commit-deploys.jsonl append are part of the CP4 packet.

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

---

### 2026-07-03 — OPERATOR VERDICT: grade + consent rule + Wave-3 triple verification (verbatim R4)

OPERATOR VERDICT (verbatim):
"Campaign grade A-. Deploy gate design approved. Acknowledgment handling was
not strict enough: 'Acknowledgment received' was recorded without the exact
phrase verifiably on record. Wave 3 begins ONLY after three verifications:
(1) Production deployment complete. (2) Mirror backfill complete with zero
unresolved collisions. (3) Production smoke and health checks green.
No new governance rules; only the eight documents evolve."

Effect:
- CONSENT ARTIFACT RULE recorded verbatim as LESSONS_LEARNED.md #5 (with the
  retro-cure: the wave12 Lesson-D acknowledgment was the operator's explicit
  selection of the exact option text "I acknowledge LOCAL-COMMIT-ONLY" —
  now quoted verbatim on the durable record).
- The three verifications align with and refine the earlier wave-order verdict
  (deploy → verification → collision-clean → ratification): after all three
  read GREEN from evidence, Wave 3 STILL requires the operator's separate
  ratification word.
- Session boundary re-affirmed: the agent runs ONLY the read-only tail on the
  operator's deploy report (public health, carrier gate 503-closed,
  service-products smoke vs pre-deploy, version/deploy records,
  local-commit-deploys.jsonl append). No sync command, no C:\PZ write, ever —
  the pz-deploy-guard boundary is correct and permanent.
- No new governance rules; no new files — the platform documents evolve.

Recorded also in PROJECT_STATE.md `# DECISIONS`. Campaign HOLDS at CP4-handover
(runbook a6e15149, hardened 1e43f8bc) awaiting the operator's deploy report.

---

### 2026-07-03 — WAVE-3 GATE: concrete predicates (operator, verbatim)

OPERATOR (verbatim):
"WAVE-3 GATE (operator's three, independently verified):
1. /health on production returns the expected response
2. Mirror backfill: wfirma_id_collisions = 0 (or all resolved by operator ruling)
3. Registry backfill: copied > 0 on prod
All three GREEN -> then, and only then, your separate word ratifies Wave 3."

Effect: refines the triple-verification gate (63446e56) into evaluable
predicates. Each is INDEPENDENTLY verified by the agent from evidence at the
read-only tail: (1) prod /health response; (2) the final mirror-backfill
collision report (`$bakdir\mirror-backfill-collision-report.txt`) showing
wfirma_id_collisions = 0, or every collision carrying an operator ruling on
record; (3) the registry-backfill output showing non-empty `copied`. GREEN×3
is a precondition for — never a substitute for — the operator's separate
Wave-3 ratification word.

---

### 2026-07-03 — WAVE-3 GATE REFINEMENT: four checks (operator, verbatim R4 — amends 8ac57f33)

OPERATOR GATE REFINEMENT (verbatim):
"Final deployment gate:
1. Production /health returns the expected response
2. Mirror backfill clean: wfirma_id_collisions = 0 in the final report,
   or every collision resolved by documented operator ruling
3. Registry backfill: copied > 0 on prod
4. Production smoke tests pass — at minimum the critical flows this
   deployment touches: service-products (including the mapped freight/
   insurance emission, the C-1f path) and the carrier gate (503-closed)
All four GREEN precede — and never replace — the operator's separate
Wave-3 ratification word."

Rationale note (operator-directed): check 4 exists because of
LESSONS_LEARNED #4 — the C-1f defect proved migrations can succeed while
runtime behavior breaks; the smoke set must exercise the actually-touched
code paths, not just endpoints being reachable. The read-only tail already
runs these probes; this ruling promotes them from advisory to GATE-BLOCKING.

Reporting contract: GREEN/RED per check, evidence cited per check.
Check-4 evidence set (minimum): GET /api/v1/proforma/service-products output
equal to the operator's pre-deploy baseline capture
(`$bakdir\service-products-pre-deploy.json`) INCLUDING the mapped
freight/insurance rows (proves the C-1f/C-3g registry emission path), and
the carrier write endpoint returning 503 with carrier_api_status "pending".

---

### 2026-07-03 — WAVE-3 GATE FINALIZATION (operator, verbatim R4 — amends 1129e74e; gate FROZEN hereafter)

REFINEMENT 1 (verbatim) — smoke = baseline comparison, not pass/fail:
"Response status identical · business payload identical where expected ·
no new warnings/errors in logs." A changed-but-working response is a RED
until explained.

REFINEMENT 2 (verbatim) — failure policy, per check:
"GREEN -> proceed to next check.
RED -> Wave 3 blocked.
AMBER -> proceed only with a documented operator ruling (e.g. an approved
mirror collision)."

FINAL WAVE-3 GATE (verbatim, FROZEN):
"1. Production /health — expected response
2. Mirror backfill — wfirma_id_collisions = 0, or every collision carries
   a documented operator ruling (AMBER path)
3. Registry backfill — copied > 0
4. Production smoke — service-products (mapped freight/insurance path) ·
   carrier gate 503-closed · responses match the pre-deploy baseline ·
   no new runtime errors in logs"

DECISION RULE (verbatim): "4x GREEN -> Technical deployment accepted.
Operator says 'Wave 3 begins' -> only then does Wave 3 start."

OPERATOR DESIGN PRINCIPLE (verbatim, recorded as directed):
"Technical acceptance is objective. Business authorization stays entirely
with the operator. Architecture, governance and deployment control remain
separate — the safest model for long autonomous campaigns."

Reporting contract: the read-only tail reports the four checks as
GREEN/AMBER/RED with evidence per check and the baseline diffs attached.
This entry FREEZES the Wave-3 gate — no further amendments; subsequent gate
changes would require a new operator ruling superseding the freeze.
Holding state unchanged: CP4-handover; board moves on "deployed" |
STOP output | collision list (per-row: evidence + recommendation from the
agent, RULING from the operator).

---

### 2026-07-03 — OPERATOR CLOSING PHILOSOPHY (verbatim R4 — CAMPAIGN_OS §11; no new rules, no behavior change)

"अब campaign का control prompt नहीं, artifacts करते हैं।
Constitution तय करता है क्या कभी नहीं बदलता।
Project Knowledge तय करता है business truth क्या है।
Architecture Map तय करता है authority कहाँ है।
Manifest तय करता है इस campaign में क्या करना है।
Campaign State तय करता है अभी कहाँ पहुँचे हैं।
Lessons Learned तय करता है कौन सी गलती दोबारा नहीं करनी।
Architectural Decisions तय करता है कौन से compromises स्वीकार किए गए।
Prompt केवल bootstrap है।
Future rules are amendments to these artifacts, never prompt growth."

Recorded in CAMPAIGN_OS.md §11 (closing section) as directed. Holding state
unchanged: CP4-handover, frozen 4-check gate (a2d13a85), board moves on
"deployed" | STOP output | collision list; 4×GREEN = technical acceptance;
"Wave 3 begins" = business authorization.

---

### 2026-07-03 — PLATFORM FREEZE v1.0 (operator ruling, verbatim R4 — the FINAL governance artifact)

OPERATOR RULING (verbatim):
"Platform Version: v1.0 — FROZEN at e2d69602.
Governance is complete. New rules are added ONLY on: a production
incident, an architectural contradiction, or a paid lesson. Never for a
good idea. Version changes only on fundamental change (v1.1, v1.2, v2.0).
PLATFORM = permanent (Constitution, Campaign OS, Project Knowledge,
Authority Map, Architectural Decisions, Lessons Learned).
CAMPAIGN = temporary (Manifest, Campaign State, current wave).
This separation is permanent. Remaining sequence: Deploy -> Verify ->
Wave 3 -> Wave 4 -> Close campaign. No governance expansion between."

Executed: "Platform v1.0 — FROZEN at e2d69602" stamped in every platform
document header (9 docs + the new CONSTITUTION.md pointer-of-record, which
points to the verbatim Constitution in CLAUDE.md rather than duplicating it —
interpretation disclosed in the file). This artifact closes the governance
era. Holding state unchanged: CP4-handover, frozen 4-check gate (a2d13a85).

---

### 2026-07-03 — FREEZE INTERPRETATION (operator, verbatim R4 — official reading of 33f893cf; no new rule under v1.0)

OPERATOR (verbatim):
"Platform v1.0 frozen means governed, not immutable. New ideas / stylistic
improvements / prompt wording tweaks: NO. Production incident /
architecture contradiction / paid lesson: YES, as amendment.
Mid-campaign discipline: Platform v1.0 is not touched during the campaign.
Lessons paid during Wave 3/4 are captured immediately in LESSONS_LEARNED
(evidence duty), but the platform amendments they justify go to the
Platform v1.1 amendment backlog, evaluated only after campaign closure
with full execution evidence."

Effect: LESSONS_LEARNED stays live during Waves 3/4 (evidence duty,
immediate capture); platform-document amendments justified by those lessons
queue in the §v1.1 backlog below and are evaluated ONLY after campaign
closure. No new file created (deferred items already live in this ledger).

## Platform v1.1 Amendment Backlog (evaluated only after campaign closure, with full execution evidence)

(empty at freeze — entries arrive only via: production incident ·
architecture contradiction · paid lesson)

| # | Date | Trigger (incident/contradiction/lesson) | Proposed amendment | Evidence |
|---|---|---|---|---|
| v1.1-001 | 2026-07-03 | Paid lesson #6 (partial /XO sync; prod ran mixed code) | CAMPAIGN_OS deploy discipline: content-hash sync-verification gate mandatory in every deploy ritual; timestamp-based copy filters forbidden; runbooks validated against the FINAL candidate SHA | LESSONS_LEARNED #6; runbook §2a-v; census total=493 MISSING=1 DIFF=39 (all stale = c7c0e14e) |

---

### 2026-07-03 — DEPLOY REMEDIATION AMENDMENT + COMPLETION CRITERION (operator, verbatim R4)

OPERATOR AMENDMENT (verbatim): "Amend the remediation so that collision
cleanup is transactional (backup rows before deletion), then provide the
exact commands. After the registry backfill, immediately verify that
service_product_registry exists. Do not assume success. Only declare
deployment complete if both the collision count is 0 and the registry
table is present."

COMPLETION CRITERION (verbatim, recorded as directed): deployment complete
ONLY when collisions = 0 AND the registry table is present with copied > 0.

Executed as four committed scripts under reports/deploy/:
collision_precheck.py (read-only row confirmation) · collision_fix.py
(per-DB single-connection BEGIN → backup-table AS SELECT → DELETE →
count-match assert → COMMIT, else ROLLBACK) · collision_postcheck.py
(zero remaining + backup counts 2+2) · registry_backfill_and_verify.py
(tool run + immediate COUNT(*) verification; on residual OperationalError
prints the mandated STOP — "repository diagnosis is wrong; reinvestigate"
— and exits 2, never asking the operator to continue).
Defect-1 basis: both collision rows repo-proven leaked test seeds
(test_proforma_pre_approve_surfacing.py:43,230 ·
test_proforma_readiness_single_authority.py:8,58). Defect-2 basis:
registry table lazily created by pildb init_db (proforma_invoice_link_db.py
:135/:173, accessors :2181/:2211; no startup hook — main.py imports none).
