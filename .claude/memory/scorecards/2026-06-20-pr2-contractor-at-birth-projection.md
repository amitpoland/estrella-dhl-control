# Agent Performance Scorecard — PR #673: Contractor-at-Birth Projection (f652de0)

**Date:** 2026-06-20
**Observer:** agent-performance-observer (RULE 2 auto-fire — 9 distinct named-agent invocations)
**Campaign:** PR-2 Contractor-at-Birth Projection — packing readiness authority campaign
**Merged SHA:** f652de0 (main)
**PR:** #673
**Scope:** Backend-only (no UI surface). New `derive_contractor_at_birth()` pure function,
  centralised-derive design, birth call-site updates (store_sales_document x3, link_as_sales,
  reingest), birth_blocked separate counter, contractor_id as reference (not key), batch_id
  path-traversal hardening, audit_skipped fix. 26 new real-builder tests + 63 smoke + 111
  at-risk regression, all passing.
**Outcome:** SUCCESS. GATE 1 satisfied. GATE 6 N/A (backend-only). 8 BACKLOG items
  (B-001..B-008) with GATE 4 dispositions.
**Agents evaluated:** 9

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| reviewer-challenge (PLAN) | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |
| gap-detection (PLAN) | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |
| backend-safety-reviewer | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| security-write-action-reviewer | 5 | 4 | 5 | 5 | 5 | 4 | 3 | 31 | EXEMPLARY |
| integration-boundary | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| test-coverage-reviewer | 4 | 5 | 4 | 5 | 5 | 3 | 3 | 29 | EXEMPLARY |
| reviewer-challenge (FINAL) | 5 | 5 | 4 | 5 | 5 | 4 | 3 | 31 | EXEMPLARY |
| final-consistency-review | 4 | 5 | 4 | 4 | 5 | 4 | 3 | 29 | EXEMPLARY |
| frontend-flow-reviewer | 3 | 4 | 3 | 3 | 5 | 2 | 3 | 23 | ACCEPTABLE |

---

## Scoring rationale per agent

### reviewer-challenge (PLAN) — 32 — EXEMPLARY

**Specificity (5):** Returned CLEAR-WITH-CONDITIONS / BLOCK-leaning with a precisely scoped decisive
finding: client_name is the cross-table storage key for proforma_drafts, reservation, and
service_charges — making it a re-keying risk if used as the write key for contractor identity. Named
the three affected tables by name. This is the highest-specificity possible for a PLAN-stage reviewer:
naming the cross-table key pattern before implementation and surfacing the design consequence
(contractor_id must be reference, not key). This finding reshaped the design.

**Coverage (5):** Covered the scope a PLAN-stage reviewer-challenge is responsible for: design risk
assessment before coding begins, authority-chain consequences, and cross-table write-key implications.
Did not overreach into implementation details that would be covered by later agents. The BLOCK-leaning
signal was appropriate to the risk severity — the cross-table re-keying risk is a structural design
defect, not an implementation detail.

**Severity (5):** BLOCK-leaning / CLEAR-WITH-CONDITIONS is correctly calibrated for a cross-table
re-keying risk at PLAN stage. Using client_name as the write key across proforma_drafts/reservation/
service_charges is a data-integrity risk at system scale, not a cosmetic concern. The agent correctly
escalated rather than noting the pattern as advisory. The finding level (design-blocking) matches the
impact class (structural integrity across three tables).

**Actionability (5):** The finding directly produced a concrete, implementable design decision:
contractor_id as reference not key. The operator acted on this immediately — it reshaped the
entire contractor-at-birth implementation design. This is the highest actionability signal: the
verdict altered the design before any code was written, which is precisely what a PLAN-stage
reviewer is meant to produce.

**Substitution (5):** reviewer-challenge is canonical agent #16 in the registry. No substitution.
GATE 5 N/A.

**Evidence (4):** Named tables (proforma_drafts, reservation, service_charges) and the specific
client_name cross-table key pattern are concrete, independently verifiable claims. The verdict was
derived from the design proposal, not from file reads, so file:line artifact-level evidence is
appropriate to score lower — but the claim (client_name is a storage key across these three tables)
is verifiable against the schema and could be confirmed by any reader who inspects those tables.
Minor deduction: no quoted schema field or table DDL to ground the cross-table key claim with
artifact-level precision; the claim is specific but stops one level above the artifact anchor.

**Environment (3):** PLAN-stage reviewer operating against a design proposal rather than implemented
code. Working tree self-disclosure is structurally less critical at PLAN stage (no file reads
required to assess a design proposal), but the verdict block as reported does not self-state the
tree path or any design document artifact path examined. Standard gap per Issue #597. Score 3/5:
no PATH GUARD violation risk at PLAN stage; disclosure missing but the impact class is lower than
for code-reading agents.

---

### gap-detection (PLAN) — 32 — EXEMPLARY

**Specificity (5):** Found all sales-row birth call sites — store_sales_document (x3), link_as_sales,
reingest — by enumeration. Named the result["blocked"] semantic collision (existing use of "blocked"
key in another semantic context). Named migration ordering constraints. These are the three highest-
specificity signals possible for a pre-implementation gap scan: exhaustive call-site enumeration,
semantic collision naming, and dependency ordering. Each claim is independently verifiable.

