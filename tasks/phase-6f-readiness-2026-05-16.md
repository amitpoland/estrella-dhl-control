# Phase 6F Readiness Verification — Inspection Report

> **STATUS: INSPECTION ONLY. Phase 6F implementation NOT started.**
>
> Campaign: Operational Stabilization + Observation · Phase: 4 · Author: claude-session 2026-05-16
>
> Companion to `tasks/phase-6f-architecture.md` (architecture proposal).
> This document verifies the architecture is still safe to implement after
> the stability work landed and identifies the safest first batch.

---

## 1 — Re-read of architecture proposal (delta since last update)

Architecture doc reviewed: `tasks/phase-6f-architecture.md` (11 sections).
No changes were made to that file during Phase 2 stability work. The proposal
remains intact:

- 5 new tables in new `<storage_root>/finance_postings.sqlite` (charges,
  postings, payments, payment_allocations, settlements).
- 7 staged batches (6F.1 → 6F.7) gated on operator approval.
- 9 hard rules verified compliant.

---

## 2 — Coupling probe results (current code)

### 2.1 — `proforma_service_charges_db.py` — the existing charge surface

```
ALLOWED_CHARGE_TYPES = frozenset({"freight", "insurance"})
Schema: (batch_id, client_name, charge_type) → amount REAL
UPSERT semantics; DELETE removes. 174 lines, isolated module.
```

**Coupling:** Read by `routes_proforma.py` at draft preview/approve/post time
(`POST /api/v1/proforma/draft/{id}/service-charges`). No other consumers.

**Implication for Phase 6F:** The new `charges` table can subsume this without
breaking callers IF (a) the existing endpoint keeps writing here AND ALSO
mirrors into `charges`, or (b) the new endpoint is rolled out behind a flag
and the legacy table is deprecated only after a parallel-run period.

### 2.2 — `ledger_aggregator.py` — payment-state forbidden list

```
FORBIDDEN_ENTRY_FIELDS = (
    "payment_state", "paymentstate", "remaining", "alreadypaid",
    "due_date", "paymentdate", "paid_date", "aging",
)
```

**Coupling:** Pure aggregator. No I/O. Outputs 7 fields per invoice per
currency. Zero links to charges, postings, or payments today.

**Implication for Phase 6F:** Adding the new tables does NOT change anything
this module sees. Payment-state output is FORBIDDEN until Phase 10A.5 probe
lands — Phase 6F can land BEFORE 10A.5 because the new `payments` /
`settlements` tables are populated locally (operator-recorded or via a
future wFirma probe), not by the aggregator.

### 2.3 — `routes_proforma.py` — POST endpoints touching charges

Confirmed POST endpoints that today read/write charges in some form:

- `POST /api/v1/proforma/draft/{draft_id}/service-charges` — writes
  `proforma_service_charges` rows.
- `POST /api/v1/proforma/draft/{draft_id}/post` — issues proforma to wFirma;
  the existing service-charges feed into the line list at issuance time.
- `POST /api/v1/proforma/draft/{draft_id}/approve` — local approval.
- `POST /api/v1/proforma/create/{batch_id}/{client_name}` — legacy direct
  create path (still present).

**Implication for Phase 6F:** The new "post-snapshot to `charges` table" hook
attaches to the post endpoint AFTER wFirma issuance succeeds. The pre-flight
guard would be a feature flag `settings.explicit_charges_enabled` defaulting
False until operator green-lights rollout.

### 2.4 — PZ landed-cost engine — read of fx/vat/master tables

Phase B8's `test_pz_engine_never_reads_master_data_fx_rates` source-grep
guard is currently green. Re-verified during this inspection by re-running
the hard-rule contract suite: **15/15 green.**

The PZ engine path reads NBP live; reads no charges; reads no postings;
reads no payments. Phase 6F therefore has **zero PZ coupling**.

---

## 3 — Risk map

| Risk | Where it lives | Surface area | Severity | Mitigation |
|---|---|---|---|---|
| R1: New `charges` table contradicts legacy `proforma_service_charges` totals | DB | One column (`amount`) | MEDIUM | Migrate via additive `INSERT INTO charges SELECT FROM proforma_service_charges`; keep legacy table writable during parallel run; cut over with flag |
| R2: New `payments` table populated by hand, then a future wFirma payments-find probe arrives later and conflicts | DB | `wfirma_payment_id` column | LOW | Use UNIQUE on (`posting_id`, `wfirma_payment_id` IS NOT NULL); operator-recorded rows have NULL `wfirma_payment_id` so they cannot collide |
| R3: FX delta at settlement is computed from rates locked in at issue vs payment time; if NBP table number is wrong, delta is wrong | calc | `payments.fx_rate_at_payment` field | MEDIUM | Source FX from existing NBP feed; store table number for audit; never override the PZ engine read path |
| R4: Settlement-close trigger fires prematurely when sum-of-payments crosses sum-of-charges within tolerance | trigger | `maybe_close_settlement` function | MEDIUM | Make trigger explicit (operator-invoked endpoint) for batches 6F.1–6F.5; auto-trigger gated behind a 6F.6 flag |
| R5: VAT delta between local `vat_config` and wFirma invoice VAT confuses operator if both displayed in the same panel | UI | Future statement view | LOW | The Phase 6F UI does NOT show local VAT_config; it shows only the VAT that was actually posted to wFirma at issuance time (carried on the `charges` table as `charge_type='vat_pl'`) |
| R6: Credit-limit consumption (M5 in the architecture doc) requires reading `customer_master.kuke_limit` — new write coupling | DB read | One read | LOW | Read-only access; no schema change to customer_master |
| R7: Old `proforma_service_charges` table left orphaned after parallel-run cutover | DB | Storage only | LOW | Cleanup migration in 6F.7 ONLY after operator confirms parallel-run is satisfactory |
| R8: Rollback of Phase 6F mid-rollout could leave `charges` rows orphaned | rollback | Storage | LOW | Each batch has explicit `DELETE FROM charges WHERE source=?` reversal; the file `finance_postings.sqlite` is also reversible by deletion (idempotent re-init) |

