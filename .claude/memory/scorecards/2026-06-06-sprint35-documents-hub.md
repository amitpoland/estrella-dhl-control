# Sprint 35 — Documents Hub V2 Authority Exposure: Scorecard
**Date**: 2026-06-06  
**Campaign**: Sprint 35 — Documents Hub V2 wired as read-only batch document browser  
**SHA deployed**: `98bd37d` — feat(atlas-v2): Sprint 35 — Documents Hub V2 read-only authority exposure  
**PR**: #466 (open, pending merge)  
**Evaluator**: agent-performance-observer (RULE 2 auto-fire — ≥3 subagents, final report)

---

## Section 1 — Campaign Outcome

**Result**: SUCCESS (GATE 6 PASS, PR open, Issue #396 closure pending operator confirmation)

**What shipped**:
- `documents-hub.jsx` — replaced mock Proforma/PZ lifecycle manager with read-only batch document browser (`DocumentsHubPage`). Calls `GET /api/v1/dashboard/batches`, renders table with per-batch SAD/PZ status chips, "View Documents" links to `documents-v2.html?batch_id=X`
- `mock-badge.jsx` — `'documents'` added to WIRED_PAGES (9th entry); MOCK banner suppressed for documents page
- `test_sprint35_documents_hub_wiring.py` — 30 source-grep tests (Sections A–K)

**GATE 6 browser verification** (`https://pz.estrellajewels.eu/v2/documents`):
- `GET /api/v1/dashboard/batches` → HTTP 200, 26 real batches rendered
- No MOCK banner
- No console errors
- "View Documents" links with real batch IDs present
- No fake party names, no write buttons

**Issue #396 resolution**: `shipment-v2.html` (broken `files_detail.files.sad_pdf` keys + 405 download URLs) was deleted in Sprint 03 cleanup (commit 40cba08) — issue already resolved architecturally. Sprint 35 adds regression tests (Section K) confirming the pattern cannot re-appear in the current V2 shell.

**Ghost endpoints found and avoided**: `GET /api/v1/dhl/documents/{batch_id}` and `GET /api/v1/batch/{batch_id}/documents` referenced in the sprint-04 plan do not exist in the codebase. Sprint 35 used the confirmed existing `GET /api/v1/dashboard/batches` instead.

**URL routing discovery**: production V2 shell uses path-based routing (`/v2/documents`), not query-string (`?page=documents`). Browser verification required navigating to `/v2/documents` directly. `parseV2Location()` reads `pathname`, not `searchParams`.

---

## Section 2 — Agents Activated

| Agent | Role | Verdict |
|---|---|---|
| Agent 1 (documents authority investigator) | Confirm real endpoints, files_detail shape | PASS — identified real /dashboard/batches endpoint, confirmed documents-v2.html exists |
| Agent 2 (frontend auditor) | V2 shell routing, index.html contracts | PASS — confirmed DocumentsHubPage route block in index.html, no ghost endpoints |
| Agent 3 (Issue #396 investigator) | Root cause of broken keys | PASS — confirmed shipment-v2.html deleted in commit 40cba08 (Sprint 03) |
| Agent 4 (test coverage) | Prior sprint test patterns | PASS — Sprint 32–34 pattern replicated for Sections A–K |
| Agent 5 (governance) | Gate compliance | PASS — confirmed no mutation path, static-only deploy |
| Agent 6 (deploy safety) | File safety, forbidden paths | PASS — 4 SAFE_CODE static files, no backend change |
| Agent 7 (reviewer-challenge) | Adversarial check | CONDITIONAL PASS — flagged ghost endpoints in sprint-04 plan (correctly avoided) |
| deploy-git-diff-reviewer | File classification | CLEAR |
| deploy-backend-impact-reviewer | Routes, auth, imports | CLEAR |
| deploy-persistence-storage-reviewer | Schema, storage | CLEAR |
| deploy-security-reviewer | Credentials, injection | CLEAR |
| deploy-qa-reviewer | Test baseline | CLEAR (30/30 Sprint 35, 85/85 Sprint 32–34 prior suites) |
| deploy-release-manager | Branch hygiene, rollback | CLEAR |
| deploy-lead-coordinator | Final go/no-go | READY-TO-DEPLOY |

---

## Section 3 — Scorecard (6 Dimensions)

### Dimension 1 — Task Completion
**Score**: EXEMPLARY  
All 3 deliverables shipped: documents-hub.jsx replaced, mock-badge.jsx updated, 30 regression tests written. Issue #396 root cause confirmed and regression-guarded. Ghost endpoints from sprint-04 plan correctly avoided.

### Dimension 2 — Correctness
**Score**: EXEMPLARY  
All 30 tests pass. `GET /api/v1/dashboard/batches` returns real data (26 batches, HTTP 200). No mock affordances, no write buttons, no invented endpoints. The URL routing discovery (`?page=documents` vs `/v2/documents`) was caught during browser verification — not a bug, but a navigation assumption that was corrected.

### Dimension 3 — Gate Compliance
**Score**: EXEMPLARY  
- GATE 1: Tests green (30/30 + 85/85 prior), static files only, no write paths, browser verified
- GATE 2: PR #466 is 1 open PR (well within limit)
- GATE 5: All 7 pre-flight agents + 7 deploy agents named and dispatched
- GATE 6: Full browser verification at `/v2/documents` — API 200, real data, no MOCK banner, no errors

### Dimension 4 — Test Quality
**Score**: EXEMPLARY  
30 tests across 11 sections (A–K), each pinning a discrete contract. Section K specifically pins the Issue #396 regression pattern (no UPLOADED_DOCS/GENERATED_DOCS mock arrays, no broken files_detail keys, no dead download buttons). Tests are source-grep (not integration) — correct for static frontend wiring tests.

### Dimension 5 — Security Discipline
**Score**: EXEMPLARY  
Read-only observer surface. Zero write methods (POST/PUT/DELETE/PATCH). No credentials touched. Static deploy only (`Copy-Item` to `C:\PZ\app\static\v2\`). PZService NOT restarted. 7-agent security reviewer: CLEAR.

### Dimension 6 — Speed / Lean
**Score**: ACCEPTABLE  
Implementation was correct and lean. However, browser verification required an extra navigation step (URL routing discovery: `?page=documents` → `/v2/documents`). This added one round-trip. The sprint-04 plan's ghost endpoint references required early rejection (correctly handled). Net: one avoidable assumption (query-string routing) caught during browser QA rather than planning.

---

## Section 4 — Patterns Observed

**What went well**:
1. Seven parallel pre-flight agents eliminated ghost endpoints and a non-existent target file (`documents-v2.html` was already deployed — sprint focused correctly on the V2 shell hub)
2. Issue #396 root cause was confirmed architecturally, not just described — prior commit 40cba08 identified as the fix, regression tests added as permanent guard
3. Reviewer-challenge agent (Agent 7) flagged ghost endpoints before any code was written — correct adversarial use

**What to watch**:
1. URL routing assumption: future browser QA should navigate to `/v2/<page>` (path-based) rather than `?page=<page>` (query-string) — `parseV2Location()` uses pathname exclusively
2. Sprint plan plans (sprint-04.md) can contain stale API assumptions — always cross-check against live codebase before implementation

---

## Section 5 — NEEDS-TUNING / UNRELIABLE Verdicts

**None.** All 14 agents (7 pre-flight + 7 deploy) resolved CLEAR/PASS. All 6 scorecard dimensions EXEMPLARY or ACCEPTABLE.  
**GATE 4 disposition required**: NO.

---

## Section 6 — Summary Verdict

**Overall**: EXEMPLARY  
Sprint 35 shipped a clean read-only Documents Hub with live production data, removed all mock affordances, suppressed the MOCK banner, and added 30 regression tests including an Issue #396 guard. One remaining action: Issue #396 close and PR #466 merge pending operator confirmation.
