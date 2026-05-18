# Interface Contracts — Frozen at Phase 1
**Status:** DRAFT (frozen when Phase 1 merges)
**Do not change these contracts without updating all dependent lanes.**

---

## Contract 1 — CompanyProfile Dataclass

```python
@dataclass
class CompanyProfile:
    # Identity
    legal_name:       str           # "Estrella Jewels Sp. z o.o. Sp. k."
    short_name:       Optional[str] = None
    street:           Optional[str] = None
    postal_city:      Optional[str] = None
    country:          str           = "PL"
    nip:              Optional[str] = None    # Polish tax ID
    vat_eu:           Optional[str] = None    # EU VAT (PL5252812119)
    regon:            Optional[str] = None
    # Contact
    email:            Optional[str] = None    # import@estrellajewels.eu
    phone:            Optional[str] = None
    # Bank — Estrella as payee
    iban_eur:         Optional[str] = None
    iban_usd:         Optional[str] = None
    iban_pln:         Optional[str] = None
    swift:            Optional[str] = None
    bank_name:        Optional[str] = None
    # Legal boilerplate (operator-maintained, static text)
    place_of_issue:   Optional[str] = None    # "Warszawa"
    signatory_name:   Optional[str] = None
    signatory_title:  Optional[str] = None
    returns_policy_pl: Optional[str] = None
    gdpr_text_pl:     Optional[str] = None
    # Meta
    updated_at:       Optional[str] = None
```

## Contract 2 — ProformaDraft New Columns (Phase 1 additions)

```python
# Added to ProformaDraft dataclass and proforma_drafts table:
fx_rate_date:    Optional[str]   = None   # ISO date "YYYY-MM-DD"
fx_rate_source:  str             = "NBP"  # e.g. "NBP", "ECB"
incoterm:        Optional[str]   = None   # e.g. "DAP", "FCA", "DDP"
insurance_eur:   Optional[float] = None   # declared shipment insurance EUR
```

Populated at draft creation by `proforma_draft_sync.py` from:
- `fx_rate_date`: NBP rate date embedded in batch FX data (if available) or current date
- `fx_rate_source`: "NBP" constant unless future integration provides different source
- `incoterm`: operator-set per draft (no auto-source available)
- `insurance_eur`: operator-set per draft

## Contract 3 — API Endpoints (settings router)

```
GET  /api/v1/settings/company-profile
     Response: CompanyProfile JSON (empty strings where not set)
     Auth: required (pz_session cookie)

PATCH /api/v1/settings/company-profile
     Body: partial CompanyProfile fields (any subset)
     Response: {"ok": true, "profile": <updated CompanyProfile>}
     Auth: required
     Immutability: none — operator can update at any time (pre-posting only affects preview)
```

## Contract 4 — Renderer Read Sources

The `preview.html` renderer reads in this exact priority order:

| Section | Source | Fallback |
|---|---|---|
| Seller block | `company_profile` | Show "Company profile not configured" banner |
| Bank details | `company_profile.iban_*` + `swift` + `bank_name` | Omit bank section entirely |
| PLN total | `draft.exchange_rate × grand_total` | Omit if exchange_rate is None |
| FX date | `draft.fx_rate_date` | Omit date label |
| Shipment AWB | `audit.json["awb"]` via batch_id | Show "—" |
| Shipment carrier | `audit.json["carrier"]` | Show "—" |
| Clearance path | `audit.json["clearance_decision"]["clearance_path"]` | Omit |
| HS code per line | `editable_lines_json[line].hs_code` | Omit column |
| Tax code | computed from `draft.currency` + customer VAT context | "0%" |
| Incoterm | `draft.incoterm` | Show "—" |
| Insurance | `draft.insurance_eur` + " EUR" | Omit |

## Contract 5 — Snapshot Immutability

Fields frozen on `draft_state → posted`:
- All `editable_lines_json` content
- `buyer_override_json`, `ship_to_override_json`
- `exchange_rate`, `fx_rate_date`, `fx_rate_source`
- `currency`, `incoterm`, `insurance_eur`
- `payment_terms_json`, `remarks`

Fields that can be written after posting (from wFirma post-posting enrichment only):
- `wfirma_proforma_fullnumber` (already exists)
- `wfirma_issue_date`, `wfirma_payment_due`, `wfirma_payment_method` (Phase 3)
- `posted_at`, `posted_by`, `posting_started_at`, `posting_started_by`

## Contract 6 — Audit.json Read-Through (renderer only, no mutation)

The renderer (or preview endpoint) may read `audit.json` for display-only purposes:
```python
# Allowed read-through fields for renderer:
AUDIT_READABLE_FIELDS = {
    "awb": str,
    "carrier": str,
    "clearance_decision.clearance_path": str,
    "dhl_precheck.insurance_total_usd": float,   # display only, USD
}
# Returns None/empty for any missing field — never raises on missing audit.json
```

**The renderer NEVER writes to audit.json.**
