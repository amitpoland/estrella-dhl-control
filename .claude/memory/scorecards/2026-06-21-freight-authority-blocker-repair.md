# Agent Performance Scorecard — PR #708: Freight Suggestion Authority + Blocker Repair (d546f49)

**Date:** 2026-06-21
**Observer:** agent-performance-observer (RULE 2 auto-fire — 5 distinct named-agent invocations)
**Campaign:** "Freight suggestion authority + blocker repair"
**Branch:** fix/freight-authority-blocker-repair
**Commit:** d546f49 (based on origin/main 53a3cc7)
**PR:** #708 (https://github.com/amitpoland/estrella-dhl-control/pull/708)
**Scope:** Backend + V1/V2 frontend. Root cause: "freight_fixed_amount_usd is not set" blocked
  Clear-Diamonds with no identity context in the API response. Fix: `pick_freight` reports the
  missing `field`; `routes_proforma` adds a `freight_authority` block to `/suggest-freight` and
  `/suggest-combined` only when resolved; V1 `shipment-detail.html` + V2 `proforma-detail.jsx`
  deep-link to the exact resolved CM record with a read-only retry. General authority model —
  no hardcoded names, no override/silent fallback.
**Outcome:** PR #708 OPEN. GATE 1 satisfied: all 5 agents returned verdicts; all in-scope
  findings resolved inline (6 total fixes); 24 new tests pass; 123 endpoint-suite green;
  V1 + V2 JSX compile-checked (Babel 7.26.4); pre-commit smoke 63 pass. GATE 2: full room
  (0 impl PRs open). GATE 6: deferred — browser-verify + deploy are post-merge operator steps.
**Agents evaluated:** 5

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| reviewer-challenge | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |
| frontend-flow-reviewer | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| backend-safety-reviewer | 4 | 4 | 4 | 4 | 5 | 4 | 3 | 28 | ACCEPTABLE |
| security-write-action-reviewer | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |
| test-coverage-reviewer | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |

---

## Scoring rationale per agent

### reviewer-challenge — 32 — EXEMPLARY

**Specificity (5):** Returned APPROVE-WITH-NITS and surfaced a genuine dual-URL-construction
risk: V1 rebuilt the deep-link URL on the frontend instead of consuming the backend's
authoritative `edit_url` field — a latent divergence that would silently produce the wrong
link if the CM routing logic ever changes. This is the "question nobody asked" in the
reviewer-challenge contract: the nominally working V1 URL construction looked correct against
the current CM routes but was structurally fragile. The agent also independently identified
that the unsupported-currency dict lacked the `field` key, a concrete schema-consistency
finding verifiable by inspecting the error-path return dict. Both findings are named at the
mechanism level and independently verifiable. The governance compliance sweep (no override,
no hardcoded names, no write path, Lesson F V1-freeze as critical-correctness defensible,
Lesson M capability-suppression OK) is reported as a structured positive confirmation, not
just a label. agentId a003d107f40a68803 recorded.

**Coverage (5):** Covered the full reviewer-challenge mandate for this PR class: (a) design
safety — does resolved:False ever synthesize identity? (b) Lesson F V1-freeze compliance —
is the deep-link change defensible as critical-correctness? (c) Lesson M — does the
resolved/unresolved branch split suppress or suppress no existing capability? (d) the dual
URL construction latent divergence — a structural weakness in the V1 implementation not
visible from the diff alone. The APPROVE-WITH-NITS verdict correctly reflects that no
BLOCK-class design defect was found (the authority model is clean, no false identity
synthesis) while surfacing two concrete actionable nits. This is the full chartered scope
for a reviewer-challenge dispatched at FINAL stage on a backend+frontend PR.

**Severity (5):** APPROVE-WITH-NITS is precisely calibrated. The dual-URL-construction
divergence is correctly treated as a nit (latent risk, not a current production defect) —
if it were a current incorrect URL, it would have been surfaced as BLOCK-level. The
unsupported-currency dict `field` omission is a schema-consistency nit, not a HIGH finding
(it only affects the error path, not the resolved authority path). Both nits were correctly
sized below BLOCK and are resolved inline. The reviewer did not inflate nit-level findings
to BLOCK — the calibration is precise. The positive governance sweep (no override, no
hardcoded names, resolution-failure safe) is correctly stated as CLEAR, not
CLEAR-WITH-CONDITIONS.

**Actionability (5):** Both nits directly drove inline fixes before PR open: V1 now
consumes `edit_url` from the backend response instead of rebuilding the URL client-side;
the unsupported-currency dict now includes the `field` key. Both are confirmed fixed by
the campaign outcome. The governance compliance confirmations (Lesson F defensible,
Lesson M OK) are directly actionable as GATE 1 clearance signals for the operator. The
"question nobody asked" — dual URL construction — is the highest-value actionability
contribution: the fix eliminates an entire class of future divergence, not just the
current instance.

