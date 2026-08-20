# Session Performance Guard

**Status:** measured and binding · **Established:** 2026-08-20 · **Scope:** Claude Code session
health on this workstation. Nothing here touches the PZ application runtime, production data,
`PZService`, or the deployment authority.

This document is the evidence base. The binding one-paragraph rule lives in `CLAUDE.md`
(§ *Session performance guard*); everything below is why each clause says what it says.

Governs Claude Code session behaviour only. It is **subordinate** to the OPERATING MODEL, the
Engineering Lessons and the seven-agent gate, and it never relaxes a security or governance
control.

---

## 0. What this replaces

The compaction-thrashing root cause was found and fixed on 2026-08-20: the persistent
`CLAUDE_CODE_DISABLE_1M_CONTEXT=1` in `HKCU\Environment` had been pinning Opus 5 to the 200 K
boundary. **That investigation is closed.** This document is the next layer: detect degradation
early, keep avoidable context growth out, and prove performance claims with measurement.

---

## 1. Reference baseline (2026-08-20)

Every number below was measured on this workstation, session `f757d746`, PID 3852, and is the
comparison point for any future performance claim. **Re-measure before relying on it** — a
baseline is memory, the machine is the authority (Lesson Q rule 3).

### 1.1 Environment

| Fact | Value |
|---|---|
| Claude Code (agent process) | **2.1.234** (CLI on `PATH` had self-updated to 2.1.236 — record the agent's version, not the CLI's) |
| Node | v24.15.0 · entrypoint `claude-desktop` |
| Model / effort | `claude-opus-5` / `high` |
| `CLAUDE_CODE_DISABLE_1M_CONTEXT` | **absent** — process env and `HKCU\Environment` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | unset |
| Effective context window | **1,000,000** |
| Machine at capture | CPU 21.2 % · RAM 15.94 GB total / 7.33 GB free · 16 `claude.exe`, 8 `node`, 2 `python` · **4 concurrent interactive sessions** |

### 1.2 The 1M window — two independent proofs

Both are recorded because a single proof of an *absence* is the highest-risk kind of claim
(Lesson Q rule 7).

1. **Static, from the running binary** (`claude.exe` 2.1.234, the build this session actually
   runs): the model table carries `claude-opus-5 … window:1e6, native_1m:!0,
   supports_1m_beta:!0`; the disable-flag gate resolves undefined; `ANTHROPIC_BASE_URL` is
   `https://api.anthropic.com`, so the first-party branch is taken.
2. **Behavioural, from this session**: occupancy reached **223,932 tokens with zero
   compactions**. The immediately-preceding pre-fix session compacted at **162,407** and its
   all-time ceiling was **212,204**. Passing both, without a single compaction record, is
   observed behaviour rather than inference.

### 1.3 Static context floor

| Surface | Tokens |
|---|---|
| Interactive Desktop session, this repo | **122,731** (12.3 % of the window) |
| Headless `claude -p`, same settings | 68,630 |
| Headless with all customizations off (`--safe-mode`) | 26,425 |

Sizes on disk: project `CLAUDE.md` 49,695 B · user `CLAUDE.md` 9,300 B · `MEMORY.md` 19,911 B ·
auto-memory dir 189 files / 1.5 MB.

### 1.4 Latency

Command level, 7 reps each (ms, p50 / p95 / max):

| Probe | p50 | p95 | max |
|---|---|---|---|
| trivial bash (`true`, `echo`) | 18 | 20 | 21 |
| `git status --porcelain` | 64 | 79 | 85 |
| `git log --oneline -10` | 56 | 58 | 59 |
| `python -c pass` | 67 | 69 | 69 |
| `python -c "import json,os,sys"` | 88 | 90 | 90 |
| read 50 KB file | 35 | 36 | 36 |
| repo-wide `grep -rl` | 121 | **3,708** | **5,244** |
| `find … \| wc -l` | 91 | 101 | 104 |

The `grep` p95/max is a **cold filesystem cache on first search** — subsequent searches run at
p50. Budget for it once per session; do not read it as a steady-state cost.

