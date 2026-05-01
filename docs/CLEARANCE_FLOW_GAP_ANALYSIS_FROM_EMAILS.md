# Clearance Flow Gap Analysis
## From Email Evidence vs. System Design
### Source: 11 shipments, Jan 27 – Apr 27, 2026

---

## Summary

The email record reveals **7 significant gaps** between the observed real-world workflow
and the current system design assumptions. Three gaps are blocking risks that have already
caused delays. Four are operational gaps that increase manual overhead.

---

## Gap 1 — Payment Confirmation is Invisible to the System (CRITICAL)

**What the system assumes:** After ACS sends PZC + duty notice, the operator confirms payment
in the dashboard, which closes the loop.

**What the emails show:** Estrella's accounts team (Tejal, `account@estrellajewels.eu`) pays
the duty directly — no payment confirmation email was found inbound to any monitored address.
The only confirmation observed is Ganther's "dzieki, płaci się" email, which arrives
**after** payment, as an informal acknowledgment.

**Real-world path:**
```
ACS duty notice → Ganther notifies account@estrellajewels.eu (PLN amount)
→ Tejal initiates bank transfer
→ Ganther receives payment (from which bank account? unclear)
→ Ganther sends "dzieki, płaci się" to thread
```

**Gap:** The system has no way to detect when duty is actually paid. The "paid" event
only exists as Ganther's informal reply in a thread.

**Impact:** Clearance status cannot auto-advance to "duty paid". Manual dashboard update required.

**Recommended fix:** Treat GANTHER_PAYMENT_ACK email ("płaci się") as the duty-paid signal.
Add `clearance_status = "duty_paid"` trigger when this email is detected on a known AWB thread.

---

## Gap 2 — ZC429/SAD File Arrives as Email Attachment (OPPORTUNITY)

**What the system assumes:** SAD/ZC429 file is uploaded manually to the dashboard.

**What the emails show:** `no-reply@acspedycja.pl` sends the ZC429 document as an email
attachment (TYPE 4: AIS_ZC429_CLEARANCE_NOTIFICATION) automatically the moment customs
clearance is approved. It arrives at `import@estrellajewels.eu` and `account@estrellajewels.eu`
**before** anyone calls or emails.

**Gap:** The system waits for manual upload of the ZC429 document, but it is already being
delivered by email to Estrella's mailbox — automatically, reliably, with a predictable
sender (`no-reply@acspedycja.pl`) and static subject line.

**Impact:** Every batch that uses the dashboard requires a manual download-and-upload step
that could be fully automated.

**Recommended fix:** Monitor `no-reply@acspedycja.pl` emails. When TYPE 4 (AIS_ZC429) is
detected, download the PDF attachment, match to AWB (from thread context or preceding emails),
and auto-attach to the pending batch in the system.

---

## Gap 3 — No Monitoring for Stuck/Delayed Shipments (CRITICAL)

**What the emails show:** AWB 2824221912 (Mar 10, 2026) sat for **28 days** without a duty
payment or shipment release. Amit had to manually send an "URGENT CUSTOMS CLEARANCE" email
to Ganther. Ganther replied confirming everything was done on their side — the delay was
entirely on Estrella's side (nobody in accounts was aware of the duty notice).

**The Ganther response was explicit:**
"We make Cust Clearance of the shipment, released shipment by mail to DHL, send you duty/tax
nota and PZC document, issued our invoice to Estrella. As per DHL, shipment 2824221912 is
delivered to consignee. So the matter is closed."

**What this means:** Ganther did their job. ACS did their job. DHL released the shipment.
**But Estrella paid 28 days late**. The nota was sent to `account@estrellajewels.eu`
and went unactioned.

**Gap:** No timeout or escalation trigger exists for unacknowledged duty payment notices.

**Impact:** Shipments can sit at DHL (accruing storage fees) or be released before payment,
creating a payment tracking problem.

**Recommended fix:** When GANTHER_DUTY email is detected and no GANTHER_PAYMENT_ACK follows
within 3 business days, send an escalation notification to `amit@estrellajewels.eu`.

---

## Gap 4 — Broker Appointment Timing is Manual and Inconsistent

**What the system assumes:** Estrella's broker appointment letter is sent as a fixed response
after the DHL notification is received.

**What the emails show:**
- AWB 3283625844: Estrella sent broker appointment BEFORE DHL sent the cesja (Apr 13 vs Apr 14)
- AWB 5180358875: Estrella sent multiple document replies directly to DHL (no standard broker letter pattern)
- Most shipments: No outgoing broker appointment letter found in sent folder

**Gap:** In most clearance threads, there is no evidence of Estrella sending a formal broker
appointment letter. Either (a) it was sent before the date range, (b) sent from a different
account, or (c) DHL proceeds without it after an earlier standing instruction.

**What this means for the system:** The `send_dhl_reply` step (the DHL cesja reply in the
current system) may not always be the correct starting point. DHL may already have Ganther's
standing authorization for this account.

