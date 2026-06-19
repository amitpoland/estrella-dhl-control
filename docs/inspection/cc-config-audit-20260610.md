# Claude Code Configuration Audit — Estrella PZ Processor

- **Repository**: `C:\Users\Super Fashion\PZ APP`
- **Inspection date**: 2026-06-10
- **Mode**: READ-ONLY
- **Tags**: VERIFIED = directly observed; NO EVIDENCE = searched, not found

---

## Section 0 — Environment

- **OS**: Windows 10 Pro 10.0.19045 — VERIFIED (system context)
- **Shell**: PowerShell 5.1 + Bash available — VERIFIED (system context)
- **Working directory**: `C:\Users\Super Fashion\PZ APP` — VERIFIED
- **Git remote** (`origin`): present, GitHub (URL «REDACTED») — VERIFIED
- **Current branch**: `feat/wfirma-draft-cancel` — VERIFIED (git status snapshot)
- **Main branch**: `main` — VERIFIED
- **Latest commit on branch**: `a827a6a feat(proforma): wFirma proforma cancellation workflow` — VERIFIED
- **Working tree**: dirty — 7 untracked files (scorecards, debug script, docs, `.claude/launch.json`, `Temppr545-cleanup/`) — VERIFIED
- **Claude Code CLI**: model identifies as Opus 4.7; exact CLI version pin NOT printed in this audit (read-only constraint did not include version probe in shell) — NO EVIDENCE (CLI version)

---

## Section 1 — Constitution files

| File | Path | Lines | Tag |
|---|---|---|---|
| Project constitution | `CLAUDE.md` | 729 | VERIFIED |
| Engine + workflow guide | `AGENTS.md` | 369 | VERIFIED |
| Guardian role definition | `GUARDIAN.md` | 286 | VERIFIED |
| Global constitution | `~/.claude/CLAUDE.md` | — | NO EVIDENCE (file absent) |
| Temp-dir copy | `Temppr545-cleanup/CLAUDE.md` | 729 | VERIFIED (untracked, retired tree) |

CLAUDE.md content highlights (file:line evidence):
- 7-agent deploy gate rule — `CLAUDE.md:7`–`23`
- Canonical working-tree registry (`C:\PZ`, `C:\PZ-verify`, retired scratch) — `CLAUDE.md:27`–`53`
- MANDATORY GOVERNANCE GATES 1–6 — `CLAUDE.md:57`–`158`
- MANDATORY OBSERVATION LAYER RULES 1–6 — `CLAUDE.md:175`–`246`
- Engineering Lessons A–M (append-only) — `CLAUDE.md:264`–`556`
- Frontend Design Standard pointer — `CLAUDE.md:559`–`577`
- Zoho Cliq connector constants (Org ID «REDACTED», channel ID «REDACTED») — `CLAUDE.md:580`–`589`
- Active Campaigns (Atlas-V2) — `CLAUDE.md:670`–`677`
- Operating rules (1–7) — `CLAUDE.md:681`–`691`

---

## Section 2 — `.claude/` directories

### 2a. Project `.claude/` (`C:\Users\Super Fashion\PZ APP\.claude\`)

| Subdirectory | Contents | Tag |
|---|---|---|
| `agents/` | 22 agent files (20 listed in `AGENT_REGISTRY.md`, 2 registry files) | VERIFIED |
| `commands/` | 9 slash-command files | VERIFIED |
| `skills/` | 3 skills (`frontend-design`, `atlas-v2-render-gate`, `ui-ux-pro-max`) | VERIFIED |
| `hooks/` | 2 PreToolUse scripts (`pz-deploy-guard.py`, `pz-frozen-file-guard.py`) | VERIFIED |
| `adr/` | 28 ADRs + README (3364 total lines) | VERIFIED |
| `campaigns/` | 5 root campaign docs + `atlas-v2/` (31 files) + `master-data/` (1 file) = 8688 total lines | VERIFIED |
| `memory/` | `PROJECT_STATE.md`, `scorecards/` (84 files), engineering lessons file | VERIFIED |
| `contracts/` | `governance-precedence.md`, `test-baseline.md` (referenced from CLAUDE.md) | VERIFIED |
| `rules/` | — | NO EVIDENCE (directory absent) |