End-to-end, from this session's own transcript:

| Measure | n | p50 | p95 | max |
|---|---|---|---|---|
| Model turn latency (user/tool → assistant) | 21 | **6,588** | 15,692 | 20,077 |
| `Bash` tool round-trip (incl. hooks + harness) | 22 | **2,238** | 5,967 | 13,767 |

**Where a 2,238 ms Bash round-trip goes:** ~20–150 ms command + ~105 ms hooks + **~2,000 ms
harness**. The hooks are not the bottleneck and the classifier is not either (§4, §5).

---

## 2. Safe-mode A/B (n = 5 per cell, cleaned env, identical model/prompt/repo)

Wall-clock median, headless:

| Arm | P1 (no tools) | vs normal | P2 (one Bash call) | vs normal |
|---|---|---|---|---|
| normal | 6,535 ms | — | 8,606 ms | — |
| `--permission-mode acceptEdits` | 6,292 ms | −3.7 % | 9,511 ms | **+10.5 %** |
| `--safe-mode` | 3,690 ms | **−43.5 %** | 6,139 ms | **−28.7 %** |
| `--bare` | *(failed)* | — | *(failed)* | — |

Three results, each of which contradicts a plausible assumption:

- **`--bare` is not a performance option here.** All 10 runs returned
  `is_error: true, "Not logged in — Please run /login"` with 0 tokens and
  `duration_api_ms: 0`. It requires `ANTHROPIC_API_KEY` and cannot authenticate on this OAuth /
  Max-plan setup. Its 1.3 s "result" was a fast *failure*. **A fast arm that did no work is not
  a fast arm** — check `is_error` and token counts before reading any A/B cell.
- **Auto mode's permission classifier is not the per-call cost.** `acceptEdits` removes the
  classifier and was *slower* on the tool-using prompt. Do not weaken permission handling for
  speed.
- **Safe mode is materially faster, and the reason is context size, not customization
  machinery.** It carries 42,205 fewer static tokens (26,425 vs 68,630) and its median
  time-to-first-token is 1,578 ms vs 2,139 ms — **≈560 ms per turn** attributable to the larger
  prompt.

**Interpretation.** ~560 ms/turn against a 6,588 ms p50 turn is ≈8 %. That does not justify
disabling governance, skills or memory, all of which exist for correctness reasons. It does
justify not *growing* the static surface without a reason, and it prices any future proposal to
add to it.

---

## 3. Where context actually goes

Corpus: 25 real sessions, 1,042 tool results, ~1,020,557 estimated tool-result tokens.

| Tool | Calls | Tokens | Share | Largest single |
|---|---|---|---|---|
| **Read** | 223 | **631,186** | **61.8 %** | 18,253 |
| Bash | 548 | 270,534 | 26.5 % | 4,477 |
| Grep | 189 | 94,691 | 9.3 % | 4,376 |
| Glob | 38 | 11,293 | 1.1 % | 2,438 |
| everything else | 44 | 12,853 | 1.3 % | 5,213 |

Within shell output: file reads 55.2 %, searches 28.4 %, **test runs only 5.8 %**, git history
3.9 %.

`Read` in detail: p50 **1,221** · p90 10,324 · p99 17,542 · max 18,253.

- **98 whole-file reads (no `offset`/`limit`) = 490,871 tokens = 77.8 % of all Read and ~48 % of
  every tool token in the corpus.**
- Re-reading a path already read in the same session: **76,239 tokens (12.1 %)**. Worst
  offenders: the production deploy runbook script (11,675), `proforma_invoice_link_db.py`
  (10,294), `main.py` (8,370).
- Tokens above a 1,500-token-per-read cap: 395,340 — **62.6 % of Read from just 91 calls.**

**The intuition to discard:** pytest output, logs and JSON blobs are *not* the problem here
(test runs are 1.6 % of all tool tokens). Whole-file reads of large service modules are.

### 3.1 The model's own output is the larger source