**Coverage (5):** Birth call-site discovery is precisely the scope of gap-detection at PLAN stage.
The agent found all 5 birth paths rather than a subset, which is the coverage correctness requirement
for a call-site scan. The semantic collision finding (result["blocked"]) goes beyond call-site
enumeration into behavioral gap detection — exactly what gap-detection is chartered to do per its
agent definition ("cross-phase contradiction finder"). Migration ordering as an additional finding
demonstrates scope coverage across both code topology and operational sequencing.

**Severity (5):** The result["blocked"] semantic collision is correctly surfaced as a design-blocking
concern — two callers assigning different meanings to the same result key in the same return path is
a silent ambiguity risk at integration time, not an advisory. All three finding classes (call-site
coverage, semantic collision, migration ordering) are correctly classified at their actual risk level:
design-affecting, not cosmetic. No inflation: the findings are high-value gaps, not everything-is-
critical noise.

**Actionability (5):** The exhaustive call-site list drove the centralised-derive design: instead of
patching individual call sites independently, the centralised `derive_contractor_at_birth()` function
provides a single authority surface. The semantic collision drove the birth_blocked separate counter
(not reusing result["blocked"]). Both design outcomes are directly traceable to gap-detection's
findings. This is the maximum actionability signal: findings produced architectural decisions that
changed the implementation approach.

**Substitution (5):** gap-detection is canonical agent #19 in the registry. No substitution. GATE 5 N/A.

**Evidence (4):** The call-site enumeration (named functions, named counts) is the correct evidence
class for a call-site scan — independently verifiable by any reader who runs a grep for those
function names. The semantic collision claim (result["blocked"]) is a named, verifiable key conflict.
Migration ordering is stated as a sequencing constraint traceable to the call-site graph. Minor
deduction: the campaign summary provides the findings as conclusions rather than quoting raw
grep output or file:line references from the agent's own verdict block. The claims are specific,
but the evidence chain is mediated through the campaign narrative rather than presented as raw
agent artifact output.

**Environment (3):** PLAN-stage agent scanning the codebase for call sites — file reads from the
working tree are required for call-site enumeration. The verdict block does not self-report the
working tree path or commit SHA examined. Standard gap per Issue #597. For a PLAN-stage scan
reading from `C:\PZ-pr2` (the working tree in scope for this PR), the absence of explicit
disclosure is a structural gap but not a confirmed PATH GUARD violation. Score 3/5.

---

### backend-safety-reviewer — 27 — ACCEPTABLE

**Specificity (4):** Named three specific areas: merge-not-replace behavior, idempotency, no external
write; raised pre-existing store_sales_document dup-row as B-002. These are the correct backend
safety surfaces for a birth-path change. The B-002 citation (pre-existing dup-row risk) is the
highest-specificity finding — naming a specific known defect by its BACKLOG item identifier
(B-002) is exactly the evidence an operator can act on. Minor deduction: PASS-WITH-NOTES without
naming specific functions, line ranges, or the concrete merge-not-replace pattern verified in the
implementation (e.g., what pattern confirms "merge-not-replace" was verified rather than asserted).

**Coverage (4):** Covered the primary backend safety surfaces for this change type: write-pattern
safety (merge-not-replace), idempotency of the birth-path function, absence of unintended external
writes. These are the three mandatory backend-safety dimensions for any audit-field-writing function
per the agent's chartered scope. Minor gap: the verdict as reported does not confirm whether the
agent explicitly checked the `_normalise_X` boundary-helper requirement from Lesson A (every
coordinator/builder PR must include this check), or whether the audit_merge.PRESERVED_KEYS contract
was checked (authority hash / preserve-merge context). The PASS scope may be narrower than the
full chartered surface.

**Severity (4):** PASS-WITH-NOTES is correctly calibrated — the three core safety properties are
confirmed, and B-002 is correctly elevated to BACKLOG (pre-existing, out-of-scope for this PR).
Not inflated (no items escalated to CRITICAL that are MEDIUM-class backlog items) and not deflated
(B-002 is not silently absorbed as LOW when it is a real structural risk). Score 4 rather than 5:
the PASS-WITH-NOTES label does not disclose whether B-002 is HIGH or MEDIUM in severity, making
the calibration partially opaque.

**Actionability (4):** The three confirmed safety properties (merge-not-replace, idempotency, no
external write) are actionable as GATE 1 clearance signals. B-002 is actionable as a BACKLOG item
with GATE 4 disposition. Minor deduction: "merge-not-replace confirmed" is a conclusion that does
not tell the operator what implementation pattern was verified — the actionable form would include
the specific function or merge guard that was checked, so an operator could verify it without
re-reading the full diff.

**Substitution (5):** backend-safety-reviewer is canonical agent #2 in the registry. No substitution.
GATE 5 N/A.

