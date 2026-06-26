# Customer Intelligence Architecture

**Owner:** Customer Master authority  
**Status:** Phase 1 complete — VIES + KUKE guard live  
**Last updated:** 2026-06-26  

---

## 1. Design Principles

1. **Customer Master is the authority.** All compliance facts that affect fiscal posting, DHL customs declarations, and wFirma documents are stored in `customer_master.sqlite :: customer_master`. No other table or layer may override them.
2. **Customer Intelligence enriches; it does not govern.** The intelligence layer produces findings and proposed updates. Writes to Customer Master happen only through explicit, operator-confirmed actions via named endpoints.
3. **Every external call is auditable.** Every connector invocation — whether it returns a result or fails — produces an audit log entry with: customer ID, VAT/EORI/entity number queried, timestamp (UTC ISO-8601), source system, result status, and operator identity.
4. **Unavailability is never a hard block.** If an external compliance API is unreachable, the system falls through to the existing Customer Master value and surfaces an advisory. It never blocks fiscal or shipping operations due to external API downtime.
5. **Operator override beats derived state.** When a manual override field exists (e.g. `vat_mode`), it exits the derived path entirely. Override is always the highest priority.
6. **No write happens automatically on page load.** All compliance data writes are triggered by explicit operator action (endpoint call or UI button). No background sync modifies Customer Master without a named audit entry.

---

## 2. Layer Map

```
┌────────────────────────────────────────────────────────────────────┐
│                      EXTERNAL CONNECTORS                           │
│  VIES (EC)  │  EORI (EC)  │  Sanctions  │  Creditsafe  │  KUKE    │
└──────────────────────────────────┬─────────────────────────────────┘
                                   │  ViesConnector / EoriConnector / …
                                   │  (injectable Protocol — mockable in tests)
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│              CUSTOMER INTELLIGENCE SERVICE LAYER                   │
│  service/app/services/customer_intelligence.py                     │
│                                                                     │
│  run_intelligence_check()  →  IntelligenceReport (read-only)       │
│  validate_customer_vat()   →  ViesValidationAction (write-capable) │
│  kuke_is_currently_active() → bool (pure derived, no write)        │
│  get_kuke_risk()           →  Optional[RiskFinding] (pure derived) │
└──────────────────────────────────┬─────────────────────────────────┘
                                   │  targeted writes via update_vat_eu_result()
                                   ▼
┌────────────────────────────────────────────────────────────────────┐
│                    CUSTOMER MASTER AUTHORITY                        │
│  customer_master.sqlite :: customer_master                         │
│                                                                     │
│  vat_eu_valid          Optional[bool]   — Phase 1 VIES result      │
│  vat_eu_validated_at   Optional[str]    — UTC ISO-8601 timestamp   │
│  vat_mode              Optional[int]    — operator override (wins) │
│  kuke_approved         bool             — operator-entered         │
│  kuke_expiry_date      Optional[str]    — operator-entered         │
│  … (72 fields total)                                               │
└──────────────────────────────────┬─────────────────────────────────┘
                                   │  read-only
                    ┌──────────────┼───────────────┐
                    ▼              ▼               ▼
            routes_proforma  wfirma_client   routes_dhl_*
            (readiness gate) (D3 ADR-027)   (EORI gate — Phase 2)
```

---

## 3. Customer Master Authority

**Table:** `customer_master.sqlite :: customer_master`  
**Owner module:** `service/app/services/customer_master_db.py`

### Write rules

| Field | Who may write | How | Condition |
|---|---|---|---|
| `vat_eu_valid` | `customer_intelligence.validate_customer_vat()` | `update_vat_eu_result()` — 2-column targeted UPDATE | Only when VIES returns `valid` or `invalid`; never on `unavailable` |
| `vat_eu_validated_at` | Same as above | Same | Same |
| `vat_mode` | Operator via Customer Master edit endpoint | Full upsert | Operator decision — overrides all derived VAT paths |
| `kuke_approved` | Operator only | Full upsert | Never written automatically |
| `kuke_expiry_date` | Operator only | Full upsert | Never written automatically |
| All other fields | Operator or wFirma sync | Full upsert | Per existing write rules |

### `update_vat_eu_result()` contract

Touches ONLY `vat_eu_valid` and `vat_eu_validated_at`. No other field is modified. Returns `True` if a row was updated, `False` if contractor not found. Caller is responsible for audit logging.

---

## 4. Connector Architecture

### Protocol

All external compliance connectors implement the `ViesConnector` Protocol pattern:

```python
class ViesConnector(Protocol):
    def check(self, country_code: str, vat_number: str) -> ViesResult: ...
```

The same pattern will be used for future connectors. This makes every connector:
- **Mockable in tests** — `MockViesConnector(result)` replaces live calls
- **Swappable** — alternate providers can be injected without touching service logic
- **Independently testable** — connector logic is isolated from business logic

### Connector registry (current and planned)

