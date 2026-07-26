# SEC-WAREHOUSE-APIKEY-1 — Ops Runbook

Fix for the confirmed authenticated-but-unsafe disclosure: `GET /api/v1/warehouse/config`
returned `settings.api_key` (the admin-equivalent inbound `X-API-Key`) to any authenticated
session. Route removed; warehouse writes role-gated (`require_api_key_privileged`); browser
authenticates by session cookie.

## Security invariant (binding on all steps)

> **No running version may expose the active `API_KEY`.**

The former `/warehouse/config` route violates this invariant. It must **never** run again
against a live `API_KEY`. This constraint overrides the normal "restore the previous artifact"
rollback pattern.

## Rollback — security-safe

**Preferred: FORWARD-FIX. Never restore the disclosure route.**
- Any defect found post-merge is fixed by a *new* commit on top, never by reverting PR #1034
  or restoring a pre-fix `C:\PZ\bak\app-pre-deploy-*` backup — both reintroduce
  `/warehouse/config` and would expose the (by-then rotated) key. `git revert` of this PR is
  **forbidden** while the key is live.
- Warehouse writes are additive auth-tightening + a route deletion; no schema/data change, so a
  forward-fix is always available (e.g. re-widen a write gate, correct a frontend call).

**Emergency rollback — ONLY if forward-fix is impossible, and ONLY under all of:**
1. **Isolate access first** — take the warehouse/inventory surfaces out of external reach
   (Cloudflare/edge block or service stop) before any restore.
2. **Revoke/replace the active key** — rotate `API_KEY` so the value the restored route would
   expose is already dead.
3. **Block `/api/v1/warehouse/config` externally** — edge rule returning 404/403 for that path,
   so even a restored artifact cannot serve the secret.
4. **Explicit security approval** — a named operator security sign-off, recorded.
5. **Shortest possible recovery window** — restore only to recover, then forward-fix and
   re-remove `/config` immediately; do not leave the disclosure route running.

## Credential rotation (operator; separate from the code deploy)

`API_KEY` → `Settings.api_key` = inbound admin/automation `X-API-Key` (`core/config.py`,
`core/security.py`). Rotation authority = the app's secret owner (self-issued shared secret);
if operator inspection shows the value is also a foreign-provider key, revoke it there too.

1. Generate a **new** `API_KEY` value.
2. Update `C:\PZ\.env` **and every X-API-Key automation consumer** out-of-band (never echo it).
3. Restart PZService separately (startup-bound setting).
4. **Verify — never send the compromised OLD key:**
   - NEW key, no session cookie → **authorized (2xx)**
   - no key, no session cookie → **rejected (401)**
   - freshly-generated INVALID value, no cookie → **rejected (401)**

## Automation compatibility

- **VERIFIED:** `require_api_key_privileged` retains the `X-API-Key` automation path
  (`core/security.py` — key checked before session), proven by
  `test_api_key_automation_executes_write`.
- **VERIFIED:** no non-browser warehouse HTTP caller was found in inspected source
  (no `.ps1`/tool/script calls `/api/v1/warehouse/*` with `X-API-Key`; only two browser pages).
- **UNKNOWN:** compatibility of any unseen/external automation not present in this repo. If such
  a caller exists, it continues to work via the retained key path but must be re-issued the new
  key at rotation.
