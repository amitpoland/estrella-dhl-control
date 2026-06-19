# Claude Code Configuration Audit — Estrella PZ Processor

- **Repository**: `C:\Users\Super Fashion\PZ APP`
- **Inspection date**: 2026-06-12
- **Branch / HEAD**: `fix/proforma-warehouse-gate-pz-mapping` @ `614743e` — VERIFIED
- **Mode**: READ-ONLY (this report is the only write)
- **Tag legend**: VERIFIED = directly observed; INFERRED = derived from observed evidence; ABSENT = searched, not found
- **Predecessor**: `docs/inspection/cc-config-audit-20260610.md` (this file refreshes Sections 1–6, replaces Section 7 ranking, and reflects 2026-06-11/12 changes — addition of `.claude/launch.json`, `.claude/hooks/pz-frozen-file-guard.py`, and the `pre-commit` git-hook landing)

Secrets policy: no API keys, OAuth tokens, or credential-bearing URLs are printed. `claudeAiMcpEverConnected` names are connector display names from the local cache — not URLs.

---

## Section 1 — AGENTS & SUBAGENTS

### 1a. Inventory totals

| Source | File count | Notes |
|---|---|---|
| Project `.claude/agents/*.md` (excl. registry/audit) | **20** | listed in `AGENT_REGISTRY.md:5` as canonical 20 |
| User `~/.claude/agents/*.md` | **54** | broad domain set (legal, dhl, wFirma, frontend, intake, etc.) |
| Built-in / harness-bundled agents (visible in this turn's tool block) | ~37 | includes `chief-orchestrator`, `Explore`, `Plan`, `claude`, `general-purpose`, `brand-voice:*` (4), `brand-voice-content-generation`, `claude-code-guide`, deploy_* duplicates, etc. |
| Plugin-injected agents | unknown — none enumerated through a `.claude/plugins/` install (project-level `enabledPlugins=[]` per `~/.claude.json`) but 14 `*@inline` plugins are active (see §4) |

**Project ↔ user name collisions (project copy wins by precedence):**
`final-consistency-review`, `gap-detection`, `integration-boundary`, `reviewer-challenge`, `ux-flow` — all exist in BOTH `.claude/agents/` (inspect-only, Bash-stripped) and `~/.claude/agents/` (still Bash-capable in some cases). Source: `.claude/agents/AGENT_REGISTRY.md:8-11` flags 5 agents installed 2026-06-06 with "pending fresh-session confirmation" of project-over-user precedence. **Effective unique count ≈ 54 + 20 − 5 = 69 user-or-project-defined agents**, before plugins.

### 1b. Project agents — frontmatter snapshot

Source: `grep -E "^(name|tools|model):" .claude/agents/*.md`

| # | Name | Tools | Model |
|---|---|---|---|
| 1 | `adr-historian` | Read, Grep, Glob, Write, Edit | (default) |
| 2 | `agent-performance-observer` | Read, Grep, Glob, **Bash**, Write | (default; prompt states "Opus-class preferred") |
| 3 | `backend-safety-reviewer` | Read, Grep, Glob | (default) |
| 4 | `deploy-backend-impact-reviewer` | Read, Grep, Glob | (default) |
| 5 | `deploy-git-diff-reviewer` | Read, Grep, Glob | (default) |
| 6 | `deploy-lead-coordinator` | Read, Grep, Glob | (default) |
| 7 | `deploy-persistence-storage-reviewer` | Read, Grep, Glob | (default) |
| 8 | `deploy-qa-reviewer` | Read, Grep, Glob | (default) |
| 9 | `deploy-release-manager` | Read, Grep, Glob | (default) |
| 10 | `deploy-security-reviewer` | Read, Grep, Glob | (default) |
| 11 | `final-consistency-review` | Read, Glob, Grep | **opus** |
| 12 | `flow-context-keeper` | Read, Grep, Glob, **Bash**, Write, Edit | (default) |
| 13 | `frontend-flow-reviewer` | Read, Grep, Glob | (default) |
| 14 | `gap-detection` | Read, Glob, Grep | **opus** |
| 15 | `gap-hunter` | Read, Grep, Glob | (default) |
| 16 | `integration-boundary` | Read, Glob, Grep | sonnet |
| 17 | `reviewer-challenge` | Read, Glob, Grep | sonnet |
| 18 | `security-write-action-reviewer` | Read, Grep, Glob | (default) |
| 19 | `test-coverage-reviewer` | Read, Grep, Glob | (default) |
| 20 | `ux-flow` | Read, Glob, Grep | haiku |

Capability classification (per `AGENT_REGISTRY.md:27-50`): 17 **INSPECT-ONLY**, 3 **DOCS-WRITE** (`adr-historian`, `agent-performance-observer`, `flow-context-keeper`). No project-installed agent has product-code write access — `service/app/**` is unreachable from any of them.

### 1c. User agents — frontmatter snapshot

54 agents in `~/.claude/agents/`. Tool grants are broader than project copies. Highlights:

- **Write-capable (Edit/Write/Bash):** `backend-api`, `browser-verifier`, `client-contractor-mapping`, `dashboard-operations`, `database-storage`, `deployment-windows-ops`, `dhl-customs`, `document-intelligence`, `email-evidence-recovery`, `frontend-ui`, `git-workflow`, `inventory-state-machine`, `legal-*` (5), `prompt-engineering`, `pz-purchase-accounting`, `sales-proforma`, `testing-verification`, `warehouse-ops`, `wfirma-integration` — full file-mutation surface.
- **Model overrides:** `chief-orchestrator` → opus; `compliance` → opus; `final-consistency-review` → opus; `flow-continuity` → opus; `gap-detection` → opus; `legal-argument-builder` → opus; `legal-drafting` → opus; `legal-research` → opus; `legal-risk-review` → opus; `misunderstanding-prevention` → opus; `system-architect` → opus; `memory-lessons` → haiku; `prompt-engineering` → haiku; `task-classification` → haiku; `ux-flow` → haiku. All other user agents → sonnet (overrides `CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-4-20250514`).

### 1d. Overlapping scopes (the ping-pong surface) — VERIFIED

Scope-overlapping pairs/clusters found in user+project sets:

1. **Pre-work intake stack (6 agents)** — `natural-language-intake` → `multimodal-evidence` → `context-resolution` → `intent-clarification` → `task-classification` → `product-owner-interpreter`. Source: `~/.claude/agents/*.md` descriptions. All fire on operator input.
2. **Pre-implementation review stack (4–5 agents)** — `gap-detection` + `misunderstanding-prevention` + `assumption-builder` + `planning-task-breakdown` + `system-architect`. Source: descriptions in `~/.claude/agents/`.
3. **Reviewer cluster (8+ agents, large overlap)** — `reviewer-challenge`, `gap-hunter`, `gap-detection`, `frontend-flow-reviewer`, `backend-safety-reviewer`, `security-write-action-reviewer`, `test-coverage-reviewer`, `integration-boundary`, `final-consistency-review`. Several have nearly identical triggers (e.g. `reviewer-challenge` "fires automatically on every plan and significant code change"; `gap-hunter` "cross-phase contradiction finder"; `gap-detection` "first detection layer").
4. **Post-run governance (3 agents)** — `flow-context-keeper`, `agent-performance-observer`, `memory-lessons`. Two of the three are mandatory per `CLAUDE.md:188-205` (RULES 2 + 3).
5. **Deploy gate (7 agents)** — required by `CLAUDE.md:10-17`. This is intentional, not ping-pong.

### 1e. Auto-spawning flags

| Flag | Source | Value | Effect |
|---|---|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | `~/.claude/settings.json:3` | **"1"** | Enables team-spawning experimental mode — VERIFIED. |
| `CLAUDE_CODE_SUBAGENT_MODEL` | `~/.claude/settings.json:4` | `claude-sonnet-4-20250514` | Default subagent model is Sonnet 4 — VERIFIED. (Per-agent `model:` frontmatter overrides.) |
| `CLAUDE_CODE_FORK_SUBAGENT` | searched in both settings files | not set — ABSENT |
| `CLAUDE_AUTO_BACKGROUND_TASKS` | searched | not set — ABSENT |
| `CLAUDE_CODE_MAX_TURNS` | searched | not set — ABSENT |

---

## Section 2 — OUTPUT / RESPONSE BEHAVIOR

| Knob | Value | Source | Effect |
|---|---|---|---|
| Main model | `claude-opus-4-7` (Opus 4.7) | system prompt header — VERIFIED | high-capability default; reflected in CLI status |
| `ANTHROPIC_MODEL` | not set | searched both settings — ABSENT | model selection is harness-driven |
| `CLAUDE_CODE_SUBAGENT_MODEL` | `claude-sonnet-4-20250514` | `~/.claude/settings.json:4` — VERIFIED | every subagent runs Sonnet 4 unless its `model:` frontmatter overrides |
| `permissions.default_mode` | **`plan`** | `~/.claude/settings.json:6-8` — VERIFIED | new sessions start in plan-approval mode; prevents drive-by writes |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | **`16000`** | `~/.claude/policy-limits.json` is org-policy only; the user-set value is in `~/.claude/settings.local.json:3` — VERIFIED | 16k response cap (high) — allows long generative replies |
| `DISABLE_NON_ESSENTIAL_MODEL_CALLS` | `1` | `~/.claude/settings.local.json:4` — VERIFIED | suppresses background quality/telemetry calls |
| `DISABLE_COST_WARNINGS` | `1` | `~/.claude/settings.local.json:5` — VERIFIED | hides cost prompts |
| `MAX_THINKING_TOKENS` | not set — ABSENT | — | uses harness default |
| `CLAUDE_CODE_SIMPLE` / `SIMPLE_SYSTEM_PROMPT` | not set — ABSENT | — | full system prompt + skill block injected (large) |
| `CLAUDE_CODE_MAX_TURNS` | not set — ABSENT | — | **no hard turn cap** — sessions can spin indefinitely |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | not set — ABSENT | — | harness default; auto mode is on (see below) |
| Auto mode | **ON** | system-reminder this turn — VERIFIED | "bias toward working without stopping for clarifying questions" |
| `agentPushNotifEnabled` | true | `~/.claude/settings.json:12` — VERIFIED | background-completion notifications enabled |
| Output style | not customized — ABSENT (no `output_style` key) | — | default Claude Code prose |
| `skipWorkflowUsageWarning` | true | `~/.claude/settings.json:10` — VERIFIED | does not block on workflow cost prompts |

Compaction: there is no explicit override; the harness will auto-summarize prior turns near context limits (system prompt: "context management" section). Combined with `agentPushNotifEnabled=true` and the very large `MAX_OUTPUT_TOKENS=16000`, the system will produce long replies and continue across compaction events without warning.

---

## Section 3 — HOOKS

### 3a. Native (settings-defined) hooks

Source: `.claude/settings.json:2-23` — VERIFIED.

| Event | Matcher | Command | File |
|---|---|---|---|
| `PreToolUse` | `Bash\|PowerShell` | `python "${CLAUDE_PROJECT_DIR}/.claude/hooks/pz-deploy-guard.py"` | `.claude/hooks/pz-deploy-guard.py` |
| `PreToolUse` | `Edit\|Write` | `python "${CLAUDE_PROJECT_DIR}/.claude/hooks/pz-frozen-file-guard.py"` | `.claude/hooks/pz-frozen-file-guard.py` |

Both hooks: fail-OPEN ("any error → exit 0, no output"). Both emit `permissionDecision="ask"` on match (interactive confirm, not hard block).

- **`pz-deploy-guard.py`** — guards `Copy-Item|robocopy|xcopy|cp` into `C:\PZ`, `gh pr merge`, and `git push * main *`. Source: `.claude/hooks/pz-deploy-guard.py:45-67`.
- **`pz-frozen-file-guard.py`** — guards Edit/Write of `dashboard.html` or `shipment-detail.html` (Lesson F V1 freeze). Source: `.claude/hooks/pz-frozen-file-guard.py:27-30`. **NEW since 2026-06-10 audit.**

No `PostToolUse`, `Stop`, `SubagentStop`, `SessionStart`, or `Notification` hooks configured in either settings layer — ABSENT.

### 3b. User-level hook script

`~/.claude/hooks/PreToolUse.sh` — VERIFIED, but **not wired into any settings.json** (neither user `settings.json` nor project `settings.json` references it). It is a dormant file. If user settings were edited to register it, it would:
- BLOCK (exit 2) on `rm -rf`, `rm -r /`, `rmdir /`, `chmod 777`
- BLOCK on `.env.prod|production.config|prod.settings` edits
- BLOCK on `"stella.mail"|"simplex.mail"|"zoho.mail"` (deprecated Zoho connector references)
- WARN on suspected org-id-as-chat-id, and on wFirma POST/PUT without an `idempotency` token

Status: **defined but unregistered** — INFERRED from absence of a `command` entry pointing to it in either settings file.

### 3c. Git hooks

| Hook | Source | Behavior |
|---|---|---|
| `core.hooksPath` | `hooks` (repo-relative) | `git config --get core.hooksPath` → `hooks` — VERIFIED |
| `hooks/pre-commit` | repo-tracked | When `golden_constants.py` is staged, runs `test_pz_regression.py` and BLOCKS commit on failure — VERIFIED (`hooks/pre-commit:1-30`) |

This is the only repo-installed git hook. It is correctly scoped (only fires when golden_constants is touched).

### 3d. Overlapping matchers / loop risk

- `Bash|PowerShell` → only the deploy guard. No second matcher overlaps.
- `Edit|Write` → only the frozen-file guard.
- **No loop risk**: hooks are exit-0 on the happy path and emit `ask` (not `block`), so a tool retry will not re-enter the hook in a tight loop.

### 3e. Protective hooks NOT present

- **No `SessionStart` hook to enforce CLAUDE.md "RULE 1 — read PROJECT_STATE.md first"** — that rule is purely doctrinal; the harness will not force it. INFERRED.
- **No `PostToolUse` to log production-write events** — the deploy guard is interactive only; there's no audit trail of operator-approved sync commands beyond chat history.
- **No PreToolUse on MCP write tools** — wFirma write tools, Cliq post, Workdrive upload, Gmail send all bypass any guard.

---

## Section 4 — PLUGINS

### 4a. Marketplaces

Source: `~/.claude/plugins/known_marketplaces.json` — VERIFIED.

- `claude-plugins-official` (github: `anthropics/claude-plugins-official`, last updated 2026-05-17) → installed at `~/.claude/plugins/marketplaces/claude-plugins-official`. Contains:
  - **35 first-party plugins** (`marketplaces/.../plugins/`) — e.g. `agent-sdk-dev`, `clangd-lsp`, `claude-code-setup`, `code-modernization`, `code-review`, `code-simplifier`, `commit-commands`, `feature-dev`, `frontend-design`, `hookify`, `pr-review-toolkit`, `pyright-lsp`, `ralph-loop`, `security-guidance`, `session-report`, `skill-creator`, `swift-lsp`, `typescript-lsp` (full list in marketplace dir).
  - **15 external plugins** (`external_plugins/`) — `asana`, `context7`, `discord`, `fakechat`, `firebase`, `github`, `gitlab`, `greptile`, `imessage`, `laravel-boost`, `linear`, `playwright`, `serena`, `telegram`, `terraform`.

### 4b. Active plugins (enabled / inline)

Critical observation: `enabledPlugins` is **empty** in both top-level `~/.claude.json` and per-project (`projects[…].enabledPlugins=[]`) — VERIFIED. **However**, `pluginUsage` lists 14 `@inline` plugins as actually invoked:

> `pdf-viewer@inline`, `operations@inline`, `human-resources@inline`, `engineering@inline`, `design@inline`, `data@inline`, `brand-voice@inline`, `legal@inline`, `product-management@inline`, `enterprise-search@inline`, `finance@inline`, `bio-research@inline`, `apollo@inline`, `anthropic-skills@inline`.

These match the skill-namespace prefixes in this turn's available-skills block (`legal:*`, `operations:*`, `human-resources:*`, `engineering:*`, `design:*`, `data:*`, `brand-voice:*`, `product-management:*`, `enterprise-search:*`, `finance:*`, `bio-research:*`, `apollo:*`, `anthropic-skills:*`, `pdf-viewer:*`). They are injecting **96 skills** into the available-skills list (count by line-counting the skill-block prefix matches) — every prompt pays the context cost.

`pdf-viewer-inline` plugin has a data dir at `~/.claude/plugins/data/pdf-viewer-inline/` and exposes 9 MCP tools (`mcp__plugin_pdf-viewer_pdf__*`) — VERIFIED in this turn's deferred-tool list.

### 4c. Project-level plugin config

`projects[r"C:\Users\Super Fashion\PZ APP"]` has no `enabledPlugins`, `mcpServers`, or `enabledMcpjsonServers` keys populated — all empty/absent. INFERRED meaning: this project inherits everything from the user/inline level; nothing is project-scoped.

### 4d. Plugin sprawl quantified

- **35 official + 15 external plugins available** → ~50 plugin manifests on disk
- **14 inline plugins actively used** (skill-injection level)
- **96+ skills** appearing in the skill list this turn (from inline plugins + bundled CLI skills)
- **Built-in agents from harness**: ~37 (visible in this turn's Agent tool registry)
- **+20 project + 54 user agents** → effective agent registry ~70 unique names
- Combined: every turn ships an extremely long system prompt and a deferred-tool surface that triggers ToolSearch for many third-party tools.

---

## Section 5 — SETTINGS (precedence-resolved EFFECTIVE)

Precedence rule: managed > project.local > project > user.local > user. Managed policy files are not present on this box (none found at `C:\ProgramData\…`) — ABSENT.

### 5a. Layer dump

| Layer | File | Key facts |
|---|---|---|
| User | `~/.claude/settings.json` | `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, `env.CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-4-20250514`, `permissions.default_mode=plan`, `autoUpdatesChannel=latest`, `skipWorkflowUsageWarning=true`, `theme=auto`, `agentPushNotifEnabled=true` |
| User.local | `~/.claude/settings.local.json` | `env.CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000`, `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1`, `DISABLE_COST_WARNINGS=1` |
| Project | `.claude/settings.json` | `hooks.PreToolUse` × 2 (deploy guard, frozen-file guard) — no other keys |
| Project.local | `.claude/settings.local.json` | `permissions.allow` × 4 (restart.ps1, elevated restart, `Get-Service *`, `Get-Item *`) |
| Managed/enterprise | not present — ABSENT | — |
| Legacy | `~/.claude.json` (41,295 bytes) | per-user state cache (model costs, plugin usage, oauth, project roots, MCP-everConnected list) — not a settings source per se |

### 5b. Conflicts between layers

- `permissions.default_mode=plan` (user) vs `permissions.allow=[…]` (project.local) — **not a conflict**, the latter narrows specific commands inside plan mode. INFERRED.
- `CLAUDE_CODE_SUBAGENT_MODEL=sonnet-4` (user env) vs per-agent `model: opus` / `model: haiku` frontmatter — **per-agent frontmatter wins** for those agents. No conflict in the broken sense, but it means 13 user agents and 3 project agents are running on Opus / Haiku, not the env default.
- No two layers set the same key with different values. VERIFIED.

### 5c. Effective settings, condensed

```json
{
  "model": "claude-opus-4-7",          // main loop
  "subagent_model": "claude-sonnet-4-20250514",  // default, overridable per-agent
  "max_output_tokens": 16000,
  "permissions.default_mode": "plan",
  "permissions.allow": [
    "PowerShell(& 'C:\\PZ\\restart.ps1')",
    "PowerShell(Start-Process powershell -Verb RunAs -ArgumentList '-File C:\\PZ\\restart.ps1' -Wait)",
    "PowerShell(Get-Service *)",
    "PowerShell(Get-Item *)"
  ],
  "experimental.agent_teams": true,
  "agentPushNotifEnabled": true,
  "disable_non_essential_model_calls": true,
  "disable_cost_warnings": true,
  "hooks.PreToolUse": [
    {"matcher":"Bash|PowerShell","command":"pz-deploy-guard.py"},
    {"matcher":"Edit|Write","command":"pz-frozen-file-guard.py"}
  ]
}
```

---

## Section 6 — CONNECTORS / MCP

### 6a. Configured MCP servers (file-based)

- `.mcp.json` in project root — **ABSENT** (does not exist).
- `mcpServers` in `~/.claude/settings.json` — ABSENT.
- `mcpServers` in `~/.claude.json` (legacy) — `0` entries — VERIFIED via python parse.
- `mcpServers` in `~/.claude.json` projects entry for this repo — `0` entries — VERIFIED.
- `enabledMcpjsonServers` / `disabledMcpjsonServers` — both `[]` — VERIFIED.

**Conclusion: zero locally-defined MCP servers.** All MCP surface comes from claude.ai-side connectors + plugin-bundled servers.

### 6b. claude.ai MCP connectors (display names cached)

Source: `~/.claude.json` → `claudeAiMcpEverConnected` (list of 16) — VERIFIED:

1. claude.ai Google Calendar
2. claude.ai Postman
3. claude.ai Gmail
4. claude.ai Google Drive
5. claude.ai Fireflies
6. claude.ai Europe Simpleks Mail v2
7. claude.ai Estrella mail
8. claude.ai Estrella workdrive
9. claude.ai Cloudflare Developer Platform
10. claude.ai Figma
11. claude.ai cliq
12. claude.ai Zoho Projects
13. claude.ai Zoho CRM
14. claude.ai Stella Cliq
15. claude.ai Stella mail
16. claude.ai Estrella Cliq

These are the ever-connected set; whether each is currently active depends on session connect-state at runtime. Notable: **3 distinct ZohoMail connectors** (Estrella, Europe Simpleks Mail v2, Stella) and **3 distinct Cliq connectors** (cliq, Stella Cliq, Estrella Cliq) — overlap matches the deferred-tool list, which shows ~8 distinct UUID-namespaced ZohoMail tool sets and ~4 ZohoCliq tool sets.

### 6c. Plugin-bundled MCP servers (deferred this turn)

From this turn's deferred-tool block:

- `plugin:pdf-viewer:pdf` → 9 tools (`display_pdf`, `interact`, `list_pdfs`, `poll_pdf_commands`, `read_pdf_bytes`, `save_pdf`, `submit_*`)
- `Claude_Preview` → 13 tools (preview_start/click/eval/etc.)
- `Claude_in_Chrome` → 26 tools (computer/browser)
- `computer-use` → 30 tools (mouse, keyboard, screen)
- `ccd_session`, `ccd_directory`, `ccd_session_mgmt` → ~10 tools (chip / chapter / widget / send_message)
- `mcp-registry`, `scheduled-tasks`, `visualize` → ~6 tools
- `bio-research` cluster (biorxiv, c-trials, chembl, consensus) — auto-loaded via instructions block this turn

### 6d. Tool-search / deferral

- `ENABLE_TOOL_SEARCH` — **not set in any settings file** — ABSENT. But the harness is operating in deferred-tool mode this turn (per the multi-screen deferred-tool list in the system reminder). INFERRED: tool-search is on by default in this harness build.

### 6e. Total MCP tool surface (order-of-magnitude)

From this turn's deferred + active tool listing (counting only `mcp__*` prefixes):

- 8 ZohoMail UUID namespaces × ~50–60 tools each = **~400–500 ZohoMail tools** (with heavy overlap; same connector duplicated across email accounts)
- 4 ZohoCliq UUID namespaces × ~15 tools = **~60 Cliq tools**
- 1 Zoho CRM × ~50 tools = **~50 CRM tools**
- 1 Zoho WorkDrive × ~17 tools = **~17 WorkDrive tools**
- 1 Zoho Projects × ~25 tools = **~25 Projects tools**
- 1 Postman, Fireflies, Calendar, Figma, gdrive each ~10–35 tools = **~80 tools**
- Plugin tools (pdf, computer-use, preview, chrome, ccd, scheduled-tasks, visualize, mcp-registry) = **~100 tools**
- **Grand total ≈ 700–900 MCP tools deferred** behind ToolSearch.

This is the dominant context-bloat surface. Most are duplicated capability across multiple ZohoMail connector instances.

---

## Section 7 — DRIFT-CONTRIBUTOR SUMMARY (RANKED)

Cross-cut of Sections 1–6 against the failure-mode list (story-creating · new-code-instead-of-fix · agent ping-pong · non-convergence).

### Rank 1 — Agent-team experimental mode + no turn cap
- **Evidence**: `~/.claude/settings.json:3` `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`; `CLAUDE_CODE_MAX_TURNS` ABSENT (no hard cap); `agentPushNotifEnabled=true`.
- **Behavior**: subagents can spawn other subagents in a team, with no global turn budget and notification-driven background continuation. Combined with overlapping reviewer scopes (Section 1d clusters 1–4), the loop "another reviewer might catch this → spawn another reviewer" has no terminator other than self-restraint.
- **Failure mode**: ping-pong + non-convergence.

### Rank 2 — Massive overlapping-reviewer agent registry (~70 unique, ≥9 overlapping reviewers)
- **Evidence**: Section 1d. Pre-work intake stack of 6, pre-implementation review stack of 5, reviewer cluster of 8+, post-run governance of 3. Several agents' descriptions are near-identical ("fires automatically on every plan and significant code change").
- **Behavior**: the orchestrator can dispatch 8+ reviewers in sequence with overlapping findings; each one is INSPECT-ONLY so they cannot actually fix anything, which guarantees additional rounds. CLAUDE.md GATES 1–6 plus Lessons A–M (line 264–556) mandate even more reviewers per change class.
- **Failure mode**: ping-pong, non-convergence, story-creating (long synthesis text instead of code).

### Rank 3 — Plan mode + 16k output tokens + auto-mode "don't ask"
- **Evidence**: `~/.claude/settings.json:7` `default_mode=plan`; `~/.claude/settings.local.json:3` `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000`; this turn's reminder "Auto Mode Active — bias toward working without stopping for clarifying questions".
- **Behavior**: plan mode pushes for elaborate planning artifacts; 16k output budget allows producing them; auto-mode suppresses "should I just do it?" pauses. Net effect is long planning documents instead of small code edits.
- **Failure mode**: story-creating, new-code-instead-of-fix.

### Rank 4 — 14 inline plugins injecting ~96 skills + ~700–900 deferred MCP tools
- **Evidence**: Section 4b (pluginUsage list of 14 `@inline`); Section 6e MCP-tool count.
- **Behavior**: every turn ships a multi-page available-skills block + tool-search deferral. The model spends turns deciding which skill or MCP tool to invoke, with high false-positive rate (e.g. legal/HR/finance plugins are clearly irrelevant to a PZ build). Each ToolSearch call costs round-trips.
- **Failure mode**: ping-pong (tool-shopping), context bloat (compaction-driven drift later in the session).

### Rank 5 — Project agents are inspect-only, but user agents have full write — silent precedence ambiguity
- **Evidence**: 5 agents collide by name (Section 1c); `AGENT_REGISTRY.md:8-11` explicitly notes "tool-stripping is pending fresh-session confirmation of project-over-user precedence." `final-consistency-review`, `gap-detection`, `integration-boundary`, `reviewer-challenge`, `ux-flow` exist in both layers.
- **Behavior**: orchestrator may believe it is dispatching the inspect-only project copy; runtime may dispatch the broader user copy with Bash/Write grants — Lesson B (CLAUDE.md:294) flags this exact failure class.
- **Failure mode**: new-code-instead-of-fix (a "reviewer" that actually edits), governance bypass.

### Rank 6 — No `PostToolUse` audit or `SessionStart` rule enforcement
- **Evidence**: Section 3e. CLAUDE.md RULE 1 ("read PROJECT_STATE.md first") is doctrinal-only; no hook enforces it. No PostToolUse audit on MCP write tools (wFirma, Cliq, Workdrive, Gmail send).
- **Behavior**: every session must self-discipline to read PROJECT_STATE.md; failures are invisible. External-write actions through MCP (Gmail send, Cliq post, wFirma push) have no harness-side trail beyond chat.
- **Failure mode**: story-creating without grounding (new session starts cold and re-derives state), silent governance drift.

### Rank 7 — User-level `PreToolUse.sh` is defined but unwired
- **Evidence**: Section 3b — `~/.claude/hooks/PreToolUse.sh` exists with strong block rules but no settings entry references it.
- **Behavior**: a safety net that the operator likely believes is active (rm -rf block, prod-config block, deprecated-Zoho block, wFirma-idempotency warning) is in fact dormant.
- **Failure mode**: false sense of safety; new-code-instead-of-fix in dangerous places (Zoho deprecation, missing idempotency).

### Rank 8 — Subagent model is `sonnet-4` while overlapping reviewers are `opus`
- **Evidence**: `~/.claude/settings.json:4` env default `sonnet-4`; per-agent frontmatter pins 13 user agents and 3 project agents to opus or haiku.
- **Behavior**: cost is fine; the side-effect is that the 8+ reviewer cluster mixes opus + sonnet + haiku verdicts with different verbosity, encouraging the synthesizer to write more "merging-views" prose.
- **Failure mode**: story-creating in the synthesis step.

### Rank 9 — Auto-compact / no MAX_THINKING_TOKENS
- **Evidence**: `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and `MAX_THINKING_TOKENS` both ABSENT.
- **Behavior**: harness default auto-compaction triggers mid-task and replaces conversation with summaries; with no explicit pct override + 16k output budget + push-notif background continuation, the model resumes after compaction with weaker grounding and a tendency to re-state context as new narrative ("story-creating").
- **Failure mode**: story-creating, non-convergence (loses track of "this fix"), new-code (writes the same thing twice after compaction).

---

## Recommendations (PROPOSE, do not apply)

These are the smallest possible changes that would attack the top three drift drivers without breaking the deploy/security gates:

1. **Bound the loop**: set `CLAUDE_CODE_MAX_TURNS` (e.g. 60–100) in `~/.claude/settings.json:env`. Attacks Rank 1 + Rank 9.
2. **Disable experimental agent teams unless the operator opts in for a specific campaign**: remove `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` from default user env; enable per-session via env when actually wanted. Attacks Rank 1 + Rank 2.
3. **Wire the dormant `~/.claude/hooks/PreToolUse.sh`** into `~/.claude/settings.json:hooks.PreToolUse` (matcher `Bash|PowerShell|Edit|Write`). Attacks Rank 7.
4. **Resolve the 5 project↔user agent name collisions** by deleting the user-level copies (or renaming the project copies). Attacks Rank 5 / Lesson B.
5. **Disable inline plugins unrelated to PZ scope** (legal, HR, finance, brand-voice, design, product-management, bio-research, apollo, enterprise-search): they re-inject ~70 skills per turn that this project does not use. Attacks Rank 4.
6. **Lower `CLAUDE_CODE_MAX_OUTPUT_TOKENS`** to 4000–6000 to discourage long planning prose. Attacks Rank 3 + Rank 8.
7. **Add a `SessionStart` hook** that reads and prints `.claude/memory/PROJECT_STATE.md` to satisfy CLAUDE.md RULE 1 mechanically rather than doctrinally. Attacks Rank 6.

**No changes have been made.** This report is read-only output written to `docs/inspection/cc-config-audit-20260612.md`.

---

## Appendix A — File inventory (key paths)

```
~/.claude/settings.json               302 B   2026-06-08
~/.claude/settings.local.json         273 B   2026-05-17
~/.claude/policy-limits.json          184 B   2026-06-09
~/.claude.json                     41,295 B   2026-06-12  (legacy / state cache)
~/.claude/agents/*.md              54 files
~/.claude/hooks/PreToolUse.sh         dormant — no settings.json reference
~/.claude/commands/*.md             4 files
~/.claude/skills/                   1 dir (senior-architect)
~/.claude/plugins/marketplaces/
   claude-plugins-official/
     plugins/                       35 plugin manifests
     external_plugins/              15 external plugins
~/.claude/plugins/data/
   pdf-viewer-inline/                MCP server data

.claude/settings.json                530 B   2026-06-11   (hooks only)
.claude/settings.local.json          144 B   2026-06-07   (allow list only)
.claude/launch.json                  490 B   2026-06-10   (two http.server harnesses)
.claude/agents/*.md                 20 .md (+ AGENT_REGISTRY, RUNTIME_AGENT_AUDIT)
.claude/hooks/pz-deploy-guard.py     117 lines
.claude/hooks/pz-frozen-file-guard.py 98 lines  (NEW since 2026-06-10)
.claude/commands/*.md                9 files
.claude/skills/                     4 entries (SKILL_REGISTRY, atlas-v2-render-gate,
                                                frontend-design, ui-ux-pro-max/)
.mcp.json                            ABSENT
hooks/pre-commit                     golden_constants regression guard
```

— end —
