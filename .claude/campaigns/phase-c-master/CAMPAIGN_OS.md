# Phase-C Inventory Master — Campaign Operating System (CAMPAIGN_OS.md)

**Platform v1.0 — FROZEN at `e2d69602` (operator ruling 2026-07-03)**

**Version:** 1.0 · **Adopted:** 2026-07-03 · **Status:** ACTIVE
**Campaign:** EJ Dashboard Phase-C Inventory Master Campaign
**Governed by:** Phase-C Constitution R4 (CLAUDE.md §"EJ Dashboard Phase-C Constitution (Final)")
**Subordinate to:** CLAUDE.md GATES 1–6 · 7-agent deploy gate · Engineering Lessons A–N ·
`docs/governance/anti-hold-and-completion.md` (Anti-HOLD)

Provenance: the pre-launch platform design rounds R1–R3 occurred in a channel this
repository has no record of. This platform was authored fresh in-session under explicit
operator authorization ("Author the platform here", 2026-07-03), from repo evidence only,
with the operator's FINAL PRE-LAUNCH AMENDMENT (verbatim R4) folded in at creation.

---

## §0 Mission

Implement only inside the existing EJ Dashboard architecture. The objective is not to
create software. The objective is to extend the existing business system without
introducing any new authority. (Constitution §0.)

- Implementation order LOCKED (Constitution §16): Product → Customer → Reservation →
  Inventory → Sample → Consignment → Returns → Invoice Selection → MM Integration →
  Webhook Synchronization. Nothing may skip this order.
- Every module reaches wFirma only through: `<module> → EJ Dashboard <Master> → Mirror → wFirma`.
- Before every code line, prove (Constitution §20): this feature extends
  EXISTING AUTHORITY → EXISTING PAGE → EXISTING SERVICE → EXISTING DATABASE → EXISTING API.
  If any arrow cannot be proven, STOP.

## §1 Platform Documents (Load Order)

Every campaign session loads, in order, before any task work:

1. `CLAUDE.md` — GATES 1–6, Constitution R4, Engineering Lessons, deploy gate
2. `CAMPAIGN_OS.md` ← this file
3. `MASTER_MANIFEST.md` — wave map, WAVE ASSUMPTIONS register, CAMPAIGN BUDGET, launch ruling
4. `RUNTIME.md` — live campaign state (current wave/slice, budget, confidence)
5. `OPEN_ITEMS.md` — OI ledger (check OPEN items gating the current + next wave)
6. `KNOWLEDGE.md` — Phase-0 validated architecture facts
7. `WIREFRAME_AUTHORITY.md` — UI authority map (mandatory before any UI slice)
8. `DECISIONS.md` — campaign decision ledger
9. `LESSONS_LEARNED.md` — operator-ratified campaign lessons (durability, tree protection)

**Do not begin implementation until all eight documents are loaded.** A session that
skips the load is operating without authoritative context.

## §2 Phase 0 Protocol (research-first, Constitution §19)

Phase 0 fires before Wave 1. Purpose: validate knowledge, populate the wave-assumption
registers from evidence, resolve OIs where current evidence already answers them.

1. Read the ground-truth sources: CLAUDE.md Constitution R4;
   `reports/inspection/2026-07-03T-integration-architecture-audit.md`;
   `reports/inspection/2026-07-02T-wfirma-wireframe-inspection.md`;
   `.claude/campaigns/ej-dashboard-master.md`; PROJECT_STATE.md `# DECISIONS` tail.
2. For each OI in OPEN_ITEMS.md: if current evidence resolves it, mark ANSWERED with
   citation; otherwise keep OPEN. Never guess a wFirma capability (Constitution §19).
3. For each entry in the MASTER_MANIFEST.md WAVE ASSUMPTIONS register: verify against
   evidence; mark VALID / AT-RISK / INVALIDATED with citation.
4. Reconcile `git log` HEAD against RUNTIME.md's completed-slice ledger.
5. Append all findings to KNOWLEDGE.md (append-only).
6. Produce CP1 (CP STATUS SUMMARY, §6) before entering Wave 1.

Phase 0 STOP condition: any **Wave 1** assumption INVALIDATED → stop after Phase 0,
propose a manifest amendment, wait for the operator's architectural ruling.

## §3 Checkpoint Definitions

| CP | Name | Trigger | Action |
|---|---|---|---|
| **CP1** | Skeleton + Status | Phase 0 complete | Type CP STATUS SUMMARY (§6) to chat. Informational — continue unless operator stops. |
| **CP2** | Skeleton + Status | Every wave boundary | Type CP STATUS SUMMARY to chat. Auto-continue ONLY if the next wave's assumptions are all VALID (§5). |
| **CP3** | Screenshots | Any UI slice, before the slice closes | Browser verification per GATE 6: full flow, console clean, network clean; screenshots to chat. |
| **CP4** | Pre-execution | Before ANY destructive / fiscal / live-write step (wFirma live write, production DB migration, `C:\PZ` sync, service restart) | STOP and wait for explicit operator ruling. Blocking gate. |

