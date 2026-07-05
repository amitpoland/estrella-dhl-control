---
allowed-tools: Task, Read, Grep, Glob, Write
description: Read-only authority census; dispatches 5 inspectors, writes 6 reports to reports/authority-census/.
---

# /authority-census

Read-only authority census for Estrella PZ.
Dispatches 5 inspector subagents in parallel via Task.
Produces 6 deliverables in `C:\PZ-verify\reports\authority-census\<UTC-stamp>\`.

> **Tool budget:** `Task` fires inspectors; `Read` + `Grep` + `Glob` load skill
> templates and agent outputs only; `Write` emits the 6 deliverables. No
> `Bash` / `PowerShell` / `Edit` on this command — the orchestrator does not
> run shell and does not mutate any existing file. The census-guard hook
> confines every `Write` to `reports\authority-census\`.

**Base SHA recorded in every deliverable: `aa414d90`.**

**Capability:** READ-ONLY — census-guard.py blocks all writes outside `reports\authority-census\`.
Operator approval not required to run. No production action follows from census output.

---

## Pre-conditions (verify first; abort if any fails)

```powershell
# 1. Census mode must be active
if ($env:EJ_CENSUS -ne "1") { Write-Error "EJ_CENSUS must be 1 — abort."; exit 1 }

# 2. Source SHA (record actual SHA; warn if differs from aa414d90)
$sha = git -C "C:\PZ-verify" rev-parse HEAD
Write-Host "Source SHA: $sha"
if (-not $sha.StartsWith("aa414d90")) {
    Write-Warning "HEAD is $sha — expected aa414d90. Recording actual SHA in headers."
}

# 3. Clean working tree
$dirty = git -C "C:\PZ-verify" status --porcelain
if ($dirty) { Write-Warning "Uncommitted changes found — scanning committed content only." }
```

---

## Step 1 — Create output directory

```powershell
$stamp = (Get-Date -AsUTC -Format "yyyy-MM-ddTHHmmssZ").Replace(":", "")
$outDir = "C:\PZ-verify\reports\authority-census\$stamp"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Write-Host "Output directory: $outDir"
```

Record `$outDir`. All 6 deliverables write here.

---

## Step 2 — Dispatch 5 inspector subagents via Task (parallel)

### Hard rule — separation of duties

The orchestrator **does NOT scan `service/`, `atlas/`, `static/`, or any
application source itself**. Its only jobs are:

1. **Dispatch** the 5 inspector agents via the `Task` tool
2. **Collect** each agent's Markdown output verbatim
3. **Synthesize** the census-index counters from those outputs
4. **Write** the 6 deliverable files into `$outDir`

Any orchestrator-level `Read` / `Grep` / `Glob` against application source
(anything outside `.claude\`, `skills\authority-census\templates\`, or the
agents' returned text) is a discipline violation — the inspectors do the
scanning, the orchestrator does the writing. If a summary counter cannot be
derived from an inspector's output, re-dispatch that inspector with a
refinement prompt rather than reading source directly.

### Shared evidence standard

Every inspector prompt inherits these clauses (do not restate; they apply by
reference — the agent files already encode them, this is the orchestrator's
contract with the operator that they hold):

- **Root:** `C:\PZ-verify`
- **Base SHA:** `aa414d90` — record in the report header
- **Format:** return raw Markdown only — no chat preamble, no "Here is..." lead-in
- **Schema fidelity:** follow the report table schema in your agent-file exactly
- **Fact vs inference:** mark inferred rows with a trailing `(INFERRED)` tag
- **Sources block:** end the report with `## Sources` listing every file (and
  line-number range where relevant) that was read to produce the findings

### Launch — all 5 Task calls in a single message (parallel execution)

Send the following five `Task` tool calls in **one message** so they execute
concurrently. Do not send them serially and do not wait between them.

**Task 1 — Frontend Authority**

```
Task({
  subagent_type: "frontend-authority-inspector",
  description: "Frontend authority scan",
  prompt: "Produce the Frontend Authority Map per your agent contract at base SHA aa414d90 in C:\\PZ-verify (service/app/static/*.html + v2/*.jsx + atlas/*.html); obey the shared evidence standard and close with a ## Sources block."
})
```