| Connector | Status | API | Data written to CM | Write field |
|---|---|---|---|---|
| `HttpViesConnector` | ✅ Phase 1 | EC VIES REST (`taxation_customs`) | `vat_eu_valid`, `vat_eu_validated_at` | `update_vat_eu_result()` |
| `EoriConnector` | Phase 2 | EC EORI validation API | `eori_valid`, `eori_validated_at` | `update_eori_result()` (Phase 2) |
| `SireneConnector` | Phase 3 | INSEE Sirene (France — free) | Read-only intelligence layer only | None |
| `EuSanctionsConnector` | Phase 3 | EU Consolidated List (data.europa.eu) | `sanctions_screened_at`, `sanctions_result` | `update_sanctions_result()` (Phase 3) |
| `OfacConnector` | Phase 4 | OFAC SDN API | Same | Phase 4 |
| `UnSanctionsConnector` | Phase 4 | UN Security Council consolidated list | Same | Phase 4 |
| `UkSanctionsConnector` | Phase 4 | OFSI (UK) | Same | Phase 4 |
| `KukeConnector` | Phase 4 | KUKE policy API (commercial, if available) | `kuke_approved`, `kuke_expiry_date` (operator-confirmed only) | Never auto-written |
| `CreditsafeConnector` | Phase 5 | Creditsafe REST API (commercial) | Read-only intelligence layer only | None |
| `DunBradstreetConnector` | Phase 5 | D&B Direct+ API (commercial) | Read-only intelligence layer only | None |
| `ComplyAdvantageConnector` | Phase 5 | ComplyAdvantage API (commercial) | `pep_check_result`, `aml_risk_rating` (operator-confirmed only) | Never auto-written |

### Connector design rules

1. **Free public APIs write.** Results from EC VIES, EC EORI, EU Consolidated List may update Customer Master fields when operator-triggered.
2. **Commercial providers are advisory.** Results from Creditsafe, D&B, ComplyAdvantage go to the intelligence layer only. They NEVER auto-update Customer Master without explicit operator confirmation per finding.
3. **National registry connectors are read-only.** Sirene (FR), KRS (PL), Infogreffe (FR) data enriches the intelligence report but does not update Customer Master.
4. **KUKE is operator-only.** Even if a KUKE connector becomes available, `kuke_approved` and `kuke_expiry_date` are never auto-written. The operator confirms renewal.

---

## 5. Cache Strategy

### Phase 1 (current)

No cache layer. Every call to `POST /{id}/validate-vat` makes a live VIES request. This is acceptable for Phase 1 because:
- The endpoint is manually triggered by operator action, not called on page load
- VIES results are stored in Customer Master as `vat_eu_valid` / `vat_eu_validated_at`
- The stored result serves as a durable cache between manual revalidations

### Phase 2 (planned)

Short-lived in-memory result cache (TTL: 24h) per contractor_id + connector combination. Cache is:
- **Bypassed** when the operator explicitly selects "Revalidate" (force=true parameter)
- **Invalidated** when Customer Master `vat_eu_number` changes
- **Never used** as a hard gate — a cache miss falls through to a live call, never blocks

### Cache invalidation rules

| Event | Effect |
|---|---|
| `vat_eu_number` changes on CM update | VIES cache for that contractor invalidated |
| Operator selects "Revalidate" | Cache bypassed for this request; result stored again |
| TTL expires (24h) | Next manual trigger makes a live call |
| VIES returns `unavailable` | Result is NOT cached (live call will retry next time) |

---

## 6. Audit Strategy

### What is logged

Every connector invocation writes an audit entry via `audit_safe()`:

```
Entity:   "customers"
Action:   "update"
Subject:  contractor_id
Before:   {vat_eu_valid: <old>, vat_eu_validated_at: <old>}
After:    {vat_eu_valid: <new>, vat_eu_validated_at: <new>, vies_status: ..., source: ...}
Request:  FastAPI Request object (extracts operator identity, request ID, IP)
```

### What the audit record captures

| Field | Source |
|---|---|
| Customer ID | `contractor_id` path parameter |
| VAT number | Read from Customer Master before call |
| Validation timestamp (UTC) | `date.today().isoformat()` (Phase 1), full UTC datetime (Phase 2) |
| Validation source | `"EC VIES REST API"` |
| Validation result | `vies_status`: `valid` / `invalid` / `unavailable` / `not_applicable` |
| Operator identity | `Request` object → `X-Operator-ID` header or JWT claim |
| Before state | `{vat_eu_valid, vat_eu_validated_at}` before write |
| After state | `{vat_eu_valid, vat_eu_validated_at, vies_status, source}` after write |

### What is NOT logged

- Raw VIES response body (name, address) — stored in `ViesValidationAction` fields returned to the caller but not persisted. Add `vat_eu_raw_name` / `vat_eu_raw_address` columns if persistence is required (Phase 2 schema addition).
- VIES request ID / consultation number — not returned by the EC VIES REST API (REST does not provide a consultation number; SOAP/WSDL did). If required for legal evidence, switch to SOAP or record the response timestamp as the reference.

---

## 7. Validation Lifecycle

### VIES lifecycle per customer