CP1/CP2 are informational (typed, then continue). CP3 is a verification gate (must pass
before the UI slice closes). CP4 is a blocking gate (no execution without ruling).

## §4 Health-Check Protocol

Health checks fire: at every wave boundary (with CP2); after any slice consuming >2h of
wave budget; whenever RUNTIME.md's "Next slice" changes unexpectedly.

1. Update RUNTIME.md: Consumed / Remaining / Forecast per wave (CAMPAIGN BUDGET rule).
2. Verify the NEXT wave's assumption register (Architecture Confidence Gate, §5).
   Any state change → record immediately in MASTER_MANIFEST.md + RUNTIME.md.
3. Check OPEN_ITEMS.md: OIs gating the next wave still OPEN → mark that wave AT-RISK.
4. Consumed > 1.5× wave budget → SELF_ASSESSMENT.md entry (scope-vs-estimate). Continue.
5. Consumed > 2× wave budget → SELF_ASSESSMENT.md entry AND manifest-revision proposal at
   the next wave boundary. **Budget overrun is never a silent scope cut** — the proposal
   states options; the evidence decides or the operator rules.

## §5 ARCHITECTURE CONFIDENCE GATE

**Operator rule (verbatim, FINAL PRE-LAUNCH AMENDMENT item 1):**

> "Continue automatically only while the architecture assumptions required
> for the next wave remain valid."

Mechanics:

- MASTER_MANIFEST.md carries the WAVE ASSUMPTIONS register — each wave lists the named
  assumptions it depends on. States: VALID / AT-RISK / INVALIDATED.
- At **every wave boundary** AND **every health check**, the gate verifies the NEXT
  wave's register against current evidence.
- Any assumption INVALIDATED → the campaign **STOPS at the wave boundary**, proposes a
  manifest amendment, and waits for the architectural decision (operator ruling) before
  entering that wave.
- Inspector discoveries **mid-wave** that invalidate a FUTURE wave: recorded immediately
  in the register as INVALIDATED; the current wave may finish **only its unaffected
  slices**. No mid-wave stop for future-wave invalidations; only the affected future
  wave is gated.
- On operator ruling: record in DECISIONS.md + PROJECT_STATE.md `# DECISIONS`, update
  MASTER_MANIFEST.md + RUNTIME.md, then resume.

## §5a PERMANENT RATIFICATION RULE (operator, verbatim, 2026-07-03)

> "Whenever the manifest is authored or materially reconstructed from
> repository evidence instead of an already-ratified manifest, the next wave
> requires operator ratification before execution."

Applies NOW: this platform's manifest was reconstructed from repo evidence
(575bb3f3), so every wave entry (Wave 2, 3, 4) requires operator ratification at
the preceding boundary — auto-continue applies only within a ratified wave.
Operator stop-line (2026-07-03, verbatim): "After C-1d, STOP for operator
ratification of the restored Wave 2-4 plan. Do not enter Wave 2 automatically
because the manifest was reconstructed from repo evidence."

## §6 CP STATUS SUMMARY (30-second read)

Typed to chat, with the skeleton, at CP1, CP2, and every wave boundary
(operator amendment item 2). Fields filled from RUNTIME.md + MASTER_MANIFEST.md:

```
=== PHASE-C CAMPAIGN STATUS ===
Campaign Status:   [ACTIVE / BLOCKED / COMPLETE]
Completed:         [slices done this wave + waves done]
Current Wave:      [Wave N — name · current slice]
Remaining Waves:   [list]
Architecture Confidence:
  Wave 1: [VALID / AT-RISK / INVALIDATED — reason if not VALID]
  Wave 2: [...]
  Wave 3: [...]
  Wave 4: [...]
Budget:            [per wave: Consumed / Budget / Forecast]
Known Risks:       [list or NONE]
Blocked Items:     [list with OI# or NONE]
ETA:               [to wave end / campaign end]
=== END STATUS ===
```

## §7 Hard Stops

Immediate STOP — no auto-continue (name the condition when stopping; record one line in
`.claude/memory/TASK_STATE.md`):

1. **Constitution §17** — slice cannot name Authority owner / existing page / existing
   API / existing DB / existing service.
2. **Constitution §18** — the work would invent architecture, workflow, fields, tables,
   pages, or APIs.
