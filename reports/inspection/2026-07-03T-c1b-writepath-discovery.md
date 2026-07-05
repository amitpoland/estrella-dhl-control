# C-1b Write-Path Reroute — discovery + decision fork (read-only)

- **Date:** 2026-07-03 · read-only discovery, ZERO code mutated · precedes any C-1b edit.
- **Slice:** C-1b of "EJ Dashboard Master Authority Establishment" — reroute product
  write paths through the Master (V1 = routes_wfirma create/edit/resolve; V6 =
  routes_reservations get_product_by_code shim).
- **R1 scope-lock (operator):** routes_wfirma.py, routes_reservations.py,
  reservation_db.py, the two route test files + the consumption pin, PROJECT_STATE,
  DECISIONS. (Operator explicitly put "the consumption pin" in scope.)

## The real write sites (grounded, not assumed)

**routes_wfirma.py**
- `wfirma_products_resolve` (@ /shipment/{id}/wfirma/products/resolve): a large
  authority endpoint (authority pre-flight + description-engine + timeline). Direct
  wFirma product access: `wfirma_client.get_product_by_code(pc)` (:1926),
  `wfirma_client.create_product(...)` (:2003), gate `settings.wfirma_create_product_allowed`
  (:1944). Reads/writes the split cache via `wfirma_db.*` methods (NOT raw table SQL).
- `wfirma_products_sync_names` (@ .../products/sync-names): `wfirma_client.edit_product(...)`
  (:2320), gate `settings.wfirma_create_product_allowed` (:2243, a top-of-endpoint 422 guard).

**routes_reservations.py**
- `sync_products_by_codes` (@ /wfirma/products/sync-by-codes): imports + shims
  `get_product_by_code` (:161/:166) and passes a `_ClientShim` into
  `rworker.sync_wfirma_products_by_codes` (worker updates `wfirma_product_mapping`).
  (Note: the sibling `create_reservation` shim is SALES authority — out of C-1b scope.)

**reservation_db.py** — confirmed PURE persistence: it does NOT import `wfirma_client`
or `settings`. It already owns `upsert_product_master` / `get_product_master` /
`upsert_wfirma_product_mapping` and the C-1a `wfirma_product_mirror` writes. It is the
ONLY whitelisted sync-layer module inside the R1 file list.

## Measured baseline — crude(current pin) vs precise(access-only)

Ran a per-file matcher over every business `routes_*.py` (whitelist excluded).
Precise = strip comments+docstrings, then match real access only:
`.get_product_by_code(` / `.create_product(` / `.edit_product(` /
`def|import get_product_by_code` / table-context `wfirma_products|_mapping|_mirror`.

| file | crude hits | precise (real access) hits |
|---|---|---|
| routes_dashboard.py | wfirma_products, create_product | table:wfirma_products |
| routes_packing.py | wfirma_products | table:wfirma_products |
| routes_proforma.py | wfirma_products | table:wfirma_products |
| routes_reservations.py | wfirma_products, wfirma_product_mapping, get_product_by_code | def+import:get_product_by_code |
| routes_wfirma.py | wfirma_products, get_product_by_code, create_product, edit_product | call:create_product, call:edit_product, call:get_product_by_code |
| routes_wfirma_capabilities.py | (all four) | call:create/edit/get + table:wfirma_products |

- **Crude offender files = 6. Precise offender files = 6. Identical set.**
  Crude-only false-positive files = **none**. → refining the pin to precise access
  does NOT change WHICH files are flagged (proven equivalent today); it only removes
  per-file false-positive REASONS (the gate-flag name, function identifiers, prose).
- **The C-1a baseline of 8 was loose:** `routes_master_data.py` and `routes_admin.py`
  contain ZERO forbidden patterns (they only mention `product_master`, which is not
  forbidden). They are phantom allowlist entries — harmless (KNOWN ⊇ offenders keeps
  the pin green) but the ratified "8" over-counts by 2. **Real offenders today = 6.**

## The fork (why this needs an operator ruling)

To satisfy the operator's acceptance criterion "routes_wfirma + routes_reservations
LEAVE the pin," the direct client CALLS must relocate into `reservation_db` (the only
in-scope whitelisted module) under BOTH options. They differ on the pin + the gate:

**Path A — keep the crude substring pin, literal drain.**
- Also relocate the gate-flag control-flow (`wfirma_create_product_allowed`) into
  reservation_db, RENAME `wfirma_products_resolve`/`wfirma_products_sync_names`, and
  scrub docstrings — purely to erase crude substrings.
- Cost: forces the write GATE + create/edit orchestration into a persistence module
  (layering regression); contradicts operator constraint (2) "unchanged in gating";
  large blast radius + churn on the most sensitive wFirma file; the renames/scrubs
  buy ZERO authority improvement.

**Path B — refine the pin to precise access-patterns, reroute the real calls only. [RECOMMENDED]**
- Reroute the 3 real client calls (`get_product_by_code`, `create_product`,
  `edit_product`) through Master-first `reservation_db` helpers (write MASTER → gated
  wFirma push → write MIRROR); the gate CHECK stays in the route (honors "unchanged in
  gating"); no renames, no docstring scrubbing.
- Refine `_FORBIDDEN` from crude substrings to real access (calls + table context,
  comments/docstrings stripped) + add a POSITIVE-CONTROL test proving a synthetic
  `wfirma_client.create_product(` / `FROM wfirma_products` IS still flagged.
- This is the ONLY reading consistent with ALL operator constraints at once
  (writes through Master + routes leave pin + gating unchanged + no layering regression).

## Baseline-number question (independent of path)

After the reroute, the REAL remaining offenders = {dashboard, packing, proforma,
wfirma_capabilities} = **4**. The operator's stated "8→6" was anchored to the loose
C-1a baseline (2 phantoms + the 2 now-rerouted). Options:
- **B-honest:** set KNOWN to the real 4, count pin 8→4, disclose the phantom finding.
- **B-literal:** keep the 2 phantoms, remove only the 2 rerouted → KNOWN 8→6 (matches
  the stated number), disclose that 2 entries are phantom + real offenders are 4.

Recommendation: **B-honest (baseline 4)** — the campaign's core value is honest counts;
carrying phantom "known violations" is exactly the fake-readiness pattern to avoid.

## Recommendation

Path **B** + baseline **4** (honest), pin refined to precise access + positive control.
No code mutated pending operator ruling. On approval this is a single-shot implement.