**Substitution (5):** reviewer-challenge is canonical agent #16 in AGENT_REGISTRY.md.
No substitution required. GATE 5 N/A.

**Evidence (4):** The dual-URL-construction finding names the specific mechanism (V1
rebuilding the URL vs consuming `edit_url`), the specific risk (routing divergence if CM
routes change), and the specific resolution (consume backend field). The unsupported-currency
`field` omission names the specific dict and the specific missing key. Both are verifiable
claims. Minor deduction: the campaign summary does not quote the agent's raw structured
output block (3 assumptions, 3 failure scenarios, SPOF, question nobody asked format per
agent contract) or provide file:line citations from the verdict block itself. The findings
are reported at the conclusion level via the campaign narrative, not as directly quoted
artifact-level output from the agent.

**Environment (3):** Verdict block does not self-report which worktree path the agent read
from or the commit SHA examined. Standard disclosure gap per Issue #597. The campaign
context indicates the worktree is `fix/freight-authority-blocker-repair` at d546f49; the
agent did not self-report this in its verdict block. No PATH GUARD violation confirmed.
Score 3/5.

---

### frontend-flow-reviewer — 27 — ACCEPTABLE

**Specificity (4):** The decisive in-scope finding — F5, the "implied record exists" copy
on resolution failure — is named at the mechanism level: the V1 banner's copy read as though
a record existed even in the unresolved case, creating a false implication for the operator.
The resolved/unresolved branch split fix is the correct resolution. The pre-existing/out-of-scope
findings are also named specifically (badge-amber hex fallbacks, panel-wide bare `<button>`
elements, `#fff` and `--danger` token usage, V1 banner dismiss behavior). The agent correctly
classified these as pre-existing rather than introduced by this PR. The F5 finding
demonstrates the agent read the V1 copy carefully enough to detect implied-state language.
Minor deduction: the reported verdict does not include file:line anchoring for F5 (which
component, which text string was the implied-record copy?) — the finding is named at the
semantic level but not at the artifact level.

**Coverage (4):** Covered the primary frontend-flow-reviewer surfaces for a PR that touches
V1 deep-link UI and V2 JSX: (a) copy accuracy on resolution-failure path (F5 — the real
in-scope finding), (b) CSS token compliance (amber hex fallbacks, `#fff`, `--danger`),
(c) interactive element accessibility (bare `<button>`), (d) V1 banner behavior. The agent
correctly distinguished in-scope findings from pre-existing issues and did not demand fixes
for pre-existing out-of-scope items while still surfacing them for operator awareness.
Minor gap: the agent's reported findings do not confirm whether it explicitly ran the Lesson M
capability-suppression check for the V2 `proforma-detail.jsx` changes — a V2 PR touching a
workflow action (deep-link + read-only retry) must pass the Lesson M panel-suppression test
per CLAUDE.md. The reviewer-challenge confirmed Lesson M OK, but the frontend-flow-reviewer
verdict block as reported does not independently confirm this.

**Severity (4):** CONCERNS is correctly calibrated for the mix of findings: F5 (real in-scope
UX accuracy concern) combined with pre-existing token/accessibility issues. CONCERNS is the
right verdict when real in-scope issues exist but none rise to BLOCK. The F5 finding is
correctly sized as CONCERNS rather than BLOCK — it is a copy accuracy issue (implied record
exists when it does not), which is a UX correctness concern but not a data-integrity or
financial correctness blocker. Pre-existing issues are correctly surfaced as informational
rather than as blocking conditions for this PR. Score 4 rather than 5: the severity
vocabulary (LOW/MEDIUM/HIGH) is not applied per-finding in the reported verdict; the
calibration is implicit from "CONCERNS" at the aggregate level rather than severity-labeled
per finding.

**Actionability (4):** F5 was resolved inline via the resolved/unresolved branch split in
the V1 banner copy. The pre-existing/out-of-scope findings are correctly surfaced with no
resolution demand (they pre-date this PR). The CONCERNS verdict is actionable as a GATE 1
signal: the real in-scope finding was resolved, PR open is appropriate. Minor deduction:
the pre-existing issues (amber hex fallbacks, bare buttons) are surfaced without a GATE 4
disposition or BACKLOG registration — the campaign outcome notes they are "pre-existing /
out-of-scope; correctly flagged but not introduced by this PR" but does not confirm they
received a SCHEDULED, ISSUE, or REJECTED disposition. If these remain unfiled, they
become invisible governance debt.

**Substitution (5):** frontend-flow-reviewer is canonical agent #3 in AGENT_REGISTRY.md.
No substitution required. GATE 5 N/A.

