# Sprint 12 — Auth V2

**Campaign:** Atlas-V2  
**Sprint:** 12 of 13  
**Branch:** `atlas-v2/sprint-12-auth-v2`  
**Dependency:** Sprint 11 merged  
**Files:** `service/app/static/login.html`, `service/app/static/signup.html`, `service/app/static/forgot-password.html`  
**Note:** These are NOT new files — they are hardening existing auth pages to match V2 design standard

---

## Authority Boundary

```
OWNS:  login form (POST /api/v1/auth/login), signup form (POST /api/v1/auth/signup),
       forgot-password form (POST /api/v1/auth/forgot-password),
       session error feedback, redirect-after-login to correct landing page
NEVER: any business domain data, admin operations, wFirma, DHL,
       proforma, PZ, inventory
```

---

## Page Purpose

Bring the three auth pages into design-token compliance. They should use the same CSS
custom properties (`--bg`, `--card`, `--accent`) as all V2 pages. They should use
`Btn` from `dashboard-shared.js` for form submission. They should show proper loading
states and error feedback.

This is not a rewrite — it is a design-token alignment pass + accessibility hardening.

**Important:** Auth pages DO load `dashboard-shared.js` for `Btn` only. They do NOT
load `pz-api.js`, `pz-state.js`, or `pz-components.js` — those are business-domain layers
that auth pages have no business touching.

---

## What Changes Per Page

### `login.html`
- Replace bare `<button>` with `Btn variant="primary"`, `data-testid="btn-login"`
- Add loading state: `disabled={loading}` during POST
- Error feedback: inline error banner (not just `alert()`)
- CSS tokens: replace any hardcoded colors with `--bg`, `--card`, `--accent`
- Post-login redirect: land on `/dashboard/inbox-v2.html` (clearance inbox — operator entry point)

### `signup.html`
- Same Btn and loading pattern
- Password confirmation field error shown inline
- `data-testid` on all fields and buttons

### `forgot-password.html`
- Same pattern
- Success state: "Check your email" message replaces form

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `gap-detection` | Find hardcoded colors, bare buttons, missing testids |
| 3 | `reviewer-challenge` | Confirm scope is auth-only — no business logic bleeds in |
| 4 | `frontend-ui` | Align three pages to V2 design tokens |
| 5 | `frontend-flow-reviewer` | Review for broken form flows |
| 6 | `testing-verification` | Tests: testid presence, loading state, error feedback |
| 7 | `test-coverage-reviewer` | Review |
| 8 | `gap-hunter` | Cross-page contradictions |
| 9 | `browser-verifier` | Test login flow end-to-end in real browser |
| 10 | `git-workflow` + `pr-author` | Commit + PR |

---

## Test Baseline

```bash
make verify                 # 160/160
cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q  # 44/44
cd service && python3 -m pytest tests/test_carrier_*.py -q             # 366/366
```

---

## Acceptance Criteria

1. All three pages render with CSS tokens — no hardcoded hex colors
2. All form buttons are `Btn variant="primary"` from `dashboard-shared.js`
3. Login POST shows loading state during request; error shown inline on failure
4. Successful login redirects to `/dashboard/inbox-v2.html`
5. Signup password mismatch shown inline
6. Forgot-password success replaces form with confirmation message
7. All form fields and buttons have `data-testid`
8. No business domain logic on auth pages
9. Rollback: git revert the three files; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 12 — Auth V2
Branch: atlas-v2/sprint-12-auth-v2 (create from origin/main, Sprint 11 must be merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Auth pages load ONLY dashboard-shared.js (Btn, Toast) — do NOT add pz-api.js, pz-state.js, pz-components.js
5. CSS: custom properties only. Zero hardcoded hex.

TASK:
Harden existing auth pages: service/app/static/login.html, signup.html, forgot-password.html
This is a design-token alignment + accessibility hardening pass — NOT a rewrite.

CHANGES PER PAGE:
login.html:
- Replace bare <button> with Btn variant="primary" data-testid="btn-login"
- Loading state: disabled={loading} during POST
- Inline error banner (not alert())
- CSS tokens: replace hardcoded colors with --bg, --card, --accent
- Post-login redirect → /dashboard/inbox-v2.html

signup.html:
- Same Btn + loading pattern
- Password confirmation error shown inline
- data-testid on all fields + buttons

forgot-password.html:
- Same pattern
- Success state: form replaced by "Check your email" message

AUTHORITY: auth flows only — no business domain data, no wFirma, no DHL

MANDATORY AGENT SEQUENCE:
1. gap-detection — find hardcoded colors, bare buttons, missing testids in all 3 pages
2. reviewer-challenge — confirm scope is auth-only
3. frontend-ui — align pages to design tokens
4. frontend-flow-reviewer — review form flows
5. testing-verification — testid presence, loading state, error feedback
6. test-coverage-reviewer
7. gap-hunter
8. browser-verifier — test full login flow in real browser
9. git-workflow + pr-author

TEST BASELINE:
- make verify → 160/160
- tests/test_proforma_v2_contract.py → 44/44
- tests/test_carrier_*.py → 366/366

End with /deploy after PR merges.
```