**Evidence (3):** The verdict provides labels ("merge-not-replace confirmed", "idempotency confirmed",
"no external write") rather than artifact-level evidence (quoted function body, grep output, named
line range). This is the core evidence gap: PASS-WITH-NOTES is a conclusion, but the evidence that
supports each conclusion (what was read, what was verified, what pattern was confirmed) is not
present in the campaign-reported verdict block. B-002 (pre-existing dup-row) is the strongest
evidence item because naming a specific defect demonstrates the agent inspected the real implementation.
Score 3: one artifact-level evidence item (B-002), two label-only items (merge-not-replace,
idempotency).

**Environment (3):** Verdict block does not self-report working tree path or commit SHA examined.
Standard gap per Issue #597. The PR was on a feature branch targeting main at f652de0; the agent's
read path is not confirmed in the verdict. No PATH GUARD violation confirmed. Score 3/5.

---

### security-write-action-reviewer — 31 — EXEMPLARY

**Specificity (5):** Named two specific, independently verifiable findings: (1) HIGH path-traversal
risk on batch_id — a named input vector, named risk class, named affected route(s); (2) audit actor
identity gap — a named authorization surface. Both were fixed inline before PR open. The path-
traversal finding is the highest-specificity security signal in this campaign: it names the input
(batch_id), the risk class (path traversal), and the consequence (filesystem escape via crafted
batch_id). This is a textbook HIGH security finding with correct specificity at all three levels
(input vector, risk class, consequence).

**Coverage (4):** Covered the two highest-priority security surfaces for a batch-id-parameterized
route writing to audit fields: path traversal on the ID input, and actor identity on write
operations. Minor gap: the verdict as reported does not explicitly confirm injection hardening on
other string inputs to the contractor-at-birth function (e.g., bill_to_name, name_pl, client_name
as stored — are these sanitized before storage or rendered?), which is within the agent's scan
scope for write-capable routes. Score 4 rather than 5 because the two named findings are the
critical ones, but the confirmed scan coverage of the full input surface is not reported.

**Severity (5):** HIGH for path-traversal on batch_id is correctly calibrated — a route that accepts
a batch_id parameter and constructs filesystem paths without validation is a genuine HIGH finding
(not CRITICAL, since the exploit requires authenticated access to a logistics route, which bounds
the blast radius). Fixed-inline treatment is correct for a pre-PR HIGH finding. The audit actor
identity gap is correctly classified below HIGH (it is an accountability gap, not a privilege
escalation). No inflation (no LOW items called HIGH) and no deflation (the path-traversal was
not downgraded to MEDIUM despite the auth-bounded context).

**Actionability (5):** Both findings were fixed inline before PR open. This is the highest
actionability outcome: the agent produced findings that were immediately actionable, the operator
fixed them, and GATE 1 was not blocked. The path-traversal fix (batch_id hardening) and the
audit actor identity fix are both concrete, implementable remediations — not vague recommendations.

**Substitution (5):** security-write-action-reviewer is canonical agent #4 in the registry. No
substitution. GATE 5 N/A.

**Evidence (4):** The path-traversal finding is named with sufficient specificity to be verifiable:
batch_id input, path construction, HIGH risk class. The actor identity gap is named as a specific
audit field concern. Minor deduction: the campaign summary does not quote the agent's raw output
including the specific route name, line number, or code pattern that demonstrated the traversal
risk. The claims are specific enough to be credible and verifiable, but the evidence chain is
mediated through the campaign narrative rather than the raw verdict block.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA examined.
Standard gap per Issue #597. No PATH GUARD violation confirmed. Score 3/5.

---

### integration-boundary — 27 — ACCEPTABLE

**Specificity (4):** PASS with "all 6 boundaries wired" — a count-based confirmation. Named 6
boundaries explicitly (the exact count of integration seams verified). For an integration-boundary
agent, the count-based confirmation is a reasonable specificity level if the 6 boundaries are
named. Minor concern: the campaign summary says "all 6 boundaries wired" without enumerating
which 6 boundaries were checked (e.g., which service→route, route→audit, audit→table seams). The
count is specific; the names of the boundaries are not reported in the summary.

**Coverage (4):** "All 6 boundaries wired" at PASS implies full scan of the integration seams
for this PR's scope. The contractor-at-birth feature introduces new integration seams between
derive_contractor_at_birth(), store_sales_document (x3), link_as_sales, reingest, and the audit
write layer. If these 6 are the boundaries checked, coverage is complete. Minor gap: the verdict
as reported does not confirm whether the agent explicitly checked the birth_blocked counter
integration (a new return-path pattern not present in prior iterations), or the contractor_id
reference-vs-key boundary (the critical design change from the PLAN phase reviewer-challenge
finding). These are the highest-risk integration seams in this PR.

**Severity (4):** PASS (safe_to_act yes) is correctly calibrated for a "boundaries wired"
confirmation on a backend-only change. No inflation. Score 4 rather than 5: the severity
calibration is correct at the conclusion level, but the verdict does not expose the severity
reasoning for any seam-specific risk found and cleared.

**Actionability (4):** PASS (safe_to_act yes) is directly actionable as a GATE 1 clearance
signal. The absence of conditions or follow-ups is appropriate for a clean PASS. Minor deduction:
the verdict does not name any seam-specific observations that the operator should monitor in
production (e.g., "contractor_id reference confirmed non-null before first write" would be a
named actionable observability recommendation).

