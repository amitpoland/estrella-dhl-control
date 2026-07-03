# Phase-C Inventory Master — Lessons Learned (LESSONS_LEARNED.md)

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
