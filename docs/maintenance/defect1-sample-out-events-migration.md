# DEFECT-1 Layer B — production `sample_out_events` schema migration package

**Status: PREPARED — DO NOT EXECUTE without explicit operator approval.**
Origin: POST-RELEASE STABILIZATION-1, 2026-07-10. `GET /api/v1/inventory/samples`
returned 500 because production `C:\PZ\storage\warehouse.db` carries the
pre-Phase-C generation of `sample_out_events`; the current-generation
migration (`draft_20260512_122327_sample_out_events.py.draft`) was applied
only to the verify tree. Layer A (merged separately) converts the failure to
`503 MIGRATION_PENDING`; this package brings production to the current
generation. **Production table row count at preparation time: 0** — verify
again before executing (step 2); the DROP path below is only valid at 0 rows.

## 1. Preconditions

- Layer A deployed (guard is column-aware).
- Maintenance window: none strictly required (table unused, endpoint 503s),
  but run during low activity; total time < 1 minute.
- Fresh backup: `Copy-Item C:\PZ\storage\warehouse.db C:\PZ\storage\warehouse.pre-defect1.$(Get-Date -Format yyyyMMdd-HHmm).db`

## 2. Verify current state (read-only)

```sql
-- sqlite3 C:\PZ\storage\warehouse.db
SELECT COUNT(*) FROM sample_out_events;          -- MUST be 0; if >0 STOP → use §6
PRAGMA table_info(sample_out_events);            -- expect OLD shape (action/event_time/...)
```

## 3. Migration SQL (forward)

```sql
BEGIN IMMEDIATE;
DROP INDEX IF EXISTS idx_sample_out_idempotency;
DROP INDEX IF EXISTS idx_sample_out_recipient_open;
DROP INDEX IF EXISTS idx_sample_out_scan_time;
DROP TABLE sample_out_events;                    -- valid ONLY at 0 rows (step 2)

CREATE TABLE sample_out_events (
    id                     TEXT PRIMARY KEY,
    scan_code              TEXT NOT NULL,
    direction              TEXT NOT NULL,          -- 'out' | 'return'
    operator               TEXT NOT NULL DEFAULT '',
    recipient_client_name  TEXT NOT NULL DEFAULT '',
    recipient_client_id    TEXT NOT NULL DEFAULT '',
    sample_reason          TEXT NOT NULL DEFAULT '',
    expected_return_date   TEXT NOT NULL DEFAULT '',
    notes                  TEXT NOT NULL DEFAULT '',
    idempotency_key        TEXT NOT NULL DEFAULT '',
    linked_state_event_id  TEXT NOT NULL DEFAULT '',
    linked_origin_event_id TEXT NOT NULL DEFAULT '',
    occurred_at            TEXT NOT NULL,
    created_at             TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_sample_out_idempotency
    ON sample_out_events (scan_code, idempotency_key)
    WHERE idempotency_key != '';
CREATE INDEX idx_sample_out_recipient_open
    ON sample_out_events (recipient_client_name, direction, expected_return_date);
CREATE INDEX idx_sample_out_scan_time
    ON sample_out_events (scan_code, occurred_at);
COMMIT;
```

(Identical result: `python service\app\db\migrations\draft_20260512_122327_sample_out_events.py.draft C:\PZ\storage\warehouse.db up` — but ONLY after the DROP block above, because the draft's `upgrade` no-ops when the table already exists.)

## 4. Rollback SQL (restores the exact pre-migration production shape)

```sql
BEGIN IMMEDIATE;
DROP INDEX IF EXISTS idx_sample_out_idempotency;
DROP INDEX IF EXISTS idx_sample_out_recipient_open;
DROP INDEX IF EXISTS idx_sample_out_scan_time;
DROP TABLE IF EXISTS sample_out_events;
CREATE TABLE sample_out_events (
    id                     TEXT PRIMARY KEY,
    scan_code              TEXT,
    action                 TEXT,
    recipient_client_name  TEXT,
    recipient_client_id    TEXT,
    sample_reason          TEXT,
    expected_return_date   TEXT,
    actual_return_date     TEXT,
    operator               TEXT,
    event_time             TEXT,
    note                   TEXT,
    idempotency_key        TEXT,
    origin_sample_event_id TEXT,
    status                 TEXT,
    created_at             TEXT
);
CREATE UNIQUE INDEX idx_sample_out_idempotency
    ON sample_out_events (scan_code, idempotency_key)
    WHERE idempotency_key != '';
COMMIT;
```

(Or restore the §1 backup file with the service stopped.)

## 5. Verification checklist (after §3)

1. `PRAGMA table_info(sample_out_events);` → 14 columns incl. `direction`, `occurred_at`.
2. `SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_sample_out%';` → 3 indexes.
3. NO service restart needed (Layer A never caches False): `GET /api/v1/inventory/samples` with `X-API-Key` → **200 `{"ok": true, "count": 0, "samples": []}`** (was 503 after Layer A, 500 before).
4. `Get-Content C:\PZ\logs\pz_stderr.log -Tail 10` → no new traceback.
5. Optional end-to-end: mark a real piece sample-out via the UI → row appears in the register.

## 6. If step 2 shows rows > 0 (STOP path)

Do NOT drop. Rename-preserve instead and escalate for a mapped copy:
`ALTER TABLE sample_out_events RENAME TO sample_out_events_legacy_20260710;`
then run §3's CREATE block only. Old rows stay queryable in the renamed table.

## 7. Maintenance window procedure (summary)

Backup (§1) → verify 0 rows (§2) → run §3 in one sqlite3 session → checklist
(§5) → done. No robocopy, no restart, no .env change. Abort = §4 or restore
backup.
