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
