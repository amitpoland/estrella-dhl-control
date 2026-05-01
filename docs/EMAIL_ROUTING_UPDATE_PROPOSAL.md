# Email Routing Update Proposal
## Config Changes Derived from Email Actor Discovery
### Status: PROPOSAL ONLY — no changes applied — admin approval required
### Based on: 11 shipments, Jan–Apr 2026 | Companion to: EMAIL_ACTOR_DISCOVERY.md

---

## Safety Rule

**No new email address becomes an active sender/recipient in the monitoring system without explicit admin approval.**

This document proposes changes. Nothing is deployed. Every proposed change is tagged with:
- **CONFIDENCE** — how certain we are this address is legitimate and stable
- **RISK** — what happens if we get it wrong
- **EVIDENCE** — exact shipment/email citations

---

## Part 1: Critical Additions (Deploy These First)

### P1.1 — Add `no-reply@acspedycja.pl` to Trusted Senders

**Proposed key:** `AIS_ZC429_SENDER`
**Proposed action:** `ADD_TO_APPROVED_SENDERS`
**Priority:** CRITICAL

```python
# Add to TRUSTED_CLEARANCE_SENDERS
"no-reply@acspedycja.pl": "AIS_ZC429",  # ACS automated ZC429 notification
```

| Field | Value |
|-------|-------|
| Confidence | VERY HIGH — automated system, consistent subject line, consistent format |
| Evidence | AWB 1214569005 (2026-03-03 09:36 UTC) and AWB 2824221912 (2026-03-12 09:36 UTC) — both ZC429 clearance notifications |
| Subject exact | `"Powiadomienie AIS - Zwolnienie do procedury (ZC429/PW429/wpis)"` |
| Sender type | Automated (WinSADMS customs software) — never sends human messages |
| Risk if missed | Every ZC429 clearance notification goes undetected; Trigger 2 never fires; entire clearance pipeline breaks |
| Risk if wrong | ZC429 is read-only — no financial or legal action taken from this email alone; safe to add |

---

### P1.2 — Add `logistyka@acspedycja.pl` to Trusted Senders

**Proposed key:** `ACS_AGENT_BACKUP`
**Proposed action:** `ADD_TO_APPROVED_SENDERS`
**Priority:** HIGH

```python
# Add to TRUSTED_CLEARANCE_SENDERS
"logistyka@acspedycja.pl": "ACS_AGENT",  # Bartłomiej Bugaj (backup for Piotr Kubsik)
```

| Field | Value |
|-------|-------|
| Confidence | HIGH — named individual, consistent email address, confirmed sender of real PZC documents |
| Person | Bartłomiej Bugaj |
| Evidence | AWB 8580992114 (2026-02-13 08:06 UTC): PZC email with attachments. AWB 8523214840 (2026-04-02 06:13 UTC): clearance email with attachments. Both were valid operational emails, not spam. |
| Pattern | Acts as Piotr Kubsik's backup when Piotr is unavailable |
| Risk if missed | Trigger 3 (ACS_PZC_RECEIVED) never fires for 2 out of 11 observed shipments; ZC429 auto-save fails |
| Risk if wrong | Malicious actor at `logistyka@acspedycja.pl` could send fake PZC — but this is a Polish customs agency with contractual relationship; very low risk of compromise |

---

## Part 2: Routing Risk Fixes (Address Routing Bugs)

### P2.1 — `tejal@estrellajewels.com` Alias Detection

**Issue:** Ganther sends duty payment notices to `tejal@estrellajewels.com` (`.com` domain) in some shipments, not `account@estrellajewels.eu`. If the `.com` mailbox is not actively monitored, duty notices silently disappear.

**Proposed fix:** Two options — pick one.

**Option A (Preferred): Monitor `.com` mailbox too**
```python
INTERNAL_MAILBOXES = [
    "info@estrellajewels.eu",
    "import@estrellajewels.eu",
    "account@estrellajewels.eu",
    "tejal@estrellajewels.com",  # ADD — duty notices sometimes sent here
]
```

**Option B: Notify Ganther of correct address**
Draft a one-time correction email to `ciagarlak@ganther.com.pl`:
```
Subject: Correct email for duty payment notices

Hi Grzegorz,

Please send all duty payment notices and notas to:
  account@estrellajewels.eu

The address tejal@estrellajewels.com is not always monitored.

Thank you.
```

| Field | Value |
|-------|-------|
| Confidence | HIGH — confirmed from AWB 2824221912 where duty notice went to `amit@estrellajewels.eu` instead of `account@estrellajewels.eu`, causing 28-day delay; `.com` variant seen as recipient in Ganther emails |
| Risk of inaction | Silent duty payment miss — exact same failure mode as AWB 2824221912 |
| Recommended path | Option B (correct source) + Option A as safety net |

