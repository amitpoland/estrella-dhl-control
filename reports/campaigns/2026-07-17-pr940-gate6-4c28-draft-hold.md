# PR #940 GATE-6 (head 4c28f28f) via merged bootstrap — DRAFT_HOLD

**Date:** 2026-07-17 · Bootstrap: merged main `74a354a4` (`service/scripts/review_launch.py` +
`review_seed.py`, byte-identical to what this session authored). Target #940 head
`4c28f28f947ff86fb6213c8fd02657a91f102fac` (OPEN/DRAFT/MERGEABLE). No merge/deploy; no raw SQL;
no production DHL/data; carrier baseline untouched; #940 code unchanged; #940 stays DRAFT.

## Box-type authority — TRACED + PROVEN + SEEDED (this is NOT the blocker)

| Aspect | Value (extracted 4c28f28f) |
|---|---|
| **List route** | `GET /api/v1/box-types/` — `routes_box_types.py:83`, auth `require_api_key` |
| **Seed-defaults route + method** | `POST /api/v1/box-types/seed-defaults` — `routes_box_types.py:109`, auth `require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR)` (X-API-Key admin-equivalent) |
| **Writer service** | `master_data_db.seed_default_box_types()` (:1709) / `upsert_box_type()` (:1626) |
| **Reader service** | `master_data_db.list_box_types(db_path, *, active=True, limit)` (:1604) / `get_box_type_by_code` |
| **Database path** | `settings.storage_root / "master_data.sqlite"` (`routes_box_types.py:42`) |
| **Filtering** | `_resolve_list_active`: omit→active-only (default), `false`→inactive, `all`→all; `WHERE active=1 ORDER BY sort_order ASC, code ASC LIMIT` |
| **Response schema** | `{count, box_types:[{id,code,name,carrier,length_cm,width_cm,height_cm,tare_weight_kg,max_weight_kg,package_type,sort_order,active,notes,created_at,updated_at}]}` |
| **Registration** | `main.py:98` import, `main.py:560` include_router |

**Seeded via the canonical API (no raw SQL):** `POST /api/v1/box-types/seed-defaults` (X-API-Key) →
created `DHL-JEWEL-S, DHL-RING, DHL-BRACELET, CUSTOM`. **Assertion PASS:** `GET /api/v1/box-types/`
returns **count=4** (≥1 selectable) before any modal work. Version fingerprint = `4c28f28f`.

## Blocker — browser SESSION-AUTH mismatch (not a box-type data issue)

The V2 frontend (`static/v2/pz-api.js`) authenticates every API call via **session cookie**
(`fetch(url, {credentials:'include'})`) — it does **not** send `X-API-Key`. The review bootstrap
provides **X-API-Key** auth (a non-empty generated key = "real review authentication"), which works
programmatically (the box-type seed + list above succeeded via curl), but supplies **no browser
login session**. Result, observed in-browser:

- `/v2` SPA shell renders, but the proforma detail shows **"Session expired or access denied."**
- Network: `GET /api/v1/proforma/draft/1` → **401**, `GET /api/v1/health` → 401,
  `GET /api/v1/webhooks/wfirma/status` → 401.

So the proforma detail never renders → the AWB modal, box-type dropdown, CMR Modern per-line origin,
and the legacy-rebook confirm/cancel gate are **all unreachable in the browser**. Only browser item 1
(served version fingerprint = 4c28f28f) passed; items 2–8 are blocked upstream of any box-type or
CMR logic.

## Why not resolved unilaterally

The two ways to give the browser a session both hit a wall in this session:
1. **Review login session** (a non-prod review user + `/auth/login` to get the `pz_session` cookie) —
   creating an account and entering a password to authenticate is a **prohibited action**; I will not
   do it unilaterally.
2. **Empty API key** (dev auth disabled, which is what the earlier M1-gate session used) — contradicts
   this task's explicit "real review authentication" requirement.

The bootstrap was deliberately built API-key-first (to avoid account creation); the V2 browser is
cookie-first. That architectural gap is the exact blocker.

## Disposition

- **DRAFT_HOLD.** The confirmation-and-cancel sequence could NOT be browser-verified → #940 stays DRAFT;
  `task_ab702256` / `task_35c61ad8` NOT marked resolved (verification did not pass).
- Box-type authority is sound (proven + seeded + ≥1). The gap to close is a **browser session** for the
  review env: operator decision needed — (a) authorise a non-prod review login (user+password), or
  (b) accept an empty-key dev-auth review run, or (c) extend the bootstrap to mint a review session
  cookie from the API key. Only (c) avoids both the prohibited-action line and the empty-key contradiction.
- Code-level #940 behaviour (legacy-rebook gate, CMR) is separately covered by the #940 test suites and
  the earlier M1-gate certification; this HOLD is specifically the authenticated-browser gate.