**Task 2 — Backend Routes**

```
Task({
  subagent_type: "backend-route-inspector",
  description: "Backend route scan",
  prompt: "Produce the Backend Authority Map per your agent contract at base SHA aa414d90 in C:\\PZ-verify (service/app/api/routes_*.py cross-referenced with service/app/main.py); obey the shared evidence standard and close with a ## Sources block."
})
```

**Task 3 — Navigation**

```
Task({
  subagent_type: "navigation-inspector",
  description: "Navigation scan",
  prompt: "Produce the Navigation Map per your agent contract at base SHA aa414d90 in C:\\PZ-verify (index.html WIRED_PAGES/NAV_TREE/ROUTE_REDIRECTS + pz-design-v2.js + atlas-shared.js); obey the shared evidence standard and close with a ## Sources block."
})
```

**Task 4 — API Wrapper**

```
Task({
  subagent_type: "api-wrapper-inspector",
  description: "API wrapper comparison",
  prompt: "Produce the API Wrapper Comparison per your agent contract at base SHA aa414d90 in C:\\PZ-verify (static/pz-api.js vs static/v2/pz-api.js, cross-referenced with backend route existence); obey the shared evidence standard and close with a ## Sources block."
})
```

**Task 5 — Service / Scheduler**

```
Task({
  subagent_type: "service-scheduler-inspector",
  description: "Service and scheduler scan",
  prompt: "Produce the Service/Scheduler Map per your agent contract at base SHA aa414d90 in C:\\PZ-verify (service/app/services/*.py + main.py startup sequence, cross-referenced to route registration); obey the shared evidence standard and close with a ## Sources block."
})
```

### Deliverable mapping (from Task result → filename)

| Task | Inspector | Deliverable filename |
|---|---|---|
| 1 | `frontend-authority-inspector` | `01-frontend-authority-map.md` |
| 2 | `backend-route-inspector` | `02-backend-authority-map.md` |
| 3 | `navigation-inspector` | `03-navigation-map.md` |
| 4 | `api-wrapper-inspector` | `04-api-wrapper-map.md` |
| 5 | `service-scheduler-inspector` | `05-service-scheduler-map.md` |

Wait for all 5 Tasks to complete before proceeding to Step 3. If any Task
returns an empty or malformed body, re-dispatch **only that one** — do not
substitute orchestrator-side scanning as a fallback.

---

## Step 3 — Write deliverables 1–5

For each completed agent result, write `$outDir\<filename>` with this mandatory header
prepended before the agent's raw output:

```
# <Title>

**Base SHA:** aa414d90
**Census timestamp:** <stamp>
**Inspector agent:** <agent-name>
**Mode:** READ-ONLY — no app code was modified
---
```

Titles:
1. Frontend Authority Map
2. Backend Authority Map
3. Navigation Map
4. API Wrapper Comparison
5. Service / Scheduler Map

---

## Step 4 — Write deliverable 6: Census Index

Write `$outDir\00-census-index.md` using the template at
`skills\authority-census\templates\00-census-index.md` as the structure.

Fill in:
- Timestamp from `$stamp`
- File links for deliverables 1–5
- Summary counters extracted from the 5 agent outputs

---

## Step 5 — Completion check

```powershell
# All 6 deliverables must exist
$expected = @(
    "$outDir\00-census-index.md",
    "$outDir\01-frontend-authority-map.md",
    "$outDir\02-backend-authority-map.md",
    "$outDir\03-navigation-map.md",
    "$outDir\04-api-wrapper-map.md",
    "$outDir\05-service-scheduler-map.md"
)
foreach ($f in $expected) {
    if (-not (Test-Path $f)) { Write-Error "Missing deliverable: $f" }
}

# No app code touched
$dirty = git -C "C:\PZ-verify" status --porcelain |
    Where-Object { $_ -notmatch "reports.authority-census" }
if ($dirty) { Write-Warning "Unexpected dirty files outside census output: $dirty" }
```

Report the final `$outDir` path to the operator. Then stop — do not open PRs or make
recommendations for code changes in this session.
