# EMAIL_ROUTING_UPDATE_PROPOSAL_EXPANDED.md
# Email Routing Configuration — Expanded Update Proposal
# Carriers: DHL + FedEx | Period: Aug 2025 – Apr 2026
# Generated: 2026-04-27

---

## Change Summary from Original Proposal (Task C)

The original proposal (EMAIL_ROUTING_UPDATE_PROPOSAL.md) covered DHL and ACS only.
This expanded proposal adds:
1. Full FedEx routing — `pl-import@fedex.com` as PRIMARY clearance trigger
2. Additional ACS agent (`adrian@acspedycja.pl`)
3. Ganther admin contact (`krzysztof.suchodola@ganther.com.pl`)
4. DO_NOT_TRIGGER list — addresses that must never fire automation
5. Internal monitoring additions
6. AWB detection regex patterns per carrier

---

## SECTION 1 — TRUSTED_CLEARANCE_SENDERS (Complete Proposed Config)

```python
TRUSTED_CLEARANCE_SENDERS = {

    # ── DHL ──────────────────────────────────────────────────────────────────
    "odprawacelna@dhl.com":              "DHL_CESJA",
    # Evidence: Every DHL shipment Aug 2025 – Apr 2026.
    # Role: Cesja initiator. Forwards clearance docs to ACS.
    # Risk: None. Confirmed across 19+ shipments.

    "plwawecs@dhl.com":                  "DHL_SPECIAL",
    # Evidence: Known from original discovery.
    # Role: Special consignment handler.

    "administracja_centralna@dhl.com":   "DHL_RELAY",
    # Evidence: CC on every ACS clearance email.
    # Role: Receives PZC release commands.

    "wawpok@dhl.com":                    "DHL_WAREHOUSE",
    # Evidence: AWB 3023090884 pickup authorization.
    # Role: Warsaw POK warehouse. Pickup coordination only.
    # Risk: Low. Use only for pickup authorization, not clearance.

    # ── ACS Spedycja (Agencja Celna Spedycja) ───────────────────────────────
    "no-reply@acspedycja.pl":            "AIS_ZC429",
    # Evidence: ZC429/PW429 automated delivery on every DHL shipment.
    # Role: AIS (WinSADMS) automated customs release notification.
    # CRITICAL — this is the ZC429 delivery address.
    # Subject always: "Powiadomienie AIS - Zwolnienie do procedury (ZC429/PW429/wpis)"

    "piotr@acspedycja.pl":               "ACS_AGENT",
    # Evidence: Primary PZC sender. Jan–Apr 2026 all shipments.
    # Full name: Piotr Kubsik — Agencja Celna Spedycja

    "logistyka@acspedycja.pl":           "ACS_AGENT",
    # Evidence: PZC sender on DHL shipments Dec 2025 – Apr 2026.
    # Full name: Bartłomiej Bugaj — Agencja Celna Spedycja

    "roman@acspedycja.pl":               "ACS_AGENT",
    # Evidence: PZC sender Nov–Dec 2025. Also involved in FedEx cesja thread.
    # Full name: Roman Kałużny — Agencja Celna Spedycja

    "adrian@acspedycja.pl":              "ACS_AGENT",
    # Evidence: PZC sender Dec 2025 (AWB 2136263684).
    # Full name: Adrian Mielcarek — Agencja Celna Spedycja
    # NEW — not in original proposal.

    "biuro@acspedycja.pl":               "ACS_OFFICE",
    # Evidence: VAT statements ("Zestawienie do VAT") monthly.
    # Also appears as "Asia AC Spedycja" in email display name.
    # Full name: Joanna Bąk — office/billing
    # Role: Billing and VAT reporting only. Not clearance trigger.

    # ── Ganther Sp. z o.o. ───────────────────────────────────────────────────
    "ciagarlak@ganther.com.pl":          "GANTHER_PRIMARY",
    # Evidence: Every shipment. DHL duty relay + FedEx full clearance.
    # Full name: Grzegorz Ciągarlak — Air & Sea Freight, Ganther
    # CRITICAL — PZC relay + duty notice for ALL carriers.

    "jaworska@ganther.com.pl":           "GANTHER_SECONDARY",
    # Evidence: CC on DHL clearance threads from Feb 2026.
    # Full name: Patrycja Jaworska — Ganther
    # Role: Secondary/backup coordinator.

    "krzysztof.suchodola@ganther.com.pl":"GANTHER_ADMIN",
    # Evidence: CC on overdue Ganther invoice demand Jan 2026.
    # Full name: Krzysztof Suchodola — Ganther
    # Role: Admin/finance (not clearance ops).
    # Risk: Low. Only visible in billing context.
    # NEW — not in original proposal.

    # ── FedEx Poland ─────────────────────────────────────────────────────────
    "pl-import@fedex.com":               "FEDEX_CUSTOMS",
    # Evidence: AWB 887467026597 Jan–Feb 2026; AWB 882994160903 Aug 2025.
    # Role: FedEx Poland Import Customs — equivalent of odprawacelna@dhl.com.
    # CRITICAL — this is the FedEx clearance trigger address.
    # Subject format: "Your FEDEX Shipment: {AWB}"
    # NEW — not in original proposal.

    "poland@fedex.com":                  "FEDEX_SERVICE",
    # Evidence: Warehouse release + case escalation messages.
    # Role: FedEx Poland customer service. NOT customs clearance.
    # Risk: Low. Only acts on escalated cases.
    # NEW — not in original proposal.
}
```

---

## SECTION 2 — INTERNAL_MAILBOXES_TO_MONITOR (Complete)

