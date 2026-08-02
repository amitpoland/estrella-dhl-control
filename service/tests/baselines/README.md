# Measured test baselines

Recorded failure sets from a specific, reproducible measurement. They exist so a
future change can be judged by **set-difference against a known list** rather
than by a count, which is the distinction that caught a no-op fix on 2026-08-01
(see below).

These are evidence, not contracts. `.claude/contracts/test-baseline.md` remains
the single source of truth for deploy-gate pass criteria; nothing here overrides
or supplements it.

---

## `auth-session-file-set.txt` — the measured scope

The 77 test files that reference auth, session, or JWT symbols, selected by:

```bash
grep -rln --include="*.py" \
  "auth.service\|create_session_token\|create_access_token\|pz_session\|require_admin\|get_current_user\|jwt\." \
  tests/ | sort
```

Regenerate with that command. It is a **symbol grep, not a call-graph analysis**:
a test that reaches a token path indirectly is not in this set. Treat results
scoped to it as a floor, not a total.

## `auth-session-failures-pre-AUTH_SECRET_KEY.txt` — the recorded baseline

The 11 failures produced by running that file set **before**
`AUTH_SECRET_KEY` was set in `conftest.py`:

```bash
python -m pytest $(cat tests/baselines/auth-session-file-set.txt | tr '\n' ' ') \
  -p no:cacheprovider -q --timeout=60
# 11 failed, 1656 passed, 4 skipped
```

Measured 2026-08-01 on **Linux / py3.11**, single process, at commit `f8456c7`
plus the fix stashed out. CI meters on **Windows / py3.9**, so platform-
conditional rows will differ.

### What the fix actually moved

| | before | after |
|---|---|---|
| failed | 11 | 9 |
| passed | 1656 | 1658 |
| `InvalidKeyError` in log | 6 | 0 |

Set-difference — the two `test_wave8_security_hardening.py` document-delete tests
moved to passing; nothing regressed. The other 9 are source-grep and contract
assertions unrelated to signing keys, and remain failing.

### Why the file exists at all

The first attempt at the same fix set `AUTH_SECRET_KEY` **43 lines too late** —
after `from app.core.config import settings`, which is where pydantic
`BaseSettings` reads the environment and builds the singleton. It verified fine
in a fresh interpreter and changed **nothing** in the suite: identical counts,
identical failure sets, 6 `InvalidKeyError` either way. Only the empty
set-difference revealed it. A count-based comparison would have looked the same
whether the fix worked or not.

---

## Using these

```bash
python -m pytest $(cat tests/baselines/auth-session-file-set.txt | tr '\n' ' ') \
  -p no:cacheprovider -q --timeout=60 2>&1 | grep '^FAILED' | sed 's/^FAILED //' | sort > /tmp/now.txt

comm -23 tests/baselines/auth-session-failures-pre-AUTH_SECRET_KEY.txt /tmp/now.txt  # fixed
comm -13 tests/baselines/auth-session-failures-pre-AUTH_SECRET_KEY.txt /tmp/now.txt  # newly broken
```

**Caveat that matters: set-difference does not rule out flakiness.** A flaky test
can pass in one run and fail in the other, appearing as a spurious "fixed" or
"newly broken" entry. A single before/after pair distinguishes a real change from
a count shift, not from an intermittent one. Confirm a surprising entry by
re-running that file alone, and prefer a delta that has a matching mechanism
(here: the `InvalidKeyError` count going 6 → 0) over one that merely looks right.

Also note this baseline embeds the failures of its moment. Unrelated commits will
change the 9 remaining entries; when they do, re-record rather than reasoning
against a stale list.
