# Test isolation audit — `service/tests/`

Date: 2026-06-11
Inspector: read-only, no edits, no full-corpus run.

## §1 — Isolation mechanism

**One conftest, two autouse fixtures, no nested conftests.**

- `service/tests/conftest.py:16` — `@pytest.fixture(autouse=True) _isolate_ai_gateway`
  Reset ai_gateway circuit breakers + evict `app.services.ai_call_ledger` /
  `app.services.ai_redactor` from `sys.modules` and the package `__dict__` so
  `patch.dict("sys.modules", ...)` is honoured by lazy imports.
- `service/tests/conftest.py:142` — `@pytest.fixture(autouse=True) _guard_storage_root`
  **Tripwire, not prevention.** Snapshots files in `_LIVE_ROOTS` before each
  test; after the test, `pytest.fail()` if a new file appears. Ignores SQLite
  WAL/SHM sidecars and four background-service subdirs.
- `_LIVE_ROOTS` (conftest.py:87-95) = `service/app/storage`, `service/storage`,
  and (if `STORAGE_ROOT` env is set) the resolved env value.

**What is NOT in conftest** (deliberate finding):

- No global mock of `wfirma_client._http_request`
- No global mock of `smtplib.SMTP_SSL` / `aiosmtplib`
- No global mock of `requests.{get,post,put,delete}` or `httpx`
- No `pytest-socket` plugin (grep across `service/` returned zero matches)
- No session-scope fixtures of any kind

Each test is **individually responsible** for patching its external clients
(`patch.object(wfc, "_http_request", ...)` is the canonical wfirma pattern —
see `tests/test_wfirma_pz_payload.py:441`).

`service/pytest.ini` has only:
```
[pytest]
timeout = 30
timeout_method = thread
```
Per-test 30s hard timeout. No collection filters, no markers, no env config.

## §2 — Default posture: OFFLINE-BY-DEFAULT (by credential absence, not by mock)

**Empirical posture on this box (verified by resolving `Settings()` live):**
```
environment:               dev
storage_root:              C:\Users\Super Fashion\PZ APP\service\app\storage
wfirma_access_key:         EMPTY
smtp_user:                 EMPTY
smtp_password:             EMPTY
workdrive_refresh_token:   EMPTY
wfirma_create_proforma_allowed: False    (Atlas invariant — write capability off)
wfirma_create_product_allowed:  False    (Atlas invariant — write capability off)
```

`service/.env` contains exactly three keys:
```
ENVIRONMENT=<set>
AUTH_SECRET_KEY=<set>
DEBUG_ALLOW_TEST_SESSIONS=<set>
```
No wFirma, SMTP, Zoho, WorkDrive, or DHL credentials are loaded.

**Effect on live integrations:**
- `wfirma_client._http_request` — without `wfirma_access_key`, no Authorization
  header → wFirma rejects → no business write.
- `email_sender.send_queued_email` — branches on `smtp_user`/`smtp_password`
  being None and returns `{"error": "smtp_not_configured"}` without opening
  any socket.
- `workdrive_uploader` — without `workdrive_refresh_token` the token-refresh
  fails closed; uploads do not proceed.

**The skipif pattern is NOT env-flag based.** Across the corpus there is
**zero** `@pytest.mark.skipif(os.environ.get("RUN_LIVE"))` style gating. Every
single skipif found is **file-existence based**: "skip if this real artifact
on disk is missing." There is no operator-toggleable live mode.

This means the gating story is:
| Live capability | What stops it from firing in tests |
|---|---|
| wFirma HTTP write | Empty `wfirma_access_key` + per-test patch of `_http_request` |
| SMTP send | Empty `smtp_user` / `smtp_password` → `smtp_not_configured` short-circuit |
| Zoho WorkDrive upload | Empty `workdrive_refresh_token` → token refresh fails |
| DHL Express API | Per-test patch of HTTP client (no global guard) |
| Read of local "live" artifacts | `skipif(not <file>.exists())` per test |

**Critical caveat — "safe because credentials are absent."** This is not the
same as "safe by test design." If `service/.env` is ever populated with real
wFirma keys, any test that forgets to mock `_http_request` will fire a real
write the moment a wfirma_create_*_allowed flag goes True. There is no
network-level brake (no pytest-socket).

## §3 — DB safety

`storage_root` resolves to:
```
C:\Users\Super Fashion\PZ APP\service\app\storage
```
This is the **dev tree**. NOT `C:\PZ\app\storage` (production NSSM
AppDirectory). Confirmed by `Settings().storage_root` print.

The dev storage tree currently contains real dev-state SQLite files:
```
correction_registry.db   (32K)
documents.db             (456K)
intake_lineage.db        (56K)
packing.db               (116K)
proforma_links.db        (160K)
reservation_queue.db     (100K)
tracking_events.db       (24K)
users.db                 (32K)
warehouse.db             (100K)
customer_master.sqlite   (separate)
master_audit.sqlite      (separate)
master_data.sqlite       (separate)
packing_resolutions.sqlite (separate)
```