```python
INTERNAL_MAILBOXES_TO_MONITOR = [
    "info@estrellajewels.eu",
    # Primary general inbox. Most carrier emails arrive here.
    # Risk: High volume — needs subject-line filtering.

    "import@estrellajewels.eu",
    # Import coordinator (Tejal). Receives all clearance CC.
    # Primary action mailbox for import decisions.

    "account@estrellajewels.eu",
    # Poland Accounts. CANONICAL duty payment target from Apr 2026.
    # Must be in TO field on all duty notices.

    "amit@estrellajewels.eu",
    # Personal inbox of Amit Gupta.
    # ROUTING RISK: duty notices were sent here Jan–Mar 2026.
    # Monitor for duty emails arriving here without account@ in TO.
    # NEW flagging — not in original proposal.
]
```

---

## SECTION 3 — DO_NOT_TRIGGER (Automated addresses to ignore)

```python
DO_NOT_TRIGGER = [
    # FedEx automated
    "CaseUpdate@fedex.com",          # Ticket status — no action needed
    "TrackingUpdates@fedex.com",     # Delivery tracking — informational only
    "ie599@mail.fedex.com",          # EXPORT clearance — not import trigger
    "pl-eksport@fedex.com",          # FedEx export team — outbound only
    "FedEx-CN-Import-SCN@fedex.com", # FedEx China import — not Polish import
    "pickup@fedex.com",              # Pickup confirmations
    "noreply@fedex.com",             # No-reply
    "onlineservice@fedex.com",       # FedEx.com profile notifications
    "DataRWA@fedex.com",             # FedEx internal ops — not clearance

    # FedEx commercial
    "Zaneta.Nagat@fedex.com",        # Sales rep — not clearance

    # Inter-company accounting
    "accounts@gjlindia.com",         # GJL India — accounting loop only
    "dyszynska@abf-biurorachunkowe.pl", # ABF accounting firm

    # DHL automated non-clearance
    "NoReply.ODD@dhl.com",           # DHL On Demand Delivery notifications
]
```

---

## SECTION 4 — AWB EXTRACTION PATTERNS

```python
AWB_EXTRACTION_PATTERNS = {
    "DHL": {
        "subject_regex": r"przesyłka numer:\s*(\d{10,12})",
        "subject_example": "[T#1WA2604140000123] - Agencja Celna DHL - przesyłka numer: 3283625844",
        "ticket_regex": r"\[T#1WA(\d{14,16})\]",
        "awb_length": 10,
    },
    "FEDEX": {
        "subject_regex": r"Your FEDEX Shipment:\s*(\d{10,12})",
        "subject_example": "Your FEDEX Shipment: 887467026597",
        "case_regex": r"C-(\d{9})",
        "awb_length": 12,
    },
    "GENERIC": {
        "body_regex": r"\b(\d{10,12})\b",  # Match any 10–12 digit number in body
    }
}
```

---

## SECTION 5 — ROUTING RISK ALERTS (Proposed Automation Guards)

### Guard 1: Duty to Personal Inbox
```python
def check_duty_routing_gap(audit: dict) -> bool:
    """Returns True if duty notice went to amit@ without account@ in TO."""
    duty_event = next(
        (ev for ev in (audit.get("timeline") or [])
         if ev.get("event") == "duty_note_received"),
        None
    )
    if not duty_event:
        return False
    to_address = (duty_event.get("detail") or {}).get("to_address", "")
    has_amit = "amit@estrellajewels.eu" in to_address
    has_account = "account@estrellajewels.eu" in to_address
    return has_amit and not has_account
```

### Guard 2: FedEx Billing Mismatch
```python
def check_fedex_billing_mode(audit: dict) -> bool:
    """Returns True if FedEx shipment has recipient-pays billing (risk of customer charge)."""
    return any(
        (ev.get("detail") or {}).get("fedex_billing_mode") == "recipient_pays"
        for ev in (audit.get("timeline") or [])
    )
```

---

## SECTION 6 — IMPLEMENTATION PRIORITY

| Item | Priority | Risk | Config Change Type |
|------|----------|------|-------------------|
| `pl-import@fedex.com` as FEDEX_CUSTOMS | HIGH | Zero risk | Add to TRUSTED_CLEARANCE_SENDERS |
| `adrian@acspedycja.pl` as ACS_AGENT | HIGH | Low risk | Add to TRUSTED_CLEARANCE_SENDERS |
| DO_NOT_TRIGGER list | HIGH | Zero risk | New section |
| Duty routing gap guard | MEDIUM | Prevents silent delay | New automation guard |
| `krzysztof.suchodola@ganther.com.pl` | LOW | Admin only | Add to TRUSTED (admin tier) |
| FedEx DSK trigger (T3) | HIGH | Low risk | New cowork trigger |

---

## SECTION 7 — APPROVAL GATE

**NONE of these changes take effect automatically.**

Before any address is added to TRUSTED_CLEARANCE_SENDERS:
1. Admin reviews this proposal
2. Admin confirms sender identity matches known contact
3. Admin approves the specific addition
4. Developer adds to config with approval reference

**Required approvals pending:**
- [ ] `pl-import@fedex.com` — FEDEX_CUSTOMS designation
- [ ] `adrian@acspedycja.pl` — ACS_AGENT designation
- [ ] `DO_NOT_TRIGGER` list implementation
- [ ] FedEx DSK trigger (T3) activation in cowork_coordinator.py

---

*This document supersedes EMAIL_ROUTING_UPDATE_PROPOSAL.md.*
*All proposals are evidence-based from email thread analysis Aug 2025 – Apr 2026.*