**Evidence (3):** F5 (the decisive in-scope finding) is named at the semantic level —
"V1 copy implied a record exists when resolution failed" — but is not anchored to a
specific file path, component name, or copy string from the agent's verdict block.
The pre-existing findings (badge-amber hex, `#fff`, `--danger`, bare `<button>`) are
named at the token/pattern level without file:line citations. For a frontend-flow-reviewer
whose chartered output requires "Files:" and "Required fix:", the expected evidence standard
includes the component name and the specific copy or token where the finding was made.
Score 3: findings named at the semantic/pattern level without artifact-level anchoring
in the reported verdict. This is the recurring evidence gap (see Repeated failure hints —
same gap class in 2026-06-20 and 2026-06-21-proforma-authority-ui scorecards).

**Environment (3):** Verdict block does not self-report the working tree path or commit SHA
examined. Standard disclosure gap per Issue #597. agentId a9c4d2f00f75c1cf3 recorded; no
PATH GUARD violation confirmed. Score 3/5.

---

### backend-safety-reviewer — 28 — ACCEPTABLE

**Context note:** This agent was flagged REPEATED-WEAK in the immediately preceding
`2026-06-21-proforma-overbill-fail-closed.md` scorecard (three consecutive ACCEPTABLE
scores, Evidence 3/5, same root cause — label-only conclusions). This scorecard must
assess whether the evidence-packaging pattern has improved.

**Specificity (4):** CLEAR verdict with a concrete list of confirmed safety properties:
GET-only endpoint (no writes introduced), no false evidence synthesis (`resolved:False`
when CM record is None rather than inventing a contractor_id), exception-safe identity-field
handling (identity fields confirmed NOT NULL so no KeyError on the `freight_authority` block),
and `field` key confirmed additive (does not mutate existing audit state). The "exception-safe
identity fields" confirmation is the highest-specificity contribution: it names the specific
safety property that prevents a new class of 500 errors on the resolution-failure path where
identity fields would be accessed on a potentially absent record. The campaign summary credits
the agent with "file:line throughout" — meaning this agent did supply file and line references
in its verdict block rather than label-only conclusions.

**Coverage (4):** Covered the critical backend safety surfaces for this PR class: (a) write-path
safety — GET-only confirmed; (b) false-evidence safety — no synthesized identity when unresolved;
(c) exception safety — identity fields NOT NULL confirmed; (d) audit additive — `field` key
addition is non-destructive. These four dimensions address the real safety risks of this change:
an endpoint that adds an identity block (`freight_authority`) to an API response could introduce
a false-identity synthesis risk (returning contractor_id from a different record) or a runtime
exception risk (accessing fields on a None object). Both are confirmed safe. Minor gap: the
verdict as reported does not confirm whether the agent checked the `audit_merge.PRESERVED_KEYS`
contract for the new `freight_authority` response field — the response field is new and additive,
but confirming it does not collide with existing audit preservation rules would be the Lesson A
full-coverage item.

**Severity (4):** CLEAR is correctly calibrated for a GET-only endpoint that adds an additive
informational block. No HIGH/CRITICAL findings are expected or warranted for a pure read
endpoint that returns richer structured data on resolution. The resolved:False/None distinction
is correctly sized as a safety-confirmation item (not a blocker finding) — the implementation
correctly handles the unresolved case. Score 4 rather than 5: the verdict as reported does not
state the blast-radius bound (what happens if `freight_authority` is missing from a response —
is the UI resilient to absence?), which would be the severity-precision that earns a 5.

**Actionability (4):** CLEAR with four explicitly confirmed safety properties is a complete
GATE 1 clearance signal for the backend reviewer surface. The file:line citations (per campaign
summary) make each confirmation independently actionable — an operator can verify the specific
code patterns that were confirmed safe. Minor deduction: no post-deploy monitoring recommendations
are named (e.g., "confirm no new 500-class errors on /suggest-freight in the first post-deploy
batch against a customer with no freight_fixed_amount_usd in CM").

**Substitution (5):** backend-safety-reviewer is canonical agent #2 in AGENT_REGISTRY.md.
No substitution required. GATE 5 N/A.

**Evidence (4):** This run shows an improvement over the prior three ACCEPTABLE instances
(Evidence 3/5 in 2026-06-20, 2026-06-21-pr3, and 2026-06-21-proforma-overbill). The
campaign summary credits the agent with "file:line throughout" — indicating that this time
the verdict block provided artifact-level citations for the confirmed safety properties,
not just label-level conclusions. If the campaign summary's characterization is accurate,
this is the evidence-packaging improvement that the prior three GATE 4 SCHEDULED items
were targeting. Score 4: the claims are artifact-grounded per the campaign summary, but
the scorecard does not receive the raw cited lines directly. A 5 would require the
specific file:line citations to be directly quoted in the campaign summary so the scorecard
can independently verify them. agentId ab82847c6f4ebe598 recorded.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA
examined. Standard disclosure gap per Issue #597. The file:line citations (per campaign
summary) imply the agent read from a specific file tree, but the self-disclosure in the
verdict block itself is absent. No PATH GUARD violation confirmed. Score 3/5.