Measured on this session, deduplicated by `requestId` (streaming records repeat `usage`, so a
naive sum roughly doubles it — dedupe or the number is wrong):

| | Tokens | Share of growth |
|---|---|---|
| Context growth over 50 API requests | 101,201 | — |
| Tool results | 17,672 | 17.5 % |
| Assistant output emitted (mean 1,350/request) | 67,483 | ~2/3, upper bound |

Once tool output is disciplined, **the assistant's own prose, thinking and tool inputs dominate
context growth.** Output hygiene therefore binds the agent's reports, not only its tools.

---

## 4. Hooks — measured, kept

Five `PreToolUse` hooks fire on every `Bash`/`PowerShell` call. Per-hook, 7 reps, benign payload
(ms, p50 / p95 / max):

| Hook | p50 | p95 | max |
|---|---|---|---|
| `campaign-branch-guard` | 107 | 139 | 151 |
| `pz-deploy-guard` | 92 | 106 | 110 |
| `implement-guard` | 91 | 109 | 116 |
| `pz-danger-guard` | 91 | 98 | 98 |
| `census-guard` | 90 | 94 | 96 |

They run **in parallel**: sum of p50 is 471 ms, max of p50 is **107 ms**, and the observed
real-world cost matches the max, not the sum. *(This supersedes any earlier note quoting ~333 ms
or ~471 ms as the hook cost — that was a sum of parallel timings.)*

~107 ms is **4.7 %** of a 2,238 ms Bash round-trip, and essentially all of it is Python
interpreter startup: the interpreter alone is 67 ms, the guards import only `sys/re/json/os`.
`python -S` saves ~13 ms.

**Verdict: KEEP all five, unchanged.** They are security and governance guards; 13 ms is not a
reason to touch a guard, and consolidating five parallel spawns into one saves nothing because
the cost is bounded by the slowest, not the sum. `pz-regression-postedit` (`PostToolUse`,
timeout 120 s) runs the golden suite only for root-level `.py` edits and exits silently
otherwise — correctly scoped, kept.

### 4.1 Known false positive (backlog, not a fix here)

`pz-deploy-guard` matches **literal command text**, so a shell command that merely *mentions* a
protected script — writing documentation about it, or grepping for it read-only — is blocked as
though it were invoking it. This was hit while authoring this very document. The correct
response is to use a tool that matches on path rather than command text (`Write`/`Edit`), **not**
to reword around a security control. Intent-aware matching remains a backlog item; the guard
stays fail-closed until then, which is the right default.

---

## 5. MCP and plugins — measured, kept

| Arm | Static tokens | Wall (P1) |
|---|---|---|
| normal | 68,630 | 6,535 ms |
| `--strict-mcp-config` with an empty server set | 65,164 | 6,866 ms |

**MCP tool schemas cost 3,466 tokens and produce no measurable speedup when removed.** Deferred
tool loading (`ToolSearch` surfaces tool *names*, and schemas load on demand) has already
solved this. The remaining 38,739 tokens are skills, plugin catalogs, `CLAUDE.md` and memory.

**Do not disable MCP servers for performance.** There is no measurement supporting it. The
Desktop entrypoint adds a further ~54,000 tokens over headless (agent list, skill catalog,
deferred tool names); that is a Claude-side surface, not something to be fixed by removing
capability.

Subagent output is likewise not a problem here: `Agent` results were 5.7 % of tool tokens in the
heaviest session and 0.1 % across the corpus. No change is justified beyond §6's return format.

---

## 6. Binding rules

### 6.1 Output hygiene — full evidence to disk, decisive evidence to the conversation

1. **Never `Read` a large file whole.** Locate first (`Grep`/`rg` with line numbers), then read a
   bounded range. A read is "large" at ~1,500 tokens; 62.6 % of all Read cost sits above that
   line.
2. **Never re-read a path already read this session** — 12.1 % of Read cost was pure repetition.
   Re-read only after the file has actually changed.