---

### P2.2 — `amit@estrellajewels.eu` Monitoring for Duty Notices

**Issue:** AWB 2824221912 — duty notice was sent to `amit@estrellajewels.eu`. When Amit does not see it (travel, high-volume inbox), duty goes unpaid indefinitely.

**Proposed fix:** Add a routing rule that flags incoming duty-pattern emails to `amit@` and forwards to `account@` automatically:

```python
# Monitoring rule — not sender-based, recipient-based
DUTY_NOTICE_RECIPIENT_WATCH = [
    "account@estrellajewels.eu",  # primary
    "amit@estrellajewels.eu",     # secondary — if duty pattern detected here, re-alert #PZ
]

# If duty email arrives at amit@ with no corresponding record in account@ thread:
# → Post to #PZ: "⚠️ Duty notice received in Amit's inbox instead of accounts — check AWB {awb}"
```

| Field | Value |
|-------|-------|
| Confidence | CONFIRMED — AWB 2824221912 root cause is documented |
| Risk of inaction | 28-day delay repeats; goods received before duty paid |

---

## Part 3: Watch-Only Additions (No Trigger Actions)

### P3.1 — Add `Iwona.Sosnowska-Zdunowska@dhl.com` as Watch/Escalation Contact

**Proposed action:** `WATCH_ONLY` — add to escalation contact list, not trigger whitelist

```python
DHL_ESCALATION_CONTACTS = {
    "Iwona.Sosnowska-Zdunowska@dhl.com": "DHL_SUPERVISOR",  # Head of DHL customs team
    # Use for: service failures, unresponsive cesja team, DHL-side delays >48h
}
```

| Field | Value |
|-------|-------|
| Confidence | MEDIUM — appears in every DHL cesja email signature as feedback contact |
| Role | Supervisor of Anna Wasacz / Paulina Debowska / Andrzej Strzelec (staff sending cesja) |
| Use case | Draft escalation email here if DHL fails to respond within SLA |
| Risk | Supervisor contact — low risk of abuse; no automated actions triggered |

---

### P3.2 — Add `plwawecs@dhl.com` as Watch-Only

**Proposed action:** `WATCH_ONLY`

```python
# For DHL atypical cases (temporary export, trade fair returns, special handling)
DHL_SPECIAL_HANDLERS = {
    "plwawecs@dhl.com": "DHL_SPECIAL",  # DHL WAW special customs team
    # Used in AWB 5180358875 (HK trade fair return)
}
```

| Field | Value |
|-------|-------|
| Confidence | MEDIUM — confirmed for AWB 5180358875, single atypical case |
| Use case | If a trade fair return or temporary import appears, route to this handler; different process |
| Risk | Low — separate handler, not standard clearance path |

---

### P3.3 — Add `jaworska@ganther.com.pl` to Forwarder Watch List

**Proposed action:** `ADD_TO_CC_ONLY` (already referenced in v2 TRUSTED_CLEARANCE_SENDERS)

```python
# Already in v2 whitelist — confirm and activate:
"jaworska@ganther.com.pl": "GANTHER_SECONDARY",
```

| Field | Value |
|-------|-------|
| Confidence | MEDIUM — CC in Ganther threads; never primary From; assumed backup contact |
| Risk | Low — always CC, never trigger source |

---

## Part 4: External Third Party — Review Required

### P4.1 — `jigar.p@simplex-hurtownia.pl`

**Proposed action:** `MANUAL_REVIEW` — do not add automatically

| Field | Value |
|-------|-------|
| Evidence | CC in AWB 1214569005 thread (ACS notification) |
| Company | simplex-hurtownia.pl — related Estrella/Europe Simpleks entity |
| Relationship | Unknown — may be warehouse, may be importer-of-record variant, may be observer |
| Recommended action | Confirm with Amit: "Is Jigar at simplex-hurtownia.pl a valid CC for import notifications?" |

---

## Part 5: Ignore List — Do Not Add to Monitoring

These addresses appeared in the corpus but have no operational role in clearance monitoring:

| Address | Reason to Ignore |
|---------|-----------------|
| `pl.dhlexp.iod@dhl.com` | DHL Data Protection Officer — GDPR legal footer only; never sends operational emails |
| `portalklienta@kuke.com.pl` | KUKE insurance portal — unrelated to customs clearance; auto-notifications |
| `privacy@estrellajewels.com` | Estrella legal footer — compliance contact only |
| `it@estrellajewels.com` | Estrella IT footer — internal support only |
| `kontakt.int@dhl.com` | Seen once in atypical HK case only; no pattern |
| `wawpok@dhl.com` | Seen once in HK case proforma query; no repeat pattern |

