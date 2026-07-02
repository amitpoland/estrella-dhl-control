# Infra hardening #4 — HTTP access logging: build + test record

- **Date:** 2026-07-03 · logging config only, zero business behavior · no deploy
- **Declared:** PROJECT_STATE DECISIONS "infra hardening #4" (truth table
  recorded verbatim there BEFORE the edit).
- **Origin:** health pass d67d3722 finding #4 — no per-request evidence
  existed anywhere; the gap already cost the campaign once (atlas retirement
  parked on "is /dashboard/atlas ever hit").

## STEP 1 — the proven gate (empirical truth table)

Three local boots with the prod-exact CLI from the NSSM AppParameters read
in d67d3722 (`python -X utf8 -m uvicorn app.main:app --host 127.0.0.1
--port <p> --log-level info --loop asyncio`), one `GET /openapi.json` each:

| variant | logging.py silencer | `--access-log` flag | access line emitted? |
|---|---|---|---|
| baseline (prod today) | WARNING (present) | absent (uvicorn default ON) | **NO** (0 lines) |
| (b) flag only | WARNING (present) | present | **NO** (0 lines) |
| (a) in-repo flip only | INFO | absent | **YES** — `INFO: 127.0.0.1:62794 - "GET /openapi.json HTTP/1.1" 200 OK` |

**Conclusion:** uvicorn's access log is ON by default; the ONLY gate is
`core/logging.py:11` silencing `uvicorn.access` to WARNING — and because
`configure_logging()` runs at app import, AFTER uvicorn's own dictConfig,
the silencer always won; the NSSM flag can never override it. Therefore the
NSSM `--access-log` parameter is **neither sufficient nor necessary — NO
operator-side NSSM change is required**; production inherits the fix at the
next normal deploy.

(Ordering disclosure: variants baseline+(b) ran on the clean tree; the
DECISIONS declaration was written before the edit; variant (a) ran after
the edit and completed the table — declare-then-edit held for the fix.)

## STEP 3 — the fix

`core/logging.py`: the silencer line flipped to an explicit
`setLevel(logging.INFO)` with a comment carrying the finding, the proven
gate, the atlas cost, and the rotation note. Format = uvicorn's default
access format: **client_addr + request line (method + path) + status** —
the atlas-class question is now answerable by grep. Rotation: NSSM online
rotation at 10MB absorbs the stream (no new mechanism); retention joins
pz_stdout.log's accepted posture (finding #8).

## STEP 4/5 — tests

`service/tests/test_access_log_enabled.py` (3 tests):
1. **Positive pin, real server**: boots an actual uvicorn server in-process
   (TestClient CANNOT pin this — access lines come from uvicorn's protocol
   layer), replicating the production ORDER (`configure_logging()` after
   uvicorn's logging setup, `log_config=None`, `lifespan="off"`); fires a
   real HTTP request; asserts the captured `uvicorn.access` record contains
   GET + /openapi.json + 200 + the remote addr.
2. **Negative source pin**: the WARNING silencer line is gone; the INFO line
   is present.
3. `configure_logging()` leaves `uvicorn.access` at INFO.

```
tests/test_access_log_enabled.py            3 passed
grep configure_logging|uvicorn.access tests/ → only the new pin suite
pytest -m smoke                             63 passed, 1 skipped
PYTHONUTF8=1 python test_pz_regression.py   160/160 golden PASS
```

## Deploy note

Zero operator action. After the next normal deploy + PZService restart,
per-request lines (`client - "METHOD /path HTTP/1.1" STATUS`) appear in
C:\PZ\logs\pz_stdout.log under the existing 10MB online rotation. First
post-deploy check: `grep "GET /" pz_stdout.log | head` — then the atlas
question can be answered with ~a week of evidence.