3. **Tests report a verdict, never a transcript.** Run to `--junitxml`, read the XML, return
   verdict + counts + failing node IDs against the floors in
   `.claude/contracts/test-baseline.md`. **An exit status is execution evidence, never
   authorization** — the carrier suite exits 1 with 758 passed against a 604 floor.
4. **Logs, JSON and process inventories are queried, not dumped.** Narrow window, selected
   fields, bounded result count; the full artifact goes to a file whose path is cited.
5. **Bound every search and listing** and refine rather than widening.
6. **Errors are never hidden.** Bounding output must never suppress a failure, a stack trace's
   decisive frame, or a non-zero exit — those are the evidence. If truncation drops something,
   say what was dropped and where the full copy is.
7. **The agent's own reports are bounded too**, for the reason in §3.1: state the conclusion and
   the evidence that carries it, cite paths for the rest.
8. **Subagents return** DECISION / EVIDENCE REFERENCES / NEW FINDINGS / BLOCKERS / RECOMMENDED
   ACTION, with detail written to durable files. This is a format rule; it never removes an
   independent review.
9. **`PROJECT_STATE.md` is 1.06 MB (~300 K tokens) — never read it whole.** Read
   `PROJECT_STATE_SUMMARY.md` (8.9 KB), or grep the large file for the specific fact. A single
   whole-file read would consume ~30 % of the window in one call.

### 6.2 Session degradation — measured triggers, not folklore

Compare against the **fresh baseline for the session's own model and effort**, re-measured, not
against the table in §1.4 assumed to still hold.

| State | Any one of |
|---|---|
| **WARN** | context ≥ 60 % of window · 2 compactions · repeated model turns > 3× fresh p95 (>47 s at the §1.4 baseline) |
| **DEGRADED** | context ≥ 80 % of window · ≥ 3 compactions · **two compactions inside 10 minutes** · post-compaction floor leaves < 25 % headroom · repeated model turns > 5× fresh p95 (>78 s) |

"Repeated" means sustained across turns, not one slow turn — a single long turn is usually a
large tool result or machine contention. **Session age alone is never a degradation signal**: a
6-hour session at 15 % occupancy with baseline latency is healthy, and killing it would destroy
working state for nothing.

### 6.3 Fresh-session handoff

On DEGRADED: **checkpoint → reconcile → exit → fresh session → reconstruct from durable state.**

Checkpointing is not optional and is not "write a summary in chat". Run:

```bash
python .claude/scripts/session-handoff.py --objective "..." --next "exact next command"
```

It collects worktree, branch, HEAD, ancestry vs `origin/main` (via `git merge-base
--is-ancestor` — behind, not diverged), changed paths, stash depth and live session-owned
processes, prints a paste-ready block for `.claude/memory/TASK_STATE.md`, and writes full detail
to a cited file. It **extends the existing TASK_STATE.md authority and never writes to it
itself** — what to persist is a judgement, and silently rewriting the state file would destroy
the audit trail it exists to keep.

The successor session **validates the checkpoint before acting** (branch / HEAD / diff) and
executes the single recorded next action. It does not re-plan work that is still valid — this is
`EXECUTION_BLOCKED`, resumable, not restartable (`anti-hold-and-completion.md` §7).

**Transcripts are preserved by default.** They are the audit trail; never mass-delete them, and
never delete one a Claude process still owns.

### 6.4 Compaction health

With the 1M window active, compaction should be **rare** in an ordinary campaign. Repeated rapid
compaction is a **performance incident**, diagnosed in this order:

1. verify the effective window (both proofs, §1.2);
2. verify `CLAUDE_CODE_DISABLE_1M_CONTEXT` and `CLAUDE_CODE_AUTO_COMPACT_WINDOW`;
3. measure occupancy and the post-compaction floor;
4. identify what refills the context (rank it — §3's method, not intuition);
5. inspect re-injection and hooks.

**Do not shrink `CLAUDE.md` again as a reflex.** THIN-A cut it 33 % (−8,212 static tokens) and
changed nothing, because the floor was never the lever. **Do not invoke `/compact` repeatedly** —
that is the symptom being treated as the cure.

### 6.5 Cache and junk

Inspect, classify, then act — never mass-delete. Classify every candidate as **ACTIVE /
AUDIT-VALUABLE / RECREATABLE / STALE / UNKNOWN** and remove only STALE items that are safely
reconstructable, following the ≥500 MB pre-deletion checklist in the user's workstation rules.

**Never deleted for performance:** session transcripts · memory · project state · credentials ·
Claude-internal databases · anything UNKNOWN. There is no measurement in this campaign
supporting a cache wipe, and none was performed.

### 6.6 Process hygiene

Identify processes by **PID, parent, command line, creation time and port — never by image
name**, and never with an image-wide kill (Lesson S rule 6). Temporary jobs a campaign starts are
terminated when it closes; anything intentionally left running is reported. Service-managed
processes (`PZService` and its NSSM parent) are never touched.

---

## 7. Status-line telemetry

`.claude/statusline/session-health.py`, wired in `.claude/settings.json`, renders:

```
CTX 184K/1.0M 18% | AGE 38m | CMP 0
```

with `WARN`/`DEGRADED` appended when §6.2 fires.

**Every field comes from the payload Claude Code already pipes in on stdin** — `context_window.
{total_input_tokens, context_window_size, used_percentage}` and `cost.total_duration_ms`. No git
call, no network call, no MCP query, no transcript scan. Compaction count is not in the payload
and is *derived*, not scanned: a compaction is the only event that makes occupancy fall sharply,
so a tiny per-session state file tracks last/max occupancy and the previous compaction time,
keeping the count O(1) instead of O(transcript).

**Measured cost — disclosed, not rounded down: p50 87–104 ms, p95 94 ms in a quiet window**, of
which ~57 ms is Python startup (`-S`). That is **above** the <100 ms target this campaign set.
It is accepted on the basis of measured invocation policy rather than hope:

- the render effect depends on `lastAssistantMessageId` and `tokenUsage` — per **turn**, not per
  frame;
- state changes are debounced at **300 ms** (`oGw = 300`);
- `refreshInterval` is undefined by default, so there is **no periodic re-run** — do not set one;
- execution is **awaited asynchronously and off the model's critical path**.

At ~1–3 invocations per 6,588 ms turn that is ≈1.5–4.5 % of turn time, async. The state file
also counts its own invocations (`n`), so this claim can be re-audited from any real session
without adding instrumentation. **If a future measurement shows it running per-frame or costing
materially more, remove it** — that is the same evidence test that admitted it.

The script fails silently to a minimal line and exit 0 on any error. A status line must never
wedge a session.

---

## 8. Standing principles

1. One campaign per session; prefer a fresh session after closure.
2. A session known to be degraded is not reused for a new campaign.
3. Full evidence to artifacts; bounded decisive evidence to the conversation — including the
   agent's own reports.
4. Large logs and test output are never streamed when a verdict will do.
5. Context health is observable (§7).
6. Repeated rapid compaction is a performance incident (§6.4).
7. A degraded session checkpoints before exit (§6.3).
8. Transcripts are preserved by default.
9. **Every performance change requires before/after measurement.** No measurement, no claim.
10. Security, permission and governance controls are never disabled for speed. Every such lever
    tested here (auto-mode classifier, hooks, MCP) was measured and found *not* to be the cost.
11. No unsupported Claude configuration tweaks — only documented flags and settings.
12. **Verify the arm did work before believing it was fast** (`--bare`, §2).

---

## 9. Reproducing this

Measurement tooling used here is throwaway by design and lives in the session scratch dir, not
the repo: transcript occupancy/tool-token scanner, end-to-end turn/round-trip timer, the A/B
sweep harness, and the per-hook timer. Re-derive them from §1–§5 rather than trusting a stale
copy. What *is* durable, versioned and reviewable is what a future session actually needs:
`.claude/statusline/session-health.py` and `.claude/scripts/session-handoff.py`.
