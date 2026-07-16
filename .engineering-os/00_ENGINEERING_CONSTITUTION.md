# 00 — Engineering Constitution

**EJ Engineering OS v1.4** · docs-only framework · created 2026-07-08 (v1.0) · v1.3 ratified 2026-07-10 · **v1.4 ratified 2026-07-17**
Status: **REFERENCE** — this is an execution framework, not application code. It changes no
behavior on its own. It composes with, and is subordinate to, `CLAUDE.md` GATES 1–6, the
Engineering Lessons, and the 7-agent deploy gate. Version delta + evidence:
`VERSION_HISTORY.md`.

---

## 0. What this OS is

The EJ Engineering OS is a **reusable execution framework** for running work packages on the
EJ Dashboard (the one application; "PZ" is a workflow inside it, per the Application Authority
Rule). It does not replace any existing authority. It **organizes** the authorities that
already exist — GATES 1–6, the 7-agent deploy gate, the skills in `SKILL_REGISTRY.md`, and the
agents in `.claude/agents/AGENT_REGISTRY.md` — into one predictable flow so that every package
is routed, reviewed, made operable, deployed, and recorded the same way.

**It is docs. It authorizes nothing.** Production mutation is owned by the 7-agent deploy gate
and the operator. Skills inform; agents execute within skill contracts; councils review;
the Executive Coordinator sequences. Nothing here overrides `CLAUDE.md`.

---

## 0.1 Primary objective (overrides everything else in this OS)

**Execution speed, correctness, and low token usage are mandatory.** The Engineering OS exists
to **reduce discussion, not increase it.** Every rule below is subordinate to this objective:
if applying a rule would generate discussion that does not change the outcome, apply the rule
silently and execute. The OS is a fast lane, not a committee.

## 1. First principles (non-negotiable)

0. **Speed is a first principle.** Reduce discussion. Default to execution when information is
   sufficient (`06 §Default Execution Mode`). Councils, agents, and skills run **internally** —
   report decisions, findings, blockers, implementation, and verification, not deliberation.
1. **Business capabilities first, not pages.** Work is scoped to a *business capability*
   (master-data, warehouse, returns-qc, manufacturing, commercial, integrations, platform),
   never to "a page" or "a file." A capability owns its authority, page, API, DB, and service.
   See `05_CAPABILITY_REGISTRY.md`.
2. **One Executive Coordinator.** Exactly one orchestration role sequences a package. It
   classifies, loads the manifest, routes, and gates — it never implements. See `01`.
3. **Skills define standards.** How a thing is done correctly is owned by a skill
   (`SKILL_REGISTRY.md`). Agents may not invent craft rules that a skill already owns.
4. **Agents execute within skill contracts.** An agent acts only inside the standard its
   governing skill defines, and only within its declared capability class (inspect-only,
   runtime write-capable, or guarded scoped-implementer). See `03`.
5. **Councils review, they do not implement.** Review bodies (Architecture, Backend,
   Frontend, Security, Test, Deploy, Governance) issue verdicts. They never mutate. See `02`.
6. **The Business Operability gate is mandatory.** No capability is "complete" short of the
   **Business Feature Completeness Standard** — the seven requirements whose **single
   authoritative definition (names, definitions, lifecycle, Business Owner registry) lives in
   `CLAUDE.md`**; this constitution deliberately does not enumerate them, so the list cannot
   drift. See `07` (gate procedure — it points to CLAUDE.md, it does not redefine the
   standard).
7. **No implementation starts until the capability manifest is loaded.** The manifest
   (`capabilities/<name>/manifest.md`) names the authority, page, API, DB, and service to be
   extended. If any is unnamable, **STOP** (mirrors CLAUDE.md §20 "prove the chain").
8. **Fast Path vs Deep Path is explicit.** Every package declares which path it runs. See
   `06`.
9. **Token economy is a first-class constraint.** Load the minimum manifest, the minimum
   skills, the minimum agents. See `09`.
