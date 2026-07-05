# Phase-C Inventory Master — Lessons Learned (LESSONS_LEARNED.md)

**Platform v1.0 — FROZEN at `e2d69602` (operator ruling 2026-07-03)**

Append-only. Entry #1 is operator-ratified verbatim (verdict 2026-07-03, R4).
This file is platform document #9 — loaded with the platform per CAMPAIGN_OS §1.

---

## #1 — Governance Durability (operator, verbatim, 2026-07-03)

"Problem: Governance prompts never reached disk. Why: Chat transport silently
dropped long prompts. Rule: Every governance change must create a durable
artifact. If the artifact does not exist, the governance change did not happen."

Companion mechanic (CAMPAIGN_OS §8a): every governance-bearing order is
ACKNOWLEDGED by naming the artifact + SHA it produced; an order without its
artifact is treated as never received.

Origin: the R1–R3 pre-launch platform design rounds never reached this machine —
the eight-document platform had to be re-authored in-session from repo evidence
(DECISIONS.md "Platform authored in-session", commit `575bb3f3`).

## #2 — Dirty-Tree Protection (operator-ratified, 2026-07-03)

"Agent must never execute: git stash, git clean, git reset --hard unless
explicitly authorized."

Slice pre-flight (mandatory): "Dirty Tree Protection — Record: modified files,
untracked files. Restore verification before commit."

Paid cost: during C-1w2 an implementation subagent ran `git stash -u`, hiding
46 working-tree entries of operator local work (supplier-invoice OCR files,
DHL scripts, modified V2 files); recovered only because the orchestrator
noticed the entry-count drop and popped the stash. Lesson-K-style negative
scope ("DO NOT run git stash") is now mandatory in every write-capable agent
prompt for this campaign.

## #3 — Import-time filesystem side effects are a fresh-checkout trap (users.db, 2026-07-03)

Ratified at Wave-2 ratification (operator amendment 4: "users.db import-time
creation -> LESSONS_LEARNED entry + follow-up task (fresh-checkout trap), not
chased now").

Fact pattern: `service/app/main.py:131-135` computes the auth DB path
(`settings.storage_root / "users.db"`) at MODULE IMPORT time. Test fixtures
patch `settings.storage_root` only around the request-serving context
(`with patch.object(settings, "storage_root", ...)`), but `from app.main
import app` runs BEFORE the patch — so the first import in any fresh
checkout/worktree creates `users.db` in the LIVE storage root. The conftest
storage-leak guard then flags a one-time "STORAGE LEAK (new)" failure that
does not reproduce on the second run (the file now exists and enters the
session baseline). In long-lived trees (`C:\PZ-verify`) the file pre-exists,
so the trap only fires on fresh checkouts — making it look flaky.

Rule: paths derived from `settings.*` must be resolved at CALL time (inside
lifespan/startup or the function that uses them), never at import time.
Import of `app.main` must be filesystem-silent.

Disposition: BACKLOG B-017 (SCHEDULED — follow-up task; not chased in Wave 2).

## #4 — Gate coverage must be proven, not assumed (operator-ratified, 2026-07-03)

Operator rule (verbatim): "the C-1f NameError shipped under both adversarial
review and the output-equivalence gate because the gate's fixtures never
walked the mapped-service-charge path. Rule: gate coverage must be proven
(the gated paths enumerated against the code paths), not assumed."

Fact pattern: C-1f (`6a781ee4`) removed the `prod = wfdb.get_product(ct)`
assignment in `_build_service_charge_lines` but left `prod.get(...)` refs —
a NameError on EVERY mapped freight/insurance emission. The
output-equivalence gate reported PASS because its fixture population never
included a MAPPED service charge (the registry suite's mapped-charge tests
were themselves in the pre-existing-failure register, so the broken path had
zero live coverage). Adversarial review also missed it: reviewers verified
the changed lines, not the reachability of every identifier the hunk left
behind.

Mechanic: before declaring an equivalence/regression gate PASSED for a
migration slice, ENUMERATE the code paths the slice touched (every branch of
every edited function) and map each to at least one fixture that actually
executes it. A path with no executing fixture is UNGATED — say so in the
slice report; do not let a green suite imply coverage it does not have.
Caught in C-3g (`568c05b2`) and pinned by source-grep + mapped-charge tests.

## #5 — CONSENT ARTIFACT RULE (operator, verbatim, 2026-07-03)

"CONSENT ARTIFACT RULE — for irreversible boundaries (deploy, prod writes,
CP4/CP5), the operator's exact acknowledgment phrase must be quoted verbatim
in the durable record BEFORE any execution line is written. A paraphrase, a
--continue, or an inferred consent is a non-acknowledgment. If the record
cannot prove the phrase was given, the acknowledgment did not happen. (Paid
cost: the Wave-2 CP4 packet's ambiguous 'Acknowledgment received' line.)"

Application note: the Lesson-D acknowledgment for the wave12 deploy WAS given
via an explicit selection of the exact option text "I acknowledge
LOCAL-COMMIT-ONLY" (session question, 2026-07-03), but the durable record
wrote only "Acknowledgment received" — insufficient under this rule. The
verbatim phrase is now on record HERE and in DECISIONS.md: the operator
selected the option labeled exactly **"I acknowledge LOCAL-COMMIT-ONLY"**.
Going forward, every irreversible-boundary record quotes the phrase before
any execution step is logged.

## #6 — Deployment runbooks are executable artifacts (operator, verbatim, 2026-07-03)

"Deployment runbooks are executable artifacts. They must be validated
against the final deploy candidate SHA, not the intermediate SHA on which
they were originally written."

Paid cost (evidence, first wave12 deploy execution 2026-07-03; precise
claim per operator amendment 1, verbatim): "Repository inspection shows
backfill_product_authority exists in the deploy candidate
(C:\PZ-deploy-w12 @ 84c292de) at
service/app/services/reservation_db.py:260. The production tree (C:\PZ)
does not contain that implementation because the deployment sync was
incomplete."
- Ritual step 2c therefore failed on prod (import from the stale tree).
- The snippet itself was correct against the candidate SHA (signature
  match at reservation_db.py:260).
  The 2a robocopy with `/XO` (timestamp-skip) left **39 modified files
  stale + 1 new file missing (services/stock_issue.py)** — every stale file
  hash-matched the pre-deploy base `c7c0e14e`; added files copied, modified
  files skipped (the /XO signature). robocopy reported success; the service
  restarted GREEN on the old code paths — "code synced" was an exit-code
  assumption, never content-verified.
- Secondary finding: `POST /api/v1/admin/product-master/backfill`
  (routes_admin.py:117-145) is a DIFFERENT backfill
  (invoice_lines→product_master projection, `require_admin` session-cookie
  auth) — documented in the runbook to prevent it being mistaken for the
  mirror backfill.

Rule (campaign discipline; the platform-level amendment queues to v1.1):
a deploy sync is complete only when a CONTENT-hash census of source vs
deployed tree reads MISSING=0 / DIFF=0 (runbook §2a-v gate). Timestamp-based
copy filters (`/XO`) are forbidden in deploy syncs.

## #7 — Storage-root assumption (operator, verbatim, 2026-07-03)

"The deployment tooling assumed C:\PZ\app\storage while production runs
from C:\PZ\storage. That incorrect assumption caused false collision
reports, false registry failures, investigation against a stale database,
and unnecessary deployment delay. Future deployment tools should obtain
the effective storage root from the running application's configuration
or environment instead of hardcoding a path."

Evidence of the stale-DB artifacts this produced (all later re-measured
against the live root): the goods-id-99 "collision" + its purge + the first
"collisions: 0" (dead copy only; live codes carry real distinct ids
50408675/50409315); the "zero fiscal usage" queries (dead copies of
documents/packing/reservation DBs); "prod cache = 1 row / zero service
products registered" (live cache: 139 rows INCLUDING freight 13002743 +
insurance 13102217); the first registry-absent verification and the
"empty registry is the correct migrated state" conclusion. Remained valid
throughout: the 2a-v SYNC census (code tree, not storage), the migrations
(live warehouse.db carries both event tables via app-init), the route-level
lazy-creation proof, and the 7-agent code reviews. The recorded memory fact
("batch storage root is C:\PZ\storage, NOT C:\PZ\app\storage") had said
this all along — the runbook contradicted it and nothing cross-checked.

