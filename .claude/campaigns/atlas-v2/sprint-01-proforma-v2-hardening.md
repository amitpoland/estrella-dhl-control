# Sprint 01 — Proforma V2 Hardening

**Campaign:** Atlas-V2  
**Sprint:** 01 of 13  
**Branch:** `atlas-v2/sprint-01-proforma-hardening`  
**Base:** `origin/main` (after PR #262 merges)  
**Dependency:** PR #262 (`fix/proforma-v2-operator-header-and-client-display`) must be MERGED before firing this sprint  
**New file:** none — hardens existing `service/app/static/proforma-v2.html`

---

## Pre-flight (run before pasting the prompt)

```bash
gh pr view 262 --json state -q .state   # must print "MERGED"
make verify                              # must print 160/160
cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q  # must print 44 passed
git log --oneline origin/main -3         # confirm PR #262 SHA is in history
```

---

## Authority Boundary

```
OWNS:  draft rendering, client selector, readiness gate display,
       approve/re-open/cancel draft (with modal confirmation),
       reset-from-sales-packing, service charges display,
       customer authority card, product mapping rows,
       remarks editor (explicit Save button), DevBypassBanner
NEVER: DHL API, warehouse scan, customs calculation, PZ creation,
       wFirma write flags, invoice creation, fiscal gate modification
```

---

## Known gaps to close (from C27 + PR #262 context)

1. **Readiness gate** — `ProformaReadinessGate` must render `blocking_reasons` (red) and `export_blockers` (amber) from `/api/v1/dashboard/batches/{batch_id}/proforma-readiness`; empty = green chip "Ready to Issue"
2. **Customer authority card** — `CustomerAuthorityCard` must show `Matched` / `No mapping` badge with `data-testid="customer-authority-card"` and a "Save Customer Mapping" Btn (explicit click only)
3. **Product mapping rows** — `ProductAuthorityRow` per draft line: show `StatusDot` (ok/warn) + wFirma product name if matched
4. **Inline line edit** — `DraftLineRow` inline edit: PATCH `/api/v1/proforma/draft/{id}/lines/{line_id}` on "Save Line" click; no auto-save on blur
5. **Toast feedback** — every write action (approve, cancel, save line, reset) shows `Toast` with success/error
6. **Empty state** — `EmptyState` component when no drafts exist for the selected client
7. **data-testid completeness** — every interactive element and panel root has a `data-testid` per `frontend-design.md` §8

---

## Mandatory Agents (activate in this order)

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Route task, anti-escalation |
| 2 | `gap-detection` | Find missing testids, broken states, unconnected buttons |
| 3 | `reviewer-challenge` | Attack any plan that touches V1 files or adds duplicate renderers |
| 4 | `frontend-ui` | Implement gaps (with `frontend-design.md` override) |
| 5 | `frontend-flow-reviewer` | Review implementation for broken flow |
| 6 | `testing-verification` | Write missing tests |
| 7 | `test-coverage-reviewer` | Review test quality |
| 8 | `gap-hunter` | Cross-phase contradictions |
| 9 | `browser-verifier` | Real browser: open page, click every button, check console |
| 10 | `integration-boundary` | Verify API calls are wired (not fake) |
| 11 | `git-workflow` | Commit + push |
| 12 | `pr-author` | Open PR |

---

## Test Baseline (must hold)

```bash
make verify                 # 160/160
cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q  # 44/44
cd service && python3 -m pytest tests/test_carrier_*.py -q             # 366/366
```

Sprint adds: any new `data-testid` assertions via playwright or DOM-grep tests.

---

## Acceptance Criteria

1. Page loads at `https://pz.estrellajewels.eu/dashboard/proforma-v2.html?batch_id=<valid>&client=<valid>` — no console errors
2. Readiness gate renders with correct red/amber/green state from API
3. Draft line table renders; inline edit fires PATCH; "Save Line" toast appears
4. "Approve Proforma" button enabled only when `draft_state = 'draft'`; fires POST; toast confirms
5. "Cancel Draft" button opens modal; requires reason text; fires POST on confirm
6. Customer authority card shows match status; "Save Customer Mapping" button writes on click
7. Product mapping rows show `StatusDot` per line — ok (matched) or warn (unmatched)
8. DevBypassBanner visible when bypass active
9. All interactive elements have `data-testid`; `document.querySelector('[data-testid="draft-state-chip"]')` returns element
10. No 4xx on happy path; auth error → `SessionBanner`; network error → `SessionBanner`
11. Rollback: remove `proforma-v2.html` from `C:\PZ\app\static\`; no service restart needed

---

## `/run` Prompt — paste this in a fresh Claude Code session

```
/run

Campaign: Atlas-V2 | Sprint 01 — Proforma V2 Hardening
Branch: atlas-v2/sprint-01-proforma-hardening (create from origin/main after PR #262 merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html — follow its CDN load order and IIFE structure exactly
5. Shared layer: dashboard-shared.js (window.EstrellaShared), pz-api.js (window.PzApi), pz-state.js (window.PzState), pz-components.js (window.PzComponents)
6. CSS: CSS custom properties only (--bg, --text, --badge-*, --accent). Zero hardcoded hex.

TASK:
Harden the existing service/app/static/proforma-v2.html page. This page shipped with PR #249 and received operator-header fixes in PR #262. Now close all remaining gaps:

Gaps to close (inspect the file first — do not assume):
1. Readiness gate — ProformaReadinessGate must render blocking_reasons (red GateBlock) and export_blockers (amber GateBlock) from GET /api/v1/dashboard/batches/{batch_id}/proforma-readiness; empty both = green Badge "Ready to Issue" with data-testid="readiness-ready-chip"
2. Customer authority card — CustomerAuthorityCard must show Matched/No mapping Badge + "Save Customer Mapping" Btn (explicit click, data-testid="btn-save-customer-mapping"); no auto-save
3. Product mapping rows — ProductAuthorityRow per draft line: StatusDot (ok=matched, warn=unmatched) + wFirma product name
4. Inline line edit — DraftLineRow PATCH fires on "Save Line" click only; toast confirms; no save-on-blur
5. Toast feedback — every write action emits Toast(success/error)
6. EmptyState — when no drafts for selected client, show EmptyState(state="empty", message="No drafts for this client.")
7. data-testid completeness — every panel root, button, and status chip has a data-testid per frontend-design.md §8

AUTHORITY BOUNDARY (enforced by reviewer-challenge):
OWNS: draft rendering, readiness gate, approve/cancel/re-open/reset, customer mapping display, product mapping display, remarks editor
NEVER: DHL, warehouse, customs calc, PZ creation, wFirma write flags, fiscal gate change

MANDATORY AGENT SEQUENCE:
1. gap-detection — find all missing data-testids, broken states, unconnected buttons in proforma-v2.html
2. reviewer-challenge — attack any plan that touches shipment-detail.html or adds a duplicate renderer
3. frontend-ui — implement gaps (frontend-design.md override in effect)
4. frontend-flow-reviewer — review implementation
5. testing-verification — write tests for any new testids or flows
6. test-coverage-reviewer — review tests
7. gap-hunter — cross-phase checks
8. browser-verifier — open the actual page, click every button, check DevTools console and network tab
9. integration-boundary — verify every API call is real (not fake)
10. git-workflow — commit service/app/static/proforma-v2.html + any shared layer changes
11. pr-author — open PR against main, title: "feat(proforma-v2): Sprint 01 hardening — testids, readiness gate, customer card"

TEST BASELINE — must hold before PR opens:
- make verify → 160/160
- cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q → 44/44 passed
- cd service && python3 -m pytest tests/test_carrier_*.py -q → 366/366 passed

End with /deploy after PR merges.
```
