# Replay Harness — Validation Record (v3)

> **v3** = v2 (hardened in place from v1) **plus** Phase 1b Product Fiscal
> Convergence and the D-6 readiness-impact measurement. Extending the file
> necessarily changes its hash, so v3 carries a **new** SHA-256; the v1/v2
> lineage is recorded below rather than an older hash being re-claimed for new
> content. **Verify `V3_SHA256` on the Windows host — not `V2_HARDENED_SHA256`.**

**Artifact:** `service/scripts/ej_replay_harness.py`
**Tests:** `service/tests/test_ej_replay_harness.py`
**Architecture baseline:** `c0416e88d5934775ea5dd90ef92463d6a3aab0e2`
**HEAD at validation:** `c0416e88` — **0 commits delta**, worktree otherwise clean.
**Validated:** 2026-08-18, macOS clone `/Users/amitgupta/code/estrella-dhl-control`

## Lineage

| | |
|---|---|
| `V1_SOURCE_SHA256` | `4079c621c63fde4e0bb7b1261db86d6eb3a4827b4103f3169123cca3ffbcddc7` |
| `V2_HARDENED_SHA256` | see §7 |

v1 was copied verbatim into `service/scripts/ej_replay_harness.py` (hash verified to match `V1_SOURCE_SHA256` at copy time) and then hardened **in place**. This is not a from-scratch rebuild; the v1→v2 diff is auditable and `V1_SOURCE_SHA256` is embedded as a constant in the harness itself.

---

## 1. The two confirmed hazards, and why v1 was vulnerable

### HAZARD A — `master_audit.sqlite`

`core/audit.py:90-92`:

```python
def audit_db_path() -> Path:
    """Resolved at call time — supports tests that monkey-patch storage_root."""
    return settings.storage_root / "master_audit.sqlite"
```

`audit_safe()` is called by `cpa_product_service` (the **sole sanctioned `product_master` writer**), `customer_intelligence`, `inventory_batch_state`, `proforma_conflict_db`. v1 omitted `master_audit.sqlite` from **both** its snapshot list and its hash list — an audit write could have reached live storage **and gone undetected**.

### HAZARD B — import-time storage capture

A repo sweep at `c0416e88` found **48 import-time captures across 29 modules**, referencing **47 distinct children** of `settings.storage_root`:

```
_OUTPUTS  = settings.storage_root / "outputs"              9 modules
_DB_PATH  = settings.storage_root / "customer_master.sqlite"
_POLL_DB  = settings.storage_root / "contractor_poll.db"
_ARCHIVED = settings.storage_root / "archived"
... finance_postings.sqlite · packing_resolutions.sqlite · tracking_events.db
    intelligence_config.json · intelligence_master.json · version.json
    polish_descriptions/ · sad_ready/ · sessions/ · working/ ...
```

These bind **at import time**. Most are covered by **no** `init_*()` seam. v1 redirected only DB pointers and never touched `storage_root`, so all 47 would have pointed at live storage for an entire run.

**Consequence:** isolation must operate on the **whole storage root**, and `storage_root` must be redirected **before any application import**. Both are now enforced.

### Other verified write-on-read hazards

| ID | Hazard | Evidence |
|---|---|---|
| H1 | `init_*()` run ALTER migrations at init | measured: 5/8 DB hashes change from init alone |
| H2 | `_build_preview` → `populate_from_packing()` writes `design_product_mapping`; `_derive_draft_readiness` calls `_build_preview` → **readiness is a writer** | `routes_proforma.py:798-806` |
| H3 | `description_engine.get_description_block()` persists + **locks** on first call | `description_engine.py:286-293` |
| H6 | wFirma / carrier / email / HTTP writers reachable from imports | `wfirma_client`, `routes_*` |

---

## 2. Mandatory startup order (enforced in `main()`)

```
1 parse CLI                      8 install network kill-switch
2 locate live storage root       9 ONLY THEN import application modules
3 hash live authorities (tree)  10 initialise DB services against snapshot
4 create snapshot root          11 run requested phase
5 SQLite online-backup all DBs  12 hash live sources again
6 copy session/output evidence  13 fail if anything changed
7 redirect settings.storage_root
```

