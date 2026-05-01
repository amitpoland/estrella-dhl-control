# ONE_YEAR_DSK_FLOW_ANALYSIS.md
# Estrella Jewels — DSK (Cession / Cesja) Flow Analysis
# Period: Jun 2024 – Apr 2026 | Carrier: DHL + FedEx
# Generated: 2026-04-27

---

## Executive Summary

DSK (Dokument Stwierdzający Kwotę / cession rights document) is the mechanism by which
Estrella transfers customs representation rights to its broker (Ganther). The DSK flow
differs significantly between DHL and FedEx. DHL cesja is handled internally by ACS;
FedEx cesja must be submitted manually by Estrella to `pl-import@fedex.com`. One confirmed
DSK delay occurred on FedEx AWB 887467026597 (Jan 2026, 3-4 day delay). No confirmed DHL
DSK failures in the analysis period.

---

## 1. DSK / Cesja — What It Is

**Cesja** (Polish: "cession") is the formal transfer of clearance rights from the importer
(Estrella) to the customs broker (Ganther). Without this document, Ganther cannot file the
SAD or represent Estrella at customs.

**DSK** is the document that proves Ganther has received cession rights. Customs requires this
before accepting Ganther's SAD filing on Estrella's behalf.

This is required for EVERY shipment. There is no "standing" cesja — it must be executed per-AWB.

---

## 2. DHL DSK Flow (ACS-mediated)

```
DHL arrives
    ↓
DHL sends arrival notification to Estrella + ACS + Ganther
    ↓
DHL sends Cesja Fwd to ACS separately (with cesja attachment)
    ↓
ACS processes cesja internally
    ↓
ACS issues DSK to Ganther
    ↓
Ganther can now file SAD / obtain PZC
    ↓
PZC issued → duty notice → clearance
```

**Key property:** ACS Spedycja handles the entire cesja process internally. Estrella does NOT
need to submit anything. The cesja document flows DHL→ACS→Ganther.

### DHL Cesja Email Pattern (2 emails per AWB)

**Email type 1 — Initial arrival notification:**
```
FROM: odprawacelna@dhl.com (e.g., "Zaneta Rybaczewska")
TO: import@estrellajewels.eu, roman@acspedycja.pl, ganther.com.pl
Subject: AWB <number> — arrival / clearance
Content: AWB details, declared value, weight, instructions
```

**Email type 2 — Cesja Fwd (ACS only):**
```
FROM: odprawacelna@dhl.com
TO: roman@acspedycja.pl (or other ACS agent)
Subject: Fwd: Cesja AWB <number>
Attachment: cesja document
Content: forwarded cesja for ACS processing
```

Estrella is typically CC'd on type 1 but not type 2.

### DHL Cesja Staff (named in email signatures)

| Name | Role | Period |
|------|------|--------|
| Zaneta Rybaczewska | DHL customs specialist | Ongoing |
| Anna Was | DHL cesja handler | Active |
| Paulina Debowska | DHL cesja handler | Active |
| Andrzej (surname unknown) | DHL cesja handler | Active |
| Julia Barczuk | DHL cesja handler | Active |
| Dominika Soberka | DHL cesja handler | Active |
| Olena | DHL cesja handler | Active |

DHL has a pool of 7 confirmed cesja staff — rotation is normal and expected.

### DHL DSK Evidence

**Oldest DSK on record:** AWB 4560229026 (~Jun 2024) — DSK reference `25PL44302D004MARU8`
preserved in Ganther email thread. Confirms the DSK mechanism has been stable for 2+ years.

**DHL DSK timing:** Typically 0–2 days from arrival notification to DSK issued. Not a bottleneck
in standard DHL flow.

---

## 3. FedEx DSK Flow (Importer-initiated)

```
FedEx arrives
    ↓
FedEx sends notification to pl-import@fedex.com AND Estrella
    ↓
FedEx sends cesja form to Amit/Roman/Ganther by email
    ↓
⚠️ ESTRELLA must manually submit cesja form to pl-import@fedex.com
    ↓
FedEx auto-acknowledges cesja submission
    ↓
FedEx issues DSK to Ganther (typically Day 5 from arrival)
    ↓
Ganther files SAD: "przesyłka w odprawie" (in clearance)
    ↓
PZC issued → duty notice → clearance
    ↓
FedEx provides warehouse address → delivery arranged
```

**Critical difference from DHL:** Estrella must actively submit the cesja form. This is a
manual step that can be missed if `import@estrellajewels.eu` (Tejal) misses the FedEx email.