**Substitution (5):** integration-boundary is canonical agent #18 in the registry. No substitution.
GATE 5 N/A.

**Evidence (3):** "All 6 boundaries wired" is a count-based conclusion. The campaign summary does
not quote the agent's raw evidence (which boundaries, what was checked at each seam, any grep
output or named function cross-references). The evidence quality is lower than the specificity
because the claim is aggregate ("6 boundaries") rather than enumerated. Score 3: the count is
concrete but the per-boundary evidence is absent from the reported verdict.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA examined.
Standard gap per Issue #597. No PATH GUARD violation confirmed. Score 3/5.

---

### test-coverage-reviewer — 29 — EXEMPLARY

**Specificity (4):** NEEDS-MORE verdict drove concrete additions: HTTP route tests, merge-precedence
tests, packing:backfill path, empty bill_to_name case. These are four specifically named test-gap
categories, each independently verifiable. The final suite count (26 new tests) is a concrete
artifact. Named four distinct coverage gaps before the additions — this is the correct specificity
for a test-coverage-reviewer: name the gaps by category, not just by count. Minor deduction: the
campaign summary does not quote the agent's verdict block directly; the four gap categories are
reported as what the agent "drove adding" rather than as raw verdict output. The specificity
inference is strong but mediated through narrative.

**Coverage (5):** Found four coverage gaps across different test dimensions: route-level (HTTP
route tests), merge-correctness (merge-precedence), path coverage (packing backfill), and edge
cases (empty bill_to_name). This cross-dimensional gap discovery demonstrates the agent scanned
the full test surface rather than stopping at count-level verification. The NEEDS-MORE verdict
also demonstrates the agent applied the quality threshold correctly — not accepting the initial
test count as sufficient when route-level tests were absent.

**Severity (4):** NEEDS-MORE is correctly applied when HTTP route tests are missing for a new
route. Missing HTTP route tests on a backend-only PR is a genuine coverage gap (not a style
preference) — the route is the integration surface that production traffic hits. Score 4 rather
than 5: the campaign summary does not indicate whether the agent distinguished the HTTP route
test gap as HIGH/MEDIUM vs the edge-case gaps (empty bill_to_name) which might be MEDIUM/LOW.
The severity gradation within the NEEDS-MORE finding is not reported.

**Actionability (5):** NEEDS-MORE directly produced 26 new tests before PR open. This is the
maximum test-coverage-reviewer actionability signal: the verdict was acted on immediately,
producing measurable output (suite growth from initial count to 26 new tests), and GATE 1 was
not blocked. The four specific gaps named are all independently verifiable as resolved by the
new tests.

**Substitution (5):** test-coverage-reviewer is canonical agent #5 in the registry. No substitution.
GATE 5 N/A.

**Evidence (3):** The four gap categories are named, which is the correct evidence class for a
coverage-gap finding. The final count (26 tests) is a concrete artifact. Minor deduction: no
raw grep output or test file list from the agent's own verdict block is quoted in the campaign
summary. The findings are reported as conclusions ("drove adding HTTP route tests") rather than
as raw verdict output. The evidence is present but mediated through narrative. Score 3 reflects
that the specific test names, file names, or function names confirmed missing are not directly
cited from the agent's raw output.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA examined.
Standard gap per Issue #597. No PATH GUARD violation confirmed. Score 3/5.

---

### reviewer-challenge (FINAL) — 31 — EXEMPLARY

**Specificity (5):** CLEAR-WITH-CONDITIONS (safe_to_act yes) after verifying D1–D5/D7. Named
specific findings: CM-unavailable warning, audit_skipped (fixed), pre-existing name_pl enrich
(B-007). Raised the CM-unavailable warning as an explicit edge case — this is the highest-
specificity contribution for a FINAL-stage reviewer: surfacing the edge condition that the
implementation has not exercised but could encounter. B-007 (pre-existing name_pl enrich) is
named by BACKLOG item identifier, confirming the agent traced it to an existing known gap
rather than treating it as an in-scope defect.

**Coverage (5):** Verified D1–D5 and D7 (6 of 7 design criteria, with D6 presumably N/A for
backend-only). Named CM-unavailable as an unresolved edge condition, audit_skipped as a resolved
fix, and B-007 as a known pre-existing gap. For a FINAL-stage reviewer-challenge, this is the
complete coverage profile: re-verify design criteria, surface remaining conditions, distinguish
fixed vs BACKLOG items. The CM-unavailable warning demonstrates coverage beyond nominal-path
verification.

**Severity (4):** CLEAR-WITH-CONDITIONS (not BLOCK) after finding CM-unavailable warning and
pre-existing B-007. The severity calibration here is important: CM-unavailable is an edge
condition worth flagging but not blocking, correctly treated as a condition rather than a
BLOCK. audit_skipped was fixed inline (the agent found it and it was fixed before CLEAR
was issued). B-007 is correctly classified as pre-existing BACKLOG. Score 4 rather than 5:
the campaign summary does not indicate what severity level the CM-unavailable warning was
assigned (LOW/MEDIUM/HIGH) — the "warning" label is correct but the standard severity
vocabulary is not confirmed in the reported verdict.

