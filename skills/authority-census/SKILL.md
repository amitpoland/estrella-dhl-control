---
name: authority-census
description: Read-only authority census for Estrella PZ. Dispatches 5 inspector subagents via Task to map every frontend page and backend route to a single canonical owner. Produces 6 structured deliverables. Controlled by EJ_CENSUS=1 environment gate.
metadata:
  type: skill
  domain: authority-audit
  version: "1.1"
  updated: 2026-07-01
  base_sha: aa414d90
---

# Estrella PZ — Authority Census Skill

## Purpose

Answer one question for every feature in the codebase:
**"Which single file is the canonical owner of this functionality?"**

When the answer is "multiple files" or "no file", that is a finding.

---

## Quick Start

```powershell
# 1. Set census mode
$env:EJ_CENSUS = "1"

# 2. Launch session
claude

# 3. Run the census
/authority-census
```

Reports land in `C:\PZ-verify\reports\authority-census\<UTC-stamp>\`.

---

## The 5 Inspector Agents

| Agent | What it scans | Deliverable |
|---|---|---|
| `frontend-authority-inspector` | `*.html` + `v2/*.jsx` | `01-frontend-authority-map.md` |
| `backend-route-inspector` | `routes_*.py` + `main.py` | `02-backend-authority-map.md` |
| `navigation-inspector` | `index.html` nav config + legacy nav | `03-navigation-map.md` |
| `api-wrapper-inspector` | `pz-api.js` vs `v2/pz-api.js` | `04-api-wrapper-map.md` |
| `service-scheduler-inspector` | `services/*.py` + startup sequence | `05-service-scheduler-map.md` |

All 5 use `tools: Read, Grep, Glob` only — no writes.

## The 6 Deliverables

| # | File | Content |
|---|---|---|
| 0 | `00-census-index.md` | Index + summary counters |
| 1 | `01-frontend-authority-map.md` | Frontend Authority Map |
| 2 | `02-backend-authority-map.md` | Backend Authority Map |
| 3 | `03-navigation-map.md` | Navigation Map |
| 4 | `04-api-wrapper-map.md` | API Wrapper Comparison |
| 5 | `05-service-scheduler-map.md` | Service / Scheduler Map |

---

## Status Vocabulary

| Status | Meaning |
|---|---|
| `AUTHORITY` | Single canonical source, wired and active |
| `FRAGMENTED` | Feature split across 2+ files; no clear single owner |
| `DUPLICATE` | Another file renders the same URL |
| `LEGACY` | Old file still active/linked but logically replaced |
| `DEAD` | On disk but not loaded or linked from anywhere |
| `UNREACHABLE` | Component defined but slug redirects away before rendering |
| `ORPHAN` | In atlas/ or not referenced by any nav, router, or active page |
| `SCHEDULER-ONLY` | Has automation but missing Business API / UI / Observability |

---

## Guard

`census-guard.py` (PreToolUse hook) is active when `EJ_CENSUS=1`:
- Blocks Write/Edit/MultiEdit/NotebookEdit to any path except `reports\authority-census\`
- Blocks shell: rm, mv, git commit, git push, gh pr, robocopy, sc.exe, nssm, curl POST

---

## Templates

Report structure templates are in `skills/authority-census/templates/`.
The census command (`/authority-census`) uses `00-census-index.md` as the index template.

---

## Reference

- Slash command: `.claude/commands/authority-census.md`
- Guard hook: `.claude/hooks/census-guard.py`
- Settings template: `.claude/settings.census.json`
- Prior census (2026-06-30): `.claude/memory/authority-census-2026-06-30.md`
- Scan paths at base SHA `aa414d90`: see `SCAN_TARGETS.md`