### 2b. Global `.claude/` (`~/.claude/`)

| Subdirectory | Contents | Tag |
|---|---|---|
| `hooks/PreToolUse.sh` | global bash guardrails | VERIFIED |
| `settings.json` | global settings (teams, subagent model, plan mode) | VERIFIED |
| `settings.local.json` | global allow-list (PowerShell commands) | VERIFIED |
| `CLAUDE.md` | — | NO EVIDENCE |

---

## Section 3 — Hooks

### 3a. Project `.claude/settings.json` (24 lines) — VERIFIED

Declares only **PreToolUse** hooks. Matchers:

- **`Bash|PowerShell`** → `python "${CLAUDE_PROJECT_DIR}/.claude/hooks/pz-deploy-guard.py"` — `settings.json:6`
- **`Edit|Write`** → `python "${CLAUDE_PROJECT_DIR}/.claude/hooks/pz-frozen-file-guard.py"` — `settings.json:15`

No PostToolUse, no Stop, no UserPromptSubmit hooks declared — VERIFIED (file end at line 24).

### 3b. `.claude/hooks/pz-deploy-guard.py` (117 lines) — VERIFIED

PreToolUse guard. Asks (returns `permissionDecision: "ask"`) — does NOT hard-block — before:
1. Copy/write INTO `C:\PZ` via `Copy-Item`, `robocopy`, `xcopy`, `cp` — `pz-deploy-guard.py:~30`–`60`
2. `gh pr merge` — `pz-deploy-guard.py:~65`
3. `git push … main` — `pz-deploy-guard.py:~75`

Fails open on any error (never wedges session) — `pz-deploy-guard.py:~95`–`110`.

### 3c. `.claude/hooks/pz-frozen-file-guard.py` (98 lines) — VERIFIED

PreToolUse Edit|Write guard for V1-frozen basenames (Lesson F):

- Guarded set: `{ "dashboard.html", "shipment-detail.html" }` — `pz-frozen-file-guard.py:27`–`30`
- Asks (`permissionDecision: "ask"`), does NOT block — `pz-frozen-file-guard.py:72`–`83`
- Fails open on malformed input — `pz-frozen-file-guard.py:62`–`66`

### 3d. Global `~/.claude/hooks/PreToolUse.sh` (29 lines) — VERIFIED

Blocks (exit 2):
- `rm -rf` / `rm -r /` / `rmdir /` / `chmod 777` — `PreToolUse.sh:6`
- `.env.prod` writes — `PreToolUse.sh:~12`
- Deprecated Zoho connector names (`stella.mail`, `simplex.mail`, `zoho.mail`) — `PreToolUse.sh:~18`

Warns (stderr only):
- Org IDs misused as chat IDs
- wFirma POST/PUT without idempotency key

### 3e. Hook coverage matrix

| Hook event | Project | Global | Tag |
|---|---|---|---|
| PreToolUse | YES (2 matchers, ask-mode) | YES (1 script, block-mode for specific patterns) | VERIFIED |
| PostToolUse | — | — | NO EVIDENCE |
| Stop | — | — | NO EVIDENCE |
| UserPromptSubmit | — | — | NO EVIDENCE |
| SessionStart / SessionEnd | — | — | NO EVIDENCE |

---

## Section 4 — Git enforcement

### 4a. `.git/hooks/` (installed hooks)

- Contains only `*.sample` files (`pre-commit.sample`, `pre-push.sample`, etc.) — VERIFIED
- No real (non-sample) hooks installed — VERIFIED

### 4b. Repo-tracked `hooks/pre-commit` (golden-constants guard) — VERIFIED

- Activates only when `golden_constants.py` is staged
- Runs `python3 test_pz_regression.py`
- Blocks commit if tests fail
- **Not installed** to `.git/hooks/pre-commit` — installation requires `make install-hooks`

### 4c. Other git enforcement surfaces