Causal sequence (operator, verbatim): "app correctly on C:\PZ\storage ->
scripts verified C:\PZ\app\storage -> dead copy held stale test artifacts ->
false collision + registry failures -> live root = production exactly as
designed."

Companion rule (same failure class): unattributed measurement is how the
wrong-root investigation happened — every recorded measurement carries its
command + output provenance (see the gate-record provenance annexe in
DECISIONS).

Disposition: tooling amendment queued as v1.1-003 (storage-root resolution
from app config/env). Platform v1.0 untouched.

## #8 — Reclassify before writing code (operator, verbatim, 2026-07-04)

"If investigation disproves the reported defect, stop. Reclassify it before
writing code." The ledger is a permanent engineering record, not a change log;
separating bugs / works-as-designed / UX-improvements preserves its integrity.

Decision tree: User reports issue -> Investigate -> {Real bug -> fix it ·
Works as designed -> close WAD (no code under that record) · UX problem ->
new UX-improvement item; the change lives there}.

Paid cost: CP3 Defect #002 (Inventory Export "doesn't work"). Investigation
DISPROVED it — export was correct (filtered rows, working download,
intentionally disabled when empty). Instead of reclassifying first, a UX
change (inline "why disabled" feedback) was written and recorded AS the bug's
fix. Operator corrected it: #002 -> Closed Works-As-Designed (no code);
#003 -> UX Improvement carries the change (commit 4f6d75e5). Record now reads
truthfully instead of "Fixed Export bug" (there was no export bug).

## #9 — Control-presence is not visual parity (operator, verbatim, 2026-07-04)

"Control-presence (matrix Missing:0) is not visual parity. A page can pass
every objective gate and still be the pre-wireframe UI. Only the operator
Recognition Gate closes this — it is not automatable."

Origin: Wave-3 status correction (2026-07-04). Every census page had passed
the 10-criterion objective gate at control-matrix Wireframe-Required-Missing=0,
and the wave was reported "complete". The operator Recognition Gate corrected
it: the pages are WIRED (authority migration done, buttons functional, data
real) but NOT PORTED (wireframe layout not implemented) — Wave 3 is ~55%. The
objective gate verified that each required control EXISTS; it never verified
that the page wears the wireframe's LAYOUT. A page can hold every control and
still be the pre-wireframe UI. The remaining work is a PORTING phase: same
data, same handlers, same authorities, same routes — wrap each page in the
wireframe's own layout/markup/tokens. Backend/write-path untouched. Each page
is its own recognition gate (build one → regenerate only its composite → HOLD
for the operator's eye → proceed).
