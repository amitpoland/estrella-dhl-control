# Governance Scorecard — Master Data Soft-Delete / V2 Campaign

**Date:** 2026-05-28
**Campaign:** Master Data soft-delete + V2 UI + referential integrity
**Verdict:** ✅ COMPLETE — structurally finished, all gates green.

---

## Phases completed

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit module (`core/audit.py`) + role-gate factory (`core/role_gate.py`) + flags, scaffolding only | ✅ |
| 1 | Audit wiring across the 8 master_data write handlers + customer/supplier/address/carrier-account; `GET /api/v1/master/audit` | ✅ |
| 2 | Role gating (`require_role_or_apikey`) on master writes; default-off; isolated master_* roles | ✅ |
| 3 | Jewelry entities — metals, stones, warehouses (new DB modules + routes + UI) | ✅ |
| 4A | Soft-delete + restore for the 3 jewelry entities | ✅ |
| 4B Wave 1 | Soft-delete for 6 low-risk legacy entities (hs_codes, units, incoterms, vat_config, fx_rates, designs) | ✅ |
| 4B Wave 2 | Soft-delete for composite-key children (client_addresses, client_carrier_accounts) + stable colon-pk audit | ✅ |
| 4B Wave 3a | Soft-delete for carriers_config (credential isolation preserved) | ✅ |
| 4B Wave 3b-1 | Soft-delete for suppliers (wFirma sync isolation) | ✅ |
| 4B Wave 3b-2 | Soft-delete for customers + child-write RI activation | ✅ |
| 4B Wave 4 | Soft-delete for product_local (overlay semantics: inactive = stop applying) | ✅ |
| 4C | Referential integrity: hs_code / customer references on write | ✅ |
| 4C-ext | Carrier reference integrity for client_carrier_accounts | ✅ |
| 4D | Structured 409 `reference_conflict` UX (`formatApiError`) | ✅ |
| 4D-ext | Generic `pickerSource` mechanism + active-carrier `ReferencePicker` | ✅ |
| 4D-ext-2 | HS-code `ReferencePicker` (product_local, designs) | ✅ |
| 5 | V2 customer detail surface (inline addresses + carrier accounts) | ✅ |
| Pre-Wave-4 | Design note authored + operator sign-off before implementation | ✅ |
| Close-out | This scorecard + PROJECT_STATE FACTS + lessons (this task) | ✅ |

Also during the campaign: repaired a pre-existing unresolved merge conflict
in `routes_proforma.py` (~line 1687) that had been blocking full app import.

---

## Recorded metrics (2026-05-28)

| Metric | Value |
|---|---|
| Final route count | **423** |
| Targeted master/audit/role/V2 suite | **956 / 956 PASS** |
| PZ regression | **160 / 160 PASS** |
| Catalog soft-deletable | **15 / 15** |
| Hard-delete-only entities remaining | **0** |
| New feature flags | 3 — `master_audit_enabled=True`, `master_role_enforcement=False`, `master_hard_delete_enabled=False` |
| Audit op vocabulary | create · update · upsert · delete · soft_delete · restore · hard_delete · transition |

---

## 6-dimension scoring

| Dimension | Score | Notes |
|---|---|---|
| Correctness | ✅ Strong | Every wave: soft-delete/restore/hard-delete gating + audit + RI proven by per-entity test suites; PZ golden 160/160 unchanged. |
| Authority discipline | ✅ Strong | Lesson F honored — V2 pages single-domain; dashboard-shared.js stayed visual-only; wFirma/PZ/NBP authority never crossed; product_local overlay semantics correct. |
| Safety / blast radius | ✅ Strong | All new behavior flag-gated to production-safe defaults; soft-delete is reversible; hard-delete double-gated (flag + master_admin). PUT-no-reactivate pinned. |
| Test rigor | ✅ Strong | 956 targeted tests; source-grep isolation tests (wFirma/PZ/DHL imports); consumer-fallback proofs for product_local; credential-isolation guards for carriers. |
| Incrementality | ✅ Strong | Rolled out by authority/risk waves (jewelry → low-risk legacy → composite → external-authority → overlay). No big-bang. Each wave independently green. |
| Documentation | ✅ Strong | Pre-implementation design note for the highest-risk entity (product_local); scorecard; PROJECT_STATE FACTS; campaign close-out; 4 new engineering lessons. |

---

## Authority boundaries preserved (test-pinned)

- **product_local** inactive = "stop applying overlay", never product deletion.
  PZ engine has no `product_local` import. Consumers fall back.
- **fx_rates** reference-only; PZ landed-cost uses live NBP.
- **carriers_config** never stores credentials (schema + dataclass + response
  + UI guards).
- **wFirma sync/apply/dictionary** endpoints untouched in every wave;
  soft-delete primitives import no wFirma client; PUT never reactivates.
- **customers/suppliers** soft-delete proven not to alter sync semantics
  (isolation source-grep tests in each wave).

---

## Remaining known non-blocker

`test_proforma_draft_editor_contract.py::test_ui_cascade_ship_to_payload_uses_ship_to_then_bill_to_fallback`
— pre-existing failure, surfaced only by a broad `-k proforma` sweep. It
inspects `shipment-detail.html` (V1 frozen page) for the ship_to→bill_to
fallback chain in `onApplyCustomerDefaults`. **Not touched by this campaign,
not a soft-delete regression.** Disposition: SCHEDULED as an isolated V1 fix
task (GATE 4 — salvage finding receives an explicit disposition).

---

## GATE 4 dispositions

| Finding | Disposition |
|---|---|
| shipment-detail.html ship_to contract test failure | **SCHEDULED** — isolated V1 fix task (prompt in campaign close-out) |
| Phase 5-ext (customer Restore button + default-address mgmt in detail page) | **SCHEDULED** — optional low-risk UX follow-up |
| product_local overlay-inactive operator-visibility (surface "overlay inactive" in proforma UI) | **ISSUE** — candidate enhancement, not required |

---

## Self-reference

Per RULE 6 this scorecard is cited in `PROJECT_STATE.md` FACTS
(Master Data Soft-Delete / V2 Campaign — COMPLETE, 2026-05-28).
