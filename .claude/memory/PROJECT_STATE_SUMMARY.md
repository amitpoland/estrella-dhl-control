# PROJECT_STATE_SUMMARY.md

Compact snapshot for session startup. **This is the tracked state file.**

`.claude/memory/PROJECT_STATE.md` is **gitignored by design** (`.gitignore:20`, PR #901
— "stop tracking PROJECT_STATE.md, forward-exposure fix, Option A"). It does not exist in
a fresh clone, so a container-based session cannot read or update it. Sessions that need
the full FACTS / DECISIONS / ASSUMPTIONS / OPEN QUESTIONS record must read it on the
operator's machine. This file is what CI-cloned and remote sessions actually see.

Last updated: 2026-08-04 (test-isolation campaign). Update via `/update-state`.

---

## Current Session

- **Main HEAD:** `c7902bd6` — `fix(tests): pin storage attributes in the five global-singleton settings patchers (#1092)` (2026-08-04)
- **Open PRs:** none
- **Active task:** none — test-isolation campaign closed

---

## Open PRs (GATE 2: 0 of 3 impl slots used)

None. Queue fully clear as of 2026-08-04.

---

## Test-isolation campaign — closed 2026-08-04

Seven PRs, all test-only, no production surface. Every merge gated on a **failing
node-ID set-difference against the exact merge base**, never on a count comparison and
never on a green check (main's suite carries a large inherited red baseline, so green is
not obtainable).

| PR | Merge SHA | What | Node-ID result |
|---|---|---|---|
| #1063 | `542888a` | Hash-based shard assignment; false-green aggregate hole closed | — |
| #1073 / #1074 / #1076 | (merged) | Inherited red cleanup | — |
| #1075 | `0cd05196` | Cross-module asyncio loop pollution | **49 cleared, 0 new** |
| #1088 | `5d11f978` | `AUTH_SECRET_KEY` test-process bootstrap (replaced #1071) | **5 cleared, 0 new** |
| #1087 | `0fb61dc1` | Engineering Lesson Q + duplicate Lesson N letter → R | docs-only |
| #1090 | `79f28a90` | Two carrier suites writing MagicMock-named files | 0 cleared, 0 new; **11 junk files → 0** |
| #1091 | `6886a6b9` | conftest guard: any test writing a repr-named path fails, named | 0 cleared, 0 new |
| #1092 | `c7902bd6` | Pin storage attrs in the 5 global-singleton settings patchers | 0 cleared, 0 new |

**Inherited main failure count over the campaign: 775 → 665 → 616 → 611.** No branch
introduced a single new failure; collection and skip totals reconciled at every step, so
none of the reduction came from tests being skipped, deselected, or lost.

### Issue #1089 — closed, fully delivered

Two carrier suites wholesale-mocked `settings`, leaving `carrier_storage_root` as a
truthy auto-mock. Production resolves `settings.X or (settings.Y / "...")`, so the `or`
short-circuited onto the mock and the first `str()` coercion wrote a **SQLite database**
named `<MagicMock name='settings.carrier_storage_root.__truediv__()' id='...'>` (plus
`-wal`/`-shm` sidecars) into the pytest CWD. 11 reached commit `6091e2d9` before being
caught.

Delivered in three layers: **#1090** fixed the two live culprits, **#1091** added
repository-wide detection, **#1092** pinned the five highest-blast-radius global mocks.

**Two findings worth carrying forward:**

1. **The defect is invisible to CI by construction.** `<` and `>` are illegal in Windows
   filenames, so the write fails on `windows-latest` and every affected test passes there.
   It is a Linux/macOS developer-machine defect. This is why the #1091 guard was verified
   by a **full local six-shard run** (0 firings across ~21,574 tests) rather than by CI.
2. **Repo-wide sweep result (2026-08-04):** 141 settings-patch sites across 32 test files;
   `settings.storage_root` builds paths at **315** production sites vs `carrier_storage_root`'s 8.
   **Zero live creators remain.** 12 files are latent (safe by luck, not design) — the 5
   global-singleton ones are now pinned by #1092; the remaining 7 are module-scoped and
   deliberately left guarded rather than over-configured.

---

## Test Baselines

**Measured on CI (`windows-latest`, py3.9), main `c7902bd6` merge-base run:**

- Service suite: **21 566 collected — 20 830 passed, 611 failed, 0 errored, 125 skipped** (6/6 shards `complete`, 6 artifacts)
- Golden regression (engine): green
- Local (Linux) totals differ and are **not** comparable — 20 813 passed / 635 failed / 126 skipped — due to Windows-only tests and env-conditional carrier-credential tests. Use CI numbers for any gate.