3. **Constitution §19** — wFirma work without prior research of API/webhook docs,
   repository, and mirror. Never guess a wFirma capability.
4. **Constitution §20** — the EXISTING AUTHORITY → PAGE → SERVICE → DB → API chain cannot
   be proven.
5. **Constitution §15 / MASTER-FIRST / MASTER CONSUMPTION** — code would create
   Inventory→wFirma direct, a new master/mirror/page, or a business module reading a
   Mirror. AUTHORITY VIOLATION → STOP.
6. **GATE 1** — PR-open preconditions unmet (verdicts, HIGH/CRITICAL findings,
   regression run, forbidden files).
7. **GATE 2** — implementation-PR limit reached (3; +1 docs-only).
8. **GATE 6 / CP3** — UI slice lacks completed browser verification.
9. **Anti-HOLD #1** — next step is a destructive production action (wFirma live write,
   `C:\PZ` mutation, DB drop/migration on prod, service restart) → CP4.
10. **Anti-HOLD #3** — legal/financial consequence (fiscal document creation) → CP4.
11. **Anti-HOLD #4** — unclear business decision with real cost of a wrong guess
    (e.g. consignment model state-vs-warehouse-dimension; WZ auto-vs-standalone).
12. **Confidence Gate** — next wave's register has an INVALIDATED assumption at a
    boundary (§5).
13. **Unresolvable OI** — a slice needs an OPEN OI; skip to the next unblocked slice;
    if no unblocked slice remains in the wave → STOP and report.
14. **Budget >2×** — at the wave boundary, do not enter the next wave until the
    manifest-revision proposal is ruled on.
15. **RED regression / stop-gate** — `make verify` failure or `.claude/hooks/pz-stop-gate.py`
    block is always a valid stop.

**Never a stop** (continue autonomously, per Anti-HOLD): code inspection, repo search,
test execution, local verification, docs/state updates, non-destructive branch work,
technical ambiguity with a sensible documented default, out-of-scope violation
discoveries (record in DECISIONS.md/KNOWLEDGE.md as backlog, continue).

## §8 Chat-Contact Protocol

Type to chat ONLY at (operator amendment item 5):

- Hard stops (§7) — with the named condition
- CP1 / CP2 — skeleton + status (informational)
- Wave-boundary stops from the Confidence Gate — WITH the manifest-amendment proposal
- CP3 — screenshots
- CP4 — pre-execution
- Unresolvable OI
- Campaign end — final status summary

Do NOT type to chat for: progress inside a slice (update RUNTIME.md instead), routine
slice completions within a wave, budget tracking below the 1.5× threshold.

### §8a Governance durability acknowledgment (operator, 2026-07-03)

Every governance-bearing order is ACKNOWLEDGED by naming the artifact + SHA it
produced. An order without its artifact is treated as never received.
(LESSONS_LEARNED.md #1: "Every governance change must create a durable artifact.
If the artifact does not exist, the governance change did not happen.")

## §9 Execution Discipline

- **Dirty-Tree Protection (operator, verbatim, 2026-07-03):** "Agent must never
  execute: git stash, git clean, git reset --hard unless explicitly authorized."
  Every slice pre-flight: "Dirty Tree Protection — Record: modified files,
  untracked files. Restore verification before commit." Every write-capable
  subagent prompt carries the explicit negative scope (Lesson K). Paid cost:
  the 46-entry stash incident during C-1w2 (LESSONS_LEARNED.md #2).
- Run `make verify` before every implementation slice; stop on RED.
- Commit every slice on `deploy/latest` (existing Phase-C convention:
  `feat(<slice-id>-…)` / `docs(<slice-id>-…)`), staging only slice-scope files.
- Update RUNTIME.md at every slice boundary.
- The standing pin `service/tests/test_master_consumption_rule.py` must stay green (or
  its xfail count shrink exactly as the slice specifies) — new violations fail the slice.
- UI slices: `frontend-design` skill + WIREFRAME_AUTHORITY.md before any component work;
  CP3 before close; Lesson M (no capability suppression without a DECISIONS record).

## §10 Subordination

This OS and all platform documents are subordinate to, in order: CLAUDE.md GATES 1–6;
the 7-agent production deploy gate; Constitution R4 (§§0–20 + Application Authority Rule
+ MASTER-FIRST + MASTER CONSUMPTION rules); Engineering Lessons (at their named gates);
Anti-HOLD rules. Where this OS conflicts with any of the above, the above wins; the
conflict is reported as a governance finding, never silently resolved in the OS's favor.

## §11 Closing Philosophy (operator, verbatim R4, 2026-07-03)

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

(Recorded as directed: an artifact amendment, not a rule — no behavior
change. The prompt is bootstrap; the platform documents govern.)