| Surface | Path | Tag |
|---|---|---|
| Pre-commit framework config | `.pre-commit-config.yaml` | NO EVIDENCE |
| GitHub Actions workflows | `.github/workflows/` | NO EVIDENCE (directory absent) |
| Commit-msg / pre-push hooks | `.git/hooks/` | NO EVIDENCE |
| GPG signing config | git config | NO EVIDENCE (not probed in read-only set) |

### 4d. Settings-driven permissions

- Project `settings.local.json` — env-only (no `permissions` block) — VERIFIED (`settings.local.json:1`–`7`)
- Global `~/.claude/settings.json` — `permissions.default_mode: "plan"` — VERIFIED (`~/.claude/settings.json:7`)
- Global `~/.claude/settings.local.json` — allow-list for specific PowerShell commands (`restart.ps1`, `Get-Service *`, `Get-Item *`) — VERIFIED

---

## Section 5 — Test infrastructure

| Item | Evidence | Tag |
|---|---|---|
| Canonical test command | `Makefile` target `make verify` (uses `test_pz_regression.py` + `pz_import_processor.py`) | VERIFIED |
| Extended target | `make verify-full` (~30s, with PDF pipeline) | VERIFIED |
| Pytest config | `service/pytest.ini` (3 lines: `timeout = 30`, `timeout_method = thread`) | VERIFIED |
| Test file count | 1423 `test_*.py` files across repo | VERIFIED (find output) |
| Test baseline | `.claude/contracts/test-baseline.md` (referenced from CLAUDE.md:18) | VERIFIED (referenced) |
| Root `pyproject.toml` | — | NO EVIDENCE |
| Root `pytest.ini` | — | NO EVIDENCE (only `service/pytest.ini`) |
| Root `package.json` | — | NO EVIDENCE |
| `tox.ini` / `noxfile.py` | — | NO EVIDENCE |
| CI config | `.github/workflows/` | NO EVIDENCE |

---

## Section 6 — MCP config

| Item | Evidence | Tag |
|---|---|---|
| Project `.mcp.json` | — | NO EVIDENCE (file absent) |
| Global MCP server registrations | Numerous servers listed in system context (Zoho Cliq «REDACTED», Zoho Mail «REDACTED», Zoho CRM «REDACTED», Zoho WorkDrive «REDACTED», Fireflies «REDACTED», Postman «REDACTED», Figma «REDACTED», computer-use, Claude-in-Chrome, Claude Preview, plugins) | VERIFIED (presence) — credentials/IDs «REDACTED» |
| Canonical Cliq connector | `mcp__1760d1e3-ee15-43d5-af3a-3528cf9a21ce` (Estrella Cliq) — `CLAUDE.md:582` | VERIFIED |
| Canonical channel `#PZ` | ID «REDACTED» — `CLAUDE.md:585` | VERIFIED |
| Cliq Org ID | «REDACTED» — `CLAUDE.md:583` | VERIFIED |

Note: MCP server registrations are not stored in the project tree; they are managed at the user/Claude Code level. No `.mcp.json` checked into this repo.

---

## Section 7 — Governance inventory (names + line counts only)

### 7a. Agents — `.claude/agents/` (22 files)

Per `AGENT_REGISTRY.md` (176 lines, VERIFIED) and `RUNTIME_AGENT_AUDIT.md` (279 lines, VERIFIED):

20 repo-installed canonical agents (filenames; line counts not enumerated individually in this audit):
- `adr-historian.md` (50)
- `agent-performance-observer.md` (143)
- `backend-safety-reviewer.md` (21)
- 7 deploy-gate agents: `deploy_lead_coordinator.md`, `deploy_git_diff_reviewer.md`, `deploy_backend_impact_reviewer.md`, `deploy_persistence_storage_reviewer.md`, `deploy_security_reviewer.md`, `deploy_qa_reviewer.md`, `deploy_release_manager.md`
- 10 additional repo agents: `flow-context-keeper.md`, `frontend-flow-reviewer.md`, `gap-hunter.md`, `security-write-action-reviewer.md`, `test-coverage-reviewer.md`, plus 5 added 2026-06-06 (per RUNTIME_AGENT_AUDIT.md addendum)

