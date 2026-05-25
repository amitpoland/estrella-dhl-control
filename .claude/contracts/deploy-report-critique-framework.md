# Post-Deploy Report Critique Framework

```
Framework authority owner: [name]
First adoption date:       [date]
Quarterly review date:     [date + 90 days]

Migration policy:
  [ ] Retrofit     — prior reviews re-run under this framework
  [ ] Forward-only — applies to reviews dated after [adoption date]
```

---

## Reviewer Provenance (required — complete before any section)

```
Reviewer: _______________

System familiarity:
  [ ] Domain expert — read service code within 30 days
  [ ] Familiar      — adjacent system knowledge
  [ ] Generalist    — no system knowledge

Evidence Scope (check all that apply):
  [ ] Documentation only
  [ ] Code inspected
  [ ] Runtime logs inspected
  [ ] Audit trail inspected
  [ ] Production state inspected

Review Class (derived — do not declare; determined by evidence scope):
  STRUCTURAL = Documentation only OR Code only
  RUNTIME    = Any of Runtime / Audit / Production checked
  FULL       = Code + any of Runtime / Audit / Production checked
```

**Rule: A review without this block is not a review. Reject it.**

---

## Self-Application

This framework is itself an artifact with a Gap Authority registry.

When applied to itself:
- Author declares conflict of interest in Reviewer Provenance
- A second reviewer independently confirms all G-class findings
- Framework's own authority owner: [name to be set]
- Findings go into the framework's own registry, not the deploy report's registry

---

## Pre-Analysis Pass (required — complete before writing any section)

Do not begin Section A until all four steps are complete.

1. List every claim in the report that uses population-scope language: "global," "all," "every," "system-wide," "complete." Write them out.
2. For each claim, state what would have to be true for it to hold.
3. For each claim, identify which of those truth conditions the report explicitly verifies versus asserts without verification.
4. Note any condition from step 2 that is neither verified nor acknowledged as unverified. These are the primary candidates for Section B gaps.

---

## Part 1 — Critique Template

---

### Section A: Strengths (required)

Name at least two things the report does well, with specific section references. This is not courtesy. A reviewer who skips this section produces feedback authors will discount as adversarial and ignore. Concrete praise also sharpens the critique: if you can say precisely *why* something works, you have established the standard you are holding the gaps to.

Format:
```
[Section X] [What it does] — [Why it works operationally]
```

**Amendment Rule:** If a gap in Sections B–H directly contradicts a strength recorded here, amend in place:

```
[AMENDED — contradicted by GAP-NNN]
```

Do not delete. Preserve the original observation and the reason for revision. Deletion removes the signal; amendment preserves the reasoning.

---

### Section B: Gaps

**Fill-Order Note:** Sections A–H are reading order, not writing order. Fill gap entries as you find them during review. Reorder by severity (P0 first) before the review is finalized. A reviewer who fills entries chronologically without reordering delivers a document ordered by when they noticed things, not by what matters most.

---

**Severity Calibration — read before assigning any severity**

```
P0: Operator acting in next [system-specific time bound] makes wrong decision
    if this gap is not disclosed.
    Requires Section D entry. No exceptions.

P1: Operator makes suboptimal decision within next 24 hours.
    Real operational cost; not immediate harm.

P2: Gap creates misleading documentation that could cause errors in a future
    review or deploy. Not immediately harmful.

P3: Refinement. Improves clarity or prevents rare edge cases.
    No immediate operational consequence.

INFLATION TEST (required before assigning P0):
  "If an operator reads this report and acts on it in the next [time bound]
  without seeing this gap, what specifically goes wrong?"
  If the answer requires more than two inference steps → P1, not P0.

DEFLATION TEST (required before assigning P2/P3 to a verification claim):
  "Is this gap covered by the Population Coverage Audit?"
  If yes and audit shows FAIL → at least P1.

Definition of "operationally safe": Section I.
```

---

**Gap Format**

One finding = one GAP-NNN object. Multiple checklist items point to it. Never create parallel gap entries for the same finding.

```
GAP-NNN (assigned sequentially at creation, not at finalization)

Authority Sources (ordered, first-surfaced first):
  [ChecklistID] ([G or D], [first-surfaced | escalated | corroborating])
  ...

Primary Class: G or D  (= highest class in Authority Sources)

Type: Structural | Verification | Operational clarity | Consumer impact |
      Performance | Root cause

Severity: P0 | P1 | P2 | P3

What the report says:    [quote or paraphrase]
Why it fails operationally: [concrete failure mode]
Concrete fix:            [specific change]

Discharge Status: OPEN | DISCHARGED
```