**Improvement assessment vs REPEATED-WEAK history:** The Evidence dimension scores 4/5
this run, up from 3/5 in the three immediately prior campaigns. This is a meaningful
improvement if the campaign summary's "file:line throughout" characterization accurately
reflects the raw verdict block content. One clean run at Evidence 4/5 does not retire
the REPEATED-WEAK flag — pattern recovery requires consistent evidence quality across
at least two campaigns. The flag status moves from REPEATED-WEAK (3 consecutive) to
"one clean data point" — monitor the next campaign for continuation.

---

### security-write-action-reviewer — 32 — EXEMPLARY

**Specificity (5):** CLEAR verdict with five distinct security-authority confirmations:
(a) no draft-level override — the fix never accepts a caller-supplied contractor_id to
substitute for the CM resolver; (b) no silent fallback — if resolution fails, the response
correctly omits the `freight_authority` block rather than synthesizing identity from a
fallback; (c) retry is read-only — the operator's retry action calls the same GET endpoint,
not a mutating endpoint; (d) deep-link only to resolved record — the edit URL in the
`freight_authority` block is emitted only when `resolved: True`, preventing a deep-link
to an ambiguous or incorrect record; (e) CM write via existing gated PATCH allowlist only —
the fix does not introduce a new write path. Each of these is a concrete, independently
verifiable security claim against the implementation. agentId ad84a5a48a8692466 recorded.
The "no silent fallback" and "deep-link only to resolved record" confirmations are the
highest-specificity items: they address the class of commercial-authority failure (wrong
contractor_id silently adopted) that would be the most damaging outcome if the fix
were implemented incorrectly.

**Coverage (5):** Covered the full security-write-action-reviewer mandate for this PR's
specific security surface. This PR adds identity context to a freight suggestion API —
the primary security risk is that a partial or failed resolution could leak a wrong
contractor_id into the UI, causing the operator to deep-link to (and potentially edit)
the wrong CM record. The agent covered this risk class exhaustively: no override, no
silent fallback, deep-link conditioned on `resolved: True`, CM write only through the
existing gated PATCH allowlist. The retry-read-only confirmation is also critical: if
the retry triggered a mutating action rather than a re-read, it would create an
unauthorized write path on the CM. All five surfaces are the correct coverage scope
for this PR class.

**Severity (5):** CLEAR with five explicit confirmations is precisely calibrated. The
commercial-authority risk (wrong contractor_id silently adopted) is correctly NOT present
in the implementation — the agent confirms this at the mechanism level. No inflation:
the CLEAR is not inflated to CLEAR-WITH-CONDITIONS or a provisional finding for a
correctly-implemented conditional response. No deflation: the "deep-link only to resolved
record" check is a real security surface that requires explicit verification, not an
assumption.

**Actionability (5):** Five explicit CLEAR confirmations are the complete GATE 1 security
clearance for this PR. Each confirmation is a distinct surface that an operator can
independently verify. The "no silent fallback" and "deep-link only to resolved record"
confirmations in particular are the exact security properties the operator must know are
correctly implemented before approving a PR that adds identity-linked deep-links to a
UI surface. This is maximum actionability: the operator can read these five points and
make a fully informed GATE 1 security decision.

**Substitution (5):** security-write-action-reviewer is canonical agent in AGENT_REGISTRY.md.
No substitution required. GATE 5 N/A.

**Evidence (4):** The five confirmed properties are described at the mechanism level
(what they confirm and why the implementation correctly satisfies each). The "no silent
fallback" and "deep-link only to resolved record" confirmations in particular name the
exact conditional logic in the implementation that produces this safety property. Minor
deduction: the campaign summary does not quote the agent's raw verdict block with
specific file:line citations for each of the five confirmation points. The five confirmations
are specific enough that a reader could locate the relevant code, but the evidence chain
is mediated through the campaign summary narrative rather than directly quoted from the
agent's structured output.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA
examined. Standard disclosure gap per Issue #597. No PATH GUARD violation confirmed.
Score 3/5.

---

### test-coverage-reviewer — 32 — EXEMPLARY

**Specificity (5):** CONCERNS verdict with three specifically named and resolved gaps:
(1) EUR-via-endpoint untested (gap: currency conversion path not tested at the endpoint
level — FIXED by adding the test); (2) combined missing_service_id (gap: the
`/suggest-combined` endpoint path where service_id is missing not covered — FIXED by
adding the test); (3) FA-11 `missing_field in html` substring-coincidence weakness
(gap: the test assertion `missing_field in html` was matching unrelated `rows_missing_fields`
text rather than the targeted `freightBlock.missing_field` output — FIXED by scoping to
`freightBlock.missing_field`). All three are named at the functional-scenario level.
The FA-11 finding is the highest-specificity contribution: it is not a missing-test gap
but a false-positive test gap — a test that claims to verify a property it does not
actually verify. The specific mechanism of the false match (substring coincidence with
`rows_missing_fields`) is independently verifiable. agentId aeb2fc41849c8403f recorded.