10. **Deployment references the existing gate.** This OS never defines a new deploy path;
    it points to the 7-agent deploy gate. See `08`.

---

## 2. The authority chain (immutable — from the Phase-C Constitution)

```
wFirma (external ERP)
  → Mirror Layer (sync-only; 6 columns; never business logic)
  → EJ Dashboard Masters (Product Master, Customer Master, Warehouse, Invoice, Packing, Inventory)
  → All business capabilities
```

No capability bypasses this chain. Inventory/Sales/Returns/etc. read product & customer facts
only from the Masters, never directly from wFirma or the Mirror (Master Consumption Rule).

---

## 3. Layered model of the OS

```
Constitution (00)            ← non-negotiable principles + precedence
      │
Executive Coordinator (01)   ← the single orchestrator (classify → route → gate)
      │
      ├── Council Registry (02)        ← review bodies (verdict-only)
      ├── Agent Router (03)            ← who executes (AGENT_REGISTRY.md source)
      ├── Skill Router (04)            ← which standards apply (SKILL_REGISTRY.md source)
      ├── Capability Registry (05)     ← what business capability is in scope
      ├── Package Lifecycle (06)       ← Fast/Deep path stages + gates
      ├── Business Operability (07)    ← mandatory completeness gate (CLAUDE.md 7-requirement authority)
      ├── Deployment Governance (08)   ← references the 7-agent deploy gate
      ├── Token Controller (09)        ← token economy
      └── Knowledge Engine (10)        ← state, memory, lessons, scorecards
```

---

## 4. Precedence (which authority wins)

When two rules appear to conflict, resolve top-down:

1. `CLAUDE.md` **GATES 1–6** and the **Engineering Lessons** (A–N).
2. The **7-agent deploy gate** for anything that syncs to `C:\PZ`.
3. **Protected-domain** stop-and-ask (financial, customs, accounting, inventory, shipment,
   fiscal writes) and **Lesson N** (advisory-vs-blocker) for readiness/gating.
4. The **owning skill** (`SKILL_REGISTRY.md`) for craft/authority within its domain.
5. This **Engineering OS** framework (sequencing, routing, operability, token economy).

The OS never sits above GATES 1–6 or the deploy gate. Where this framework appears to conflict
with them, they win — full stop.

---

## 5. What the OS explicitly does NOT do

- It does not authorize a deploy (the 7-agent gate does).
- It does not create or modify agents or skills (they are frozen per their own policies).
- It does not recompute financials (only `process_batch()` does).
- It does not create duplicate authority (one page/API/route/state per module).
- It does not promote an advisory signal to a hard blocker without a named fiscal risk
  (Lesson N).

## 6. Version discipline (amendment history)

**v1.0 was FROZEN 2026-07-08** as the deliberately-minimal baseline, with the rule that future
changes land only "after evidence from real packages." That evidence arrived: the 2026-07-10
campaign day ran every package under v1.1 practice, the operator mandated the Phase-8
certification doctrine (v1.2), and the first Phase-9 knowledge-capture record set shipped
(v1.3). **v1.1, v1.2, and v1.3 are ratified on that recorded evidence** — the delta ledger with
per-version citations is `VERSION_HISTORY.md`. The active canonical version is **v1.4**
(sections 7–14 below). **v1.4** (Policy Cohesion, ratified 2026-07-17) was ratified by
**operator directive** — the same ratification class as v1.2's operator-mandated Phase-8, **not**
pure package-friction evidence; the departure is disclosed in `VERSION_HISTORY.md`
(evidence-classification note), not dressed up as friction it does not have. Future changes go
into **v1.5+** under the same evidence gate (`10 §4.2`): an observed failure or friction captured
in a real package's record, never speculation — unless the operator again exercises directive
ratification. Extensions remain a separate, separately-approved package — never silent sprawl.

---