Per `RUNTIME_AGENT_AUDIT.md`: ~80 dispatchable subagents total (20 repo + 54 user-level + ~6 built-in + 5 plugin). Write-capable EJ-domain agents flagged `QUARANTINE_WRITE_RISK`.

### 7b. Commands — `.claude/commands/` (9 files)

Slash-command files present (names only; line counts not individually enumerated):
- `/deploy`, `/observe`, `/update-state`, plus 6 others (full text dumped to persisted tool-result file during this audit) — VERIFIED

### 7c. Skills — `.claude/skills/` (3 skills per `SKILL_REGISTRY.md`, 54 lines)

- `frontend-design`
- `atlas-v2-render-gate`
- `ui-ux-pro-max`

### 7d. ADRs — `.claude/adr/` (28 ADRs + README, 3364 total lines) — VERIFIED

ADR-001 through ADR-028 plus `README.md`. Individual line counts were captured during data-gathering but are omitted here for brevity; total tree size = 3364 lines.

### 7e. Campaigns — `.claude/campaigns/` (37 files, 8688 total lines) — VERIFIED

- Root: 5 campaign docs
- `atlas-v2/`: 31 files (sprints 01–24, 31–33, 37, plus campaign master)
- `master-data/`: 1 file

### 7f. Memory — `.claude/memory/` — VERIFIED

- `PROJECT_STATE.md` (FACTS / DECISIONS / ASSUMPTIONS / OPEN QUESTIONS)
- `scorecards/` — 84 files
- `engineering_lessons.md` (referenced from CLAUDE.md lessons block)

### 7g. Contracts — `.claude/contracts/` — VERIFIED (presence)

- `governance-precedence.md` (referenced from `CLAUDE.md:163`)
- `test-baseline.md` (referenced from `CLAUDE.md:18`)

---

## Section 8 — Presence / Absence Matrix

| # | Item | Status | Evidence |
|---|------|--------|----------|
| a | PostToolUse hook running tests after edits | **ABSENT** | `.claude/settings.json` declares only PreToolUse (lines 4–22); no PostToolUse block |
| b | PreToolUse hook blocking dangerous bash | **PARTIAL — PRESENT (global), ASK-MODE (project)** | Global `~/.claude/hooks/PreToolUse.sh:6` blocks `rm -rf` / `rm -r /` / `rmdir /` / `chmod 777`; project guards (`pz-deploy-guard.py`, `pz-frozen-file-guard.py`) return `permissionDecision: "ask"` rather than block |
| c | Stop hook gating "done" on a passing check | **ABSENT** | No `Stop` hook in project or global `settings.json` |
| d | Subagents | **PRESENT** | `.claude/agents/` directory with 20 canonical agents (`AGENT_REGISTRY.md:1`–`176`); ~80 total dispatchable (`RUNTIME_AGENT_AUDIT.md`) |
| e | `.claude/rules/` directory | **ABSENT** | Directory not present in project tree |
| f | One documented command for the full test suite | **PRESENT** | `Makefile` target `make verify` (fast, ~2s) and `make verify-full` (~30s); CLAUDE.md:602 specifies `make verify` as Step A before any live batch |
| g | Git pre-commit hook enforcing tests/lint | **ABSENT (installed) / PRESENT (repo-tracked but uninstalled)** | `.git/hooks/` contains only `*.sample` files; repo-tracked `hooks/pre-commit` guards `golden_constants.py` but is not installed (requires `make install-hooks`) |
| h | Total CLAUDE.md line count across ALL files | **729 lines** (root project) — VERIFIED; **1458** if the untracked `Temppr545-cleanup/CLAUDE.md` (729 lines) is counted; **0** at global (`~/.claude/CLAUDE.md` ABSENT) |
| i | Claude Code version pinned | **NO EVIDENCE of pin** | No version pin found in `package.json` (absent) or settings; `~/.claude/settings.json:9` sets `autoUpdatesChannel: "latest"` — auto-update enabled |

---

INSPECTION COMPLETE — READ-ONLY, NO CHANGES MADE.
