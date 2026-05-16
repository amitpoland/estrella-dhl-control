# Browser Smoke Reports

> Each smoke run produces one markdown file in this directory. The
> `campaign_status.py smoke …` command attaches the report path to the
> matching batch's state entry.

## Filename convention

```
YYYY-MM-DD-<slug>.md
```

`slug` is short, kebab-case, and identifies the entity or batch (e.g.
`carriers-config`, `master-data-stack`, `b9-post-deploy`).

## Required sections

```markdown
# Smoke report — <title>

**Date:** YYYY-MM-DD
**Campaign:** <id>
**Batch(es):** <id>[,<id>...]
**Environment:** local | production
**Tester:** <name or "claude-session">

## Coverage

| Route                                      | Action                | Expected | Actual | Console | Verdict |
|--------------------------------------------|-----------------------|----------|--------|---------|---------|
| /api/v1/suppliers/                         | POST minimal supplier | 201      | 201    | clean   | PASS    |
| /dashboard/dashboard.html#master           | open Master Data page | renders  | renders| clean   | PASS    |
| ...                                        | ...                   | ...      | ...    | ...     | ...     |

## Console errors

(paste any console.error / network 4xx/5xx here; "none" if clean)

## Artifacts left behind

- supplier id=12 named "Smoke Test Co" — clearly labelled; safe to leave
- ...

## Verdict

**PASS** | **FAIL** | **PARTIAL** — <one-line reason>

## Screenshots

If captured, list paths (relative to repo root) here. Optional.
```

## Driver script

`service/scripts/run_smoke.py` is an executable runbook that:
1. Reads a smoke-spec YAML (or inline list).
2. For each step: hits the route, records actual vs expected.
3. Writes a draft markdown report into this directory.
4. Returns non-zero exit if any step FAILed.

It does NOT replace operator-driven browser smoke for visual checks —
it covers the API-equivalent contract, which is sufficient for most
local CRUD entities.

## Rules

- Never store credentials, real customer PII, or non-test artifacts in smoke
  reports.
- Test artifacts (rows created during smoke) must be deleted at end of smoke
  OR labelled clearly so they can be identified later.
- Reports are append-only artefacts of campaign work — once written, do not
  rewrite history.
