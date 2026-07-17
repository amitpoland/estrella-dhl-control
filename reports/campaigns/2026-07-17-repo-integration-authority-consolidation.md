# Repository Integration and Authority Consolidation Campaign — /context + /plan

Date: 2026-07-17 · Session: xenodochial-wiles-6f88af (worktree) · Framework: EJ Engineering OS v1.3 (docs-only, subordinate to CLAUDE.md GATES 1–6)
Status: /context COMPLETE · /plan COMPLETE · Phase A BUILT + REVIEWED (4 verdicts, all
mitigations applied) on `integration/convert-persist-reconcile-authority` @ local —
PUSH + PR-OPEN blocked by session push permission (operator action; PR body ready at
`reports/campaigns/2026-07-17-phase-a-pr-body.md`)

---

## Task

Consolidate all completed parallel work into a safe, ordered integration plan, resolve
overlapping authorities before merge, prioritize the confirmed post-invoice
draft-persistence defect, and prevent duplicate dictionary, reconciliation,
payment-provenance, and test-infrastructure implementations.

## Scope

As stated in the operator campaign brief (2026-07-17). All named branches, PRs, commits
and worktrees verified against the live repository — nothing assumed current.

## Current State — verified repository inventory (/context)

**origin/main = `d5a453fd`** (PR #930 merged 2026-07-16; local `main` in C:\PZ-main matches).
The campaign brief's "current main" references were one merge behind — every probe below
was re-run against `d5a453fd`.

### Open PRs (4)

| PR | Branch | Head | Class | State vs main |
|---|---|---|---|---|
| #932 | claude/xenodochial-wiles-6f88af | a04361b1 | implementation (dictionary refresh + status) | MERGEABLE |
| #931 | test/927-repoint-convert-flow-pins | b09c4ede | test-only | MERGEABLE, single commit, baseline row + coverage move in same commit ✓ |
| #926 | governance/worktree-consolidation | — | governance | MERGEABLE, operator priority after #924 |
| #924 | governance/stage1-scorecard-salvage | 370f5303 | governance | MERGEABLE, operator priority first |

GATE 2: 1 implementation PR open (#932). Phase A adds a 2nd — within the limit of 3.
The later dictionary-UI / payment-provenance / portability PRs must be SEQUENCED after
merges, not stacked (queue mode noted below).

### Branch / worktree census (named in Scope, all verified)

| Branch @ tip | Worktree | Committed delta vs main | Dirty files | Verdict |
|---|---|---|---|---|
| claude/competent-lehmann-d564b3 @ e91e89c4 | .claude/worktrees/competent-lehmann… | 3 commits (8d44c9f2, 3081ffc0, e91e89c4), based ON d5a453fd (behind 0) | clean | ABSORB (Phase A) |
| claude/admiring-saha-dc6995 @ d3c016d3 | …/admiring-saha… | 1 commit, based on b195ae18 (behind 1); merge-tree vs d5a453fd = CLEAN | clean | ABSORB (Phase A) |
| claude/practical-jepsen-cda6ba @ d5a453fd | …/practical-jepsen… | 0 commits | UNCOMMITTED: routes_customer_master.py, main.py, wfirma_dictionary_cache.py, master-page.jsx, pz-api.js, new test_dictionaries_status_endpoint.py | SPLIT: frontend salvage / backend DROP (duplicates PR #932) |
| claude/goofy-benz-e8b88f @ d5a453fd | …/goofy-benz… | 0 commits | UNCOMMITTED: wfirma_dictionary_cache.py (+snapshot/lock model), test_series_cache_persistence.py (+216) | PORT onto PR #932 (conflicts with #932's rewrite — manual port) |
| claude/hopeful-dubinsky-ce2921 @ d5a453fd | …/hopeful-dubinsky… | 0 commits | UNCOMMITTED: test_master_bootstrap_normalization.py (strict utf-8 + startswith tools-exclusion + posix normalization) | CANONICAL portability patch |
| claude/friendly-blackwell-b1664e @ d5a453fd | …/friendly-blackwell… | 0 commits | UNCOMMITTED: same file, `errors="replace"` variant | RETIRE (duplicate; lenient decode weakens the audit pin) |
| claude/compassionate-moser-2125c8 @ d5a453fd | …/compassionate-moser… | 0 commits | UNCOMMITTED: payload_disclosure.py, proforma-detail.jsx, test_convert_modal_truth.py, test_phase9_payload_disclosure.py | PAYMENT PROVENANCE — verified CORRECT (below); commit after #931 merges |
| claude/amazing-feynman-affb97 @ a853503b | …/amazing-feynman… | 0 ahead, behind 2 | clean | EMPTY — delete worktree + branch |
| fix/customer-clean-invoice-description @ 92f248a5 | C:\PZ-wt-descprev | superseded (squash-merged as #930 → d5a453fd) | clean | RETIRE worktree + branch |
| fix/proforma-multidraft-transport-docs @ 14d629f5 | C:\PZ-pr7 | M1 campaign, registry state=FROZEN | clean | DO NOT TOUCH (gated on #924 → #926 → state flip) |
| governance/stage1-scorecard-salvage @ 370f5303 | C:\PZ-stage1 | PR #924 | clean | operator merge |
| test/927-repoint-convert-flow-pins @ b09c4ede | …/issue-927… (locked) | PR #931 | clean | operator merge FIRST |

Remote branches: only `claude/xenodochial-wiles-6f88af` (PR #932) among the named work.
lehmann/saha commits are **local-only** — integration must push them (cherry-pick preserves
authorship provenance).

Live-session caution: the three GATE-4 chips (task_c3cc9142 cp1252, task_92e1344b lock
consistency, task_850a2dd5 UI panel) were started by the operator in separate local
sessions and map to hopeful-dubinsky/friendly-blackwell, goofy-benz, and practical-jepsen
respectively. Their worktrees are in-flight; this campaign reads them but does not write
into them. Phase B/C absorption waits for their completion notifications (or supersedes
them explicitly).

### Dirty/untracked in C:\PZ-verify root

`reports/campaigns/` (WDT-fill evidence), `reports/deploy/2026-07-16-pr925-*`,
`reports/inspection/2026-07-16-vat-mode-anomaly-{anthropic-pbc,impact-gallery}.md`
(Finance memos — Phase E inputs), `.claude/memory/TASK_STATE.md` (local-only), and stray
`query` / `start` files (operator command droppings containing "PZService" — recommend
deletion). C:\PZ-main has untracked `.claude/state/` (campaign registry seed — belongs to
PR #926 flow; leave).

### Verified completed outcomes (unchanged by this campaign)

WDT 145/2026 exists and is correct (OFF-LIMITS). Tier-1 WDT series 17/17. PRs #925, #928,
#929, #930 merged and deployed. Duplicate invoice creation already blocked.

---

## Root Cause

(Per campaign brief, confirmed by inventory.) Valid fixes accumulated in parallel
worktrees without a single integration authority. Confirmed instances:

1. TWO local-reconciliation designs: lehmann `POST /draft/{draft_id}/reconcile-conversion-link`
   (event `conversion_link_reconciled`, privileged API-key auth) vs saha
   `GET /invoice-links/split-brain` + `POST /invoice-links/{proforma_id}/reconcile`
   (event `invoice_link_reconciled` via new `audit_persist.py`, confirm-token, read-only
   wFirma re-verify, V2 panel).
2. Dictionary status: practical-jepsen re-implemented PR #932's backend
   (`_REFRESH_RUN_STATE` + `get_refresh_status()` + `GET /dictionaries/status` +
   `trigger=` plumbing) independently, plus goofy-benz's lock model is based on pre-#932
   code and conflicts with #932's rewrite of the same module.
3. Identical test-portability fix on hopeful-dubinsky and friendly-blackwell
   (same file, divergent decode strategy).
4. Payment-days provenance risk: RESOLVED IN CODE — compassionate-moser computes a
   dedicated `payment_resolved.days_source` (draft_saved > customer_master > not_set,
   CM `0` = unset sentinel → display "Not set") and binds the days label to `days_source`,
   the method label to `source` (separate testids `convert-payment-method-source` /
   `convert-payment-days-source`; `test_days_source_reads_days_source_not_method_source`
   pins it). Resolver precedence untouched (display-only, stated in code).

The confirmed production defect (draft 67 fully drifted, draft 52 partially drifted) is
fixed on lehmann 8d44c9f2: route-level use of `_build_convert_candidate`-scoped locals in
execute step 7b + swallowed non-fatal exception. **This fix is NOT on main and NOT in
production** — it is the highest-priority integration payload.

---

## Architectural Goal

As stated in the campaign brief (forward chain: remote create → identity capture →
verify-after-create → issued link → canonical draft projection → visible converted state;
failure chain: preserve identity → classify split-brain → read-only remote verify →
operator-confirmed local reconcile → one audited repair authority → never recreate/delete
remote). Dictionary and payment end-states as stated.

---

## Authority-overlap matrix (/plan)

### A. e91e89c4 (lehmann) × d3c016d3 (saha)

| Dimension | lehmann | saha | Canonical owner |
|---|---|---|---|
| Shared files | routes_proforma.py, proforma_invoice_link_db.py, conversion_persistence.py(WAL) | routes_proforma.py, proforma_invoice_link_db.py, + audit_persist.py (new), + V2 panel | — |
| Forward persistence (step 7b fix, `draft_persisted` disclosure) | ✓ (the production-defect fix) | partial (identity capture + audit refactor of same function, different hunks) | **lehmann** |
| Remote identity capture before local finalize | — | ✓ `record_invoice_identity` | **saha** |
| Verify-after-create | — | ✓ `_verify_created_invoice` | **saha** |
| Split-brain detection (read-only) | — | ✓ `GET /invoice-links/split-brain` (confirmed/suspected classification) | **saha** |
| Reconcile route | `POST /draft/{id}/reconcile-conversion-link` | `POST /invoice-links/{proforma_id}/reconcile` (confirm token, read-only wFirma re-verify, refusal paths) | **saha** (matches campaign end-state) — lehmann's route **dropped** |
| Reconcile auth | `require_api_key_privileged` (blocks read-only roles) | session-user optional + confirm token | **graft lehmann's privileged guard onto saha's route** |
| Audit event | `conversion_link_reconciled` | `invoice_link_reconciled` via `audit_persist.record_invoice_link_reconciled` | **saha** (one event name, one writer) |
| Persistence writer | `conversion_persistence.persist_invoice_to_draft` (+WAL/busy_timeout) | same function (reconcile path) | shared — keep lehmann's WAL hardening |
| Tests | test_convert_persist_scope_and_reconcile.py (397), test_audit_proforma_converted.py (+60) | test_invoice_link_reconcile.py (645) | keep both; retarget lehmann's route-specific tests at the canonical route |
| Textual conflicts | merge-tree(main×lehmann)=CLEAN, (main×saha)=CLEAN, (lehmann×saha)=CLEAN | | integrable as ordered commits + one consolidation commit |

Integration = ordered cherry-picks (8d44c9f2 → 3081ffc0 → e91e89c4 → d3c016d3) + one
consolidation commit that: deletes lehmann's duplicate reconcile route + its audit event,
retargets its tests, grafts privileged auth onto the canonical route, verifies exactly one
forward-persistence call and one disclosure field.

### B. PR #932 × practical-jepsen × goofy-benz (dictionary)

| Dimension | PR #932 (a04361b1) | practical-jepsen (uncommitted) | goofy-benz (uncommitted) | Canonical |
|---|---|---|---|---|
| Run-state store | `_REFRESH_STATUS` + `get_refresh_status()` | duplicate `_REFRESH_RUN_STATE` + `get_refresh_status()` | — | **#932** (one tracker) |
| Status route | `GET /dictionaries/status` (canonical shape + extras) | duplicate route, same path/shape | — | **#932** |
| Scheduler refresh | ✓ Step 0 in wfirma_webhook_scheduler, cooldown, flag-gated | — | — | **#932** |
| Last-known-good semantics | ✓ (error preserves; unavailable replaces) | — | — | **#932** |
| Trigger vocabulary | startup / scheduler / **api** | startup / **operator** | — | campaign mandate: startup/scheduler/**operator** → rename `api`→`operator` on #932 branch |
| Lock-consistent snapshots | single-lock write path only | — | ✓ `_snapshot_live_cache` + `_compute_stale` + snapshot in `_persist_cache_to_disk` / `get_dictionaries` (+216 test lines) | **port onto #932** (based on pre-#932 code — manual port required; it also resurrects `seen_inv/seen_pro` dead vars #932 removed — drop those) |
| V2 UI status panel | — (GATE-4 chip) | ✓ master-page.jsx (+118) + pz-api.js transport (+4) | — | **jepsen frontend salvaged** into a UI-only PR |
| Tests | 40-case suite | test_dictionaries_status_endpoint.py (duplicate of #932 coverage — DROP; salvage any unique case into #932 suite) | test_series_cache_persistence.py +216 (port) | — |

### C. hopeful-dubinsky × friendly-blackwell (portability)

Same file (`test_master_bootstrap_normalization.py`), same intent. hopeful: strict
`encoding="utf-8"`, `startswith("app/tools/")` exclusion, posix-normalized allowlist.
friendly: `encoding="utf-8", errors="replace"`, upfront list/set normalization.
**Canonical: hopeful-dubinsky** — a source-pin audit must fail loudly on undecodable
bytes; `errors="replace"` can silently mask corrupted assertions. friendly-blackwell:
RETIRE (no commits — delete branch + worktree once its session is idle).

### D. Payment provenance (compassionate-moser) — inspection verdict: CORRECT

- days label ← `payment_resolved.days_source` ✓ (testid `convert-payment-days-source`)
- method label ← `payment_resolved.source` ✓ (separate testid; `test_no_overloaded_single_source_label`)
- CM `payment_terms_days == 0` → "Not set", never prefilled (`customer_default_days_display`, display-only; resolver `is not None` untouched, governed by separate ruling) ✓
- override → "this-invoice-only" label + conditional divergence warning + saved draft value visible + Commercial Terms deeplink (all pinned by tests) ✓
- business facts preserved: KENNY CM days unset/0; draft 67 saved=90; WDT 145/2026 7-day execution override intentional; no correction ✓
- Conflict note: it appends to `test_convert_modal_truth.py`, which PR #931 rewrites →
  **commit only after #931 merges**, rebase, then PR.

---

## Governance Rules

Per campaign brief §1–15, subordinate to CLAUDE.md GATES 1–6. Off-limits list honored:
no wFirma writes, no WDT 145/2026 access, no production DB edits, no direct C:\PZ edits,
no VAT-mode auto-correction, no Anthropic duplicate auto-consolidation, no second
status/reconciliation/payment/portability implementation.

---

## Implementation Plan + Integration sequence (validated against actual base)

1. **PR #931** — current (head=local tip, MERGEABLE vs d5a453fd, single commit) →
   RECOMMEND OPERATOR MERGE FIRST.
2. **#924 → #926** — governance queue, standing operator priority (unchanged).
3. **Phase A integration PR** (this campaign builds it): branch
   `integration/convert-persist-reconcile-authority` off d5a453fd; cherry-picks
   8d44c9f2, 3081ffc0, e91e89c4, d3c016d3 (provenance preserved) + one consolidation
   commit (single reconcile authority per matrix A) + required tests + reviewer gate.
   OPERATOR: merge, deploy (7-agent gate), then Phase-9 production repair of drafts 67/52
   through the canonical route (explicit approval, read-only verify first).
4. **PR #932** + trigger-vocab rename (`api`→`operator`) + goofy-benz lock port (after
   chip session completes) → operator merge.
5. **Dictionary V2 UI PR** — jepsen frontend salvage only (after #932 merges; GATE 2 queue).
6. **Payment-provenance PR** — moser (after #931 merges; rebase test file).
7. **Test-portability PR** — hopeful-dubinsky patch (may fold into a governance PR).

## Safety Gates

Explicit operator approval required before: merging/deploying the Phase A package;
reconciling draft 67; reconciling draft 52; any Impact Gallery / Anthropic vat_mode
change; Anthropic duplicate-row consolidation; CM payment-default changes. No approval
needed for the read-only inspection and overlap analysis above, nor for building the
integration branch + PR (GATE 1 applies at PR-open).

## Unresolved Finance decisions (Phase E — no data modified)

1. **Impact Gallery** — PL customer, valid NIP, vat_mode 228 (WDT) but likely domestic
   23%; historical intent unavailable. Memo:
   `reports/inspection/2026-07-16-vat-mode-anomaly-impact-gallery.md`. Finance ruling
   needed: reclassify vat_mode → domestic, or attest WDT legitimacy.
2. **Anthropic PBC** — US customer, vat_mode 228 likely copied from EU template, 4 active
   duplicate CM rows. Memo:
   `reports/inspection/2026-07-16-vat-mode-anomaly-anthropic-pbc.md`. Finance ruling
   needed: export treatment + which CM row is authoritative (duplicate consolidation is
   operator/Finance-gated).

## Branch disposition ledger (GATE 3 / GATE 4)

| Branch | Disposition |
|---|---|
| claude/competent-lehmann-d564b3 | ABSORBED into Phase A PR → tag `archive/claude-competent-lehmann-d564b3-2026-07-17` after merge → ARCHIVED |
| claude/admiring-saha-dc6995 | ABSORBED into Phase A PR → archive tag after merge → ARCHIVED |
| claude/practical-jepsen-cda6ba | Frontend salvaged into UI PR; backend REJECTED (duplicate of #932, reasoning above); retire after salvage |
| claude/goofy-benz-e8b88f | Ported onto PR #932; retire after port |
| claude/hopeful-dubinsky-ce2921 | CANONICAL portability patch → PR; retire after |
| claude/friendly-blackwell-b1664e | REJECTED duplicate (lenient decode weakens pin); delete branch+worktree (0 commits — nothing to tag) |
| claude/amazing-feynman-affb97 | EMPTY (0 ahead, clean); delete branch+worktree |
| fix/customer-clean-invoice-description | Superseded by merged #930; delete worktree C:\PZ-wt-descprev + branch |
| fix/proforma-multidraft-transport-docs | FROZEN (M1 registry) — untouched by this campaign |
| test/927-repoint-convert-flow-pins | PR #931 — merge, then worktree auto-retires |
| governance/stage1-scorecard-salvage | PR #924 — operator merge |

## Phase A execution record (2026-07-17)

Branch `integration/convert-persist-reconcile-authority` (local, off d5a453fd):
`3973b01f → 8ca70366 → ea897a9b` (lehmann cherry-picks) → `1032c71b` (saha cherry-pick,
all clean) → `e54ee576` (consolidation: duplicate route deleted, canonical POST with
issued/split-brain branches, stale_draft_projection detection, one audit event,
privileged auth) → `3a895bdb` (GATE-1 mitigations: _auth_write on both convert-execute
routes, draft_persisted disclosure + retryable errors in split-brain branch, scan
truncation disclosure, numeric-id guard, conflict pre-check, BOM-safe audit read,
unrestored_fields disclosure, +11 behavioral tests, S3→AST pin).

GATE 1: backend-safety PASS-W-F, reviewer-challenge PASS-W-M, security PASS-W-F,
test-coverage adopted — every HIGH/MEDIUM fixed inline; two REJECTED-with-reasoning
(preflight-except hardening; behavioral role-403 test) recorded in the PR body.
Evidence: affected 18 suites 483 passed / 32 failed with ALL 32 proven identical on
clean origin/main (29 unregistered pre-existing → GATE-4 chip task_d5609595; 2 RBAC
drift task_6a5ee6b3; 1 registered #927). Root PZ regression green; smoke 63 green.

GATE-4 follow-ups filed: task_d5609595 (pre-existing failure cluster);
draft_id-on-link-row enrichment (reviewer-challenge LOW-1) — record in next session or
fold into the production-repair session.

## Next Exact Step

OPERATOR: (1) grant push permission or run
`git push -u origin integration/convert-persist-reconcile-authority` from the worktree,
then `gh pr create --title "fix(proforma): post-conversion persistence + one canonical
reconcile authority (draft 67/52)" --body-file reports/campaigns/2026-07-17-phase-a-pr-body.md`;
(2) merge order per this report: #931 → #924 → #926 → Phase A PR → #932(+lock port +
trigger-vocab rename to startup/scheduler/operator) → dictionary UI PR → payment-provenance
PR → portability PR; (3) after Phase A deploy: operator-approved draft 67 + 52 repair via
`GET /invoice-links/split-brain` (expect both as stale_draft_projection) then
`POST /invoice-links/{proforma_id}/reconcile` each + noop re-run proof — no wFirma write.