Snapshot mutations are **allowed and expected**. Live mutations are **forbidden**.

Hard aborts: `master_audit` not redirected → exit 3; any probe path outside snapshot → exit 3; app pre-imported → exit 2; `snap == live` → exit 2; missing storage → exit 2.

---

## 3. Adversarial isolation test

`--self-test` deliberately invokes writer-capable paths, then proves the snapshot moved and live did not.

```
IMPORT_ORDER_GUARD: PASS (0 app modules pre-imported)
network kill-switch ARMED (loopback allowed; external = hard fail + caller id)
audit_db_path() -> .../selftest-snap/master_audit.sqlite   [INSIDE]

  14/14 import-time path probes ....................... INSIDE

[11] invoke WRITER-CAPABLE paths ON PURPOSE
      populate_from_packing (H2)                        OK
      description_engine.get_description_block (H3)     OK
      upsert_product_master                             OK
      audit_safe (HAZARD A) rc=15                       WROTE

[12] NetworkBlocked raised — kill-switch works
[13] live : changed=0 added=0 removed=0
     snap : changed=4 added=0
```

**Row-level landing proof** — three real writers wrote three real rows:

| Writer | snapshot | **live** |
|---|---|---|
| `product_master` `SELFTEST-PM-1` | 1 | **0** |
| `master_audit` `replay_harness_selftest` (HAZARD A) | 1 | **0** |
| `product_descriptions` `SELFTEST-DESC-1` (H3) | 1 | **0** |

`audit_safe` is flag-gated (`audit_hardening_enabled`, default `False` → returns `-1`, writes nothing). The self-test forces it **ON in-process only**, restored in a `finally`. Without that the gate would silently prove nothing, and production may legitimately run with it on.

---

## 4. Safety gates

| Gate | Result | How proven |
|---|---|---|
| `SOURCE_DB_HASH_SAFETY` | **PASS** | no live `*.db` / `*.sqlite` hash changed |
| `SOURCE_STORAGE_HASH_SAFETY` | **PASS** | whole live tree: `changed=0 added=0 removed=0` |
| `MASTER_AUDIT_REDIRECTION` | **PASS** | `audit_db_path()` resolves INSIDE snapshot; audit row landed snapshot-only |
| `OUTPUT_PATH_REDIRECTION` | **PASS** | 14/14 import-time probes INSIDE snapshot |
| `NETWORK_KILL_SWITCH` | **PASS** | `NetworkBlocked` raised on TEST-NET-3 `203.0.113.1`; caller identified |
| `IMPORT_ORDER_GUARD` | **PASS** | 0 `app.*` modules in `sys.modules` before redirection |

---

## 5. Regression results

| Suite | Result |
|---|---|
| `py_compile` | PASS |
| `tests/test_ej_replay_harness.py` | **29 passed** (v3) |
| product authority · design bridge · master consumption · authority separation · description engine · proforma description authority · readiness draft scope · reservation queue · line-mismatch advisory · customer resolver | **123 passed** |
| `pytest -m smoke` | **63 passed, 2 skipped** (21,137 deselected) |
| Root `test_pz_regression.py` | **160/160 — no regression** |
| `--phase 1` local dry run | PASS — 0 batches (local DBs schema-only), 19 live files byte-identical |

No application business logic was changed. No `packing_intake_sessions`. No Product/Design/Pro Forma behaviour change.

---

## 5b. Phase 1b — Product Fiscal Convergence (v3 addition)

Canonical Product identity and fiscal registration are **different states**. A
resolved `product_code` with no `wfirma_product_id` is
`WFIRMA_REGISTRATION_REQUIRED` — **not** `PRODUCT_MAPPING_REQUIRED`.

`phase1_fiscal_convergence()` classifies every canonical product code seen in
packing evidence, using **local evidence only** and the **same precedence the
application uses** (`routes_proforma._c1f_mirror_good_id`: mirror-first, cache
fallback), so the census reflects what the running system would decide:

| Source | DB |
|---|---|
| `wfirma_product_mirror` (`wfirma_id`, `deleted_flag`) | `reservation_queue.db` |
| `wfirma_product_mapping` (`wfirma_product_id`, `sync_status`) | `reservation_queue.db` |
| `wfirma_products` (cache fallback) | `wfirma.db` |

