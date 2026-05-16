# Campaign Runner — Operational Automation Controller

> Lightweight, file-based campaign tracker. No daemon, no DB. State lives in
> `tasks/campaign-state.json`; smoke evidence under `tasks/smoke-reports/`.
>
> Created by Operational Integrity + Automation Campaign — 2026-05-16.

---

## 1 — Goals

1. **Single source of truth for in-flight campaigns.** Every batch, every PR, every deploy, every smoke result is logged in one machine-readable file.
2. **No background process.** A Claude session reads the state file, updates it, commits. No daemon, no scheduler.
3. **Append-only audit history.** Each transition writes a new entry. The full timeline is reconstructible.
4. **Stop-condition encoded.** Each batch carries explicit blockers and an operator-checkpoint flag.
5. **Rollback evidence.** Each merge + deploy records the prior SHA so rollback is mechanical.

## 2 — Why file-based, not DB

- Campaigns are slow (hours-to-days per batch), not high-throughput.
- The state file is small (<50 KB even for 20+ batch campaigns).
- File-based state survives PZService restarts trivially.
- A 1-line JSON read + 1-line write replaces an entire SQLite layer.
- The state file is itself part of the PR — reviewers see the runner state move with the work.

## 3 — File layout

```
tasks/
├── campaign-runner.md                 ← this file (controller doc)
├── campaign-state.json                ← live state (JSON; the only mutable file)
├── master-data-campaign.md            ← legacy MDC-2026-05 controller (closed)
├── todo.md                            ← human-readable batch queue mirror
├── lessons.md                         ← append-only lessons log
├── smoke-reports/
│   ├── README.md                      ← format spec
│   ├── 2026-05-16-master-data-stack.md
│   ├── 2026-05-16-carriers-config.md
│   └── <YYYY-MM-DD>-<slug>.md
└── phase-6f-architecture.md           ← Phase 5 inspection report (no impl)
```

## 4 — State model (campaign-state.json)

```jsonc
{
  "schema_version": 1,
  "campaigns": [
    {
      "campaign_id": "MDC-2026-05",
      "title": "Master Data Completion",
      "status": "completed | active | blocked",
      "started_at": "ISO-8601",
      "closed_at":  "ISO-8601 or null",
      "batches": [
        {
          "batch_id": "B0",
          "title": "Customer Master 422 save fix",
          "status": "planned | active | pr_open | merged | deployed | smoked | blocked",
          "pr_url": "https://...",
          "pr_number": 98,
          "merge_sha": "b030382...",
          "deployed_sha": "b030382...",
          "deployed_at": "ISO-8601",
          "tests": {
            "customer_master": "82/82",
            "pz_regression":   "160/160"
          },
          "smoke_report": "tasks/smoke-reports/2026-05-16-b0-cm-422-fix.md",
          "block_reason": null,
          "next_batch": "B1"
        }
      ]
    }
  ]
}
```

## 5 — Allowed status transitions

```
planned   → active   → pr_open  → merged   → deployed → smoked   → (done)
                ↓           ↓          ↓          ↓          ↓
              blocked   blocked    blocked    blocked    blocked
```

`blocked` is reversible: clearing `block_reason` and re-setting status returns the batch to its previous open state. Any transition that loses data (e.g. setting `merge_sha = null`) is forbidden.

## 6 — CLI: `service/scripts/campaign_status.py`

```
python service/scripts/campaign_status.py list
python service/scripts/campaign_status.py show MDC-2026-05
python service/scripts/campaign_status.py update MDC-2026-05 B9 --status merged --pr 106 --sha e166c0e
python service/scripts/campaign_status.py block  MDC-2026-05 B3 --reason "security contract relaxation needed"
python service/scripts/campaign_status.py smoke  MDC-2026-05 B9 --report tasks/smoke-reports/2026-05-16-carriers-config.md
python service/scripts/campaign_status.py export MDC-2026-05         # markdown summary
```

The script is `argparse`-driven, ~250 lines, with full unit-test coverage. No HTTP, no service touch.

## 7 — Stop conditions (mechanical)

A batch MUST transition to `blocked` when ANY of:

1. `merge_sha` is set but `deployed_sha` is null after 24h
2. PR has > 2 open review threads
3. PZ regression < 160/160
4. Any source-grep contract test fails
5. wFirma live write or accounting calculation change attempted
6. `.env` modified
7. Direct production DB/storage edit attempted
8. Operator-gate explicitly required (B3 security, B6 schema sign-off)

A batch transitions to `smoked` only when ALL of:
- `merge_sha` set
- `deployed_sha` set
- `smoke_report` set and the report file exists
- `tests.pz_regression == "160/160"`

## 8 — Browser smoke report format

See `tasks/smoke-reports/README.md`. Each smoke report is a markdown file with:
- date
- batch id
- environment (local | production)
- route(s) tested
- per-test record: action / expected / actual / console errors / screenshot path
- summary verdict (PASS | FAIL | PARTIAL)
- artifacts left behind (e.g. test contractor IDs)

## 9 — Rollback evidence

Every transition to `deployed` records:
- `merge_sha` (= the new HEAD)
- `previous_main_sha` (= the SHA main was at before this PR merged)
- `rollback_command`: usually `git revert -m 1 <merge_sha> --no-edit`

For multi-PR deploys (e.g. forward-merge stacks), the controller records the SAME `previous_main_sha` for all PRs in that deploy, so rollback is one revert.

## 10 — Phase 6F handoff

The Phase 5 architecture report under `tasks/phase-6f-architecture.md` produces a list of proposed batches in this same JSON format. When the operator approves the architecture, those entries simply land in `campaign-state.json` with `status: "planned"`. No new tooling needed.