**Completion Gate:** An entry with fewer than all fields populated is a note, not a gap. Notes do not appear in the Section H must-fix list. Notes are not tracked for discharge. Notes do not count toward review completion. If a field cannot be completed because it requires domain knowledge you do not have, write "REQUIRES D REVIEWER" in that field and flag the gap for escalation. Do not leave the field blank.

---

**Mandatory Section D Linkage**

Any gap assigned P0 or P1 severity requires a completed Section D entry before the review is complete. If Section D cannot be completed — time bound unknown, verification endpoint unknown — downgrade the severity to P2 and add this flag:

```
SEVERITY DOWNGRADED — temporal bounds unverifiable.
Escalate to D reviewer before treating as P0.
```

---

### Section C: Population Coverage Audit

**Before adding an entry:** search Section B for an existing gap covering this finding. If found, append this section's checklist ID to that gap's Authority Sources. Do not create a new entry.

For every claim using "global," "all," "every," or "system-wide," complete this table:

| Claim | Population Size | Sample Checked | What Happened to the Rest |
|-------|----------------|----------------|--------------------------|
|       |                |                |                          |

**Pass/Fail Criteria for "What Happened to the Rest":**

```
PASS:        "Confirmed via [mechanism] — remainder accounted for."
             Idempotency log, sweep output, or explicit enumeration qualify.

CONDITIONAL: "Status unknown — residual risk."
             Generates a Section B gap with owner + target date.

FAIL:        "Status unknown" with no owner, no target date, no risk class.
             A FAIL means the claim is unsubstantiated.
             Downgrade in report from "global" to "verified for N of M."
```

**Any FAIL in this column → report is not operationally safe regardless of P0/P1 discharge status.** See Section I.

---

### Section D: Temporal Gaps

For every condition described as self-resolving or time-dependent, state:

```
Condition:              [description]
Resolution mechanism:   [exact mechanism]
Time bound:             [minimum and maximum in absolute terms, not relative]
Verification endpoint:  [exact URL, method, and response field to check]
Fallback action:        [what operator does if time bound passes without resolution]
```

A report that describes a condition as "may persist until the next tick" without these four elements is operationally useless for the operator reading it under time pressure.

---

### Section E: Root Cause Completeness Check

For every fix described, answer:

1. **Named location:** Is the defective code path named — file, function, line range — not just "the callback chain"?
2. **Class or instance:** Does the fix address a class of failure or a single instance? If instance, is the class named and scoped separately?
3. **Speculative language audit:** Search the fix description for "likely," "probably," "possibly." Each is an unresolved root cause. Flag it.
4. **Re-occurrence risk:** Under what conditions can this exact failure happen again? Does the fix prevent it or detect-and-repair it?

For every fix, two mandatory sentences:

```
Location sentence:  "The defect is in [file], [function], [line range]. It fails because [mechanism]."
                    If this cannot be written, root cause is not known — say so explicitly.

Class sentence:     "This instance belongs to the class of [failure pattern].
                    The class affects [N other code paths | this path only].
                    The fix covers [the class | this instance only]."
```

Symptom-repair disclosure (required when a fix patches rather than resolves):

```
"This is a symptom repair. The defect — [description] — remains.
Re-occurrence conditions: [when].
Re-occurrence is now detectable because: [how]."
```

---

### Section F: Behavioral Change Consumer Map

**Before adding an entry:** search Section B for an existing gap covering this finding. If found, append this section's checklist ID to that gap's Authority Sources. Do not create a new entry.

For every fix that changes schema, field semantics, or record counts:

| Fix | Field Changed | Pre-Deploy Semantics | Post-Deploy Semantics | Consumers Tested | Historical Records Affected |
|-----|--------------|---------------------|----------------------|-----------------|----------------------------|
|     |              |                     |                      |                 |                            |

"Consumers Tested" must distinguish write-path tests from read-path tests. These are not the same thing.

---

### Section G: Missed Baseline Windows

For every performance concern identified as a future audit item:

```
Concern:                 [description]
Natural baseline window: [first post-deploy execution; timestamp if known]
Window used:             yes | no
If no:                   State explicitly. State next available window
                         and what must be captured.
```

