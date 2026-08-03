# Measured test baselines

Recorded failure sets from a specific, reproducible measurement. They exist so a
future change can be judged by **set-difference against a known list** rather
than by a count, which is the distinction that caught a no-op fix (see below).

These are evidence, not contracts. `.claude/contracts/test-baseline.md` remains
the single source of truth for deploy-gate pass criteria; nothing here overrides
or supplements it. Nothing in the repo reads these files — they are read by
people, not by CI.

---

## `auth-session-file-set.txt` — the measured scope, as measured

The 77 test files the measurement actually ran. **The selector that produced it
was flawed**; it is preserved verbatim because the recorded failures below
correspond to *this* set and no other. Do not regenerate this file — see
*Corrected selector* for future work.

The selector used was:

```
auth.service | create_session_token | create_access_token | pz_session
| require_admin | get_current_user | jwt.
```

Two of those seven alternatives — `create_session_token` and
`create_access_token` — **match nothing in this repository**. The function that
actually mints tokens is `create_token`, and the setting under change,
`auth_secret_key`, was not in the pattern at all. Consequences:

- `test_atlas_v2_sprint1.py` and `test_debug_health_endpoints.py` were excluded
  despite patching `auth_secret_key` directly;
- `test_auth_forgot_password_email.py` is excluded and *is* affected — it posts
  `/auth/login`, whose handler is the only caller of `create_token`. It reaches
  the token path through the route, which is exactly the indirect case the
  "symbol grep, not a call-graph analysis" caveat describes.

So "nothing regressed" below is proven **over this set**, not over the affected
surface. That is a completeness gap in the evidence, not a known defect.

### Corrected selector, for future measurements

```bash
grep -rln --include="*.py" --exclude=conftest.py \
  "auth\.service\|create_token\|pz_session\|require_admin\|get_current_user\|auth_secret_key\|jwt\." \
  tests/ | sort          # 80 files
```

`--exclude=conftest.py` is required: `conftest.py` now self-matches, because the
comment explaining this fix contains both `auth/service.py` and `jwt.encode`. A
measurement whose selector matches the file being measured is not a scope, it is
an accident.

## `auth-session-failures-pre-AUTH_SECRET_KEY.txt` — the recorded baseline

The 11 failures produced by running that file set **before** `AUTH_SECRET_KEY`
was set in `conftest.py`:

```bash
python -m pytest $(cat tests/baselines/auth-session-file-set.txt | tr '\n' ' ') \
  -p no:cacheprovider -q --timeout=60
# 11 failed, 1656 passed, 4 skipped
```

Entries are **bare node IDs**. An earlier revision of this file kept pytest's
`-q` summary suffix on one line (`… - Assertio...`), which is terminal-width
dependent — the `comm` workflow below would then have reported that entry as
both "fixed" and "newly broken" on any host with a different width, manufacturing
the exact false signal this file exists to prevent.

### Provenance

Measured **2026-08-01 on Linux / py3.11**, single process, at commit `f8456c7`
with the fix stashed out. `f8456c7` was the tip of
`claude/test-isolation-stale-settings-7wtm5i`; that branch was later squash-merged
and this one **rebased onto `542888a`**, so these figures were taken on a tree
that is neither the PR base nor its head, and were not re-measured after the
rebase. CI meters on **Windows / py3.9**.

### What the fix moved

| | before | after |
|---|---|---|
| failed | 11 | 9 |
| passed | 1656 | 1658 |
| `InvalidKeyError` in log | 6 | 0 |

Set-difference: the two `test_wave8_security_hardening.py` document-delete tests
moved to passing; nothing regressed.

**Only one of those two was a real win.**
`test_document_delete_rejects_nonmaster_session_when_enforced` reaches 403 only
downstream of a successful `decode_token`, so it does prove a JWT round-trip.
`test_document_delete_default_config_is_no_op` was passing *vacuously*: the suite
leaves `settings.api_key` empty, so `require_api_key` returns at its
`# dev only — auth disabled` branch before reading the cookie, and the test
passed identically with no session at all. It has since been repaired (api_key
patched non-empty, asserts `== 404`) and given a negative control.

The 9 remaining failures are **not** all inert. At least three are behavioural,
not source-greps: `test_wfirma_status.py::test_scheduler_health_boundary_exactly_2x_interval`
and both `test_proforma_purchase_transit_bypass.py` entries, which post to the
proforma preview route and assert on readiness and blocking reasons.

### Why the file exists

The first attempt at the fix set `AUTH_SECRET_KEY` **43 lines too late** — after
`from app.core.config import settings`, which is where pydantic `BaseSettings`
reads the environment and builds the singleton. It verified correctly in a fresh
interpreter and changed **nothing**: identical counts, identical failure sets, 6
`InvalidKeyError` either way. Only the empty set-difference revealed it. A
count-based comparison would have looked the same whether the fix worked or not.

That regression is now pinned behaviourally by
`tests/test_auth_secret_key_bootstrap.py`.

---

## Using these

```bash
python -m pytest $(cat tests/baselines/auth-session-file-set.txt | tr '\n' ' ') \
  -p no:cacheprovider -q --timeout=60 2>&1 \
  | grep '^FAILED' | sed 's/^FAILED //' | cut -d' ' -f1 | sort > /tmp/now.txt

comm -23 tests/baselines/auth-session-failures-pre-AUTH_SECRET_KEY.txt /tmp/now.txt  # fixed
comm -13 tests/baselines/auth-session-failures-pre-AUTH_SECRET_KEY.txt /tmp/now.txt  # newly broken
```

`cut -d' ' -f1` is load-bearing — it strips pytest's message suffix so both sides
are bare node IDs.

**Caveat that matters: set-difference does not rule out flakiness.** A flaky test
can pass in one run and fail in the other, appearing as a spurious "fixed" or
"newly broken" entry. A single before/after pair distinguishes a real change from
a count shift, not from an intermittent one. Confirm a surprising entry by
re-running that file alone, and prefer a delta that has a matching mechanism
(here: the `InvalidKeyError` count going 6 → 0) over one that merely looks right.

This baseline embeds the failures of its moment. Unrelated commits will change
the 9 remaining entries; when they do, re-record against the corrected selector
rather than reasoning against a stale list.