States: `WFIRMA_MAPPING_EXISTS` · `WFIRMA_REGISTRATION_REQUIRED` ·
`WFIRMA_PENDING_ADOPTION` · `WFIRMA_MAPPING_CONFLICT` (differing ids across
sources) · `WFIRMA_LOCAL_EVIDENCE_UNAVAILABLE`.

**No external wFirma call is made.** Pinned by `test_fiscal_census_makes_no_network_call`,
which runs the census under the armed kill-switch and asserts zero connection attempts.

`phase1_d6_impact()` measures the D-6 target semantics (Draft/Approve: identity
required, wFirma ID not; Post/Convert: both) against real drafts — **measurement
only, nothing is changed**.

**Honesty limit, deliberately encoded:** a draft counts as "blocked solely by
missing `wfirma_product_id`" only when no other *locally detectable* blocker
exists (blank `product_code` line, or missing/zero price). Design ambiguity,
WDT EU-VAT, over-bill and duplicate-document require `_derive_draft_readiness`,
which calls `_build_preview` — **a writer** (`routes_proforma.py:798-806`).
Phase 1 stays read-only, so those are reported as *not locally determinable*
rather than assumed absent, and are deferred to Phase 3.

## 6. Known limitations — stated, not hidden

1. **Phases 3/4/5 have never run against populated data.** Code-complete, unexercised. Treat the first production Phase 1 as a harness shakedown as well as discovery.
2. **Description and inventory-lifecycle diffing are not implemented.** Both need the real corpus shape first.
3. **Phase 5 is arithmetic** over historical evidence, not a full service-level provisional replay.
4. `OUTPUT_PATH_REDIRECTION` probes **14 representative** constants, not all 48. The 14 span every observed pattern (`_OUTPUTS`, `_DB_PATH`, `_ARCHIVED`, `_WORKING`, `_POLL_DB`, `_DOC_DB`, `_TRACKING_DB`, `_CM_DB`) across both `api/` and `services/`. Since all derive from the same patched `settings.storage_root`, whole-tree hashing is the real backstop — but the probe list is a sample, not exhaustive proof.
5. Kill-switch patches `socket.connect`/`connect_ex`. Libraries bypassing the socket layer entirely (raw syscalls, pre-opened handles) would not be intercepted; none observed in this codebase.

---

## 7. Hashes

```
V1_SOURCE_SHA256     4079c621c63fde4e0bb7b1261db86d6eb3a4827b4103f3169123cca3ffbcddc7
V2_HARDENED_SHA256   ec4e53925d9b2ca1c04a9a2a26f2c0ec26e67cefef1ca2cb68df005689ff5d71
V3_SHA256            33f7d7676cd0198fe663762f9a01a054f5c5662a24329b09bdfde7aa36d95f5f   <-- CURRENT
V3_TESTS_SHA256      65daec9e30176100ef882b27ce14f5a28c2b5115dfd87e37b904ec3c6f870018
```

All three lineage hashes are embedded as constants in the harness and pinned by
`test_lineage_records_v1_and_v2`, so a future edit cannot silently drop them.

Recompute on the Windows host and compare **against `V3_SHA256`** before running:

```powershell
Get-FileHash "C:\PZ-main\service\scripts\ej_replay_harness.py" -Algorithm SHA256
```

---

## 8. Usage on the production host

```powershell
# 1. safety proof FIRST — must print VERDICT PASS and all six gates PASS
python service\scripts\ej_replay_harness.py `
    --storage "C:\PZ\app\storage" --out "C:\PZ-archive\replay-2026-08-18" --self-test

# 2. only if PASS: corpus discovery only
python service\scripts\ej_replay_harness.py `
    --storage "C:\PZ\app\storage" --out "C:\PZ-archive\replay-2026-08-18" --phase 1
```

Requires the PZService venv (`import app`). Do **not** run Phase 3/4/5 until the Phase 1 output is reviewed.

**Disk note:** the snapshot mirrors the entire storage root, including `outputs/` and `sessions/`. On production that may be large — check free space at `C:\PZ-archive` before the first run.