**Actionability (5):** CM-unavailable was disclosed to operator. audit_skipped was fixed inline.
B-007 received GATE 4 disposition as a BACKLOG item. All three findings have a clear resolution
path: one operator-disclosed warning, one inline fix, one GATE 4 SCHEDULED disposition. No
orphaned findings.

**Substitution (5):** reviewer-challenge is canonical agent #16 in the registry. No substitution.
GATE 5 N/A.

**Evidence (4):** Named criteria (D1–D5/D7 verified) with specific findings (CM-unavailable,
audit_skipped, B-007) provides an evidence chain grounded in the design criteria list. The
audit_skipped finding demonstrates the agent read the implementation and found a real gap that
was subsequently fixed. Minor deduction: D1–D5/D7 are referenced by identifier without quoting
the specific criterion content or the verification method for each — a reader cannot confirm
which criterion maps to which implementation behavior without cross-referencing the design
document.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA examined.
Standard gap per Issue #597. FINAL-stage reviewer-challenge reads the implemented code; working
tree path matters for verification of the fixes (audit_skipped fix in particular). No PATH GUARD
violation confirmed. Score 3/5.

---

### final-consistency-review — 29 — EXEMPLARY

**Specificity (4):** CLEAR (8/8 dimensions). Named 8 consistency dimensions checked — a count-
based comprehensive check. For a final-consistency-review, the 8/8 dimension structure is the
correct report format: it confirms exhaustive scope. Minor deduction: the campaign summary does
not enumerate which 8 dimensions were checked or what was verified at each dimension, which
would allow an independent reader to confirm the scope matches the agent's chartered purpose
without cross-referencing the agent definition file.

**Coverage (5):** 8/8 dimensions with CLEAR implies full chartered scope coverage. The
final-consistency-review is the last gate before PR open, and a CLEAR (not CLEAR-WITH-CONDITIONS)
at this stage confirms the full implementation surface was checked after all preceding agent
findings were resolved. The absence of any conditions or findings at the FINAL consistency
check stage confirms the design-criteria verification, the inline fixes, and the BACKLOG
dispositions were all complete before this agent ran.