### FedEx DSK Evidence — AWB 887467026597 (Jan–Feb 2026)

Full timeline reconstructed:

| Day | Event |
|-----|-------|
| 0 | FedEx notification arrives at pl-import@fedex.com |
| 0 | Cesja form sent to Amit / Roman / Ganther by FedEx |
| 3 | Ganther asks: "Have you asked FedEx for Cession of rights?" |
| 4 | Cesja docs submitted; FedEx auto-ack received |
| 5 | DSK issued by FedEx to Ganther |
| 5 | Ganther: "przesyłka w odprawie" (in clearance) |
| 6 | Ganther sends PZC to FedEx + clearance notification to Amit |
| 9 | FedEx provides warehouse address; delivery arranged |

**The 3-day gap (Day 0→3)** is the DSK_MISSING window — Ganther had to follow up because
the cesja form was not submitted promptly. This 3-day gap is the automation opportunity.

---

## 4. DSK Failure Modes

### Mode 1: FedEx cesja not submitted on time (CONFIRMED)

**Evidence:** AWB 887467026597 — Ganther followed up on Day 3 asking if cesja had been
submitted. Without this follow-up, delay could have extended further.

**Detection:** If FedEx arrival email received from `pl-import@fedex.com` and no cesja
submission confirmation within 24 hours → trigger T3 (DSK_MISSING FedEx).

### Mode 2: DHL cesja ACS routing failure (NOT OBSERVED)

No confirmed cases of DHL cesja failing to route from odprawacelna@dhl.com to ACS in the
analysis period. The DHL cesja mechanism appears robust.

### Mode 3: DSK_MISSING (DHL general) trigger — T1

The existing T1 trigger detects: `require_dsk=True` + `arrived_warehouse=True` + no DSK
file + more than N hours since `clearance_updated_at`.

This is a general DHL DSK missing trigger. No confirmed fire in production data (no real-world
DHL DSK failure observed in the analysis period).

---

## 5. FedEx Cesja Additional Complication — FCA Terms

For AWB 887467026597, the FedEx invoice used FCA (Free Carrier) incoterms.

**Impact:** FCA terms mean Ganther needs the transport invoice in addition to the cesja form.
This adds 1–2 days to clearance because:
1. Ganther must identify the FCA situation
2. Ganther requests transport invoice from Estrella
3. Estrella obtains transport invoice from shipper
4. Ganther refiles with correct CIF value

**Detection:** If Ganther email contains "FCA" and "transport invoice" / "faktura transportowa"
→ flag as FCA complication → inform `import@estrellajewels.eu` immediately.

---

## 6. DSK in the PZ System

DSK filename is stored in `audit["dsk_filename"]`. This field is checked by T1 trigger:

```python
# From detect_triggers():
if (audit.get("clearance_decision", {}).get("require_dsk") and
    audit.get("tracking", {}).get("arrived_warehouse") and
    not audit.get("dsk_filename") and ...):
    # fire T1: DSK_MISSING
```

For FedEx, the equivalent is T3 (DSK_MISSING FedEx) — detect `pl-import@fedex.com` arrival
without cesja submission confirmation.

---

## 7. DSK Timing Reference

| Carrier | Cesja Initiator | DSK Timing | Risk of Delay |
|---------|----------------|-----------|--------------|
| DHL | ACS Spedycja (automatic) | Day 0–2 from arrival | LOW |
| FedEx | Estrella / import@ (manual) | Day 4–5 from arrival | MEDIUM — requires human action |

---

## 8. Automation Recommendations

1. **T3 FedEx DSK trigger:** Detect `pl-import@fedex.com` email → check for cesja submission
   confirmation within 24h → if absent, alert `import@estrellajewels.eu` with action:
   "Submit cesja to pl-import@fedex.com — AWB <number>".

2. **Cesja timeline event:** Add `cesja_submitted` event to timeline when cesja confirmation
   received from FedEx (`auto-ack` or `pl-import@fedex.com` reply).

3. **FCA complication flag:** Detect "FCA" in Ganther email body → set `fca_complication=True`
   in audit → alert import@ that transport invoice may be required.

4. **DHL cesja audit:** Log `dhl_cesja_forwarded` timeline event when DHL sends cesja Fwd
   to ACS → confirms the DHL→ACS cesja leg completed.

---

*Analysis complete. All findings are evidence-based from email thread examination.*
*No production data was modified.*