**Storage-guard gap:** the `_guard_storage_root` tripwire only catches **new
file creation** — it diffs the file inventory before/after each test. **A
test that opens `documents.db` and does `UPDATE` / `DELETE` / `INSERT` is
NOT caught** (the file already existed in the snapshot). This is the
biggest real-world isolation gap. Tests that follow discipline use
`tmp_path` + `monkeypatch.setattr(settings, "storage_root", tmp_path)`
(grep confirms `test_intake.py` uses this pattern), but the corpus does
not enforce it.

**Found path violation in the corpus** — `tests/test_wfirma_pz_notes.py:219`:
```python
LIVE_AUDIT = Path("C:/PZ/storage/outputs/SHIPMENT_4789974092_2026-05_999deef1/audit.json")
@pytest.mark.skipif(not LIVE_AUDIT.exists(), reason="live audit not present")
def test_live_audit_renders_all_expected_keys():
    a = json.loads(LIVE_AUDIT.read_text(encoding="utf-8"))
```
Reads from **the production tree `C:\PZ`** (CLAUDE.md "Canonical working-tree
registry" violation — read access not strictly write, but the test is
walking into prod). Read-only, harmless on this run, worth flagging.

## §4 — Safe probe (no live calls)

Ran three known-gated tests with `python -m pytest -v` under the default
test env. Output verbatim:

```
collected 3 items

tests/test_wfirma_pz_notes.py::test_live_audit_renders_all_expected_keys PASSED [ 33%]
tests/test_parser_currency_symbols.py::test_real_clear_diamonds_file_returns_usd SKIPPED [ 66%]
tests/test_parser_currency_symbols.py::test_real_eur_files_return_eur SKIPPED [100%]

======================== 1 passed, 2 skipped in 1.68s =========================
```

Reading:
- 2/3 SKIPPED as the skipif gate intended (`_REAL_FILES_ROOT` not present
  on this box) — the gating mechanism works.
- 1/3 PASSED — but the "live" label was misleading. The test
  `read_text()`s a local JSON file. It performed no HTTP, no SMTP, no
  socket activity. Pass at 1.68s for 3 tests is consistent with local I/O
  only. **No live call was executed by any of the three.**

No blocker. The skipif-by-file-existence mechanism is honest.

## §5 — Verdict: verified-safe full-corpus command

**The corpus can be run for triage WITHOUT live HTTP/SMTP calls under the
current `service/.env` posture**, with the following caveats explicit:

```powershell
# from C:\Users\Super Fashion\PZ APP
Push-Location service
$env:PYTHONUTF8 = "1"
python -m pytest tests/ -q --tb=no -p no:cacheprovider --timeout=30 -x
Pop-Location
```

Bash equivalent:
```bash
cd "C:/Users/Super Fashion/PZ APP/service"
PYTHONUTF8=1 python -m pytest tests/ -q --tb=no -p no:cacheprovider --timeout=30 -x
```

Why this is safe **under the current env**:
1. `service/.env` does not contain wFirma / SMTP / WorkDrive / Zoho / DHL
   creds. Confirmed by direct `Settings()` resolution.
2. With those creds empty, cred-gated service code (wfirma_client,
   email_sender, workdrive_uploader) refuses to authenticate and returns
   "not configured" rather than calling out.
3. `storage_root` resolves to dev `service/app/storage`, not prod `C:\PZ`.
4. The per-test 30s timeout (`pytest.ini`) caps any hung network call.
5. The `_guard_storage_root` tripwire catches **new-file** writes into
   live storage roots.

**`-x` is intentional** for triage round 1: stop at the first failure so
the trial run does not chew through hours of compute. After the first red
is triaged, drop `-x`.

**`--timeout=30` is already enforced by `pytest.ini`** but passed
explicitly so a stale config edit cannot silently unset it.

### Disclosed residual risks (not blockers, but operator-visible)

1. **Cred-absence safety, not test-design safety.** If anyone later adds
   wFirma/SMTP creds to `service/.env`, a test that forgot to mock
   `_http_request` would suddenly fire real HTTP. Mitigation later:
   install `pytest-socket` and run with
   `--disable-socket --allow-hosts=127.0.0.1`. Not blocking; flag for a
   future hardening campaign.

2. **In-place DB mutations not caught by the storage guard.** A test that
   opens `documents.db` and does `UPDATE` corrupts dev state silently. Use
   git diff on `service/app/storage/*.db` after the triage run as the
   manual safety check, OR (recommended for the actual triage) take a
   snapshot copy of `service/app/storage/` before the run and compare.

3. **One test reads from `C:\PZ`** (`test_live_audit_renders_all_expected_keys`,
   read-only). Worth filing a follow-up to move that artifact into a
   test-owned location.

### One pre-run safety check (recommended, ~10s)

Before kicking off the full corpus, snapshot the dev DBs:
```bash
cp -r service/app/storage /tmp/storage-snapshot-pre-triage
```
After the run:
```bash
diff -r service/app/storage /tmp/storage-snapshot-pre-triage | head -20
```
Any line listed = a test mutated a dev DB without isolation. Triage finding.

---

## Summary one-liner

**Safe to triage. The corpus is offline-by-default through credential
absence, not through pytest plumbing. Run with the command in §5, snapshot
dev DBs first, and treat any post-run DB diff as an isolation bug, not an
inspection bug.**