**Coverage (5):** Covered the critical test-coverage dimensions for a freight-authority
blocker fix: (a) currency path coverage (EUR conversion tested end-to-end at the endpoint
level, not just the unit level), (b) combined-endpoint path coverage (both `/suggest-freight`
and `/suggest-combined` covered for the missing_service_id case), and (c) assertion
validity — the FA-11 finding demonstrates the agent checked not just whether tests exist
but whether the assertions within those tests are actually verifying what they claim.
The distinction between "test present" and "test correctly asserted" is the highest-value
coverage signal from a test-coverage-reviewer: a test with a substring-coincidence match
is more dangerous than a missing test because it creates false confidence. The agent's
ability to identify this class of weakness demonstrates active examination of the test
assertion logic, not just test existence counts.

**Severity (5):** CONCERNS is correctly calibrated. The FA-11 false-positive assertion is
the most serious gap (it creates false test coverage confidence for a specific enforcement
property) — correctly surfaced as CONCERNS rather than LOW because the consequence is a
regression that passes the test suite. The EUR-via-endpoint and combined missing_service_id
gaps are real coverage gaps (production paths untested at the endpoint level), correctly
sized as CONCERNS (not LOW, not BLOCK). All three were resolved inline before PR open,
confirming the CONCERNS verdict produced the correct resolution action. No inflation: the
CONCERNS verdict did not escalate the gaps to BLOCK. No deflation: the FA-11 false-positive
was not dismissed as a LOW test-style item.

**Actionability (5):** All three CONCERNS were resolved inline before PR open:
EUR-via-endpoint test added, combined missing_service_id test added, FA-11 assertion
scoped to `freightBlock.missing_field`. The final test count (24 new tests, 123
endpoint-suite green) is independent corroboration that the three gaps are closed. The
FA-11 resolution in particular — scoping the assertion from a substring match to a
targeted `freightBlock.missing_field` property — is maximally actionable: it converts
a false-confidence test into a real discriminator for the enforcement property the test
is supposed to verify. This is the correct test-coverage-reviewer lifecycle: CONCERNS
→ named gaps → concrete fixes → confirmed passing before PR open.

**Substitution (5):** test-coverage-reviewer is canonical agent #5 in AGENT_REGISTRY.md.
No substitution required. GATE 5 N/A.

**Evidence (4):** The FA-11 false-positive finding is the strongest evidence item: it
names the specific assertion pattern (`missing_field in html`), the specific false-match
mechanism (substring collision with `rows_missing_fields`), and the targeted fix
(scope to `freightBlock.missing_field`). This is independently verifiable at the test
file level. The EUR-via-endpoint and combined missing_service_id gaps are named at the
functional-scenario level. Minor deduction: the campaign summary does not quote the
agent's raw verdict block with the specific test function names or file paths that were
missing or repaired — the evidence is mediated through the campaign narrative, not
directly quoted from the agent's "Missing tests: / Priority: / Files:" output contract.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA
examined. Standard disclosure gap per Issue #597. The 24 new tests and 123 green
endpoint-suite are independent corroboration that the agent reviewed the correct tree.
No PATH GUARD violation confirmed. Score 3/5.

---

## Weak-verdict warnings

### frontend-flow-reviewer (ACCEPTABLE — 27/35)

**Weak dimensions:** Evidence (3/5), Coverage (4/5)