**Recommended fix:** Verify with DHL whether a standing POA (Power of Attorney) exists for
Ganther. If yes, remove the mandatory broker appointment step from the automation flow or
make it optional (only send if no cesja received within 48h of notification).

---

## Gap 5 — Cesja Document Not Archived by Estrella

**What the system design implies:** The DSK/cesja document should be tracked.

**What the emails show:** DHL sends the cesja to `roman@acspedycja.pl` CC `info@estrellajewels.eu`.
The email arrives in Estrella's inbox, but the cesja document itself is only ever viewed as
a CC — never saved, indexed, or used downstream in the system.

**Gap:** No cesja archive. If ACS loses the document or there's a dispute, Estrella cannot
prove the transfer of authority happened on a specific date.

**Current DSK source tracking in system:** `is_dsk_source()` checks `administracja_centralna@dhl.com`
— but cesja emails come from `odprawacelna@dhl.com`, not from `administracja_centralna@dhl.com`.
`administracja_centralna@dhl.com` only **receives** emails (as a recipient), never sends them.

**Impact:** DSK source detection will never trigger in practice with the current config.

**Recommended fix:** Add `odprawacelna@dhl.com` to `DHL_DSK_SOURCE` in `email_routing.py`,
since that is the actual sender of cesja emails.

---

## Gap 6 — Duty Amount Never Enters System Data Model

**What the emails show:** Every shipment has a specific duty amount in PLN, delivered reliably
via GANTHER_DUTY email. Amounts observed: 467, 1181, 1225, 1414, and higher PLN values.

**What the system stores:** `clearance_decision` stores USD CIF value and routing path,
but **no duty amount in PLN** is stored anywhere.

**Gap:** The actual duty cost (PLN) is not tracked in `audit.json` at any step.
This means:
- PZ documents cannot reflect actual duty paid
- Financial reconciliation requires manual lookup of Ganther emails
- The system cannot compute total landed cost accurately in PLN

**Recommended fix:** Add `duty_pln_amount` field to `audit.json` when GANTHER_DUTY email
is processed, extracted from the email body.

---

## Gap 7 — Special Handling for "Temporary Export Returnees" Not in System

**What the emails show:** AWB 5180358875 was goods returning from HK International
Jewellery Show. This required a completely different DHL process — no cesja, no ACS,
DHL handled customs internally, Estrella had to prove temporary export origin.

**Gap:** The system has no concept of temporary-export returnee (RE-IMPORT category).
All shipments are treated as standard imports.

**Impact:** When another trade fair shipment returns, the system will try to send a
standard agency email (if >$2500), which is incorrect. The ZC429 for re-imports has
different line types and SAD structure.

**Recommended fix:** Add a `shipment_type` field to batch metadata:
- `standard_import` (default)
- `re_import` (returning temporary export)

Re-import batches should skip the agency email path and require manual DHL coordination.

---

## Gap Severity Summary

| # | Gap | Severity | Status | Quick Fix |
|---|-----|----------|--------|-----------|
| 1 | No payment confirmation signal | HIGH | Active | Detect "płaci się" as paid event |
| 2 | ZC429 arrives by email, not auto-ingested | MEDIUM | Active | Monitor no-reply@acspedycja.pl |
| 3 | No timeout for unpaid duty notices | HIGH | Active — caused 28d delay | Add 3-day escalation rule |
| 4 | Broker appointment flow inconsistent | LOW | Cosmetic | Verify standing POA with DHL |
| 5 | DSK source detection points to wrong sender | HIGH | Bug | Fix DHL_DSK_SOURCE in email_routing.py |
| 6 | Duty PLN amount not in data model | MEDIUM | Missing feature | Extract from GANTHER_DUTY email |
| 7 | No re-import category | LOW | Edge case | Add shipment_type field |

---

## Immediate Action Items

### Fix 1 (Gap 5 — Critical Bug): Correct `DHL_DSK_SOURCE`
```python
# service/app/config/email_routing.py — CURRENT (wrong)
DHL_DSK_SOURCE: List[str] = ["administracja_centralna@dhl.com"]

# SHOULD BE:
DHL_DSK_SOURCE: List[str] = ["odprawacelna@dhl.com"]
```
`administracja_centralna@dhl.com` receives emails; it never sends them.
Cesja always arrives from `odprawacelna@dhl.com`.

### Fix 2 (Gap 3): Duty Payment Timeout Rule
When a GANTHER_DUTY email is classified and attached to a batch:
- Set `audit["duty_notice_received_at"] = timestamp`
- Set `audit["duty_amount_pln"] = extracted_amount`
- If no GANTHER_PAYMENT_ACK within 72 business hours: escalate to Amit

### Fix 3 (Gap 1): Payment Signal
When GANTHER_PAYMENT_ACK ("płaci się") is detected on a known AWB thread:
- Set `audit["duty_paid_signal_at"] = timestamp`
- Set `audit["clearance_status"] = "duty_paid"`