Deploy-gate pass criteria remain `.claude/contracts/test-baseline.md`; nothing here supersedes it.

Older recorded baselines (2026-06-22, **not re-verified**): PZ regression 221/221, Golden 160/160, Carrier 420/420.

---

## Recent Architectural Decisions

1. **Node-ID set-difference is the merge gate (2026-08-04):** With a large inherited red
   baseline, a green check is unobtainable and a count comparison is unsafe. Every test-PR
   merge is gated on the failing node-ID set-difference against the exact merge base, with
   6/6 shards reporting and 6 artifacts present. A count comparison once hid a completely
   no-op fix (#1071's first attempt); only the empty set-difference revealed it.
2. **`.claude/memory/PROJECT_STATE.md` is operator-local (PR #901):** gitignored for
   forward-exposure. Remote/container sessions use this summary file instead.
3. **Lesson Q + Lesson N→R reletter (2026-08-04, #1087):** safety claims in state files
   require a source citation naming the implementing function, and a citation must be
   resolved against the revision under review. Duplicate lesson letter resolved; letter
   uniqueness pinned across both lesson files.
4. **Scripted multi-file edits must be AST-checked before commit (2026-08-04):** a
   scripted helper insertion landed inside a parenthesised import block; caught by an
   immediate `ast.parse` pass. That check is now part of scripted-edit verification.

Older decisions (2026-06-16 → 2026-06-22) — six-authority separation (Lesson R), tri-state
CIF authority, resolved-CIF backend guard, contractor-at-birth, proforma description
engine, `/feature` write-capable tier, skill routing authority, observation-period policy,
PR-2 Stage A/B separation — remain recorded in the operator-local PROJECT_STATE.md and in
CLAUDE.md. Not re-verified in this session.

---

## Current Blockers / Open Questions

- **Production deploy — Windows host only.** No Linux/container session can perform it
  (no `C:\`, no PowerShell, and the repo's own PZ deploy-guard blocks `C:\PZ` operations
  as operator-only). Sequence: fetch `origin/main` from `C:\PZ-main` → resolve the current
  full 40-char SHA → compare `service/app` → `C:\PZ\app` and all **16 governed engine
  files** → `C:\PZ\engine` **by content hash** → deploy only on a real runtime delta →
  closure → read-only Chrome verification. If both surfaces already match by hash, record
  the verified state and do **not** deploy.
  - Do **not** pin a SHA quoted by a container session; resolve it fresh on the host.
  - **Lesson P:** judge blast radius by `Get-FileHash` content diff, never by robocopy
    copy counts (a fresh worktree makes `/XO` re-copy everything on mtime).
  - `pz_calculator.py` and `audit_scoring.py` are root modules **not** in the governed
    16 — per the deploy config's own authority note they deploy NEVER. If either differs
    under `C:\PZ\engine`, that is a finding, not something to sync.
- **Open issues, independent and non-blocking:** #1084 (unbounded `PyJWT` pin + no
  per-request `auth_secret_key` guard), #1085 (`tests/baselines/` has no staleness
  signal), #1086 (lifespan-startup hang that can kill a shard), #1068
  (`_pin_settings_singleton` cannot reach a module first imported mid-divergence), #1069
  (CLAUDE.md records 748 pytest files; the tree has ~974).
- **Stale, not re-verified this session:** the 2026-06-22 open questions (OQ-PR726/708/677
  merge + deploy, OQ-PR694/709 agent tuning). Those PRs are long merged; their deploy
  status was not checked here and must be re-derived before being acted on.

---

## Production State

- Service: `PZService` (NSSM, port 47213) at `C:\PZ`; public: `https://pz.estrellajewels.eu`
- **Deployed SHA: UNKNOWN from this session.** Must be resolved on the Windows host by
  content hash against a freshly fetched `origin/main`. The 2026-06-22 record said
  "pre-`282fbaf`"; that is six weeks stale and must not be relied on.
- Nothing in the 2026-08-04 test-isolation campaign touched a production surface — all
  seven PRs are test-only. Production is unchanged by them.
- Auth and wFirma flag posture: recorded 2026-06-22, **not re-verified this session**.

---

*Full FACTS / DECISIONS / ASSUMPTIONS / OPEN QUESTIONS: `.claude/memory/PROJECT_STATE.md`
— operator-local, gitignored, unavailable to container sessions.*
*Startup protocol: read this file first.*
