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

`-ReviewedSHA` is **required** for a deploy. It is the exact SHA the 7-agent gate
approved. The target is never inferred from `origin/main`, so a commit pushed after
the gate ran cannot ship.

```
# 1. plan only - writes nothing, needs no authorization
Deploy-PZ.ps1 -WhatIf -ReviewedSHA <40-char-sha>

# 2. run the 7-agent gate against that SHA, out of band

# 3. mint a single-use authorization for the approved SHA (operator shell)
python .claude/hooks/sign_deploy_authorization.py <40-char-sha> deploy Both --ttl 60

# 4. deploy
Deploy-PZ.ps1 -ReviewedSHA <40-char-sha>

# 5. validate (read-only)
Test-PZDeployClose.ps1 -ExpectedSHA <40-char-sha>
```

Options: `-Scope App|Engine|Both`, `-Bootstrap` (first-ever deploy, no rollback
target), `-ForceUnlock` (clear a lock whose process is provably gone).

**Rollback needs its own authorization.** Mint it *before* you need it - doing so
mid-incident costs time you will not have:

```
python .claude/hooks/sign_deploy_authorization.py <sha> rollback Both --ttl 1440
Deploy-PZ.ps1 -Rollback -Unit <unit>
```

## Provisioning (once per machine, before the first deploy)

Until a signing key exists, **every deploy and rollback is denied**. That is the
intended fail-closed default, not a fault. Provisioning instructions - key generation,
the two environment variables, and the artifact store location - are at the top of
`.claude/hooks/sign_deploy_authorization.py`. The key must live outside this
repository.

## Why the agent cannot deploy

`pz-deploy-guard.py` denies agent invocation **by script name** - the script is
configuration-driven, so its command line carries no production path token and the
path-based rule alone would not see it. The same name-matching covers the runtime
configuration writers (`env_config_manager.ps1`, `activate_pz_lifecycle.py`), which
write the production `.env`.

Independently, every production-write phase requires a **signed, SHA-bound, single-use
authorization** (`deploy_authorization.py`): HMAC-SHA256 over the reviewed SHA, action
and scope, with the key held outside the repository. An agent that can read every file
here still cannot mint one. The guard blocks the agent; the script also blocks itself.

## Order of operations

Preflight (source identity, clean, no local-only commits) -> validate `-ReviewedSHA`
(format, exists, descends from HEAD, equals `origin/main`, refuse if origin advanced
beyond it) -> fast-forward to it -> **authorization** -> take the lock -> **stop the
service** -> stage the immutable artifact -> back up application + engine as one
restorable unit -> inventory destination-only paths -> converge production to the
artifact -> engine sync (Lesson J) -> verify against the manifest -> write the version
file -> start the service -> validate.

The service stops **before** staging and backup, so the backup is a consistent
snapshot of a quiescent tree. That widens the downtime window compared with backing up
a live tree - a deliberate trade, because a backup taken from a running service is not
a reproducible restore point.

Tests are **not** run by the script. Run them before the gate; required counts come
from `.claude/contracts/test-baseline.md`.

A deploy of a SHA the gate did not review is refused.

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