Deferred performance baselines that do not acknowledge the missed window imply the window is still open when it is not.

---

### Section H: Summary by Category

```
Structural:           [count] gaps — [one-line pattern description]
Verification:         [count] gaps — [one-line pattern description]
Operational clarity:  [count] gaps — [one-line pattern description]
Consumer impact:      [count] gaps — [one-line pattern description]
Performance:          [count] gaps — [one-line pattern description]
Root cause:           [count] gaps — [one-line pattern description]

Must-fix before report is operationally safe
(discharge criteria in Section I):
  [list P0 and P1 gap IDs]
```

---

### Section I: Discharge

A gap is discharged when ALL three are recorded:

```
1. Authority Owner:  [file / function / owner of the source of truth]
2. Source Change:    [what changed in the authority source]
3. Evidence:         [test ID, production verification, log reference]
   Confirmed by:     [reviewer name, date ISO8601]
```

**Discharge Authority Rules:**

```
STRUCTURAL gaps:  any reviewer may discharge
RUNTIME gaps:     discharger must have Runtime/Audit/Production in Evidence Scope
D-class gaps:     discharger must be a D-class reviewer
```

**A gap is NOT discharged by:**
- "Will fix later" without owner and date
- "Accepted risk" without operator sign-off on record
- "Looks good" or "Reviewer confirms" without authority/change/evidence triple

**Report is operationally safe when BOTH conditions hold:**
1. All P0/P1 gaps discharged per the above
2. Population Coverage Audit (Section C) has zero FAIL entries

Discharged P0/P1 gaps with an unresolved Population Coverage FAIL do not make a report operationally safe.

P2 and P3 gaps may remain open with a documented owner and a target date.

---

## Part 2 — Lessons

---

### Lesson L — P0 Risks Without Immediate Operator Instructions Are Not P0 Risks (2026-05-25)

**Principle:** A risk labeled P0 that tells an operator "this may resolve on its own" without a time bound, a verification endpoint, and a fallback action is functionally a risk note, not a mitigation. P0 means the operator must be able to act in the next [system-specific time bound]. If the report doesn't support that, the P0 label is decorative.

**What this means for future reports:**

Every P0 and P1 risk entry must include four elements before the report is closed:
1. The exact self-resolution mechanism, if any
2. The time bound in absolute terms — not relative ("if reading this more than [bound] post-restart, condition has resolved; if not, proceed to step 3")
3. The verification endpoint or command — exact, callable, no lookup required
4. The fallback action if the time bound passes without resolution

**Time Bound Derivation:** The 10-minute threshold in the origin example is derived from that system's 600-second orchestrator tick interval. Do not carry this threshold to a different system without verification. Derive the time bound for your system from its slowest self-resolving mechanism. If that mechanism is unknown, the time bound cannot be stated — and per this lesson, the P0 designation cannot be used until the bound is known and derivable.

**Origin:** SHA `5c19c1c` deploy report, Section 4 / Risk Matrix P0 item. The report named the risk but provided no time bound, no verification endpoint, and no fallback.

**Binding gate:** Section D of this framework. Enforced by: any reviewer assigning P0. P0 without a completed Section D entry = Lesson L violation.

**Where it binds:** Every post-deploy report P0 or P1 risk entry. Every condition described as "may persist until."

---

### Lesson M — "Global" Is a Claim That Requires a Census (2026-05-25)

**Principle:** The word "global" in a deploy report means the fix was verified across the full population of affected entities. If the verification used a sample, the claim is not global — it is "verified for N of M." Using "global" without census data misleads operators about which entities remain at risk.

**What this means for future reports:**

Every fix described as "global," "system-wide," "all," or "every" must be accompanied by:
1. The population size
2. The sample verified
3. The disposition of the unverified remainder: confirmed via idempotency guard, confirmed via log, or explicitly stated as "status unknown — residual risk"

Three population claim types that must be stated separately:
- **Write-path global:** applies to every future write; historical records are not covered
- **Sweep-global:** ran during a sweep of M entities, explicitly confirmed N; M − N need a stated disposition
- **Schema-global:** changes field semantics for all records; pre-existing records may have old semantics; state the count of stranded records

**Origin:** SHA `5c19c1c` deploy report. F4 described as "global" — sweep processed 15 shipments, 2 confirmed reconciled, 13 unaccounted. F3 described as "every DSK generation call going forward" — true for write path; all shipments with existing DSK files left with `customs_package_generated_at` absent.