---

## Part 6: Proposed Final `TRUSTED_CLEARANCE_SENDERS` Config

This is the complete proposed config (additions from this discovery shown with `# NEW`):

```python
# v2.1 — After Email Actor Discovery Audit
TRUSTED_CLEARANCE_SENDERS = {
    # DHL
    "odprawacelna@dhl.com":              "DHL_CESJA",            # sends cesja (CORRECTED from v1)
    "plwawecs@dhl.com":                  "DHL_SPECIAL",          # DHL WAW special cases (NEW)

    # ACS Spedycja
    "no-reply@acspedycja.pl":            "AIS_ZC429",            # ACS automated ZC429 (NEW — CRITICAL)
    "piotr@acspedycja.pl":               "ACS_AGENT",            # Piotr Kubsik (existing)
    "logistyka@acspedycja.pl":           "ACS_AGENT",            # Bartłomiej Bugaj (NEW — HIGH)
    "biuro@acspedycja.pl":               "ACS_OFFICE",           # ACS office (existing)
    "roman@acspedycja.pl":               "ACS_AGENT",            # Roman Kałużny (existing)

    # Ganther
    "ciagarlak@ganther.com.pl":          "GANTHER_COORDINATOR",  # Grzegorz Ciągarlak (existing)
    "jaworska@ganther.com.pl":           "GANTHER_SECONDARY",    # Ganther backup (NEW — watch only)
}

# Billing senders (already known — no change)
BILLING_SENDERS = [
    "windykacja.DHLexpress@dhl.com",
    "Justyna.CZYNSZ@dhl.com",
]

# Monitored Estrella mailboxes — for incoming email classification
INTERNAL_MAILBOXES_TO_MONITOR = [
    "info@estrellajewels.eu",
    "import@estrellajewels.eu",
    "account@estrellajewels.eu",
    "tejal@estrellajewels.com",      # NEW — duty notice routing risk
]

# Escalation contacts — NOT trigger sources; use for drafting escalation emails only
DHL_ESCALATION_CONTACTS = {
    "Iwona.Sosnowska-Zdunowska@dhl.com": "DHL_SUPERVISOR",      # NEW — watch only
}

# DHL recipient (receives PZC release instructions FROM Ganther)
DHL_PZC_RELEASE_RECIPIENT = "administracja_centralna@dhl.com"  # NOT a sender
DHL_DSK_SOURCE = ["odprawacelna@dhl.com"]                        # CORRECTED from v1
```

---

## Part 7: Implementation Priority

| Priority | Change | Impact | Risk |
|----------|--------|--------|------|
| 🚨 P0 | Add `no-reply@acspedycja.pl` | Enables Trigger 2 (ZC429 auto-detection) | LOW — read-only automation |
| 🔴 P1 | Add `logistyka@acspedycja.pl` | Enables Trigger 3 for 2/11 shipments (Bartłomiej's) | LOW — same contract relationship as Piotr |
| 🔴 P1 | Fix `.com` duty routing (P2.1 Option B) | Prevents silent duty miss | ZERO — corrects third-party email address |
| ⚠️ P2 | Add `amit@` duty watch rule (P2.2) | Prevents repeat of AWB 2824221912 | LOW — monitoring rule only |
| ⚠️ P2 | Add `jaworska@ganther.com.pl` | Complete Ganther coverage | LOW — CC only |
| 📄 P3 | Add `plwawecs@dhl.com` watch | Atypical case handling | LOW — separate path |
| 📄 P3 | Add `Iwona.Sosnowska-Zdunowska@dhl.com` escalation | Escalation drafting | LOW — not triggered automatically |
| 🔍 P4 | Review `jigar.p@simplex-hurtownia.pl` | Confirm relationship before any action | UNKNOWN — needs admin decision |

---

## Admin Approval Checklist

Before deployment, confirm each of the following:

```
□ Confirm no-reply@acspedycja.pl is the stable ZC429 sender address (not per-installation)
□ Confirm logistyka@acspedycja.pl belongs to Bartłomiej Bugaj (not reassigned)
□ Confirm tejal@estrellajewels.com is monitored OR send address correction to Ganther
□ Confirm jigar.p@simplex-hurtownia.pl — relationship and whether to include as CC
□ Confirm Iwona.Sosnowska-Zdunowska@dhl.com as appropriate escalation contact
□ Apply fix to email_routing.py: DHL_DSK_SOURCE = ["odprawacelna@dhl.com"] (if not already done)
```

---

*This document is read-only discovery output. No configuration has been modified.*
*Generated from 11 shipment email threads, Jan 27 – Apr 27, 2026.*