**No HIGH-severity risks.** All MEDIUM risks have clear mitigations expressed
in the architecture doc; LOW risks are operationally acceptable.

---

## 4 — Irreversible-risk list

The following operations would be **irreversible** if performed wrongly. None
are scheduled in any current batch:

1. Posting a wFirma invoice with the wrong VAT — Phase 6F batches do NOT
   issue invoices to wFirma; they only annotate existing/future invoices.
2. Modifying historical `proforma_service_charges` rows — Phase 6F migration
   (batch 6F.2) reads from this table but never writes to it.
3. Deleting the `proforma_service_charges` table — explicit operator step,
   gated behind batch 6F.7 confirmation.
4. Auto-triggering settlement-close on a high-value invoice — auto-trigger
   is in batch 6F.6 (feature-flagged off by default).
5. Recording an FX rate that contradicts NBP — `validate_fx_rate` enforces
   ISO 4217 + decimal; "wrong rate" is an operator-input concern that the
   reference table (B8) does not propagate into PZ.

---

## 5 — Migration order (refined from architecture doc)

The architecture doc proposes 7 batches. The refined safest order is:

| Order | Batch | Title | Classification | Why this position |
|---|---|---|---|---|
| 1 | **6F.1** | New SQLite schema + DB module (`finance_postings_db.py`) | NEEDS_SCHEMA_APPROVAL | Pure additive; no behaviour change |
| 2 | **6F.1.5 (NEW)** | Source-grep contract tests pinning the additive nature | AUTO_SAFE | Pin "no wFirma write", "no PZ coupling", "no orphaned legacy table" BEFORE backfill lands |
| 3 | **6F.3** | Read-only `/api/v1/finance/postings/{id}/breakdown` endpoint | AUTO_SAFE | Read-only; safe even with empty tables |
| 4 | **6F.2** | Backfill from `proforma_service_charges` | AUTO_SAFE (read-only of legacy) | Now the breakdown endpoint has data to show |
| 5 | **6F.4** | UI panel: charge breakdown on proforma pipeline | AUTO_SAFE | Frontend read-only |
| 6 | **6F.5** | Modify `/post` to dual-write to `charges` (feature flag OFF) | NEEDS_SECURITY_REVIEW | Behaviour change, gated by flag — operator can toggle on for one client first |
| 7 | **6F.6** | Settlement-close event + FX delta capture | NEEDS_SECURITY_REVIEW | Depends on payments table being populated; requires Phase 10A.5 probe or operator entry |
| 8 | **6F.7** | Cleanup migration: deprecate legacy `proforma_service_charges` | NEEDS_SCHEMA_APPROVAL | Last; only after 6F.5 has run in production for ≥ 1 month |

**Critical insertion:** A NEW batch **6F.1.5** between schema and backfill
adds source-grep contract tests that pin Phase 6F's hard-rule compliance
before any data movement. This is the same pattern that saved B4/B5/B7/B8/B9
from drift.

---

## 6 — Rollback plan (per batch)

| Batch | Rollback | Cost | Data loss? |
|---|---|---|---|
| 6F.1 | Delete `finance_postings.sqlite`; revert merge | low | none — no real data yet |
| 6F.1.5 | revert merge (test-only) | trivial | none |
| 6F.3 | revert merge (read-only endpoint) | low | none |
| 6F.2 | `DELETE FROM charges WHERE source='legacy_backfill'` | low | none — backfill is re-runnable |
| 6F.4 | revert UI commit | trivial | none |
| 6F.5 | Toggle `settings.explicit_charges_enabled = False`; revert if needed | low-medium | New posts after toggle were dual-written; revert leaves `charges` rows orphaned but legacy table is still authoritative |
| 6F.6 | Disable auto-trigger; revert | medium | Any settlements recorded before disable remain in `settlements` table; cleanup query: `DELETE FROM settlements WHERE created_at > '<rollback_date>'` |
| 6F.7 | Restore from snapshot taken at 6F.7 start | high | Significant — this is the only batch that drops the legacy table. Require operator-acknowledged snapshot before merge. |