**Binding gate:** Section C Population Coverage Audit of this framework. Enforced by: the PASS/FAIL criteria. Any "global" claim with a Section C FAIL = Lesson M violation.

**Where it binds:** Every post-deploy fix description using population-scope language.

---

### Lesson N — Fix Descriptions Must Name the Defect Location and Scope Its Class (2026-05-25)

**Principle:** A fix description that uses "likely," "probably," or "possibly" to describe the root cause has not identified the root cause. It has identified a hypothesis. Deploying a repair against a hypothesis is acceptable under time pressure; documenting a hypothesis as a root cause in the post-deploy report is not. These are different acts.

**What this means for future reports:**

For every fix, two mandatory sentences in the root-cause narrative:
1. **Location sentence:** "The defect is in `[file]`, `[function]`, [line range]. It fails because [specific mechanism]." If this cannot be written, root cause is not known — say so explicitly.
2. **Class sentence:** "This instance belongs to the class of [failure pattern]. The class affects [N other code paths / this path only]. The fix covers [the class / this instance only]."

Speculative language in the root-cause narrative is a documentation flag, not a style choice. Each instance is an open root-cause investigation. When a fix is a symptom repair, state it explicitly: "This is a symptom repair. The defect remains. Re-occurrence conditions: [when]. Re-occurrence is now detectable because: [how]."

**Origin:** SHA `5c19c1c` deploy report, F4 narrative: "likely due to a process restart or exception in the callback chain." The callback location was never named. The class — any queued operation with a post-send status callback — was not scoped.

**Binding gate:** Section E Root Cause Completeness Check, item R3 of this framework. Enforced by: the speculative language scan. Any unchallenged "likely," "probably," or "possibly" in a root-cause clause = Lesson N violation.

**Where it binds:** Every fix narrative. Every incident post-mortem. Any report section using the words "root cause."

---

## Part 3 — Diagnostic Checklist

---

### Routing — Read Before Starting Any Checklist Item

```
STRUCTURAL review (Documentation or Code only):
  Run G checks. Expected completion: 20–30 minutes.
  Mark review header: "STRUCTURAL REVIEW — D CHECKS NOT RUN."
  A Structural Review does not satisfy D-column requirements.
  Do not close P0/P1 gaps that require D verification without escalation.

RUNTIME or FULL review (any Runtime/Audit/Production evidence):
  Run G + D checks.
  D checks require a reviewer who has read the service code within 30 days.
  D cannot be substituted by inference, general knowledge, or reading the report.
```

**G label = who should perform the check.**
**G label ≠ check can be passed without system knowledge.**

Verifying a G check's *accuracy* (not just its presence) may itself be a D operation. Treat accuracy verification of a G check as D responsibility. When a G check requires domain knowledge to verify accuracy rather than presence, that verification step is a D check.

When any checklist item generates a gap, record the gap in Section B with this item's checklist ID in the Authority Sources field.

---

### Structural Integrity

| ID | Check | Class | Pass condition |
|----|-------|-------|----------------|
| S1 | Does every fix entry have: component, file, change, effect, scope, risk? | G | All six fields populated; none left as "TBD" or omitted |
| S2 | Is evidence presented before conclusions? | G | Fix effect claims follow from named code changes; they do not precede them |
| S3 | Is the Risk Matrix co-located with or immediately after the gap descriptions it prioritizes? | G | P0/P1 items reachable without scrolling past more than one unrelated section |
| S4 | Does the report separate "code change is global" from "verification is global"? | G | These appear as distinct claims, not merged into a single "global fix" assertion |
| S5 | Is there a negative-space section explicitly stating what was NOT verified? | G | Present and populated; not just "further work required" |
| S6 | Does the executive summary contain three cognitive loads or fewer? | G | Reader can state the three key facts without re-reading |

---

### Verification Rigor

