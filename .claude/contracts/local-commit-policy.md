# LOCAL-COMMIT-ONLY Deploy Policy (Lesson D)

Applies when a commit is deployed to `C:\PZ` without a merged PR on `origin/main`.
Referenced by: `deploy_lead_coordinator.md`, `deploy_release_manager.md`.

Governance layer: 7-agent deploy gate.
Precedence: see `.claude/contracts/governance-precedence.md` § "GATE 1 vs LOCAL-COMMIT-ONLY".
Origin: Lesson D, Wave 1 closure 2026-05-13.

---

## Detection

Run before any deploy decision:

```bash
git branch -r --contains $(git rev-parse HEAD)
```

`origin/main` listed → standard deploy. This policy does not apply.
`origin/main` NOT listed → LOCAL-COMMIT-ONLY. Proceed to disclosure check.

---

## Disclosure header (required fields)

The gate report must contain ALL four fields before coordinator may issue READY-TO-DEPLOY:

```
SHA being deployed: <full 40-char SHA>
GitHub PR: NONE — this SHA is not on origin/main
Bypass reason: <one of: production-incident-timing | production-only-machine | toolchain-failure>
Reconciliation plan: <when and how the reconciliation PR will be filed>
```

Any field absent or blank → **block**. Output missing fields. Instruct operator to complete and re-run gate.

---

## Coordinator output block (when disclosure is complete)

Add this to the coordinator decision and require explicit acknowledgment before READY-TO-DEPLOY:

```
⚠ LOCAL-COMMIT-ONLY DEPLOY DETECTED
SHA: <sha>
PR trail: NONE
Bypass reason: <from header>
Reconciliation plan: <from header>
Operator acknowledgment required: "I acknowledge LOCAL-COMMIT-ONLY"
```

Do not issue `DECISION: READY-TO-DEPLOY` until the operator sends that exact phrase in chat.

---

## Release Manager responsibility

Release Manager detects LOCAL-COMMIT-ONLY independently via the same `git branch -r` command.

- Disclosure absent → `BLOCKER — LOCAL-COMMIT-ONLY without disclosure (Lesson D)`
- Disclosure present → `CLEAR — LOCAL-COMMIT-ONLY disclosed` (coordinator handles acknowledgment gate)

---

## Audit record

Every LOCAL-COMMIT-ONLY deploy appends one JSON line to `.claude/memory/local-commit-deploys.jsonl`:

```json
{"date": "YYYY-MM-DD", "sha": "<full SHA>", "bypass_reason": "<reason>", "reconciliation_plan": "<plan>", "operator_ack": "I acknowledge LOCAL-COMMIT-ONLY"}
```

---

## Reconciliation

A reconciliation PR must be filed before the next `git pull --ff-only origin main`.
Run `git log origin/main..HEAD` on the production machine to detect unreconciled commits.
Soft requirement (non-blocking) tracked in the audit record.

---

## Constraints

- Lesson D disclosure does NOT bypass test pass criteria. Failing tests block regardless of commit origin.
  See `.claude/contracts/test-baseline.md` for required counts.
- Lesson D does NOT relax GATE 1. GATE 1 governs PR opening; no PR means GATE 1 is not triggered.
- This policy applies only within the 7-agent deploy gate.
