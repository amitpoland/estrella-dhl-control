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

Paid cost (evidence, first wave12 deploy execution 2026-07-03):
- Ritual step 2c failed on prod: `backfill_product_authority` absent from
  the DEPLOYED `C:\PZ\app\services\reservation_db.py`.
- Root cause was NOT a stale snippet: the function exists at the candidate
  SHA `84c292de` (reservation_db.py:260, signature exactly as the runbook).
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