| ID | Check | Class | Pass condition |
|----|-------|-------|----------------|
| V1 | For every "global" or "all" claim: is population size stated? | G | Explicit count or acknowledged unknown |
| V2 | For every "global" claim: is sample size stated separately from population size? | G | "Verified for N of M" present; sample ≠ population without census |
| V3 | For every "global" claim: is the disposition of the unverified remainder stated? | G | One of: idempotency-confirmed skip, log-confirmed outcome, or "status unknown — residual risk" |
| V4 | For write-path fixes: are historical records explicitly excluded from the global claim? | D | Report distinguishes "every future write" from "all existing records" |
| V5 | For sweep-based fixes: is the per-entity outcome enumerated, not just the aggregate? | D | Each entity in scope is confirmed reconciled, confirmed skipped, or flagged unknown |
| V6 | For pointer/key fixes: are pre-existing records with the old schema identified and counted? | D | Count of stranded records present; repair or backfill path stated |
| V7 | For deduplication fixes: is the derived-count field addressed separately from the array field? | D | Report states whether derived counts are consistent across pre/post records |

---

### Operational Clarity

| ID | Check | Class | Pass condition |
|----|-------|-------|----------------|
| O1 | Does every P0 risk have an immediate operator instruction? | G | Instruction is callable without additional lookup |
| O2 | Does every self-resolving condition have an explicit time bound? | G | Minimum and maximum stated in absolute terms, not relative |
| O3 | Does every self-resolving condition have a verification endpoint? | D | Exact URL, method, and response field to check are named |
| O4 | Does every self-resolving condition have a fallback action? | D | What the operator does if the time bound passes without resolution |
| O5 | Are SLA flag states addressed post-reconciliation? | D | Report confirms whether SLA overdue flags were cleared or require separate action |
| O6 | Does the report confirm the first automated cycle fired post-deploy? | D | Timestamp of first post-restart cycle recorded, or check explicitly deferred with "not yet confirmed" |

---

### Consumer-Side Impact

| ID | Check | Class | Pass condition |
|----|-------|-------|----------------|
| C1 | For every schema change: are downstream consumers enumerated? | G | List of consumers present; "unknown" stated as a gap, not omitted |
| C2 | For every schema change: are write-path tests distinguished from read-path tests? | G | Report states which test type was used; does not conflate them |
| C3 | For every behavioral change: are existing consumer assumptions about field semantics audited? | D | Any consumer asserting field absence or field count has been checked |
| C4 | For deduplication or count-affecting changes: is the derived-field impact explicitly addressed? | D | Report states whether count-derived fields are consistent across pre/post records or creates a named discontinuity |
| C5 | For new fields added to stored records: is there any consumer that asserts the field's absence? | D | Negative assertion check performed; "none found" acceptable if search was executed |

---

### Performance and Baselines

| ID | Check | Class | Pass condition |
|----|-------|-------|----------------|
| P1 | For every new per-entity compute pattern: is the first post-deploy execution identified as a baseline window? | G | "First execution was at [timestamp]" present or "baseline window not used" acknowledged |
| P2 | Was the baseline window used? If not, is that stated explicitly? | G | "Missed" is stated; not quietly deferred to future audit |
| P3 | For linear-scan patterns over growing data structures: is the scale threshold defined? | D | At what data structure size does the pattern become a cycle-level blocker? |
| P4 | For the first post-deploy sweep: are elapsed time, call count, and data structure size recorded? | D | These three values captured, not just "sweep completed successfully" |

---

### Root Cause Completeness

| ID | Check | Class | Pass condition |
|----|-------|-------|----------------|
| R1 | Does every fix narrative contain a location sentence (file, function, line range)? | G | Named location present; absence flagged as "root cause not fully identified" |
| R2 | Does every fix narrative contain a class sentence (instance vs. class, scope of class)? | G | Class is named; whether fix covers class or instance is stated |
| R3 | Does the fix narrative contain "likely," "probably," or "possibly" in the root-cause clause? | G | Each occurrence flagged as an open root-cause investigation |
| R4 | For symptom repairs: is the distinction between repair and root-cause resolution explicit? | G | "This is a symptom repair" appears; re-occurrence conditions stated |
| R5 | For callback or async failure modes: is the specific callback location named? | D | Function name present; "callback chain" or equivalent generic reference fails this check |
| R6 | For instance fixes: are other code paths sharing the same failure class enumerated? | D | List of same-class paths present, or "class not present elsewhere" stated after search |

---

## Single Enforcement Rule

**Reject any review missing the Reviewer Provenance block. No exceptions.**

That single rule forces compliance with everything downstream. A reviewer who skips Section D but filled in Reviewer Provenance has left an auditable record. A reviewer who never filled in Provenance has produced a document that cannot be audited. Reject on that basis, not on the substance of what they wrote.