**Severity (4):** CLEAR with 8/8 is correctly calibrated — no false-positive conditions added
when the implementation is clean. Score 4 rather than 5: the severity framing (what severity
level each dimension was cleared at) is not reported. A CLEAR verdict at this stage is correct,
but the dimension-by-dimension severity gradation (e.g., "D-3 authority-merge: CLEAR at LOW
risk after verified merge-not-replace pattern") would ground the CLEAR in severity-aware
assessment rather than aggregate confirmation.

**Actionability (4):** CLEAR (8/8) is a directly actionable gate signal for PR open. The
operator can proceed to PR without conditions. Minor deduction: the 8/8 CLEAR does not produce
any named "continuing monitors" or "post-deploy checks" — a final-consistency-review CLEAR
ideally notes any behavioral properties that should be confirmed in production smoke (e.g.,
"contractor_id reference confirmed in first live birth cycle").

**Substitution (5):** final-consistency-review is canonical agent #20 in the registry. No
substitution. GATE 5 N/A.

**Evidence (4):** The 8/8 dimension count with CLEAR is a concrete aggregate artifact. The
campaign outcome (SUCCESS, GATE 1 satisfied, 26 new tests passing) provides independent
corroboration that the final-consistency-review's CLEAR is grounded in a real implementation.
Minor deduction: same as Specificity — the specific dimensions and their verification evidence
are not quoted from the agent's raw verdict block.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA examined.
Standard gap per Issue #597. No PATH GUARD violation confirmed. Score 3/5.

---

### frontend-flow-reviewer — 23 — ACCEPTABLE

**Specificity (3):** CLEAR (backend-only, no Lesson M suppression). The verdict correctly
classifies the campaign as backend-only and confirms no Lesson M capability-suppression
occurred. However, this is the minimum viable specificity for a frontend-flow-reviewer on a
backend-only PR — the agent confirmed scope exclusion rather than performing inspection.
No named elements, no named routes, no named audit fields checked for inadvertent frontend
impact. Score 3: the verdict is correct but sparse.

**Coverage (4):** For a backend-only PR with no UI surface, frontend-flow-reviewer's coverage
scope is appropriately narrow: confirm no Lesson M suppression, confirm no inadvertent V1 file
edits, confirm no frontend-state mutations. The agent correctly identified this as backend-only
and issued CLEAR. Minor gap: the campaign summary does not indicate whether the agent confirmed
no new static file changes, no new template references, and no new Jinja2 render paths — all
of which could introduce a frontend surface on a backend-only PR without triggering the
obvious "UI change" detection heuristic.

**Severity (3):** CLEAR for "backend-only, no Lesson M suppression" is correctly calibrated
at the conclusion level. However, the severity of the Lesson M check ("no suppression") is
not reported — Lesson M applies to any PR that could remove or hide a visible capability, and
a backend-only PR that changes what data a capability depends on could suppress a visible
capability without touching frontend files. The verdict as reported does not confirm this
deeper Lesson M scope was checked. Score 3: CLEAR is correct given the PR's actual scope, but
the severity reasoning for the Lesson M confirmation is not demonstrated.

**Actionability (3):** CLEAR is actionable as a gate signal. Minor deduction: for a backend-only
PR, the frontend-flow-reviewer's value-add is confirming that no unintended frontend impact
exists — a more actionable verdict would note specifically what was confirmed absent (e.g., "no
new template renders, no new static file writes, no Jinja2 context changes"). Without this,
the CLEAR is indistinguishable from a scope-exclusion rubber stamp.

**Substitution (5):** frontend-flow-reviewer is canonical agent #3 in the registry. No substitution.
GATE 5 N/A.

**Evidence (2):** "CLEAR (backend-only, no Lesson M suppression)" provides no supporting
artifact evidence — no file list checked, no grep output confirming no template references,
no negative-evidence chain for the Lesson M scope. For a backend-only PR, the evidence burden
is negative-evidence (confirming absence), which still requires a scan. The verdict as reported
provides no scan artifacts. Score 2: conclusion only, no evidence chain.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA examined.
Standard gap per Issue #597. For a frontend-flow-reviewer confirming backend-only scope, path
self-disclosure would confirm the agent read the correct file tree to make that determination.
No PATH GUARD violation confirmed. Score 3/5.

---

## Weak-verdict warnings

### backend-safety-reviewer (ACCEPTABLE — 27/35)

**Weak dimensions:** Evidence (3/5), Coverage (4/5)

**Evidence gap:** The verdict block (as reported in the campaign summary) provides three label-only
conclusions ("merge-not-replace confirmed", "idempotency confirmed", "no external write") without
artifact-level support: no quoted function bodies, no grep output, no named line ranges, no named
patterns that demonstrate the inspection was performed at the file-content level. The one artifact-
level item (B-002: pre-existing dup-row) demonstrates real inspection occurred but does not close
the evidence gap on the three primary safety claims.

**Coverage gap:** The Lesson A `_normalise_X` boundary-helper check is not reported in the verdict.
For a coordinator/builder PR, Lesson A binds at GATE 1 and requires backend-safety-reviewer to
explicitly flag whether the normalise-boundary pattern is present. "PASS" without this named
dimension leaves a Lesson A compliance gap in the gate record.

**Quoted campaign summary supporting score:**
> "backend-safety-reviewer — PASS-WITH-NOTES; merge-not-replace, idempotency, no external write;
> raised pre-existing store_sales_document dup-row (B-002)."

**Recommendation:** Do not re-dispatch for this campaign (PR is merged). For future PRs involving
new audit-field-writing functions, add explicit prompt guidance: "Verify and name the specific
function or code pattern that implements merge-not-replace (e.g., `{**existing, ...new_fields}`
pattern), the idempotency guard (e.g., key-present check before write), and any `_normalise_X`
boundary helpers per Lesson A. Cite file:line references."

---

### integration-boundary (ACCEPTABLE — 27/35)

**Weak dimensions:** Evidence (3/5), Specificity (4/5)

**Evidence gap:** "All 6 boundaries wired" is a count-based conclusion without enumerating which
6 boundaries were checked. The campaign summary does not reveal whether the agent named the
specific integration seams (e.g., "derive_contractor_at_birth → store_sales_document wiring
confirmed at service/app/services/birth_service.py:NN"). The count is concrete but the per-
boundary evidence is absent.

**Specificity gap:** Without the named boundary list, the specificity of the integration claim
cannot be verified by a reader who hasn't cross-referenced the implementation. An ACCEPTABLE
integration-boundary verdict at minimum enumerates the seams by name.

**Quoted campaign summary supporting score:**
> "integration-boundary — PASS (safe_to_act yes); all 6 boundaries wired."

**Recommendation:** Do not re-dispatch (PR is merged). For future implementation PRs, add to
the integration-boundary prompt: "In your verdict block, enumerate each integration boundary
checked by name (function-to-function or service-to-route seam), confirm it is wired, and
cite the specific file:line or function name where the wiring was verified."

---

### frontend-flow-reviewer (ACCEPTABLE — 23/35)

**Weak dimensions:** Evidence (2/5), Specificity (3/5), Severity (3/5), Actionability (3/5)

**Evidence gap (primary):** The verdict provides no artifact evidence for the "backend-only"
determination or the Lesson M confirmation. A scope-exclusion verdict ("this PR has no frontend
surface") still requires a scan to confirm, and the scan artifacts (file list, grep for template
references, confirmation of no static file changes) are absent from the reported verdict.

**Scope-exclusion verdicts need evidence too:** For a frontend-flow-reviewer, "CLEAR (backend-
only)" is the most common verdict on implementation PRs. The risk is that this verdict becomes
a rubber stamp if it requires no evidence. The Lesson M "no suppression" claim in particular
requires inspecting whether any backend change removes functionality a frontend capability
depends on — this is a non-trivial check that the verdict does not demonstrate was performed.

**Quoted campaign summary supporting score:**
> "frontend-flow-reviewer — CLEAR (backend-only, no Lesson M suppression)."

**Recommendation:** Do not re-dispatch (PR is merged). For future backend-only PRs, add to
the frontend-flow-reviewer prompt: "Even for backend-only PRs, include in your verdict block:
(a) list of files scanned to confirm no frontend surface (templates, static files, Jinja2
context), (b) confirmation no new render paths were added, (c) Lesson M check basis (e.g.,
'no capability-owning route removed or hidden'). A backend-only CLEAR requires negative-evidence
artifacts, not scope-exclusion assertion."

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed:**
1. 2026-06-18: `2026-06-18-pr652-deploy-gate.md` — 7 deploy agents; deploy-qa-reviewer ACCEPTABLE
   (23); all others EXEMPLARY
2. 2026-06-17: `2026-06-17-pr633-cif-ui-deploy-verify.md` — 7 deploy agents; deploy-backend-
   impact-reviewer, deploy-qa-reviewer, deploy-release-manager ACCEPTABLE (26 each, drift-induced);
   others EXEMPLARY
3. 2026-06-17: `2026-06-17-pr633-cif-ui-resolved-authority.md` — 3 implementation agents; all
   EXEMPLARY (28-29); Environment 2/5 across all three
4. 2026-06-17: `2026-06-17-pr2-vision-invoice-confirm.md` — 4 implementation agents; reviewer-
   challenge ACCEPTABLE (27), security-write-action-reviewer ACCEPTABLE (27), backend-safety-
   reviewer EXEMPLARY (32), test-coverage-reviewer EXEMPLARY (31)
5. 2026-06-17: `2026-06-17-ocr-ai-image-only-extraction-fallback.md` — 3 implementation agents;
   backend-safety-reviewer ACCEPTABLE (26); reviewer-challenge EXEMPLARY (30); security-
   permissions EXEMPLARY (30)

**backend-safety-reviewer — pattern check:**
- 2026-06-17 ocr-ai-image-only-extraction-fallback: ACCEPTABLE (26)
- 2026-06-17 pr2-vision-invoice-confirm: EXEMPLARY (32) — recovery
- 2026-06-17 pr633-cif-ui-resolved-authority: EXEMPLARY (28) — sustained
- 2026-06-20 pr2-contractor-at-birth (THIS): ACCEPTABLE (27) — recurrence

Pattern: Two ACCEPTABLE scores (26 and 27) in the 5-scorecard window, on non-consecutive
campaigns. The prior ACCEPTABLE (26 in ocr-ai-image-only) was followed by an EXEMPLARY
recovery (32 in vision-invoice-confirm). This campaign reverts to ACCEPTABLE with the same
evidence gap (label-only conclusions without artifact citations). The oscillation
(ACCEPTABLE → EXEMPLARY → EXEMPLARY → ACCEPTABLE) suggests the evidence quality is
prompt-sensitive rather than agent-capability-limited — the agent produced strong evidence
(32) when the campaign context provided more concrete implementation details, and thin
evidence when the campaign summary is more narrative.

**Assessment:** Not yet at REPEATED-WEAK threshold (requires ≥2 NEEDS-TUNING or UNRELIABLE
in 6 runs; two ACCEPTABLE scores do not trigger). However, the oscillating pattern warrants
a monitor flag. The root cause (evidence quality depends on campaign-context richness rather
than agent self-grounding in artifact output) is addressable at the prompt level — require
explicit file:line citations in the verdict block regardless of campaign context.

**reviewer-challenge — pattern check (both PLAN and FINAL instances scored separately):**
- PLAN instance: EXEMPLARY (32) — decisive design-blocking finding
- FINAL instance: EXEMPLARY (31) — edge-case CM-unavailable warning + audit_skipped fix
Both instances EXEMPLARY; no concern.

**frontend-flow-reviewer — pattern check:**
- 2026-06-17 pr633-cif-ui-resolved-authority: EXEMPLARY (29) — BLOCK→clear with real findings
- 2026-06-20 pr2-contractor-at-birth (THIS): ACCEPTABLE (23) — scope-exclusion without evidence

Two appearances in the 5-scorecard window; one EXEMPLARY, one ACCEPTABLE. The EXEMPLARY
appearance was on a PR with actual frontend changes (shipment-detail.html, +86/-23), where the
agent had real content to inspect and produced a BLOCK→clear cycle. The ACCEPTABLE appearance
was on a backend-only PR where the agent issued a scope-exclusion CLEAR. The performance
difference maps directly to whether there is frontend content to inspect: the agent performs
well on real frontend changes and performs weakly on scope-exclusion verdicts. This is an
evidence discipline gap on the scope-exclusion path, not a capability gap.

**Assessment:** Not at REPEATED-WEAK threshold. One ACCEPTABLE in 2 appearances does not trigger
the ≥2-in-6-runs flag. Monitor the next backend-only PR frontend-flow-reviewer dispatch.

**security-write-action-reviewer — pattern check:**
- 2026-06-17 pr2-vision-invoice-confirm: ACCEPTABLE (27)
- 2026-06-20 pr2-contractor-at-birth (THIS): EXEMPLARY (31)

Positive recovery trajectory — HIGH path-traversal finding in this campaign represents stronger
performance than the prior ACCEPTABLE. No concern.

**No REPEATED-WEAK flags generated.** No agent meets the ≥2 NEEDS-TUNING or UNRELIABLE
threshold in the 5-scorecard window. The backend-safety-reviewer oscillating ACCEPTABLE pattern
is flagged for monitoring but does not yet warrant a governance issue.

---

## GATE 4 dispositions generated by this scorecard

1. **backend-safety-reviewer evidence gap (ACCEPTABLE, recurring pattern)** —
   SCHEDULED: Add to backend-safety-reviewer prompt: "For each safety property confirmed (merge-
   not-replace, idempotency, no external write), cite the specific function name and line range
   or code pattern you verified. A PASS conclusion without artifact citation is insufficient.
   Also confirm whether `_normalise_X` boundary helpers are present per Lesson A." Target: next
   agent tuning session.

2. **integration-boundary boundary enumeration gap (ACCEPTABLE)** —
   SCHEDULED: Add to integration-boundary prompt: "In your verdict block, enumerate each
   integration boundary checked by name (function-to-function or service-to-route seam) and
   cite the specific file:line or function name where the wiring was verified. 'All N boundaries
   wired' without enumeration is insufficient." Target: next agent tuning session (can be batched
   with item 1).