The 6F.7 cleanup is the ONE batch with non-trivial rollback. Everything
upstream is reversible at low cost.

---

## 7 — Safest first implementation batch

**6F.1 — New SQLite schema + DB module (`finance_postings_db.py`).**

Why this is safest first:

1. **Zero behaviour change.** The new module is unused by any consumer until
   6F.3 lands.
2. **Pure additive.** New file (`<storage_root>/finance_postings.sqlite`).
   No existing schema touched.
3. **Idempotent init.** `CREATE TABLE IF NOT EXISTS` × 5; re-running the
   PZService startup is a no-op.
4. **Mirrors a proven pattern.** Suppliers (B4), HS/Units/Product-local
   (B5), Incoterms/VAT (B7), FX (B8), Carriers Config (B9) all followed
   exactly this shape.
5. **Test surface is bounded.** New `test_finance_postings_db.py` covers
   the 5 tables × validate/CRUD × ~30 tests; PZ regression stays 160/160
   because no calculation code is touched.
6. **No security review required at 6F.1.** The auth surface is unchanged
   (existing `require_api_key` dependency on the future route module
   inherits standard Master Data write protection).

Concrete pre-conditions before 6F.1 starts:

- Operator approves architecture doc §10.1 (schema) — currently outstanding.
- Operator approves charge-type allow-list (architecture doc §5.1) — currently outstanding.
- Operator approves rollout sequence in §5.2 — see §5 of this readiness doc for refined sequence.

---

## 8 — Hard-rule re-verification (current state, before 6F begins)

All 14 hard rules from MDC-2026-05 final audit re-verified during Phase 1+2:

| Rule | Status | Evidence |
|---|---|---|
| No wFirma live posting | ✅ INTACT | No new POSTs to wFirma added in OIA-2026-05; PR #108 is docs-only |
| No proforma posting/approval mutation | ✅ INTACT | Proforma routes untouched |
| No PZ/customs/DHL calculation change | ✅ INTACT | PZ regression 160/160 verified 12× this session |
| No `.env` changes | ✅ INTACT | git diff confirms |
| No direct production DB/storage edits | ✅ INTACT | All deploys via robocopy + restart |
| No destructive schema operation | ✅ INTACT | No ALTER/DROP in OIA campaign |
| No fake backend data | ✅ INTACT | Smoke artifacts cleaned at end of run |
| External integrations stay read-only | ✅ INTACT | wFirma reads only; sync chip read-only |
| Backend-pending buttons disabled with clear reason | ✅ INTACT | Designs + Roles still disabled with tooltip |
| Preserve existing working behaviour | ✅ INTACT | All testids preserved |
| Credentials never stored in master data | ✅ INTACT | B9 secret-shape guard 422-enforced in production smoke |
| VAT does NOT override wFirma invoice path | ✅ INTACT | Hard-rule contract test green |
| FX does NOT override PZ engine | ✅ INTACT | Source-grep guard + B8 guard test green |
| Carrier runtime not touched | ✅ INTACT | B9 isolation guard green |

**Conclusion:** All 14 hard rules from the prior campaign remain enforced.
Phase 6F can land its schema (6F.1) without violating any.

---

## 9 — Blocked / risky areas (unchanged from MDC closure)

These remain operator-gated and are NOT addressed by Phase 6F:

- **B3** — Users + Roles writes (security contract relaxation)
- **B6** — Designs Master (schema sign-off + product_identity_engine read-only-consumer guarantee)
- **MDC-071** — FX override into PZ landed-cost (HARD RULE — FORBIDDEN_NOW)

---

## 10 — Recommendation

1. **Operator review** of this readiness report alongside the architecture doc.
2. **Operator decision** on the three outstanding §10 items from the architecture doc:
   - 10.1 — schema layout (5 tables in new file)
   - 10.2 — charge-type allow-list (8 types proposed)
   - 10.3 — rollout sequence (use the refined sequence in §5 of THIS doc)
3. After approval, the **6F.1 implementation campaign** begins. Estimated:
   one PR, one deploy, no production data movement (empty new tables).
4. After 6F.1 lands in production, **6F.1.5 contract tests** ship in a
   second PR before any backfill runs.
5. **STOP point of OIA-2026-05.** This campaign's last deliverable is this
   readiness report. No further Phase 6F work happens in OIA-2026-05.

---

## 11 — Verdict

**Phase 6F is READY to start implementation when operator approves.**

- Architecture proposal is intact and hard-rule compliant.
- No new coupling discovered during stability work.
- Migration order refined to 8 batches (split with explicit contract-test
  batch 6F.1.5).
- All risks classified; none HIGH; all mitigations expressed.
- Safest first batch identified: **6F.1 schema + DB module**.
- Rollback plan exists for every batch.

The Operational Stabilization + Observation campaign closes here.
