# /deploy — Production Deploy

This document **explains** the deployment. It does not perform it, and it must never
contain executable deployment commands — prose-as-script is what created 29 competing
deployment scripts. Pinned by `service/tests/test_deploy_authority.py`.

## The authority model

| Responsibility | Sole owner |
|---|---|
| Configuration | `.claude/deploy/windows_prod_v2.json` |
| Execution + rollback | `.claude/deploy/Deploy-PZ.ps1` |
| Validation (read-only) | `.claude/deploy/Test-PZDeployClose.ps1` |
| Policy / governance | `service/docs/production_deployment_rule.md` |
| Required test counts | `.claude/contracts/test-baseline.md` |
| Pre-deploy review | the 7 `.claude/agents/deploy_*.md` agents |

Every production path, engine filename, and robocopy flag lives in the configuration.
Nothing is hardcoded anywhere else.

## What the operator runs

```
Deploy-PZ.ps1 -WhatIf                      # plan only, writes nothing
Deploy-PZ.ps1                              # halts at DEPLOYMENT_READY_AWAITING_GATE
Test-PZDeployClose.ps1 -ExpectedSHA <sha>  # read-only close conditions
Deploy-PZ.ps1 -Rollback -Unit <unit>       # restore a validated backup unit
```

Options: `-Scope App|Engine|Both`, `-Bootstrap` (first-ever deploy, no rollback target).

## Why the agent cannot deploy

`pz-deploy-guard.py` denies agent invocation of the deployment script **by script
name** — the script is configuration-driven, so its command line carries no production
path token and the path-based rule alone would not see it. Independently, the script
refuses every production-write phase unless the operator token named by
`operator_token_env` is present. The guard blocks the agent; the script also blocks
itself.

## Order of operations

Preflight (source identity, clean, no local-only commits) → capture the incoming
commit range → **7-agent gate reviews that range** → fast-forward only after approval,
aborting if `origin/main` moved → tests against the baseline contract → stage the
immutable hash-manifested artifact → back up application + engine as one restorable
unit → inventory destination-only paths → stop the service → converge production to
the artifact → engine sync (Lesson J) → verify against the manifest → write the
version file → start the service → validate.

The gate reviews the commits that will actually ship. A deploy whose reviewed range is
empty is structurally impossible.

## Rollback

Rollback restores a manifest-validated backup unit and **never** touches the certified
source's git history. `git revert`, `git reset`, and historical checkout are forbidden
as production rollback.

After a rollback the source may already sit at the reviewed SHA, so the next run
reports `NOTHING TO DEPLOY`. That is expected: re-run the same reviewed SHA if the
failure was transient, or push a fix commit if the release itself was bad.

## Disaster recovery without the script

Backup units carry `app.manifest.csv` and `engine.manifest.csv` (SHA256). If the script
is unavailable, an operator can restore a unit by hand and verify it against those
manifests. Recovery does not depend on this file.