```
NEW CUSTOMER
     │
     ▼
vat_eu_number set on CM
     │
     ▼
[ADVISORY] D3 fires on every proforma draft
     │  (vat_eu_valid = NULL → advisory warning, does not block)
     │
     ▼ operator triggers "Validate VAT"
POST /api/v1/customer-master/{id}/validate-vat
     │
     ├─── VIES: valid ──────→ vat_eu_valid = True, validated_at = today
     │                        D3 advisory cleared on proforma
     │
     ├─── VIES: invalid ────→ vat_eu_valid = False, validated_at = today
     │                        D3 BLOCK fires on proforma (readiness gate)
     │                        Operator must set vat_mode override to proceed
     │
     └─── VIES: unavailable → CM unchanged, advisory remains
                              No block (VIES downtime must not block shipping)
```

### KUKE lifecycle

```
kuke_approved = True (operator-entered)
kuke_expiry_date = <date> (operator-entered)
     │
     ▼
kuke_is_currently_active(cm, today)
     ├─ True  → active (no finding)
     └─ False → get_kuke_risk() fires
                ├─ KUKE_EXPIRED (CRITICAL) — expiry in the past
                ├─ KUKE_EXPIRING_SOON (WARNING) — within 30-day window
                └─ KUKE_NO_EXPIRY (WARNING) — approved but no date recorded

No automatic CM write occurs.
Operator must:
  (a) Obtain renewal → update kuke_expiry_date
  OR
  (b) Lapse insurance → set kuke_approved = False
```

### D3 VAT readiness state machine

| `vat_eu_valid` | `vat_mode` | Proforma readiness effect |
|---|---|---|
| `None` (unverified) | not set | Advisory warning — D3 fires, does not block |
| `True` (VIES confirmed) | any | D3 cleared — no warning |
| `False` (VIES confirmed invalid) | not set | **Block** — readiness gate prevents finalisation |
| `False` | set (operator override) | Override wins — D3 not evaluated; proforma proceeds under operator-chosen VAT treatment |

---

## 8. Phase Roadmap

### Phase 0 — Read-only intelligence report ✅
- `run_intelligence_check()` — produces `IntelligenceReport` with all findings
- `render_markdown()` — human-readable report
- CLI script: `scripts/customer_intelligence_report.py`
- Scope: read-only, no writes, advisory findings only
- Tests: 23 passing

### Phase 1 — VIES validation action + KUKE guard ✅
- `validate_customer_vat()` — live VIES call, targeted CM write
- `POST /{id}/validate-vat` endpoint — operator-triggered, audited
- `kuke_is_currently_active()`, `get_kuke_risk()` — derived guard
- D3 split: `None` = advisory, `False` = block
- Tests: 45 passing (Phase 0 + Phase 1)

### Phase 2 — EORI + Company Registry enrichment (next)
- `EoriConnector` — EC EORI validation API (free)
- `update_eori_result()` — targeted 2-column write for `eori_valid` + `eori_validated_at`
- `POST /{id}/validate-eori` endpoint
- `SireneConnector` (FR), `KrsConnector` (PL) — read-only intelligence only
- Result cache (24h TTL, operator-bypassable)
- Schema addition: `eori`, `eori_valid`, `eori_validated_at` columns (if not present)
- Goal: remove EORI_MISSING finding for Verhoeven Joaillier after operator enters EORI

### Phase 3 — EU Sanctions screening
- `EuSanctionsConnector` — EU Consolidated List (data.europa.eu — free, XML download)
- Local sanctions index built from downloaded XML (refresh on deploy)
- `update_sanctions_result()` — targeted write for `sanctions_screened_at`, `sanctions_result`
- `POST /{id}/screen-sanctions` endpoint
- Scope: EU list only (Phase 3); OFAC/UN/UK in Phase 4

### Phase 4 — Full sanctions coverage + commercial connectors (planning)
- OFAC, UN, UK OFSI connectors
- Creditsafe, D&B — advisory only (no auto-write)
- ComplyAdvantage — PEP/adverse media (operator-confirmed write only)

### Phase 5 — Periodic compliance refresh (planning)
- Calendar-driven revalidation for VIES, EORI, sanctions
- Notification to operator when expiry or findings change
- Never auto-blocks; always advisory until operator confirms

---

## 9. Anti-Patterns (Forbidden)

These patterns have been explicitly rejected and must not be reintroduced:

| Anti-pattern | Why rejected |
|---|---|
| Call VIES on every page load | Latency + quota; breaks Lesson E (execution-time validation only) |
| Auto-overwrite `kuke_approved` | Insurance decisions require human confirmation |
| Auto-overwrite `vat_mode` | Operator override must never be silently changed by automation |
| Block shipping because VIES is down | External API downtime must not propagate to production operations |
| Store compliance decisions in a separate authority table | Customer Master is the single source; splits cause sync divergence |
| Use VIES result to change fiscal posting | Fiscal rules are set by `vat_mode` operator override or `decide_proforma_vat_context()` — never by raw VIES status |
| Write commercial provider data without operator confirmation | ComplyAdvantage / D&B findings are advisory; operator confirms before CM write |