## 7. Campaign Execution (v1.1 — ratified 2026-07-10)

The **Campaign Run is the execution unit** (Campaign-Run doctrine, standing since
MASTER-EXEC-1): inspect → diagnose → design → implement → verify → deliver → prod-verify →
close, owned end-to-end, pausing **only** at operator gates.

1. **Continue from the latest stable state; never restart solved work.** A sealed package or
   verified conclusion is reused, not re-derived (`09 §3.5`, `10 §4.1`).
2. **Delta verification over rediscovery.** When a prior inspection is on record, verify only
   the delta against it (MASTER-EXEC-1 Campaign Run 7 continuity rule).
3. **Isolated worktrees.** Each package's implementation and each verification/gate run gets
   its own git worktree; nobody edits a tree another session owns (working-tree registry +
   one-session rule, CLAUDE.md).
4. **Exactly one implementation owner** per branch/worktree. A second concurrent session is
   **VERIFY/GATE only**: it inspects, tests, gates, and seals — it does not edit
   implementation files. If its review finds a concrete blocker, it documents the blocker
   first, then applies the smallest correction on the same PR branch — never a duplicate PR
   (PFW Slice 3 concurrency ruling + PFW-EXT-1 charter, 2026-07-10).
5. **Concurrency truth signals.** Uncommitted work in another session's tree is never staged,
   reset, recovered, or claimed without operator approval. The implementation-complete signal
   is a **remote branch with commit SHA(s) above the agreed base** — a branch-name collision
   is not completion evidence (WF-3 name-collision incident, 2026-07-10).
6. **Explicit operator gates.** Merge, deploy, schema/destructive migration, credentials, and
   fiscal writes pause for the operator. Everything else continues autonomously (Anti-HOLD).
7. **Evidence-based completion + standard output.** Every phase reports in the standard
   campaign format (PACKAGE / STATUS / authority map / evidence / rollback / next exact step);
   "done" claims carry evidence, per §8.

---

## 8. Release Certification (v1.2 — ratified 2026-07-10)

Phase-8 doctrine (operator-mandated 2026-07-10; first applied to PFW Slices 3+4): every
implementation campaign ends with an **evidence-only release certification** before the next
slice.

1. **Verify the full chain:** Git (merge SHA on `origin/main`) → deployed disk (file hashes) →
   process (fresh PID, service RUNNING) → logs (clean stderr) → endpoint (authenticated
   probes) → business behavior (the feature demonstrably works).
2. **Deployed-file hash matching** is the byte-level proof: `git hash-object` of the deployed
   file must equal the blob in `git ls-tree origin/main`.
3. **Record three SHAs** for every release: main SHA, production content SHA, rollback SHA
   (`git revert <squash-sha>` template — record it at merge time).
4. **Never seal from chat claims.** A completion claim (even the operator relaying one) is
   verified against fetch / PR-state / PID / hash evidence before any seal; a false claim is a
   **HALT**, not a seal (seven-plus contradicted completion relays on 2026-07-10 alone).
   **HALT (defined):** refuse to record the seal, state the contradicting evidence, and give
   the operator the exact commands to reach the claimed state — a HOLD-class stop scoped to
   the seal itself (autonomous read-only verification continues; nothing else blocks).
5. **Deploy-source discipline** (operator-ratified 2026-07-10, after a double incident):
   verify the sync source is at the target SHA **before** copying and hash-verify the target
   **after**; when `main` is held by another worktree, detach at `origin/main`; exclude
   `storage` from the app sync (`/XD storage`); **no destructive mirror deployment** (`/MIR`
   is forbidden — evidence: the EOS-UPGRADE-1 operator charter names it explicitly, the
   #875/#879 release-manager sync plans are non-mirror, and a Slice-4 coordinator draft
   saying `/MIR` was corrected at the gate); stop the service and **wait for STOPPED** before
   starting; a deployment is incomplete until `PZService` reports **RUNNING** (see `08 §6.1`).

