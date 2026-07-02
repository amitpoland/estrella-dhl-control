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