3. **frontend-flow-reviewer scope-exclusion evidence gap (ACCEPTABLE)** —
   SCHEDULED: Add to frontend-flow-reviewer prompt: "For backend-only PRs, include in your
   verdict block: (a) list of files scanned to confirm no frontend surface, (b) confirmation no
   new render paths were added, (c) Lesson M check basis. A backend-only CLEAR without negative-
   evidence artifacts is a rubber stamp, not an inspection." Target: next agent tuning session
   (can be batched with items 1 and 2).

---

## RULE 5 self-evaluation cadence check

**Most recent self-eval file:** `C:\PZ-pr2\.claude\memory\scorecards\self-eval-2026-06-16.md`
**Self-eval date:** 2026-06-16
**Today:** 2026-06-20
**Calendar days elapsed:** 4 days
**7-day threshold reached:** NO (4 < 7; threshold falls on 2026-06-23)
**SELF-DEGRADATION DETECTED in self-eval-2026-06-16.md:** NO — scored 30/35 EXEMPLARY;
  prior 2026-06-15 degradation confirmed recovered; no new degradation flag set; no 3rd-run
  counter active.

**Self-evaluation: SKIPPED — not triggered.**

Next self-eval due: 2026-06-23 (7 calendar days from 2026-06-16) OR at 3rd campaign scorecard
run after any future SELF-DEGRADATION flag. This is the 1st campaign scorecard run since the
2026-06-16 self-eval.