---

## 9. Operational Excellence & Knowledge Capture (v1.3 — ratified 2026-07-10)

A campaign is not closed when the code ships — it is closed when its knowledge is captured
and its residue is classified. First full record set: the PFW closure
(`docs/governance/campaign-closure-proforma-wireframe-2026-07-10.md`) + ADR + runbook, and
`docs/campaigns/master-exec-1-closure.md`.

1. **Phase-9 record set per campaign:** campaign closure record, ADR
   (`docs/decisions/`), operator runbook (`service/docs/ops/`), technical-debt register with
   **GATE-4 dispositions** (SCHEDULED / ISSUE / REJECTED — "noted" is not valid), dependency
   audit, production health observation, and a performance baseline where relevant.
2. **Open-PR disposition audit.** Periodically (and at campaign close) every open PR receives
   an explicit disposition — merge order, supersede, or close with reason (2026-07-10 audit:
   #877 merged, #878 superseded #808, #799 closed as superseded).
3. **Residue classification.** Closure states residue honestly ("Complete with Residue" +
   register) instead of claiming perfection.
4. **Closed campaigns cannot silently gain new slices.** Work appearing after closure is
   re-chartered as a **named continuation campaign** with its own record (PR #879 →
   PFW-EXT-1, 2026-07-10 — explicitly "not Slice 5").
5. **Post-release stabilization monitoring.** Major releases are followed by a
   production-verification-only observation window with persistent monitors (POST-RELEASE
   STABILIZATION-1 — its monitors caught DEFECT-1 live in production).

---

## 10. Skills & commands compatibility (disclosure rule)

The OS references only skills registered in `SKILL_REGISTRY.md` (9, FROZEN) and slash
commands actually installed under `.claude/commands/` (`/deploy`, `/implement-slice`,
`/engineering-lessons`, `/context-lite`, `/context-pr`, `/context-task`, `/pz-loop`, …).
**`/context` and `/analyze` are NOT installed commands in this repository.** Where an
installed skill's text references `/context`, meet its intent by **direct repository
inspection** (read the router, canonical pages, registries, PROJECT_STATE) — do not claim to
have run a command that does not exist, and disclose an unavailable skill/command instead of
simulating it (GATE 5 substitution-disclosure applies to commands as well as agents).

---

## 11. Evidence Contract (v1.4 — ratified 2026-07-17)

Every claim that could influence a gate, a seal, or a "done" statement is classified into
exactly one **input evidence tier** before the OS acts on it:

- **VERIFIED** — independently confirmed **this session** by direct evidence: a file read, a
  `git hash-object` match, an authenticated endpoint probe, a test run, a DB read, or browser
  inspection. Cite the concrete source.
- **PRIOR EVIDENCE** — on record in a durable artifact (`PROJECT_STATE.md`, a closure record,
  a scorecard, a merged PR, a dated ADR) but **not re-confirmed this session**. PRIOR EVIDENCE
  is usable, but triggers **delta-verification per §7.2** before the next stage proceeds — verify
  the delta against the record, do not re-derive from scratch and do not trust it blindly.
- **UNVERIFIED** — assumed, inferred, stale, self-reported, or relayed by chat. **UNVERIFIED may
  never seal a phase, close a package, or justify a "done" claim.** A completion claim that
  arrives in this tier is handled by the **§8.4 HALT protocol** (refuse to seal, state the
  contradicting evidence, hand the operator the exact commands) — §11 does not restate that
  protocol; it routes to it.

Rules: never present UNVERIFIED information as fact; never invent file paths, commands, test
results, runtime/deploy state, or root causes; if evidence is missing, inspect it or disclose
the limitation rather than guessing. Keep **code completion, merge completion, deployment
completion, and live-activation** as separate claims, each with its own tier.

**Distinct from — and compatible with — the output three-state contract.** `CLAUDE.md
§Verification rules` (`True` = verified / `False` = confirmed mismatch / `None` = could-not-
verify) governs what a **verification result means** (output semantics). §11 governs how an
**incoming claim is classified** before the OS relies on it (input semantics). They compose:
a `None` output is not evidence and classifies as UNVERIFIED input; a `False` output is
VERIFIED evidence of a mismatch. §11 adds the tier label to the §7.7 standard output format; it
does not redefine §7.7's meaning of "evidence."

---

## 12. MODULAR-MINIMAL execution principle + Anti-Bloat gate (v1.4 — ratified 2026-07-17)

**MODULAR-MINIMAL** is the named execution form of the §0.1 primary objective (speed,
correctness, low token usage). Every change is the **smallest complete set** that satisfies the
stated, VERIFIED objective — and nothing more:

- Extend the existing canonical authority (page, service, route, writer, model, config); do not
  add a duplicate. This is the per-change expression of §5 ("does not create duplicate
  authority") and of the `CLAUDE.md` **FRONTEND AUTHORITY CONSTITUTION** (one authority per
  module; five pre-development checks) — consult those for the UI application; §12 does not
  restate them. For EJ Dashboard modules, the **Phase-C Constitution §13/§14** (`CLAUDE.md`:
  "no new pages", "no duplicate services") and **Lessons F and M** are the binding
  domain-specific expressions — consult them before any UI or service-layer change.
- Do not add abstraction, dependency, page, table, or route for hypothetical future use. A new
  abstraction must have demonstrated current use and a named owner.
- Do not mix unrelated cleanup or modernization into a bounded task. **Modernization is not a
  default mode** and is never inferred from "improve", "clean up", or "modernize" in passing —
  a structural rewrite, dependency upgrade, or legacy retirement requires an explicitly approved
  modernization/replacement package.
- Remove any temporary parallel path the change introduced before completion. If the same
  defect returns after a prior fix, **stop additive patching and inspect for a surviving
  duplicate authority** (the recurrence is the signal).

**Anti-Bloat Verification gate** — runs at the IMPLEMENT → VERIFY transition (`06` stage 7),
before any seal. It answers, in the closure record: (1) Was every new file necessary? (2) Could
this have extended an existing canonical module instead? (3) Did the change create or preserve
duplicate authority? (4) Did any file change outside the declared scope? (5) Does each new
abstraction have demonstrated current use? (6) Was any dependency added unnecessarily? (7) Is
temporary/dead code left behind? (8) Is the diff size proportionate to the requirement? Any
unexplained "yes" to a risk question **blocks the seal**. This is the **architectural** gate; it
composes with — does not replace — the **file-level** `git diff --name-only` plan-list guard in
`/feature` Phase 3. The two are complementary layers.

---

## 13. Bounded Engineering Loop (v1.4 — ratified 2026-07-17)

The Bounded Engineering Loop is the **iterative** execution mode for work that converges through
repeated apply→verify cycles (a diagnostic hunt, a flaky-test fix, a refactor toward a metric)
rather than a single linear pass. It is **distinct from** the linear 5-phase `/feature` flow;
its entry point is the `/pz-loop` command (`.claude/commands/pz-loop.md`). Sessions must not
build ad-hoc loops outside this governance.

**Required loop inputs — the loop may not start unless all four are stated:**

- **OBJECTIVE** — one sentence stating the convergence goal (must be VERIFIED-checkable).
- **STOP_CONDITIONS** — at least one explicit, objective exit condition. Aspirational phrasing
  ("until it works") is not a stop condition.
- **ITERATION_CAP** — the maximum number of iterations. **Default 5**; another value is allowed
  but must be stated explicitly, even when accepting the default.
- **VERIFY_CMD** — the real, executable command(s) run after each iteration to measure progress.

If these cannot be derived safely from repository evidence, **STOP and request the missing
decision** — do not invent them.

**Per-iteration cycle:** apply the **smallest** change toward OBJECTIVE (§12) → run VERIFY_CMD →
classify the result under §11 → check STOP_CONDITIONS → then exit **CONVERGED**, exit
**CAP_REACHED**, pause **HOLD_TRIGGERED**, or continue. An iteration is a meaningful
inspect/change/verify cycle, not a single tool call.

**Boundaries (referenced, not restated):**

- Each iteration respects **§7.3–§7.5** (isolated worktree, one implementation owner, concurrency
  truth signals) and the `CLAUDE.md` **Canonical working-tree registry** + one-session rule; a
  worktree/ownership conflict inside an iteration is a valid HOLD.
- A HOLD arising in any iteration is **named per `CLAUDE.md` ANTI-HOLD** (the four HOLD
  conditions) and pauses the loop; the full decision table is
  `docs/governance/anti-hold-and-completion.md`. §13 adds no new HOLD conditions and does not
  restate the four. Operator gates within a loop function identically to the **§7.6** campaign
  gates.
- Before iteration 1, classify prior work under **§11**: if PRIOR EVIDENCE exists, apply the
  **§7.2** delta-verification rather than restarting solved work.

At the iteration cap: **stop, preserve the worktree, report completed work + remaining failure
with evidence (§11 tier), and recommend the exact next step.** Do not continue past the cap and
do not restart solved work.

**Worked examples (illustrative — the rule is above):**

- **Example A — read-only request.** "Does endpoint X validate country?" → classify as read-only
  inspection; run **one** evidence cycle and answer with a §11 tier. **No implementation loop
  starts.** (A loop is for convergent *implementation*, not for a single lookup.)
- **Example B — cap reached.** ITERATION_CAP = 5, STOP_CONDITIONS still unmet after iteration 5
  → **STATUS = CAP_REACHED**; surface the current state, the last VERIFY_CMD result, and the next
  exact step to the operator. The loop does **not** silently run a 6th iteration.
- **Example C — operator gate inside the loop.** Iteration 3 would require a robocopy to `C:\PZ`
  (a production mutation) → **STATUS = HOLD_TRIGGERED, HOLD = "Destructive production action"**;
  the loop pauses and hands the operator the exact commands. The loop never crosses an operator
  gate on its own.

---

## 14. OS-load arming, operator gates, and user-facing output (v1.4 — ratified 2026-07-17)

**Arming.** §11–§14 are **armed automatically** whenever `CLAUDE.md` names this OS version in its
"Engineering OS (canonical version pointer)" section — the pointer is always in context at
session start (no hook reads `.engineering-os/` directly, and none is required). These policies
are **not opt-in**; naming v1.4 in the pointer is what activates them. Arming the OS does **not**
start implementation — the actual task determines whether the session runs one read-only evidence
cycle, a bounded diagnostic loop (§13), a bounded implementation loop, a monitoring cycle, or an
operator-gated release workflow.

**Operator gates.** The conditions that pause for the operator are **owned by `CLAUDE.md`
ANTI-HOLD** (the four HOLD conditions) and `docs/governance/anti-hold-and-completion.md`, and
mirrored for campaigns at **§7.6**. **§14 defines no new gate conditions** — this is an explicit
non-duplication declaration. A loop or campaign may *prepare and verify* a gated action (merge,
deploy, schema/destructive migration, credentials, fiscal/wFirma write, branch/worktree
deletion, force-push, changing canonical authority) but must **not cross the gate**.

**User-facing output hygiene.** Every status claim the OS emits carries a §11 evidence tier;
speculative completion language ("probably done", "should be working", "likely deployed") is not
valid output. Business-facing documents and operator-facing screens must not expose implementation
metadata, internal IDs, payload hashes, debugging state, or developer overrides unless explicitly
requested. The §7.7 standard campaign output format is extended with the evidence-tier field on
the STATUS line; §14 does not otherwise redefine §7.7.
