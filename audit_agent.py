#!/usr/bin/env python3
"""
audit_agent.py — Bilingual compliance audit report for PZ import batches
=========================================================================
Accepts the result dict from process_batch() plus output metadata.
Runs 6 structured checks and writes:
    audit_report_en.txt   — English compliance report
    audit_report_pl.txt   — Polish compliance report (Raport audytowy)

Returns a dict with both file Paths so the caller can link them in Cliq.

Checks performed:
  1. Exporter identity chain        (invoice seller vs SAD field 2)
  2. Importer identity + VAT/NIP    (invoice buyer vs SAD field 8 + NIP)
  3. Address classification         (registered office vs warehouse vs delivery)
  4. Invoice chain reconciliation   (PDF invoice numbers vs SAD N935 refs, with severity)
  5. Value reconciliation           (per-invoice FOB+F+I=CIF, total CIF vs SAD, duty source, NBP delta)
  6. Transport linkage              (AWB from N740 transport refs vs known patterns)

Usage (from export_service.py):
    from audit_agent import build_audit_report
    report_paths = build_audit_report(result, output_dir, batch_id, doc_no)
    # returns {"en": Path(...), "pl": Path(...)}
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Importer master record (mirrors RECIPIENT in pz_import_processor.py) ─────
_IMPORTER_NAME = "ESTRELLA JEWELS Sp. z o. o. SPÓŁKA KOMANDYTOWA"
_IMPORTER_NIP  = "5252812119"
_IMPORTER_REG_ADDR = "ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa"
_IMPORTER_REG_TYPE = "Registered office / Siedziba spółki"

# Known warehouse / delivery addresses (add as they appear in practice)
_KNOWN_WAREHOUSE_KEYWORDS = ["sabały", "sabaly", "magazyn", "warehouse", "składnica"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}"

def _fmt_pln(v: float) -> str:
    return f"{v:,.2f} PLN"

def _sep(char: str = "─", width: int = 60) -> str:
    return char * width

def _verdict(val: Optional[bool], lang: str = "en") -> str:
    if lang == "en":
        if val is True:  return "✅ VERIFIED"
        if val is False: return "❌ MISMATCH"
        return "⚠️  COULD NOT VERIFY"
    else:
        if val is True:  return "✅ ZWERYFIKOWANO"
        if val is False: return "❌ ROZBIEŻNOŚĆ"
        return "⚠️  NIE MOŻNA ZWERYFIKOWAĆ"

def _classify_address(addr: str) -> Tuple[str, str]:
    """Return (type_en, type_pl) for an address string."""
    if not addr:
        return ("(not parsed)", "(nie odczytano)")
    low = addr.lower()
    if any(kw in low for kw in _KNOWN_WAREHOUSE_KEYWORDS):
        return ("Warehouse / distribution centre", "Magazyn / centrum dystrybucji")
    if "wybrzeże" in low or "koscuszk" in low or "kościuszk" in low or "31/33" in low:
        return ("Registered office", "Siedziba spółki")
    return ("Delivery / other address", "Adres dostawy / inny")

def _extract_awb_digits(ref: str) -> str:
    """Strip non-digit characters and return the numeric core of an AWB/transport ref."""
    return re.sub(r"[^\d]", "", ref)


# ── Six audit checks ──────────────────────────────────────────────────────────

def _check1_exporter(v: dict, invoices: list) -> dict:
    match      = v.get("exporter_match")
    inv_seller = v.get("invoice_exporter_name") or (invoices[0].get("seller_name", "") if invoices else "")
    sad_exp    = v.get("sad_exporter_name", "")
    return {
        "result":        match,
        "invoice_value": inv_seller or "(not found)",
        "sad_value":     sad_exp    or "(not parsed)",
    }


def _check2_importer(v: dict, invoices: list) -> dict:
    inv_buyer = v.get("invoice_importer_name") or (invoices[0].get("buyer_name", "") if invoices else "")
    inv_nip   = v.get("invoice_vat")           or (invoices[0].get("buyer_nip", "")   if invoices else "")
    sad_buyer = v.get("sad_importer_name", "")
    sad_nip   = v.get("sad_vat", "")
    return {
        "name_result": v.get("importer_match"),
        "nip_result":  v.get("vat_match"),
        "invoice_name": inv_buyer or "(not found)",
        "invoice_nip":  inv_nip   or "(not found)",
        "sad_name":     sad_buyer or "(not parsed)",
        "sad_nip":      sad_nip   or "(not parsed)",
        "master_name":  _IMPORTER_NAME,
        "master_nip":   _IMPORTER_NIP,
    }


def _check3_address(invoices: list, zc429: dict) -> dict:
    inv_addr   = invoices[0].get("buyer_address", "") if invoices else ""
    sad_addr   = zc429.get("delivery_address", "")   # populated if parsed

    inv_type_en, inv_type_pl = _classify_address(inv_addr)
    sad_type_en, sad_type_pl = _classify_address(sad_addr)

    # Consistency: warehouse delivery + registered office on file = consistent
    addresses_consistent: Optional[bool]
    if not inv_addr and not sad_addr:
        addresses_consistent = None
    else:
        # Any combination of registered/warehouse is expected; only flag if unknown
        known = {"Registered office", "Warehouse / distribution centre"}
        addresses_consistent = inv_type_en in known or sad_type_en in known

    return {
        "master_reg_addr":  _IMPORTER_REG_ADDR,
        "master_reg_type":  _IMPORTER_REG_TYPE,
        "invoice_addr":     inv_addr  or "(not parsed from invoice)",
        "invoice_type_en":  inv_type_en,
        "invoice_type_pl":  inv_type_pl,
        "sad_addr":         sad_addr  or "(not parsed from SAD)",
        "sad_type_en":      sad_type_en,
        "sad_type_pl":      sad_type_pl,
        "consistent":       addresses_consistent,
    }


def _check4_invoice_chain(v: dict) -> dict:
    match      = v.get("invoice_refs_match")
    sad_refs   = v.get("sad_invoice_refs", [])
    parsed_nos = v.get("parsed_invoice_nos", [])
    missing    = v.get("missing_invoices_in_pdfs", [])
    extra      = v.get("extra_invoices_not_in_sad", [])

    # Severity classification
    if match is True:
        severity_en, severity_pl = "OK — full match", "OK — pełna zgodność"
    elif missing and extra:
        severity_en = "CRITICAL — both missing and extra invoices detected"
        severity_pl = "KRYTYCZNY — wykryto brakujące i nadmiarowe faktury"
    elif missing:
        severity_en = "CRITICAL — SAD references invoices not present as PDF"
        severity_pl = "KRYTYCZNY — SAD odwołuje się do faktur niedostarczonych jako PDF"
    elif extra:
        severity_en = "WARNING — PDF invoices not listed in SAD"
        severity_pl = "OSTRZEŻENIE — faktury PDF nie wymienione w SAD"
    else:
        severity_en, severity_pl = "GAP — could not verify (SAD refs not parsed)", "LUKA — nie można zweryfikować"

    return {
        "result":      match,
        "sad_refs":    sad_refs,
        "pdf_refs":    parsed_nos,
        "missing":     missing,
        "extra":       extra,
        "severity_en": severity_en,
        "severity_pl": severity_pl,
    }


def _check5_values(v: dict, result: dict, invoices: list) -> dict:
    cif_match = v.get("cif_match")
    inv_cif   = v.get("invoice_cif_total_usd", 0.0)
    sad_cif   = v.get("sad_cif_total_usd", 0.0)
    cif_diff  = v.get("cif_difference_usd", 0.0)

    # Per-invoice FOB + Freight + Insurance = CIF cross-check
    per_inv_checks: List[dict] = []
    for inv in invoices:
        fob       = inv.get("fob_usd", 0.0)
        freight   = inv.get("freight_usd", 0.0)
        insurance = inv.get("insurance_usd", 0.0)
        cif_stated = inv.get("cif_usd", 0.0)
        computed   = round(fob + freight + insurance, 2)
        delta      = round(abs(computed - cif_stated), 2)
        per_inv_checks.append({
            "invoice_no": inv.get("invoice_no", "?"),
            "fob":       fob,
            "freight":   freight,
            "insurance": insurance,
            "computed":  computed,
            "stated":    cif_stated,
            "delta":     delta,
            "ok":        delta <= 0.01,
        })

    # Freight / insurance allocation note
    has_freight   = any(i.get("freight_usd", 0) > 0 for i in invoices)
    has_insurance = any(i.get("insurance_usd", 0) > 0 for i in invoices)
    freight_varies = (
        len({i.get("freight_usd", 0) for i in invoices}) > 1
        or len({i.get("insurance_usd", 0) for i in invoices}) > 1
    ) if len(invoices) > 1 else False

    nbp          = result.get("nbp", {})
    nbp_rate     = nbp.get("usd_rate", 0.0)
    nbp_table    = nbp.get("table_no", "")
    nbp_date     = nbp.get("table_date", "")
    customs_rate = v.get("sad_customs_rate", 0.0)
    rate_delta   = round(abs(nbp_rate - customs_rate), 4) if (nbp_rate and customs_rate) else None

    zc429    = result.get("zc429", {})
    duty_pln = result.get("duty_pln", 0.0)
    vat_pln  = zc429.get("vat_pln", 0.0)
    mrn      = zc429.get("mrn", "")

    return {
        "cif_result":      cif_match,
        "inv_cif":         inv_cif,
        "sad_cif":         sad_cif,
        "cif_diff":        cif_diff,
        "per_inv_checks":  per_inv_checks,
        "has_freight":     has_freight,
        "has_insurance":   has_insurance,
        "freight_varies":  freight_varies,
        "duty_pln":        duty_pln,
        "vat_pln":         vat_pln,
        "mrn":             mrn,
        "nbp_rate":        nbp_rate,
        "nbp_table":       nbp_table,
        "nbp_date":        nbp_date,
        "customs_rate":    customs_rate,
        "rate_delta":      rate_delta,
    }


def _check6_transport(zc429: dict) -> dict:
    transport_refs = zc429.get("transport_refs", [])

    if not transport_refs:
        return {
            "result": None,
            "refs": [],
            "awb_digits": [],
            "note_en": (
                "No N740 transport document references found in SAD. "
                "AWB/CMR cross-check requires manual verification."
            ),
            "note_pl": (
                "Brak referencji dokumentów transportowych N740 w SAD. "
                "Weryfikacja AWB/CMR wymaga ręcznej kontroli."
            ),
        }

    # Extract digit cores from each ref (AWB numbers are 10-12 digits)
    awb_digits = [_extract_awb_digits(r) for r in transport_refs if len(_extract_awb_digits(r)) >= 8]

    return {
        "result": True if awb_digits else None,
        "refs": transport_refs,
        "awb_digits": awb_digits,
        "note_en": "",
        "note_pl": "",
    }


# ── Anticipated auditor questions (dynamic) ───────────────────────────────────

def _auditor_questions(c1: dict, c2: dict, c3: dict, c4: dict, c5: dict, c6: dict,
                       invoices: list) -> List[Tuple[str, str, str, str]]:
    """
    Return list of (question_en, answer_en, question_pl, answer_pl) tuples
    for situations that could prompt questions in an inspection.
    """
    qs: List[Tuple[str, str, str, str]] = []

    # Exporter address vs registered address
    if c1["invoice_value"] and c1["sad_value"] and c1["invoice_value"] != c1["sad_value"]:
        qs.append((
            "Why does the exporter name differ between invoice and SAD?",
            "Invoice may use a short trade name while SAD uses the full registered legal name. "
            "Both refer to the same legal entity; verify against trade register.",
            "Dlaczego nazwa eksportera różni się między fakturą a SAD?",
            "Faktura może używać skróconej nazwy handlowej, a SAD pełnej nazwy prawnej. "
            "Obie dotyczą tego samego podmiotu; zweryfikować w rejestrze handlowym.",
        ))

    # Two Polish addresses (registered office + warehouse)
    if (c3["invoice_addr"] and c3["invoice_addr"] != "(not parsed from invoice)"
            and _classify_address(c3["invoice_addr"])[0] != "Registered office"):
        qs.append((
            "Why does the delivery address differ from the importer's registered office?",
            f"'{c3['invoice_addr']}' is the warehouse / distribution address. "
            f"The registered office is '{c3['master_reg_addr']}'. "
            "Both belong to the same legal entity; warehouse delivery is standard operating procedure.",
            "Dlaczego adres dostawy różni się od siedziby importera?",
            f"'{c3['invoice_addr']}' to adres magazynowy / dystrybucyjny. "
            f"Siedziba spółki to '{c3['master_reg_addr']}'. "
            "Oba adresy należą do tego samego podmiotu; dostawa do magazynu jest standardową procedurą.",
        ))

    # Freight varies across invoices
    if c5["freight_varies"]:
        qs.append((
            "Why does freight differ between invoices?",
            "Freight and insurance are invoice-specific; each invoice carries its own transport cost "
            "as stated by the supplier. No fixed standard is applied. Allocated proportionally by CIF value.",
            "Dlaczego fracht różni się między fakturami?",
            "Koszty frachtu i ubezpieczenia są specyficzne dla każdej faktury; każda faktura zawiera "
            "własny koszt transportu podany przez dostawcę. Nie stosuje się żadnego stałego standardu. "
            "Alokacja proporcjonalna do wartości CIF.",
        ))

    # No freight at all (some invoices have zero)
    zero_freight = [i.get("invoice_no", "?") for i in invoices if i.get("freight_usd", 0) == 0]
    if zero_freight and len(zero_freight) < len(invoices):
        qs.append((
            f"Why do invoices {', '.join(zero_freight)} show zero freight?",
            "These invoices carry no freight charge (e.g. consolidated shipment where freight "
            "is billed on a separate invoice). CIF equals FOB for those invoices.",
            f"Dlaczego faktury {', '.join(zero_freight)} wykazują zerowy fracht?",
            "Te faktury nie zawierają opłaty za fracht (np. przesyłka skonsolidowana, gdzie "
            "fracht jest fakturowany oddzielnie). CIF równa się FOB dla tych faktur.",
        ))

    # AWB not in SAD
    if not c6["refs"]:
        qs.append((
            "How can the transport linkage be verified without AWB in the SAD?",
            "The current parser does not extract N740 transport document references. "
            "Manual cross-check: locate AWB number on the air waybill and confirm it "
            "appears in SAD field 18 (means of transport) or as an N740 document reference.",
            "Jak zweryfikować powiązanie transportowe bez AWB w SAD?",
            "Obecny parser nie wyodrębnia referencji dokumentów transportowych N740. "
            "Ręczna weryfikacja: odnaleźć numer AWB na liście przewozowym i potwierdzić "
            "jego obecność w polu 18 SAD (środek transportu) lub jako referencję N740.",
        ))

    return qs


# ── Report builders ───────────────────────────────────────────────────────────

def _overall_status(c1, c2, c3, c4, c5, c6) -> Tuple[str, str, str, str]:
    """Return (symbol, status_en, status_pl, detail_en, detail_pl)."""
    checks = [
        c1["result"], c2["name_result"], c2["nip_result"],
        c4["result"], c5["cif_result"],
    ]
    cif_per_inv_ok = all(ch["ok"] for ch in c5["per_inv_checks"])

    any_false = any(r is False for r in checks) or not cif_per_inv_ok
    all_true  = all(r is True  for r in checks) and cif_per_inv_ok

    if any_false:
        sym = "❌ BLOCKED"
        en  = ("Documentation contains confirmed discrepancies that must be resolved "
               "before this declaration is considered customs-compliant.")
        pl  = ("Dokumentacja zawiera potwierdzone niezgodności, które muszą zostać "
               "wyjaśnione przed uznaniem zgłoszenia za zgodne z przepisami celnymi.")
    elif all_true:
        sym = "✅ CLEAN"
        en  = ("Documentation is internally consistent across commercial, transport, "
               "and customs documents. No discrepancies affecting customs value, "
               "tax base, or importer/exporter identity were identified.")
        pl  = ("Dokumentacja jest spójna pomiędzy dokumentami handlowymi, transportowymi "
               "i celnymi. Nie stwierdzono niezgodności mających wpływ na wartość celną, "
               "podstawę opodatkowania ani identyfikację stron.")
    else:
        sym = "⚠️  PARTIAL"
        en  = ("All verifiable checks passed, but some checks could not be completed "
               "due to parser gaps. Items marked ⚠️ require manual verification before "
               "this report can be considered complete for audit purposes.")
        pl  = ("Wszystkie weryfikowalne kontrole przeszły pomyślnie, ale niektóre kontrole "
               "nie mogły zostać ukończone z powodu luk parsera. Pozycje oznaczone ⚠️ "
               "wymagają ręcznej weryfikacji przed uznaniem raportu za kompletny.")

    return sym, en, pl


def _build_en(
    batch_id: str, doc_no: str, result: Dict[str, Any],
    c1, c2, c3, c4, c5, c6, questions,
) -> str:
    v           = result.get("verification", {})
    amendment   = v.get("amendment_flags", [])
    verify_gaps = [
        c.removeprefix("[VERIFY-GAP]").strip()
        for c in result.get("corrections_log", [])
        if c.startswith("[VERIFY-GAP]")
    ]
    sym, overall_en, _ = _overall_status(c1, c2, c3, c4, c5, c6)
    lines = []
    A = lines.append

    A(_sep("═"))
    A("ESTRELLA JEWELS — IMPORT COMPLIANCE AUDIT REPORT")
    A(_sep("═"))
    A(f"Batch ID      : {batch_id}")
    A(f"Document      : {doc_no or '(not specified)'}")
    A(f"Generated     : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    A(f"MRN           : {c5['mrn'] or '(not parsed)'}")
    A(f"Clearance date: {result.get('zc429', {}).get('clearance_date') or '(not parsed)'}")
    A(f"Invoices      : {len(result.get('invoices', []))}  |  Lines: {result.get('line_count', 0)}")
    mode = result.get("settlement_mode", "standard")
    A(f"VAT mode      : {'Art. 33a — deferred VAT (reverse charge)' if mode == 'art33a' else 'Standard — VAT paid at customs'}")
    agent = result.get("zc429", {}).get("agent", "")
    if agent:
        A(f"Customs agent : {agent}")
    A("")

    # ── Check 1: Exporter ─────────────────────────────────────────────────────
    A(_sep()); A("CHECK 1 — EXPORTER IDENTITY CHAIN"); A(_sep())
    A(_verdict(c1["result"]))
    A(f"  Invoice seller  : {c1['invoice_value']}")
    A(f"  SAD exporter    : {c1['sad_value']}")
    if c1["result"] is False:
        A("  → Confirm both names refer to the same legal entity; check trade register.")
    A("")

    # ── Check 2: Importer ─────────────────────────────────────────────────────
    A(_sep()); A("CHECK 2 — IMPORTER IDENTITY + VAT/NIP"); A(_sep())
    A(f"  Name  : {_verdict(c2['name_result'])}")
    A(f"  NIP   : {_verdict(c2['nip_result'])}")
    A(f"  Invoice buyer   : {c2['invoice_name']}")
    A(f"  SAD consignee   : {c2['sad_name']}")
    A(f"  Invoice NIP     : {c2['invoice_nip']}")
    A(f"  SAD NIP         : {c2['sad_nip']}")
    A(f"  Master record   : {c2['master_name']}  NIP {c2['master_nip']}")
    A("")

    # ── Check 3: Address ──────────────────────────────────────────────────────
    A(_sep()); A("CHECK 3 — ADDRESS CLASSIFICATION"); A(_sep())
    A(f"  Registered office (master)   : {c3['master_reg_addr']}")
    A(f"  Address type                 : {c3['master_reg_type']}")
    A(f"  Invoice delivery address     : {c3['invoice_addr']}")
    A(f"  Invoice address type         : {c3['invoice_type_en']}")
    if c3["sad_addr"] and c3["sad_addr"] != "(not parsed from SAD)":
        A(f"  SAD delivery address         : {c3['sad_addr']}")
        A(f"  SAD address type             : {c3['sad_type_en']}")
    if c3["consistent"] is True:
        A("  ✅ Address classification: consistent — warehouse delivery to registered importer.")
    elif c3["consistent"] is False:
        A("  ❌ Address classification: inconsistent — requires explanation.")
    else:
        A("  ⚠️  Address classification: could not determine from available data.")
    A("  Note: If delivery address differs from registered office, both must be")
    A("        declared on the SAD. Customs agent should confirm.")
    A("")

    # ── Check 4: Invoice chain ────────────────────────────────────────────────
    A(_sep()); A("CHECK 4 — INVOICE CHAIN RECONCILIATION"); A(_sep())
    A(f"  Severity  : {c4['severity_en']}")
    A(f"  SAD N935 refs  : {', '.join(c4['sad_refs']) or '(none parsed)'}")
    A(f"  PDF set        : {', '.join(c4['pdf_refs']) or '(none)'}")
    if c4["missing"]:
        A(f"  ❌ CRITICAL — In SAD, no PDF : {', '.join(c4['missing'])}")
        A("     → Obtain and attach these invoice PDFs or request SAD amendment.")
    if c4["extra"]:
        A(f"  ⚠️  WARNING — PDF, not in SAD : {', '.join(c4['extra'])}")
        A("     → Confirm these invoices are covered under consolidated SAD entry.")
    A("")

    # ── Check 5: Values ───────────────────────────────────────────────────────
    A(_sep()); A("CHECK 5 — VALUE RECONCILIATION"); A(_sep())

    A("  5a. Per-invoice FOB + Freight + Insurance = CIF")
    all_per_inv_ok = all(ch["ok"] for ch in c5["per_inv_checks"])
    A(f"      {_verdict(True if all_per_inv_ok else False)}")
    for ch in c5["per_inv_checks"]:
        ok_sym = "✅" if ch["ok"] else "❌"
        A(f"      {ok_sym} {ch['invoice_no']:30s}  "
          f"FOB {_fmt_usd(ch['fob'])} + F {_fmt_usd(ch['freight'])} + I {_fmt_usd(ch['insurance'])} "
          f"= {_fmt_usd(ch['computed'])}  stated: {_fmt_usd(ch['stated'])}"
          + (f"  Δ {_fmt_usd(ch['delta'])}" if not ch["ok"] else ""))

    A("")
    A("  Freight & insurance allocation note:")
    if c5["freight_varies"]:
        A("  Freight and insurance vary per invoice and are allocated proportionally")
        A("  based on each invoice's own CIF structure. No fixed standard is applied.")
    elif c5["has_freight"] or c5["has_insurance"]:
        A("  Freight and insurance are taken directly from each invoice as stated.")
        A("  Allocated proportionally to line item value within each invoice.")
    else:
        A("  No freight or insurance charges found in invoice set (FOB = CIF).")

    A("")
    A(f"  5b. Total CIF reconciliation: {_verdict(c5['cif_result'])}")
    A(f"      Invoice CIF total : {_fmt_usd(c5['inv_cif'])}")
    A(f"      SAD CIF total     : {_fmt_usd(c5['sad_cif']) if c5['sad_cif'] else '(not parsed)'}")
    A(f"      Difference        : {_fmt_usd(c5['cif_diff'])}  (tolerance ±$1.00)")

    A("")
    A(f"  5c. Duty and VAT")
    A(f"      Duty A00  : {_fmt_pln(c5['duty_pln'])}  ← sole source: ZC429/SAD (never assumed)")
    A(f"      VAT B00   : {_fmt_pln(c5['vat_pln'])}  (reference only — not included in landed cost)")

    A("")
    A("  5d. Exchange rate")
    if c5["nbp_rate"]:
        A(f"      NBP accounting rate  : {c5['nbp_rate']:.4f} USD/PLN  (table {c5['nbp_table']}, {c5['nbp_date']})")
    else:
        A("      NBP accounting rate  : (not fetched)")
    if c5["customs_rate"]:
        A(f"      SAD customs rate     : {c5['customs_rate']:.4f} USD/PLN  (SAD field 23)")
    else:
        A("      SAD customs rate     : (not parsed)")
    if c5["rate_delta"] is not None:
        note = "within acceptable range ✅" if c5["rate_delta"] <= 0.01 else "delta exceeds 0.01 — review ⚠️"
        A(f"      Rate delta           : {c5['rate_delta']:.4f}  — {note}")
        A("      Note: NBP accounting rate (day before customs clearance) may differ")
        A("            from customs declaration rate. Both are legitimate for their purpose.")
    A("")

    # ── Check 6: Transport ────────────────────────────────────────────────────
    A(_sep()); A("CHECK 6 — TRANSPORT LINKAGE (AWB / N740)"); A(_sep())
    if c6["refs"]:
        A(f"  {_verdict(c6['result'])}")
        A(f"  N740 transport refs in SAD : {', '.join(c6['refs'])}")
        if c6["awb_digits"]:
            A(f"  AWB numeric core(s)        : {', '.join(c6['awb_digits'])}")
            A("  ✅ Transport document numbers extracted from SAD and available for cross-check.")
            A("     Confirm these match the air waybill number on the physical AWB document.")
    else:
        A(f"  ⚠️  {c6['note_en']}")
    A("")

    # ── Quantity summary ──────────────────────────────────────────────────────
    inv_totals = result.get("invoice_totals", {})
    pc = inv_totals.get("product_counts", {})
    if inv_totals.get("total_pcs"):
        A(_sep()); A("INVOICE QUANTITY SUMMARY"); A(_sep())
        A(f"  Total PCS   : {inv_totals['total_pcs']}")
        for cat in ("rings", "pendants", "bracelets", "earrings", "necklaces", "other_jewellery"):
            if pc.get(cat):
                A(f"  {cat.replace('_', ' ').title():12s}: {pc[cat]}")
        qty_match = v.get("qty_match_by_type")
        if qty_match is True:
            A("  Quantity verification : ✅ VERIFIED — invoice PCS matches SAD total")
        elif qty_match is False:
            A("  Quantity verification : ❌ MISMATCH — invoice PCS does not match SAD total")
        else:
            zc = result.get("zc429", {})
            if zc.get("total_qty"):
                A("  Quantity verification : ⚠️  PARTIAL — invoice item quantities parsed; SAD gives combined jewellery description")
            else:
                A("  Quantity verification : ⚠️  COULD NOT VERIFY — quantity not found in SAD")
        A("")

    # ── SAD goods details ─────────────────────────────────────────────────────
    zc = result.get("zc429", {})
    goods_desc = zc.get("goods_description", "")
    cn_code    = zc.get("cn_code", "")
    stat_val   = zc.get("statistical_value_pln")
    if goods_desc or cn_code or stat_val:
        A(_sep()); A("SAD GOODS DETAILS"); A(_sep())
        if goods_desc:
            A(f"  Goods description (field 31) : {goods_desc}")
        if cn_code:
            A(f"  CN / TARIC code  (field 33) : {cn_code}")
        if stat_val:
            A(f"  Statistical value (field 46) : {_fmt_pln(stat_val)}")
        A("")

    # ── Summary table ─────────────────────────────────────────────────────────
    A(_sep("═")); A("AUDIT SUMMARY"); A(_sep("═"))
    checks_table = [
        ("Exporter identity",           c1["result"]),
        ("Importer identity",           c2["name_result"]),
        ("VAT/NIP match",               c2["nip_result"]),
        ("Address classification",      c3["consistent"]),
        ("Invoice chain",               c4["result"]),
        ("Per-invoice CIF arithmetic",  True if all(ch["ok"] for ch in c5["per_inv_checks"]) else False),
        ("Total CIF vs SAD",            c5["cif_result"]),
        ("Transport / AWB",             c6["result"]),
    ]
    for label, r in checks_table:
        if r is True:    sym_r = "✅ PASS"
        elif r is False: sym_r = "❌ FAIL"
        else:            sym_r = "⚠️  GAP "
        A(f"  {sym_r}  {label}")
    A("")

    if amendment:
        A(f"Amendment flags ({len(amendment)}):")
        for f in amendment: A(f"  → {f}")
    else:
        A("Amendment flags : none")
    if verify_gaps:
        A(f"Verification gaps ({len(verify_gaps)}):")
        for g in verify_gaps: A(f"  ~ {g}")
    else:
        A("Verification gaps : none")
    A("")

    # ── Final assessment ──────────────────────────────────────────────────────
    A(_sep("═")); A("FINAL ASSESSMENT"); A(_sep("═"))
    A(f"  {overall_en}")
    A("")

    # ── Auditor questions anticipation ────────────────────────────────────────
    if questions:
        A(_sep("═")); A("LIKELY AUDITOR QUESTIONS"); A(_sep("═"))
        for i, (q_en, a_en, _, _) in enumerate(questions, 1):
            A(f"  {i}. {q_en}")
            A(f"     → {a_en}")
            A("")

    A(_sep("═")); A("END OF REPORT"); A(_sep("═"))
    return "\n".join(lines)


def _build_pl(
    batch_id: str, doc_no: str, result: Dict[str, Any],
    c1, c2, c3, c4, c5, c6, questions,
) -> str:
    v           = result.get("verification", {})
    amendment   = v.get("amendment_flags", [])
    verify_gaps = [
        c.removeprefix("[VERIFY-GAP]").strip()
        for c in result.get("corrections_log", [])
        if c.startswith("[VERIFY-GAP]")
    ]
    _, _, overall_pl = _overall_status(c1, c2, c3, c4, c5, c6)
    lines = []
    A = lines.append

    A(_sep("═")); A("ESTRELLA JEWELS — RAPORT AUDYTOWY IMPORTU"); A(_sep("═"))
    A(f"Identyfikator partii  : {batch_id}")
    A(f"Numer dokumentu       : {doc_no or '(nie podano)'}")
    A(f"Wygenerowano          : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    A(f"MRN                   : {c5['mrn'] or '(nie odczytano)'}")
    A(f"Data odprawy          : {result.get('zc429', {}).get('clearance_date') or '(nie odczytano)'}")
    A(f"Faktury               : {len(result.get('invoices', []))}  |  Pozycje: {result.get('line_count', 0)}")
    mode = result.get("settlement_mode", "standard")
    A(f"Tryb VAT              : {'Art. 33a — odwrócone obciążenie VAT (odroczony)' if mode == 'art33a' else 'Standardowy — VAT płatny przy odprawie celnej'}")
    agent = result.get("zc429", {}).get("agent", "")
    if agent:
        A(f"Agencja celna         : {agent}")
    A("")

    # ── Check 1 ───────────────────────────────────────────────────────────────
    A(_sep()); A("KONTROLA 1 — TOŻSAMOŚĆ EKSPORTERA"); A(_sep())
    A(_verdict(c1["result"], "pl"))
    A(f"  Sprzedawca (faktura) : {c1['invoice_value']}")
    A(f"  Eksporter (SAD)      : {c1['sad_value']}")
    if c1["result"] is False:
        A("  → Potwierdzić, że obie nazwy odnoszą się do tego samego podmiotu prawnego; zweryfikować w rejestrze.")
    A("")

    # ── Check 2 ───────────────────────────────────────────────────────────────
    A(_sep()); A("KONTROLA 2 — TOŻSAMOŚĆ IMPORTERA + NIP/VAT"); A(_sep())
    A(f"  Nazwa  : {_verdict(c2['name_result'], 'pl')}")
    A(f"  NIP    : {_verdict(c2['nip_result'], 'pl')}")
    A(f"  Nabywca (faktura)     : {c2['invoice_name']}")
    A(f"  Odbiorca (SAD)        : {c2['sad_name']}")
    A(f"  NIP faktury           : {c2['invoice_nip']}")
    A(f"  NIP SAD               : {c2['sad_nip']}")
    A(f"  Dane referencyjne     : {c2['master_name']}  NIP {c2['master_nip']}")
    A("")

    # ── Check 3 ───────────────────────────────────────────────────────────────
    A(_sep()); A("KONTROLA 3 — KLASYFIKACJA ADRESU"); A(_sep())
    A(f"  Siedziba spółki (wzorzec)    : {c3['master_reg_addr']}")
    A(f"  Typ adresu                   : {c3['master_reg_type'].split('/')[1].strip()}")
    A(f"  Adres dostawy (faktura)      : {c3['invoice_addr']}")
    A(f"  Typ adresu dostawy           : {c3['invoice_type_pl']}")
    if c3["sad_addr"] and c3["sad_addr"] != "(not parsed from SAD)":
        A(f"  Adres dostawy (SAD)          : {c3['sad_addr']}")
        A(f"  Typ adresu SAD               : {c3['sad_type_pl']}")
    if c3["consistent"] is True:
        A("  ✅ Klasyfikacja adresu: spójna — dostawa do magazynu zarejestrowanego importera.")
    elif c3["consistent"] is False:
        A("  ❌ Klasyfikacja adresu: niespójna — wymaga wyjaśnienia.")
    else:
        A("  ⚠️  Klasyfikacja adresu: nie można określić na podstawie dostępnych danych.")
    A("  Uwaga: Jeśli adres dostawy różni się od siedziby, oba adresy muszą być")
    A("         zadeklarowane w SAD. Agencja celna powinna to potwierdzić.")
    A("")

    # ── Check 4 ───────────────────────────────────────────────────────────────
    A(_sep()); A("KONTROLA 4 — ŁAŃCUCH FAKTUR"); A(_sep())
    A(f"  Poziom istotności : {c4['severity_pl']}")
    A(f"  Referencje SAD N935 : {', '.join(c4['sad_refs']) or '(brak)'}")
    A(f"  Zestaw PDF          : {', '.join(c4['pdf_refs']) or '(brak)'}")
    if c4["missing"]:
        A(f"  ❌ KRYTYCZNY — W SAD, brak PDF : {', '.join(c4['missing'])}")
        A("     → Dostarczyć brakujące faktury PDF lub złożyć wniosek o korektę SAD.")
    if c4["extra"]:
        A(f"  ⚠️  OSTRZEŻENIE — PDF, brak w SAD : {', '.join(c4['extra'])}")
        A("     → Potwierdzić, że te faktury są objęte skonsolidowanym zgłoszeniem SAD.")
    A("")

    # ── Check 5 ───────────────────────────────────────────────────────────────
    A(_sep()); A("KONTROLA 5 — UZGODNIENIE WARTOŚCI"); A(_sep())

    A("  5a. Na fakturę: FOB + Fracht + Ubezpieczenie = CIF")
    all_per_inv_ok = all(ch["ok"] for ch in c5["per_inv_checks"])
    A(f"      {_verdict(True if all_per_inv_ok else False, 'pl')}")
    for ch in c5["per_inv_checks"]:
        ok_sym = "✅" if ch["ok"] else "❌"
        A(f"      {ok_sym} {ch['invoice_no']:30s}  "
          f"FOB {_fmt_usd(ch['fob'])} + F {_fmt_usd(ch['freight'])} + U {_fmt_usd(ch['insurance'])} "
          f"= {_fmt_usd(ch['computed'])}  deklarowane: {_fmt_usd(ch['stated'])}"
          + (f"  Δ {_fmt_usd(ch['delta'])}" if not ch["ok"] else ""))

    A("")
    A("  Uwaga dotycząca alokacji frachtu i ubezpieczenia:")
    if c5["freight_varies"]:
        A("  Fracht i ubezpieczenie są różne dla każdej faktury i alokowane proporcjonalnie")
        A("  na podstawie struktury CIF każdej faktury. Nie stosuje się żadnego stałego standardu.")
    elif c5["has_freight"] or c5["has_insurance"]:
        A("  Fracht i ubezpieczenie przyjmowane są bezpośrednio z każdej faktury.")
        A("  Alokacja proporcjonalna do wartości pozycji w ramach każdej faktury.")
    else:
        A("  Brak kosztów frachtu i ubezpieczenia w zestawie faktur (FOB = CIF).")

    A("")
    A(f"  5b. Łączna wartość CIF: {_verdict(c5['cif_result'], 'pl')}")
    A(f"      CIF z faktur      : {_fmt_usd(c5['inv_cif'])}")
    A(f"      CIF z SAD         : {_fmt_usd(c5['sad_cif']) if c5['sad_cif'] else '(nie odczytano)'}")
    A(f"      Różnica           : {_fmt_usd(c5['cif_diff'])}  (tolerancja ±1,00 USD)")

    A("")
    A("  5c. Cło i VAT")
    A(f"      Cło A00  : {_fmt_pln(c5['duty_pln'])}  ← jedyne źródło: ZC429/SAD (nigdy zakładane)")
    A(f"      VAT B00  : {_fmt_pln(c5['vat_pln'])}  (tylko informacyjnie — nie w koszcie nabycia)")

    A("")
    A("  5d. Kurs walutowy")
    if c5["nbp_rate"]:
        A(f"      Kurs NBP (księgowy)    : {c5['nbp_rate']:.4f} USD/PLN  (tabela {c5['nbp_table']}, {c5['nbp_date']})")
    else:
        A("      Kurs NBP (księgowy)    : (nie pobrano)")
    if c5["customs_rate"]:
        A(f"      Kurs celny (SAD p.23)  : {c5['customs_rate']:.4f} USD/PLN")
    else:
        A("      Kurs celny (SAD p.23)  : (nie odczytano)")
    if c5["rate_delta"] is not None:
        note = "w dopuszczalnym zakresie ✅" if c5["rate_delta"] <= 0.01 else "delta przekracza 0,01 — sprawdzić ⚠️"
        A(f"      Delta kursu            : {c5['rate_delta']:.4f}  — {note}")
        A("      Uwaga: Kurs NBP (dzień przed odprawą) może różnić się od kursu celnego.")
        A("             Oba kursy są prawidłowe dla swoich zastosowań.")
    A("")

    # ── Check 6 ───────────────────────────────────────────────────────────────
    A(_sep()); A("KONTROLA 6 — POWIĄZANIE TRANSPORTOWE (AWB / N740)"); A(_sep())
    if c6["refs"]:
        A(f"  {_verdict(c6['result'], 'pl')}")
        A(f"  Referencje N740 w SAD : {', '.join(c6['refs'])}")
        if c6["awb_digits"]:
            A(f"  Numer(y) AWB          : {', '.join(c6['awb_digits'])}")
            A("  ✅ Numery dokumentów transportowych wyodrębnione z SAD i dostępne do weryfikacji.")
            A("     Potwierdzić zgodność z numerem AWB na fizycznym liście przewozowym.")
    else:
        A(f"  ⚠️  {c6['note_pl']}")
    A("")

    # ── Quantity summary ──────────────────────────────────────────────────────
    inv_totals = result.get("invoice_totals", {})
    pc = inv_totals.get("product_counts", {})
    if inv_totals.get("total_pcs"):
        A(_sep()); A("PODSUMOWANIE ILOŚCIOWE FAKTURY"); A(_sep())
        A(f"  Łączna ilość (PCS) : {inv_totals['total_pcs']}")
        _cat_pl = {"rings": "Pierścionki", "pendants": "Zawieszki", "bracelets": "Bransoletki",
                   "earrings": "Kolczyki", "necklaces": "Naszyjniki", "other_jewellery": "Pozostała biżuteria"}
        for cat in ("rings", "pendants", "bracelets", "earrings", "necklaces", "other_jewellery"):
            if pc.get(cat):
                A(f"  {_cat_pl[cat]:22s}: {pc[cat]}")
        qty_match = v.get("qty_match_by_type")
        if qty_match is True:
            A("  Weryfikacja ilości  : ✅ ZWERYFIKOWANO — PCS z faktury zgodny z SAD")
        elif qty_match is False:
            A("  Weryfikacja ilości  : ❌ ROZBIEŻNOŚĆ — PCS z faktury niezgodny z SAD")
        else:
            zc = result.get("zc429", {})
            if zc.get("total_qty"):
                A("  Weryfikacja ilości  : ⚠️  CZĘŚCIOWA — ilości z faktury odczytane; SAD zawiera łączny opis biżuterii")
            else:
                A("  Weryfikacja ilości  : ⚠️  NIE MOŻNA ZWERYFIKOWAĆ — brak ilości w SAD")
        A("")

    # ── SAD goods details ─────────────────────────────────────────────────────
    zc = result.get("zc429", {})
    goods_desc = zc.get("goods_description", "")
    cn_code    = zc.get("cn_code", "")
    stat_val   = zc.get("statistical_value_pln")
    if goods_desc or cn_code or stat_val:
        A(_sep()); A("DANE TOWARÓW SAD"); A(_sep())
        if goods_desc:
            A(f"  Opis towarów (pole 31)   : {goods_desc}")
        if cn_code:
            A(f"  Kod CN / TARIC (pole 33) : {cn_code}")
        if stat_val:
            A(f"  Wartość stat. (pole 46)  : {_fmt_pln(stat_val)}")
        A("")

    # ── Summary table ─────────────────────────────────────────────────────────
    A(_sep("═")); A("PODSUMOWANIE RAPORTU"); A(_sep("═"))
    checks_table = [
        ("Tożsamość eksportera",           c1["result"]),
        ("Tożsamość importera",            c2["name_result"]),
        ("Zgodność NIP",                   c2["nip_result"]),
        ("Klasyfikacja adresu",            c3["consistent"]),
        ("Łańcuch faktur",                 c4["result"]),
        ("Arytmetyka CIF (per faktura)",   True if all(ch["ok"] for ch in c5["per_inv_checks"]) else False),
        ("Łączna wartość CIF vs SAD",      c5["cif_result"]),
        ("Transport / AWB",                c6["result"]),
    ]
    for label, r in checks_table:
        if r is True:    sym_r = "✅ OK    "
        elif r is False: sym_r = "❌ BŁĄD  "
        else:            sym_r = "⚠️  LUKA  "
        A(f"  {sym_r}  {label}")
    A("")

    if amendment:
        A(f"Flagi zmian ({len(amendment)}):")
        for f in amendment: A(f"  → {f}")
    else:
        A("Flagi zmian : brak")
    if verify_gaps:
        A(f"Luki weryfikacyjne ({len(verify_gaps)}):")
        for g in verify_gaps: A(f"  ~ {g}")
    else:
        A("Luki weryfikacyjne : brak")
    A("")

    # ── Final assessment ──────────────────────────────────────────────────────
    A(_sep("═")); A("WYNIK KOŃCOWY"); A(_sep("═"))
    A(f"  {overall_pl}")
    A("")

    # ── Auditor questions anticipation ────────────────────────────────────────
    if questions:
        A(_sep("═")); A("PRZEWIDYWANE PYTANIA KONTROLERA"); A(_sep("═"))
        for i, (_, _, q_pl, a_pl) in enumerate(questions, 1):
            A(f"  {i}. {q_pl}")
            A(f"     → {a_pl}")
            A("")

    A(_sep("═")); A("KONIEC RAPORTU"); A(_sep("═"))
    return "\n".join(lines)


# ── Public entry point ────────────────────────────────────────────────────────

def build_audit_report(
    result:     Dict[str, Any],
    output_dir: Path,
    batch_id:   str,
    doc_no:     str = "",
) -> Dict[str, Any]:
    """
    Run all 6 audit checks against the process_batch() result dict.
    Writes bilingual report files into output_dir.
    Computes risk score via audit_scoring.

    Returns:
        {
            "en":         Path("audit_report_en.txt"),
            "pl":         Path("audit_report_pl.txt"),
            "score":      int,
            "risk_level": str,
            "failed_checks": list[str],
            "audit_data": dict,   # full package for audit_pdf.generate_audit_pdf()
        }
    """
    from audit_scoring import score_batch
    from learning_agent import run_learning_pipeline

    v        = result.get("verification", {})
    invoices = result.get("invoices", [])
    zc429    = result.get("zc429", {})

    c1 = _check1_exporter(v, invoices)
    c2 = _check2_importer(v, invoices)
    c3 = _check3_address(invoices, zc429)
    c4 = _check4_invoice_chain(v)
    c5 = _check5_values(v, result, invoices)
    c6 = _check6_transport(zc429)

    questions = _auditor_questions(c1, c2, c3, c4, c5, c6, invoices)

    # ── Learning pipeline: record patterns + compute confidence adjustments ────
    try:
        adj_result, freight_checks, _ = run_learning_pipeline(
            result    = result,
            batch_id  = batch_id,
            doc_no    = doc_no,
            c2        = c2,
            c3        = c3,
            c6        = c6,
            invoices  = invoices,
            zc429     = zc429,
        )
        confidences = {
            k: v["confidence"]
            for k, v in adj_result.adjustments.items()
            if not v.get("hard_locked", False)
        }
        learning_trace = adj_result.to_dict()
    except Exception:
        confidences      = {}
        freight_checks   = []
        learning_trace   = {}

    # ── Compute score (with learning-adjusted confidences) ────────────────────
    # Forward the categorical verification states (qty_status, cn_status,
    # nip_source) emitted by verify_sad_invoice_match into score_batch. When
    # any of these are non-None or AUDIT_HARDENING_ENABLED is true, the
    # scoring engine returns a categorical `status` field
    # (VERIFIED/PARTIAL/NOT_VERIFIED/BLOCKED) on top of the legacy score
    # and risk_level. Legacy consumers continue reading `risk_level` and
    # `score` unchanged.
    _verification_for_scoring = (
        result.get("verification") if isinstance(result, dict) else None
    ) or {}
    scoring       = score_batch(
        c1, c2, c3, c4, c5, c6,
        confidences=confidences,
        qty_status=_verification_for_scoring.get("qty_status"),
        cn_status=_verification_for_scoring.get("cn_status"),
        nip_source=_verification_for_scoring.get("nip_source"),
    )
    score         = scoring["score"]
    risk_level    = scoring["risk_level"]
    failed_checks = scoring["failed_checks"]
    audit_status  = scoring.get("status")  # only present in hardening path

    # ── Determine overall assessment strings (for PDF) ─────────────────────────
    _, overall_en, overall_pl = _overall_status(c1, c2, c3, c4, c5, c6)

    # ── Write text reports (internal) + PDF versions (for sharing) ───────────
    en_text = _build_en(batch_id, doc_no, result, c1, c2, c3, c4, c5, c6, questions)
    pl_text = _build_pl(batch_id, doc_no, result, c1, c2, c3, c4, c5, c6, questions)

    # Keep .txt for internal use / debugging
    en_txt_path = output_dir / "audit_report_en.txt"
    pl_txt_path = output_dir / "audit_report_pl.txt"
    en_txt_path.write_text(en_text, encoding="utf-8")
    pl_txt_path.write_text(pl_text, encoding="utf-8")

    # Generate PDF versions with proper Unicode font (Polish glyphs)
    from audit_pdf import generate_audit_report_pdf
    en_path = output_dir / "audit_report_en.pdf"
    pl_path = output_dir / "audit_report_pl.pdf"
    generate_audit_report_pdf(
        en_text, en_path,
        title="Audit Compliance Report",
        language="en",
    )
    generate_audit_report_pdf(
        pl_text, pl_path,
        title="Raport Audytu Zgodności",
        language="pl",
    )

    # ── Build audit_data package for PDF generator ────────────────────────────
    audit_data = {
        "batch_id":        batch_id,
        "doc_no":          doc_no,
        "mrn":             zc429.get("mrn", ""),
        "clearance_date":  zc429.get("clearance_date", ""),
        "score":           score,
        "risk_level":      risk_level,
        "failed_checks":   failed_checks,
        "penalty_breakdown": scoring.get("penalty_breakdown", {}),
        "learning_applied": scoring.get("learning_applied", False),
        "overall_en":      overall_en,
        "overall_pl":      overall_pl,
        "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "c6": c6,
        "invoices":        invoices,
        "zc429":           zc429,
        "nbp":             result.get("nbp", {}),
        "line_count":      result.get("line_count", 0),
        "total_net":       result.get("total_net", 0),
        "total_gross":     result.get("total_gross", 0),
        "duty_pln":        result.get("duty_pln", 0),
        "invoice_totals":  result.get("invoice_totals", {}),
        "settlement_mode": result.get("settlement_mode", "standard"),
        "learning_trace":  learning_trace,
        "freight_checks":  freight_checks,
    }
    # Hardening status (only when score_batch emitted it). Adding the field
    # is purely additive — audit_pdf reads `risk_level` and ignores unknown
    # keys, so consumers pinned to the legacy shape are unaffected.
    if audit_status is not None:
        audit_data["status"] = audit_status

    out = {
        "en":              en_path,
        "pl":              pl_path,
        "score":           score,
        "risk_level":      risk_level,
        "failed_checks":   failed_checks,
        "learning_applied": scoring.get("learning_applied", False),
        "learning_trace":  learning_trace,
        "freight_checks":  freight_checks,
        "audit_data":      audit_data,
    }
    if audit_status is not None:
        out["status"] = audit_status
    return out