---

## Campaign quality summary

**Overall campaign verdict: EXEMPLARY** — 6 EXEMPLARY agents, 3 ACCEPTABLE agents. No NEEDS-TUNING
or UNRELIABLE verdicts. GATE 1 satisfied before PR open. All HIGH/CRITICAL findings resolved inline.
8 BACKLOG items properly dispositioned (GATE 4).

**Highest-value agent contributions:**
- **reviewer-challenge (PLAN):** Decisive design-blocking finding (client_name cross-table re-keying
  risk) that reshaped the entire implementation approach at zero implementation cost. This is the
  maximum value a PLAN-stage reviewer can produce — blocking a structural data-integrity risk before
  a single line was written.
- **gap-detection (PLAN):** Exhaustive call-site enumeration (5 birth paths) that directly produced
  the centralised-derive architecture. Without this finding, the implementation would likely have
  been 5 independent call-site patches rather than a single authority function.
- **security-write-action-reviewer:** HIGH path-traversal finding on batch_id, fixed inline. A
  filesystem-escape risk on an authenticated logistics route is a genuine HIGH that warranted the
  BLOCK treatment and the inline fix before PR open.

**ACCEPTABLE verdicts — root cause analysis:**
All three ACCEPTABLE verdicts (backend-safety-reviewer, integration-boundary, frontend-flow-reviewer)
share a common failure class: **insufficient evidence in the verdict block** rather than incorrect
findings. Each agent's conclusion is plausible or correct given the outcome (PR merged successfully,
tests passing), but the evidence chain presented in the reported verdict does not independently
support the conclusion. This is a campaign-reporting discipline gap as much as an agent quality gap:
the campaign summary mediates verdict blocks through narrative, which loses artifact-level detail.
However, the evidence-first scoring standard requires that verdict blocks contain their own
artifact citations rather than relying on the campaign narrative to carry them.

**Structural systemic gap (all 9 agents):** Environment dimension at 3/5 across all agents —
no agent self-reported working tree path or commit SHA in verdict block. Standing governance item
per Issue #597. No new filing required.

**GATE 4 dispositions required (per RULE 6):** 3 SCHEDULED items generated (items 1–3 above).
Can be batched into a single agent-tuning session targeting backend-safety-reviewer,
integration-boundary, and frontend-flow-reviewer prompt templates.