**Evidence gap:** The decisive in-scope finding (F5 — "V1 copy implied a record exists
when resolution failed") is named at the semantic level but not anchored to a specific
component name, file path, or copy string in the reported verdict block. The pre-existing
findings (badge-amber hex fallbacks, bare `<button>`, `#fff`, `--danger`) are named at
the token/pattern level without file:line citations. Per the agent's defined output contract
("Files:"), each finding should name the file where the pattern was found.

**Verdict excerpt supporting the ACCEPTABLE score:**
> "frontend-flow-reviewer — CONCERNS. Real in-scope finding: V1 copy implied a record
> exists when resolution failed (F5 — FIXED via resolved/unresolved branch split). Other
> findings (badge-amber hex fallbacks, panel-wide bare <button>/#fff/--danger, V1 banner
> dismiss) were PRE-EXISTING / out-of-scope; correctly flagged but not introduced by this PR."

**Coverage gap:** The Lesson M capability-suppression check for the V2 `proforma-detail.jsx`
changes is not independently confirmed in the frontend-flow-reviewer verdict (only confirmed
by reviewer-challenge). For a PR touching V2 JSX workflow surfaces, CLAUDE.md mandates
Lesson M fire automatically via frontend-flow-reviewer.

**Pre-existing issue disposition:** The four pre-existing findings (amber hex, bare button,
`#fff`, `--danger`) are surfaced but the campaign does not confirm they received a GATE 4
disposition (SCHEDULED / ISSUE / REJECTED). "Pre-existing / out-of-scope" is not a valid
GATE 4 disposition. These should be filed as ISSUE or explicitly REJECTED.

**Recommendation:** Do not re-dispatch for this PR (GATE 1 is satisfied, in-scope finding
resolved). For future freight-related V1/V2 PRs: extend the frontend-flow-reviewer prompt
to require (a) file path for each FINDING, (b) explicit Lesson M V2 surface check as a
separate verdict item, (c) GATE 4 disposition for any pre-existing finding surfaced.

---

### backend-safety-reviewer (ACCEPTABLE — 28/35)

**Note on REPEATED-WEAK upgrade assessment:** This agent carried a formal REPEATED-WEAK
flag from `2026-06-21-proforma-overbill-fail-closed.md` (three consecutive ACCEPTABLE at
Evidence 3/5). The present campaign scores Evidence 4/5, based on the campaign summary's
"file:line throughout" characterization. This is the first evidence-quality improvement
data point since the REPEATED-WEAK flag was applied.

**Continued weak dimensions:** Environment (3/5) — standard disclosure gap; Coverage (4/5)
minor gap on `audit_merge.PRESERVED_KEYS` and `_normalise_X` Lesson A check.

**REPEATED-WEAK flag status:** One clean Evidence data point (4/5) after three consecutive
3/5 instances does not retire the flag. The flag is elevated from "three consecutive" to
"three consecutive + one improvement" — the pattern has broken once but is not yet confirmed
recovered. CONTINUED MONITORING is required. See GATE 4 disposition below.

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed:**
1. 2026-06-21: `2026-06-21-proforma-overbill-fail-closed.md` — 4 agents; 2 EXEMPLARY,
   2 ACCEPTABLE (backend-safety-reviewer 27 Evidence 3/5, security-write-action-reviewer 27)
2. 2026-06-21: `2026-06-21-proforma-authority-ui.md` — 4 agents; 3 EXEMPLARY,
   1 ACCEPTABLE (frontend-flow-reviewer 27, Evidence 3/5, Coverage 4/5)
3. 2026-06-21: `2026-06-21-pr3-dropdown-selection-authority.md` — 6 agents; 5 EXEMPLARY,
   1 ACCEPTABLE (backend-safety-reviewer 27, Evidence 3/5)
4. 2026-06-20: `2026-06-20-pr2-contractor-at-birth-projection.md` — 9 agents; 6 EXEMPLARY,
   3 ACCEPTABLE (backend-safety-reviewer 27, integration-boundary 27, frontend-flow-reviewer 23)
5. 2026-06-18: `2026-06-18-pr652-deploy-gate.md` — 7 deploy agents; 6 EXEMPLARY,
   1 ACCEPTABLE (deploy-qa-reviewer 23)

**backend-safety-reviewer — REPEATED-WEAK (formal flag from prior scorecard, under observation):**

Scorecard history for Evidence dimension in 5-scorecard window:
- 2026-06-18 pr652-deploy-gate: not dispatched in this campaign
- 2026-06-20 pr2-contractor-at-birth: ACCEPTABLE (27) — Evidence 3/5 (label-only)
- 2026-06-21 pr3-dropdown: ACCEPTABLE (27) — Evidence 3/5 (label-only)
- 2026-06-21 proforma-overbill: ACCEPTABLE (27) — Evidence 3/5 (label-only) — REPEATED-WEAK FORMAL FLAG APPLIED
- 2026-06-21 THIS campaign: ACCEPTABLE (28) — Evidence 4/5 (file:line cited per campaign summary)

`REPEATED-WEAK: agent backend-safety-reviewer has scored ACCEPTABLE with Evidence 3/5 in
3 of the last 5 runs.` This flag was formally applied in `2026-06-21-proforma-overbill-fail-closed.md`.

**The present run shows Evidence improvement (4/5)**. The formal flag is not yet retired:
one clean run at 4/5 following three at 3/5 is a positive signal, not a confirmed recovery.
The GATE 4 ISSUE filed in the prior scorecard (for filing a `agent-tuning` GitHub issue)
remains the governance action. Recommendation: confirm the Issue is filed; if the next
campaign shows Evidence 4/5 again, consider retiring the flag. If it reverts to 3/5,
escalate the Issue priority.

**Issue #694 status (per campaign prompt):** Referenced as an open agent-tuning Issue for
backend-safety-reviewer's evidence-packaging gap. The present run's Evidence 4/5 is
consistent with prompt-level improvement having taken effect, but operator should confirm
the Issue disposition once confirmed improvement is sustained across two campaigns.

**frontend-flow-reviewer — active REPEATED-WEAK approach:**

Scorecard appearances in 5-scorecard window:
- 2026-06-20 pr2-contractor-at-birth: ACCEPTABLE (23) — scope-exclusion, no negative artifacts
- 2026-06-21 proforma-authority-ui: ACCEPTABLE (27) — FINDINGS not file:line anchored; GATE-6 basis gap
- 2026-06-21 THIS campaign: ACCEPTABLE (27) — F5 not file:line anchored; Lesson M V2 check absent

**THREE CONSECUTIVE ACCEPTABLE scores** (23, 27, 27) for frontend-flow-reviewer with Evidence
dimension at 3/5 in all three appearances. The formal REPEATED-WEAK threshold (≥2 NEEDS-TUNING
or UNRELIABLE) is not met by ACCEPTABLE verdicts alone, but three consecutive ACCEPTABLE
instances with the same Evidence 3/5 root cause (findings named at pattern level without
file:line anchoring) constitute a REPEATED-WEAK pattern by the spirit of the rule, matching
the identical pattern that triggered the formal REPEATED-WEAK flag for backend-safety-reviewer.

`REPEATED-WEAK: agent frontend-flow-reviewer has scored ACCEPTABLE (Evidence 3/5) in 3 of
the last 3 runs — formal flag applied.`

See GATE 4 disposition below.

**security-write-action-reviewer — pattern check:**
- 2026-06-21 proforma-overbill: ACCEPTABLE (27) — confirmatory campaign, label-level evidence
- 2026-06-21 THIS campaign: EXEMPLARY (32) — five named mechanism-level confirmations, strong Evidence (4/5)

Recovery from the prior ACCEPTABLE is confirmed for this campaign. The oscillation pattern
(EXEMPLARY on discovery/adversarial campaigns, ACCEPTABLE on confirmatory campaigns) remains
a pattern to monitor. Two appearances in the 5-scorecard window; not at formal REPEATED-WEAK
threshold. Security-write-action-reviewer performed EXEMPLARY here on a campaign with clear
security authority surfaces to evaluate — consistent with the discovery-campaign strength
profile documented in prior scorecards.

**reviewer-challenge — pattern check:**
- All appearances in 5-scorecard window: EXEMPLARY (28-32)
- THIS campaign: EXEMPLARY (32)
No concern. reviewer-challenge continues its unbroken EXEMPLARY trajectory.

**test-coverage-reviewer — pattern check:**
- 2026-06-21 pr3-dropdown: EXEMPLARY (32) — REPEATED-WEAK flag retired
- 2026-06-21 proforma-overbill: EXEMPLARY (32)
- 2026-06-21 THIS campaign: EXEMPLARY (32)
Three consecutive EXEMPLARY after the flag retirement. Recovery fully confirmed.
No concern.

---

## GATE 4 dispositions generated by this scorecard

1. **backend-safety-reviewer REPEATED-WEAK (formal flag ongoing, first improvement data point)** —
   ISSUE (ongoing from `2026-06-21-proforma-overbill-fail-closed.md` scorecard; referenced as
   Issue #694 in the campaign prompt): The present Evidence 4/5 is the first clean data point
   after three consecutive 3/5 instances. The ISSUE disposition stands: confirm Issue #694 is
   filed and active. Do not close until two consecutive Evidence ≥4/5 campaigns are confirmed.
   If next campaign reverts to Evidence 3/5, escalate Issue #694 priority and require
   prompt-level review.

2. **frontend-flow-reviewer REPEATED-WEAK (three consecutive ACCEPTABLE, Evidence 3/5)** —
   ISSUE (new): Three consecutive ACCEPTABLE scores for frontend-flow-reviewer with Evidence 3/5
   root cause (pattern-level FINDINGS without file:line component anchoring) constitutes the
   same REPEATED-WEAK pattern that was formally flagged for backend-safety-reviewer. Required
   action: file a GitHub issue tagged `agent-tuning` for `frontend-flow-reviewer`. Prompt update
   must require: "For each FINDING, name the specific file path and component where the
   anti-pattern was found (e.g., 'hardcoded-hex: `service/app/static/js/shipment-detail.html`
   line ~NNN, badge color var fallback'). Do not report pattern-level findings without artifact
   anchoring. For PRs touching V2 JSX, include an explicit Lesson M capability-suppression check
   as a separate verdict item. For pre-existing findings, assign a GATE 4 disposition
   (SCHEDULED / ISSUE / REJECTED) rather than noting them as out-of-scope."
   Supersedes the SCHEDULED escalations from `2026-06-21-proforma-authority-ui.md` and
   `2026-06-20-pr2-contractor-at-birth-projection.md`.

3. **Pre-existing frontend findings (amber hex, bare button, #fff, --danger) disposition** —
   SCHEDULED: The four pre-existing findings surfaced by frontend-flow-reviewer in this campaign
   lack GATE 4 dispositions. An operator must assign one of SCHEDULED / ISSUE / REJECTED for
   each within the next tuning session. "Pre-existing / out-of-scope" is not a disposition.

---

## RULE 5 self-evaluation cadence check

**Most recent self-eval file:** `C:\PZ-freight\.claude\memory\scorecards\self-eval-2026-06-16.md`
**Self-eval date:** 2026-06-16
**Today:** 2026-06-21
**Calendar days elapsed:** 5 days
**7-day threshold reached:** NO (5 < 7; threshold falls on 2026-06-23)
**SELF-DEGRADATION DETECTED in self-eval-2026-06-16.md:** NO — scored 30/35 EXEMPLARY;
  prior 2026-06-15 degradation confirmed recovered; no new degradation flag; no 3rd-run
  counter active.
**Campaign scorecard runs since self-eval-2026-06-16.md:**
  Run 1: 2026-06-18 pr652-deploy-gate
  Run 2: 2026-06-20 pr2-contractor-at-birth-projection
  Run 3: 2026-06-21 pr3-dropdown-selection-authority
  Run 4: 2026-06-21 proforma-authority-ui
  Run 5: 2026-06-21 proforma-overbill-fail-closed
  Run 6: 2026-06-21 freight-authority-blocker-repair (THIS)
  Counter: 6 runs since last self-eval. No active SELF-DEGRADATION counter; 3rd-run trigger
  does not apply (that trigger requires an active SELF-DEGRADATION flag, which is not set).
  Calendar trigger requires 7 days (2026-06-23); not yet reached.

**Self-evaluation: SKIPPED — not triggered.**
Next self-eval due: 2026-06-23 (7 calendar days from 2026-06-16 self-eval), or at the 3rd
campaign scorecard run after any future SELF-DEGRADATION flag (no such flag active).

---

## Campaign quality summary

**Overall campaign verdict: EXEMPLARY** — 3 EXEMPLARY agents (reviewer-challenge,
security-write-action-reviewer, test-coverage-reviewer), 2 ACCEPTABLE (frontend-flow-reviewer,
backend-safety-reviewer). No NEEDS-TUNING. No UNRELIABLE. GATE 1 satisfied. All 6 in-scope
review findings resolved inline before PR open. GATE 2 compliant. GATE 6 deferred to
post-merge operator steps (not a gap — backend endpoint changes have no browser surface until
deployed; V1+V2 JSX compile-checked at Babel 7.26.4 as interim gate).

**Highest-value agent contributions:**
- **reviewer-challenge:** "Dual URL construction" finding — V1 rebuilding the deep-link URL
  client-side instead of consuming the backend's `edit_url` field — is the campaign's defining
  quality signal. This pattern would silently produce the wrong link under any CM routing change,
  making it a structural future-divergence risk rather than a current defect. Finding and fixing
  this before PR open eliminates an entire class of future link-break bugs. This is the
  canonical "question nobody asked" contribution.
- **security-write-action-reviewer:** Five distinct mechanism-level security confirmations
  covering the core commercial-authority risk (wrong contractor_id never silently adopted)
  at the deepest level of implementation detail. The "deep-link only to resolved record" and
  "no silent fallback" confirmations are particularly high-value: they demonstrate the agent
  examined the conditional logic that gates identity emission, not just the intent.
- **test-coverage-reviewer:** FA-11 false-positive assertion detection — identifying that
  `missing_field in html` matched unrelated `rows_missing_fields` text rather than the
  targeted enforcement property — is the highest-value test-quality finding in this campaign.
  Converting a false-confidence test into a real discriminator is more valuable than adding
  a missing test.

**ACCEPTABLE verdict root causes:**
- backend-safety-reviewer: Minor Coverage gap (PRESERVED_KEYS / Lesson A check not reported);
  Environment 3/5 (standard disclosure gap). Evidence improved to 4/5 this run — first break
  in the three-consecutive-3/5 pattern. REPEATED-WEAK flag under observation.
- frontend-flow-reviewer: Evidence 3/5 (F5 finding not file:line anchored; pre-existing
  findings named at pattern level without anchoring); Coverage 4/5 (Lesson M V2 check not
  independently confirmed). REPEATED-WEAK flag formally applied (third consecutive ACCEPTABLE,
  Evidence 3/5 — matching the pattern that triggered backend-safety-reviewer's flag).

**Structural systemic gap (all 5 agents):** Environment dimension at 3/5 across all agents —
no agent self-reported working tree path or commit SHA in verdict block. Standing governance
item per Issue #597. No new filing required.

**GATE 4 dispositions generated:** 3 items (see GATE 4 section above):
1. backend-safety-reviewer REPEATED-WEAK — ISSUE ongoing (Issue #694, first improvement data point)
2. frontend-flow-reviewer REPEATED-WEAK — ISSUE new (file agent-tuning issue)
3. Pre-existing frontend findings disposition — SCHEDULED (amber hex, bare button, #fff, --danger)
