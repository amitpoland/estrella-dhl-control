#!/usr/bin/env python3
"""
correction_engine.py — Auto-correction suggestion engine + amendment draft generator  v2
========================================================================================
Turns the audit system from a "problem detector" into a "decision assistant."

For each confirmed audit failure it produces:
  • A concrete, actionable fix suggestion in plain English + Polish
  • A bilingual (EN+PL) amendment draft text ready to paste into SAD
  • A severity classification: CRITICAL / WARNING / ADVISORY
  • A structured diff showing Field / Current / Corrected
  • A recommended next action (AMEND_SAD / VERIFY_DOCS / ESCALATE_CUSTOMS / RESOLVE_INTERNALLY)
  • A monetary/risk impact estimate
  • A confidence score (0.0–1.0)

Architecture:
  audit_agent  →  correction_engine  →  amendment drafts (EN + PL text)
                                      →  structured correction report (JSON/dict)
                                      →  PDF section (rendered by audit_pdf)

Public API:
    build_corrections(audit_data, result, batch_id, doc_no, ...)
        → CorrectionReport

    draft_amendment_text(corrections, doc_no, settlement_mode)
        → (en_text: str, pl_text: str)

    write_correction_report(corrections, output_dir, batch_id, ...)
        → {"en": Path, "pl": Path, "json": Path}

v2 changes:
    • Hard-lock enforcement — HARD_LOCK_CHECKS corrections always CRITICAL + auto_override=False
    • MAX_CORRECTIONS=5 + consecutive-number grouping for invoice lists
    • primary_action on CorrectionReport — one clear recommended next step
    • source_check field — explicit audit check traceability
    • structured_diff — Field/Current/Corrected table in every correction
    • confidence field — 0.0–1.0 derived from audit certainty + learning confidence
    • Freeze mode — when learning_frozen=True, learned-pattern corrections flagged + confidence=0
    • impact field — monetary and risk impact estimate per correction
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional


# ── Constants ─────────────────────────────────────────────────────────────────

# Mirror of learning_agent.HARD_LOCK_CHECKS — these checks can never be
# softened by learning, and their corrections always remain CRITICAL with
# auto_override=False regardless of confidence or freeze mode.
HARD_LOCK_CHECKS: frozenset = frozenset({
    "identity_mismatch",
    "value_mismatch",
    "cif_formula_error",
    "invoice_missing",
})

# Soft checks — affected by learning freeze mode
SOFT_CHECKS: frozenset = frozenset({
    "freight_anomaly",
    "address_inconsistency",
    "transport_mismatch",
})

MAX_CORRECTIONS = 5   # surface at most 5 — more causes alert fatigue


# ── Severity and action enums ─────────────────────────────────────────────────

Severity   = Literal["CRITICAL", "WARNING", "ADVISORY"]
NextAction = Literal[
    "AMEND_SAD",
    "VERIFY_DOCS",
    "ESCALATE_CUSTOMS",
    "RESOLVE_INTERNALLY",
]


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class CorrectionItem:
    """One suggested correction for one failed check."""
    check_key:       str
    source_check:    str            # explicit audit check key for traceability
    severity:        Severity
    next_action:     NextAction
    auto_override:   bool           # True=can be overridden; False=hard lock, immutable
    confidence:      float          # 0.0–1.0: certainty this correction is correct
    title_en:        str
    title_pl:        str
    problem_en:      str            # What went wrong, in plain English
    problem_pl:      str            # Same in Polish
    fix_en:          str            # Concrete fix instruction, EN
    fix_pl:          str            # Same in Polish
    amendment_en:    str            # Draft amendment clause text, EN
    amendment_pl:    str            # Draft amendment clause text, PL
    structured_diff: List[Dict]     = field(default_factory=list)
    # e.g. [{"field": "Importer NIP", "current": "123", "corrected": "456"}]
    impact:          Dict[str, Any] = field(default_factory=dict)
    # e.g. {"duty_pln": "+120", "risk": "HIGH → LOW", "notes": "..."}
    diff:            Dict[str, Any] = field(default_factory=dict)
    # raw diff for backward compat
    evidence:        List[str]      = field(default_factory=list)
    # Supporting facts extracted from audit data


@dataclass
class CorrectionReport:
    batch_id:             str
    doc_no:               str
    generated:            str
    corrections:          List[CorrectionItem]
    has_critical:         bool = False
    has_warning:          bool = False
    primary_action:       str  = ""    # e.g. "AMEND_SAD"
    primary_action_text:  str  = ""    # human-readable, EN
    primary_action_pl:    str  = ""    # human-readable, PL
    learning_frozen:      bool = False # True when LEARNING_FROZEN=1 was active
    total_count:          int  = 0     # total corrections before MAX_CORRECTIONS cap
    shown_count:          int  = 0     # corrections surfaced (capped at MAX_CORRECTIONS)

    def by_severity(self, severity: Severity) -> List[CorrectionItem]:
        return [c for c in self.corrections if c.severity == severity]

    def to_dict(self) -> dict:
        return {
            "batch_id":            self.batch_id,
            "doc_no":              self.doc_no,
            "generated":           self.generated,
            "has_critical":        self.has_critical,
            "has_warning":         self.has_warning,
            "primary_action":      self.primary_action,
            "primary_action_text": self.primary_action_text,
            "primary_action_pl":   self.primary_action_pl,
            "learning_frozen":     self.learning_frozen,
            "total_count":         self.total_count,
            "shown_count":         self.shown_count,
            "corrections": [
                {
                    "check_key":       c.check_key,
                    "source_check":    c.source_check,
                    "severity":        c.severity,
                    "next_action":     c.next_action,
                    "auto_override":   c.auto_override,
                    "confidence":      round(c.confidence, 3),
                    "title_en":        c.title_en,
                    "title_pl":        c.title_pl,
                    "problem_en":      c.problem_en,
                    "problem_pl":      c.problem_pl,
                    "fix_en":          c.fix_en,
                    "fix_pl":          c.fix_pl,
                    "amendment_en":    c.amendment_en,
                    "amendment_pl":    c.amendment_pl,
                    "structured_diff": c.structured_diff,
                    "impact":          c.impact,
                    "diff":            c.diff,
                    "evidence":        c.evidence,
                }
                for c in self.corrections
            ],
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _confidence_for(check_key: str, learning_confidence: Dict[str, float]) -> float:
    """
    Derive correction confidence:
      - Hard locks: always 1.0 (audit-determined, not learned)
      - Soft checks: use learning confidence if available, else 0.7 default
    """
    if check_key in HARD_LOCK_CHECKS:
        return 1.0
    return learning_confidence.get(check_key, 0.7)


def _group_invoice_refs(refs: List[Any]) -> str:
    """
    Compact consecutive invoice numbers into ranges.
    ['1318','1319','1320','1325'] → '1318–1320, 1325'
    Non-numeric refs are kept as-is.
    """
    if not refs:
        return ""
    numeric = []
    non_numeric = []
    for r in refs:
        try:
            numeric.append(int(str(r).strip()))
        except ValueError:
            non_numeric.append(str(r).strip())

    numeric.sort()
    groups = []
    if numeric:
        start = end = numeric[0]
        for n in numeric[1:]:
            if n == end + 1:
                end = n
            else:
                groups.append(str(start) if start == end else f"{start}–{end}")
                start = end = n
        groups.append(str(start) if start == end else f"{start}–{end}")

    return ", ".join(groups + non_numeric)


def _make_structured_diff(
    rows: List[tuple[str, str, str]]   # (field, current, corrected)
) -> List[Dict[str, str]]:
    return [{"field": f, "current": c, "corrected": r} for f, c, r in rows]


# ── Per-check correction builders ─────────────────────────────────────────────

def _fix_identity_mismatch(
    audit_data: dict, result: dict,
    learning_confidence: Dict[str, float],
) -> Optional[CorrectionItem]:
    """c1/c2: exporter or importer identity confirmed mismatched."""
    c1 = audit_data.get("c1", {})
    c2 = audit_data.get("c2", {})

    evidence       = []
    diff           = {}
    problems       = []
    problems_pl    = []
    amendments_en  = []
    amendments_pl  = []
    sdiff_rows     = []

    # Exporter
    sad_exp = c1.get("sad_exporter", "")
    inv_exp = c1.get("inv_exporter", "")
    if c1.get("result") is False and sad_exp and inv_exp and sad_exp != inv_exp:
        evidence.append(f"SAD field 2 exporter: '{sad_exp}'")
        evidence.append(f"Invoice seller: '{inv_exp}'")
        diff["exporter"] = {"sad": sad_exp, "invoice": inv_exp}
        sdiff_rows.append(("SAD Field 2 — Exporter", sad_exp, inv_exp))
        problems.append(
            f"SAD field 2 shows exporter as '{sad_exp}' "
            f"but invoice seller is '{inv_exp}'."
        )
        problems_pl.append(
            f"Pole 2 SAD wskazuje eksportera jako '{sad_exp}', "
            f"ale na fakturze sprzedawca to '{inv_exp}'."
        )
        amendments_en.append(
            f"Correct SAD field 2 (Exporter) from '{sad_exp}' to '{inv_exp}', "
            f"or obtain a supplier declaration confirming that '{inv_exp}' "
            f"is a trading name of '{sad_exp}'."
        )
        amendments_pl.append(
            f"Skoryguj pole 2 SAD (Eksporter) z '{sad_exp}' na '{inv_exp}', "
            f"albo uzyskaj od dostawcy oświadczenie potwierdzające, że '{inv_exp}' "
            f"jest nazwą handlową '{sad_exp}'."
        )

    # Importer name
    sad_imp = c2.get("sad_importer", "")
    inv_imp = c2.get("inv_importer", "")
    if c2.get("name_result") is False and sad_imp and inv_imp:
        evidence.append(f"SAD field 8 importer: '{sad_imp}'")
        evidence.append(f"Invoice buyer: '{inv_imp}'")
        diff["importer_name"] = {"sad": sad_imp, "invoice": inv_imp}
        sdiff_rows.append(("SAD Field 8 — Importer name", sad_imp, inv_imp))
        problems.append(
            f"SAD field 8 shows importer as '{sad_imp}' "
            f"but invoice buyer is '{inv_imp}'."
        )
        problems_pl.append(
            f"Pole 8 SAD wskazuje importera jako '{sad_imp}', "
            f"ale na fakturze nabywca to '{inv_imp}'."
        )
        amendments_en.append(
            f"Correct SAD field 8 (Consignee) from '{sad_imp}' to '{inv_imp}'. "
            f"Ensure the Polish tax ID (NIP) also matches."
        )
        amendments_pl.append(
            f"Skoryguj pole 8 SAD (Odbiorca) z '{sad_imp}' na '{inv_imp}'. "
            f"Sprawdź, czy NIP również jest zgodny."
        )

    # NIP mismatch
    sad_nip = c2.get("sad_nip", "")
    inv_nip = c2.get("inv_nip", "")
    if c2.get("nip_result") is False and sad_nip and inv_nip:
        evidence.append(f"SAD NIP: '{sad_nip}'")
        evidence.append(f"Invoice NIP: '{inv_nip}'")
        diff["nip"] = {"sad": sad_nip, "invoice": inv_nip}
        sdiff_rows.append(("SAD NIP / VAT ID", sad_nip, inv_nip))
        problems.append(
            f"NIP/VAT mismatch: SAD has '{sad_nip}', invoice has '{inv_nip}'."
        )
        problems_pl.append(
            f"Niezgodność NIP: SAD zawiera '{sad_nip}', faktura '{inv_nip}'."
        )
        amendments_en.append(
            f"This is a hard compliance failure. "
            f"File a SAD amendment to correct NIP from '{sad_nip}' to '{inv_nip}'. "
            f"Contact customs authority before attempting release."
        )
        amendments_pl.append(
            f"To twarda niezgodność compliance. "
            f"Złóż korektę SAD, aby zmienić NIP z '{sad_nip}' na '{inv_nip}'. "
            f"Skontaktuj się z urzędem celnym przed zwolnieniem towaru."
        )

    if not problems:
        return None

    is_nip: bool = "nip" in diff
    action: NextAction = "AMEND_SAD" if is_nip else "VERIFY_DOCS"
    risk_note = (
        "NIP mismatch blocks tax deductibility and may trigger customs inspection."
        if is_nip else
        "Identity mismatch may flag for customs examination."
    )

    return CorrectionItem(
        check_key       = "identity_mismatch",
        source_check    = "identity_mismatch",
        severity        = "CRITICAL",       # always CRITICAL — hard lock
        next_action     = action,
        auto_override   = False,            # hard lock — cannot be softened
        confidence      = 1.0,
        title_en        = "Identity Mismatch — Exporter / Importer / NIP",
        title_pl        = "Niezgodność tożsamości — eksporter / importer / NIP",
        problem_en      = " ".join(problems),
        problem_pl      = " ".join(problems_pl),
        fix_en          = (
            "Option A: Amend the SAD to reflect the correct party names and NIP as shown on invoices. "
            "Option B: Obtain a written supplier declaration confirming name equivalence. "
            "Option C: If invoices are incorrect, obtain corrected invoices from the supplier."
        ),
        fix_pl          = (
            "Opcja A: Złóż korektę SAD z poprawnymi nazwami stron i NIP-em zgodnym z fakturami. "
            "Opcja B: Uzyskaj pisemne oświadczenie dostawcy potwierdzające równoważność nazw. "
            "Opcja C: Jeśli faktury są błędne, uzyskaj skorygowane faktury od dostawcy."
        ),
        amendment_en    = " | ".join(amendments_en),
        amendment_pl    = " | ".join(amendments_pl),
        structured_diff = _make_structured_diff(sdiff_rows),
        impact          = {
            "risk":  "HIGH — identity mismatch may block release or trigger inspection",
            "notes": risk_note,
        },
        diff            = diff,
        evidence        = evidence,
    )


def _fix_invoice_missing(
    audit_data: dict, result: dict,
    learning_confidence: Dict[str, float],
) -> Optional[CorrectionItem]:
    """c4: invoice referenced in SAD has no matching PDF, or vice versa."""
    c4 = audit_data.get("c4", {})
    if c4.get("result") is not False:
        return None

    missing_from_pdf = c4.get("in_sad_not_pdf", [])
    missing_from_sad = c4.get("in_pdf_not_sad", [])
    evidence  = []
    diff      = {}
    sdiff_rows: List[tuple] = []

    grouped_pdf = _group_invoice_refs(missing_from_pdf)
    grouped_sad = _group_invoice_refs(missing_from_sad)

    problem_en = ""
    problem_pl = ""
    amendment_en = ""
    amendment_pl = ""

    if missing_from_pdf:
        evidence.append(f"SAD references these invoices but no PDF found: {grouped_pdf}")
        diff["in_sad_not_pdf"] = missing_from_pdf
        sdiff_rows.append((
            "Invoices in SAD without PDF",
            grouped_pdf,
            "Attach missing PDF(s) or remove SAD reference",
        ))
        problem_en += (
            f"SAD references invoice(s) {grouped_pdf} but the corresponding PDF(s) "
            f"were not found in this submission. "
        )
        problem_pl += (
            f"SAD odwołuje się do faktury/faktur {grouped_pdf}, "
            f"ale odpowiadające PDF-y nie zostały załączone. "
        )
        amendment_en += (
            f"Attach the missing invoice PDF(s) for: {grouped_pdf}. "
            f"If not available, file a SAD amendment to remove the reference. "
        )
        amendment_pl += (
            f"Dołącz brakujące PDF-y faktury/faktur: {grouped_pdf}. "
            f"Jeśli niedostępne, złóż korektę SAD usuwającą odniesienie. "
        )

    if missing_from_sad:
        evidence.append(f"PDFs submitted but not in SAD: {grouped_sad}")
        diff["in_pdf_not_sad"] = missing_from_sad
        sdiff_rows.append((
            "Invoices as PDF but not in SAD references",
            grouped_sad,
            "Add to SAD invoice references or remove PDF from submission",
        ))
        problem_en += (
            f"Invoice PDF(s) were submitted for {grouped_sad} "
            f"but these are not referenced in the SAD. "
        )
        problem_pl += (
            f"Dołączono PDF-y faktur dla {grouped_sad}, "
            f"ale SAD nie zawiera odwołania do tych dokumentów. "
        )
        amendment_en += (
            f"Option A: Add invoice(s) {grouped_sad} to SAD item references. "
            f"Option B: Remove the unmatched invoice PDF(s) from the submission "
            f"if they belong to a different declaration."
        )
        amendment_pl += (
            f"Opcja A: Dodaj fakturę/faktury {grouped_sad} do odwołań w pozycjach SAD. "
            f"Opcja B: Usuń niezgodne PDF-y z przesyłki, jeśli należą do innej deklaracji."
        )

    total_gap = len(missing_from_pdf) + len(missing_from_sad)
    return CorrectionItem(
        check_key       = "invoice_missing",
        source_check    = "invoice_missing",
        severity        = "CRITICAL",
        next_action     = "AMEND_SAD",
        auto_override   = False,            # hard lock
        confidence      = 1.0,
        title_en        = (
            f"Invoice Chain Gap — {total_gap} Invoice(s) Mismatched"
            if total_gap > 1 else
            "Invoice Chain Gap — SAD ↔ PDF Mismatch"
        ),
        title_pl        = (
            f"Luka w łańcuchu faktur — {total_gap} faktura/faktury niezgodne"
            if total_gap > 1 else
            "Luka w łańcuchu faktur — niezgodność SAD ↔ PDF"
        ),
        problem_en      = problem_en.strip(),
        problem_pl      = problem_pl.strip(),
        fix_en          = (
            "Reconcile the invoice set: ensure every SAD reference has a matching PDF "
            "and every submitted PDF is referenced in the SAD. "
            "Do not release until the invoice chain is complete."
        ),
        fix_pl          = (
            "Uzgodnij zestaw faktur: upewnij się, że każde odwołanie SAD ma pasujący PDF "
            "i każdy załączony PDF jest wymieniony w SAD. "
            "Nie zwalniaj towaru do czasu uzupełnienia łańcucha faktur."
        ),
        amendment_en    = amendment_en.strip(),
        amendment_pl    = amendment_pl.strip(),
        structured_diff = _make_structured_diff(sdiff_rows),
        impact          = {
            "risk":  "HIGH — release blocked until invoice chain is complete",
            "notes": f"{total_gap} invoice reference(s) need resolution before SAD can be finalised.",
        },
        diff            = diff,
        evidence        = evidence,
    )


def _fix_value_mismatch(
    audit_data: dict, result: dict,
    learning_confidence: Dict[str, float],
) -> Optional[CorrectionItem]:
    """c5: CIF total on invoices does not match SAD CIF value."""
    c5 = audit_data.get("c5", {})
    if c5.get("cif_result") is not False:
        return None

    sad_cif     = c5.get("sad_cif",     0.0)
    invoice_cif = c5.get("invoice_cif", 0.0)
    diff_abs    = abs(invoice_cif - sad_cif)
    diff_pct    = (diff_abs / sad_cif * 100) if sad_cif else 0
    currency    = c5.get("currency", "USD")

    if diff_abs < 0.01:
        return None  # rounding only

    evidence = [
        f"SAD CIF value: {sad_cif:,.2f} {currency}",
        f"Invoice CIF total: {invoice_cif:,.2f} {currency}",
        f"Discrepancy: {diff_abs:,.2f} {currency} ({diff_pct:.2f}%)",
    ]

    per_inv = c5.get("per_inv_checks", [])
    formula_errors = [ch for ch in per_inv if not ch.get("ok")]
    for fe in formula_errors:
        evidence.append(
            f"Invoice {fe.get('invoice_no','?')}: "
            f"FOB {fe.get('fob',0):,.2f} + Freight {fe.get('freight',0):,.2f} "
            f"+ Insurance {fe.get('insurance',0):,.2f} = "
            f"{fe.get('computed_cif',0):,.2f} ≠ stated CIF {fe.get('stated_cif',0):,.2f}"
        )

    direction = "over-declared" if invoice_cif > sad_cif else "under-declared"
    direction_pl = "zawyżony" if invoice_cif > sad_cif else "zaniżony"

    # Approximate duty impact (EU average ~4% on jewellery)
    duty_impact_approx = round(diff_abs * 0.04, 2)
    nbp_rate = result.get("nbp", {}).get("usd_rate") or 4.0  # fallback
    duty_pln_approx = round(duty_impact_approx * nbp_rate, 2) if currency == "USD" else duty_impact_approx

    if formula_errors:
        inv_nos = ", ".join(fe.get("invoice_no", "?") for fe in formula_errors)
        amendment_en = (
            f"SAD CIF is {direction} by {diff_abs:,.2f} {currency} ({diff_pct:.2f}%). "
            f"FOB+Freight+Insurance ≠ CIF on invoice(s) {inv_nos}. "
            f"Request corrected invoices from the supplier showing correct CIF breakdown."
        )
        amendment_pl = (
            f"CIF w SAD jest {direction_pl} o {diff_abs:,.2f} {currency} ({diff_pct:.2f}%). "
            f"FOB+Fracht+Ubezpieczenie ≠ CIF na fakturze/fakturach {inv_nos}. "
            f"Wnioskuj o skorygowane faktury od dostawcy z prawidłowym rozbiciem CIF."
        )
        fix_en = (
            f"Step 1: Identify which invoices have formula errors (FOB+F+I ≠ stated CIF). "
            f"Step 2: Request corrected invoices from the supplier. "
            f"Step 3: If CIF cannot be corrected, file a SAD amendment with the correct value. "
            f"Step 4: Recalculate duty based on the corrected CIF."
        )
        fix_pl = (
            f"Krok 1: Zidentyfikuj faktury z błędem formuły (FOB+F+I ≠ podane CIF). "
            f"Krok 2: Zwróć się do dostawcy o skorygowane faktury. "
            f"Krok 3: Jeśli CIF nie można skorygować, złóż korektę SAD z poprawną wartością. "
            f"Krok 4: Przelicz cło na podstawie skorygowanego CIF."
        )
    else:
        amendment_en = (
            f"SAD CIF is {direction} by {diff_abs:,.2f} {currency} ({diff_pct:.2f}%). "
            f"File a SAD value correction to change CIF from {sad_cif:,.2f} "
            f"to {invoice_cif:,.2f} {currency}. Recalculate duty accordingly."
        )
        amendment_pl = (
            f"CIF w SAD jest {direction_pl} o {diff_abs:,.2f} {currency} ({diff_pct:.2f}%). "
            f"Złóż korektę wartości SAD, zmieniając CIF z {sad_cif:,.2f} "
            f"na {invoice_cif:,.2f} {currency}. Przelicz cło odpowiednio."
        )
        fix_en = (
            f"File a SAD value amendment: change CIF from {sad_cif:,.2f} to "
            f"{invoice_cif:,.2f} {currency}. Recalculate A00 duty. "
            f"If the declared duty was too low, pay the difference before release."
        )
        fix_pl = (
            f"Złóż korektę wartości SAD: zmień CIF z {sad_cif:,.2f} na "
            f"{invoice_cif:,.2f} {currency}. Przelicz cło A00. "
            f"Jeśli zadeklarowane cło było za niskie, dopłać różnicę przed zwolnieniem towaru."
        )

    sdiff_rows = [("SAD CIF value", f"{sad_cif:,.2f} {currency}", f"{invoice_cif:,.2f} {currency}")]
    if formula_errors:
        for fe in formula_errors:
            sdiff_rows.append((
                f"Invoice {fe.get('invoice_no','?')} CIF formula",
                f"FOB+F+I = {fe.get('computed_cif',0):,.2f} ≠ stated {fe.get('stated_cif',0):,.2f}",
                "Request corrected invoice from supplier",
            ))

    return CorrectionItem(
        check_key       = "value_mismatch",
        source_check    = "value_mismatch",
        severity        = "CRITICAL",
        next_action     = "AMEND_SAD",
        auto_override   = False,        # hard lock
        confidence      = 1.0,
        title_en        = f"CIF Value Mismatch — {diff_pct:.1f}% Discrepancy",
        title_pl        = f"Niezgodność wartości CIF — rozbieżność {diff_pct:.1f}%",
        problem_en      = (
            f"The total CIF value on invoices ({invoice_cif:,.2f} {currency}) "
            f"does not match the CIF declared in the SAD ({sad_cif:,.2f} {currency}). "
            f"Discrepancy: {diff_abs:,.2f} {currency} ({diff_pct:.2f}%)."
        ),
        problem_pl      = (
            f"Łączna wartość CIF na fakturach ({invoice_cif:,.2f} {currency}) "
            f"nie zgadza się z CIF zadeklarowanym w SAD ({sad_cif:,.2f} {currency}). "
            f"Rozbieżność: {diff_abs:,.2f} {currency} ({diff_pct:.2f}%)."
        ),
        fix_en          = fix_en,
        fix_pl          = fix_pl,
        amendment_en    = amendment_en.strip(),
        amendment_pl    = amendment_pl.strip(),
        structured_diff = _make_structured_diff(sdiff_rows),
        impact          = {
            "duty_approx":   f"~{duty_pln_approx:,.2f} PLN duty impact",
            "risk":          "HIGH → resolves after SAD value correction",
            "notes":         f"CIF {direction} by {diff_abs:,.2f} {currency}. "
                             f"Estimated duty adjustment: ~{duty_pln_approx:,.2f} PLN.",
        },
        diff            = {
            "sad_cif":        sad_cif,
            "invoice_cif":    invoice_cif,
            "diff_abs":       round(diff_abs, 2),
            "diff_pct":       round(diff_pct, 2),
            "currency":       currency,
            "formula_errors": [fe.get("invoice_no") for fe in formula_errors],
        },
        evidence        = evidence,
    )


def _fix_address_inconsistency(
    audit_data: dict, result: dict,
    learning_confidence: Dict[str, float],
    learning_frozen: bool,
) -> Optional[CorrectionItem]:
    """c3: delivery address classification inconsistency."""
    c3 = audit_data.get("c3", {})
    if c3.get("consistent") is not False:
        return None

    inv_addr  = c3.get("invoice_addr", "unknown")
    reg_addr  = c3.get("registered_office", "")
    addr_type = c3.get("address_type", "unknown")
    confidence = _confidence_for("address_inconsistency", learning_confidence)

    extra_evidence = []
    if learning_frozen:
        confidence = 0.0
        extra_evidence = [
            "[FROZEN] Learned address pattern check suspended — confidence set to 0 during audit period."
        ]

    return CorrectionItem(
        check_key       = "address_inconsistency",
        source_check    = "address_inconsistency",
        severity        = "WARNING",
        next_action     = "VERIFY_DOCS",
        auto_override   = True,             # soft check — can be overridden
        confidence      = confidence,
        title_en        = "Delivery Address Classification — Warehouse vs Registered Office",
        title_pl        = "Klasyfikacja adresu dostawy — magazyn vs siedziba",
        problem_en      = (
            f"Invoice delivery address '{inv_addr}' was classified as '{addr_type}'. "
            f"This differs from the registered office on record ({reg_addr}). "
            f"Delivery to a warehouse or third-party address requires explicit "
            f"documentation of the goods' destination."
        ),
        problem_pl      = (
            f"Adres dostawy na fakturze '{inv_addr}' sklasyfikowano jako '{addr_type}'. "
            f"Różni się od zarejestrowanej siedziby ({reg_addr}). "
            f"Dostawa do magazynu lub adresu strony trzeciej wymaga "
            f"wyraźnej dokumentacji miejsca przeznaczenia towaru."
        ),
        fix_en          = (
            "Option A: If the warehouse is a known declared place of delivery, "
            "add a note to the SAD confirming the goods' physical destination. "
            "Option B: Obtain a warehouse receipt or delivery confirmation for customs. "
            "Option C: If the address is incorrect on the invoice, obtain a corrected invoice."
        ),
        fix_pl          = (
            "Opcja A: Jeśli magazyn jest zadeklarowanym miejscem dostawy, "
            "dodaj adnotację do SAD potwierdzającą fizyczne miejsce przeznaczenia towaru. "
            "Opcja B: Uzyskaj kwit magazynowy lub potwierdzenie dostawy dla celnika. "
            "Opcja C: Jeśli adres na fakturze jest błędny, uzyskaj skorygowaną fakturę."
        ),
        amendment_en    = (
            f"Add delivery destination note to SAD: "
            f"'Goods delivered to {inv_addr} (declared warehouse/place of delivery). "
            f"Supporting warehouse documentation available on request.'"
        ),
        amendment_pl    = (
            f"Dodaj adnotację o miejscu dostawy do SAD: "
            f"'Towar dostarczony do {inv_addr} (zadeklarowany magazyn/miejsce dostawy). "
            f"Dokumentacja magazynowa dostępna na żądanie.'"
        ),
        structured_diff = _make_structured_diff([
            ("Delivery address on invoice", inv_addr, "Confirm or correct"),
            ("Registered office on record", reg_addr, "—"),
            ("Classification", addr_type, "warehouse / registered"),
        ]),
        impact          = {
            "risk":  "MEDIUM — may require supporting documentation",
            "notes": "No duty impact expected. Documentation gap only.",
        },
        diff            = {"invoice_addr": inv_addr, "registered_office": reg_addr, "type": addr_type},
        evidence        = [
            f"Invoice delivery address: '{inv_addr}'",
            f"Classified as: {addr_type}",
            f"Registered office on record: '{reg_addr}'",
        ] + extra_evidence,
    )


def _fix_transport_mismatch(
    audit_data: dict, result: dict,
    learning_confidence: Dict[str, float],
    learning_frozen: bool,
) -> Optional[CorrectionItem]:
    """c6: AWB/CMR not found or not linkable to SAD."""
    c6 = audit_data.get("c6", {})
    if c6.get("result") is not False:
        return None

    sad_refs   = c6.get("sad_transport_refs", [])
    found_refs = c6.get("found_refs", [])
    awb_in_sad = c6.get("awb_in_sad", "")
    confidence = _confidence_for("transport_mismatch", learning_confidence)

    extra_evidence = []
    if learning_frozen:
        confidence = 0.0
        extra_evidence = [
            "[FROZEN] Learned transport pattern check suspended — confidence set to 0 during audit period."
        ]

    return CorrectionItem(
        check_key       = "transport_mismatch",
        source_check    = "transport_mismatch",
        severity        = "WARNING",
        next_action     = "VERIFY_DOCS",
        auto_override   = True,
        confidence      = confidence,
        title_en        = "Transport Document Not Linked — AWB / CMR",
        title_pl        = "Brak powiązania dokumentu transportowego — AWB / CMR",
        problem_en      = (
            f"The transport document reference in the SAD "
            f"({awb_in_sad or 'not found'}) "
            f"could not be verified against the submitted documents. "
            + (f"SAD N740 refs: {sad_refs}. " if sad_refs else "")
            + (f"Refs found in PDFs: {found_refs}." if found_refs else "No transport refs found in PDFs.")
        ),
        problem_pl      = (
            f"Numer dokumentu transportowego w SAD "
            f"({awb_in_sad or 'brak'}) "
            f"nie może być zweryfikowany na podstawie załączonych dokumentów. "
            + (f"Referencje N740 w SAD: {sad_refs}. " if sad_refs else "")
            + (f"Referencje znalezione w PDF: {found_refs}." if found_refs else "Brak referencji transportowych w PDF-ach.")
        ),
        fix_en          = (
            "Step 1: Locate the original Air Waybill (AWB) or CMR document. "
            "Step 2: Verify the AWB number matches the reference in SAD field N740. "
            "Step 3: Attach the AWB copy to the customs file. "
            "Step 4: If the SAD reference is wrong, file a SAD amendment to correct field N740."
        ),
        fix_pl          = (
            "Krok 1: Znajdź oryginał listu przewozowego (AWB lub CMR). "
            "Krok 2: Sprawdź, czy numer AWB zgadza się z odwołaniem w polu N740 SAD. "
            "Krok 3: Dołącz kopię AWB do akt celnych. "
            "Krok 4: Jeśli odwołanie w SAD jest błędne, złóż korektę pola N740."
        ),
        amendment_en    = (
            f"Attach AWB copy to customs file. "
            f"If SAD field N740 is incorrect, file amendment to correct transport reference "
            f"from '{awb_in_sad}' to the correct AWB number."
        ),
        amendment_pl    = (
            f"Dołącz kopię AWB do akt celnych. "
            f"Jeśli pole N740 SAD jest błędne, złóż korektę zmieniającą referencję transportową "
            f"z '{awb_in_sad}' na właściwy numer AWB."
        ),
        structured_diff = _make_structured_diff([
            ("SAD N740 transport reference", awb_in_sad or "—", "Correct AWB number"),
            ("Transport refs in submitted PDFs", str(found_refs or "none"), "Must match SAD"),
        ]),
        impact          = {
            "risk":  "MEDIUM — transport document gap may delay customs clearance",
            "notes": "No direct duty impact. Documentation compliance risk.",
        },
        diff     = {"sad_ref": awb_in_sad, "found_refs": found_refs, "sad_n740": sad_refs},
        evidence = [
            f"SAD N740 transport refs: {sad_refs or 'none'}",
            f"Transport refs found in submitted PDFs: {found_refs or 'none'}",
        ] + extra_evidence,
    )


def _fix_freight_anomalies(
    audit_data: dict, result: dict, freight_checks: List[dict],
    learning_confidence: Dict[str, float],
    learning_frozen: bool,
) -> Optional[CorrectionItem]:
    """Freight anomalies from learning layer. Advisory — soft check."""
    anomalies = [
        fc for fc in (freight_checks or [])
        if fc.get("status") in ("ANOMALY", "OUTSIDE_TOLERANCE")
    ]
    if not anomalies:
        return None

    evidence   = []
    diff       = {}
    sdiff_rows = []
    confidence = _confidence_for("freight_anomaly", learning_confidence)

    extra_evidence = []
    if learning_frozen:
        confidence = 0.0
        extra_evidence = [
            "[FROZEN] Freight pattern check from learning system suspended — confidence set to 0."
        ]

    for fc in anomalies:
        inv_no   = fc.get("invoice_no", "?")
        actual   = fc.get("actual_freight_pct", 0)
        expected = fc.get("expected_freight_pct")
        status   = fc.get("status")
        evidence.append(
            f"Invoice {inv_no}: actual freight {actual:.2%}, "
            f"expected {expected:.2%}" if expected else
            f"Invoice {inv_no}: actual freight {actual:.2%} (no baseline)"
        )
        diff[inv_no] = {
            "status":   status,
            "actual":   actual,
            "expected": expected,
            "reason":   fc.get("reason", ""),
        }
        sdiff_rows.append((
            f"Invoice {inv_no} — freight rate",
            f"{actual:.2%}",
            f"Expected ~{expected:.2%}" if expected else "Check with forwarder",
        ))

    is_anomaly = any(fc.get("status") == "ANOMALY" for fc in anomalies)
    severity: Severity = "WARNING" if is_anomaly else "ADVISORY"
    inv_list = _group_invoice_refs([fc.get("invoice_no", "?") for fc in anomalies])

    return CorrectionItem(
        check_key       = "freight_anomaly",
        source_check    = "freight_anomaly",
        severity        = severity,
        next_action     = "VERIFY_DOCS",
        auto_override   = True,         # soft check — can be overridden
        confidence      = confidence,
        title_en        = (
            f"Freight Rate Anomaly — {len(anomalies)} Invoice(s)" if is_anomaly else
            f"Freight Rate Outside Tolerance — {len(anomalies)} Invoice(s)"
        ),
        title_pl        = (
            f"Anomalia stawki frachtu — {len(anomalies)} faktura/faktury" if is_anomaly else
            f"Stawka frachtu poza zakresem tolerancji — {len(anomalies)} faktura/faktury"
        ),
        problem_en      = (
            f"Freight rate on invoice(s) {inv_list} "
            f"{'significantly deviates from the historical 3σ band' if is_anomaly else 'is outside the expected tolerance band'} "
            f"for this supplier. This may indicate an error or unusual commercial terms."
        ),
        problem_pl      = (
            f"Stawka frachtu na fakturze/fakturach {inv_list} "
            f"{'znacząco odbiega od historycznego zakresu 3σ' if is_anomaly else 'wykracza poza oczekiwany zakres tolerancji'} "
            f"dla tego dostawcy."
        ),
        fix_en          = (
            "Step 1: Contact the freight forwarder and confirm the freight charges on invoice(s). "
            "Step 2: Request a freight note or rate confirmation. "
            "Step 3: If the freight is correct but unusual, document the commercial reason. "
            "Step 4: If the freight is incorrect, obtain a corrected invoice before filing."
        ),
        fix_pl          = (
            "Krok 1: Skontaktuj się ze spedytorem i potwierdź naliczone koszty frachtu. "
            "Krok 2: Uzyskaj notę frachtową lub potwierdzenie stawki. "
            "Krok 3: Jeśli fracht jest poprawny ale niestandardowy, udokumentuj powód handlowy. "
            "Krok 4: Jeśli fracht jest błędny, uzyskaj skorygowaną fakturę przed zgłoszeniem."
        ),
        amendment_en    = (
            f"Document freight justification for invoice(s) {inv_list}. "
            f"Attach freight forwarder rate confirmation to customs file."
        ),
        amendment_pl    = (
            f"Udokumentuj uzasadnienie frachtu dla faktury/faktur {inv_list}. "
            f"Dołącz potwierdzenie stawki od spedytora do akt celnych."
        ),
        structured_diff = _make_structured_diff(sdiff_rows),
        impact          = {
            "risk":  "LOW — freight anomaly is advisory; no duty recalculation required unless mismatch confirmed",
            "notes": f"{len(anomalies)} invoice(s) with freight rate deviation. Verify with forwarder.",
        },
        diff     = diff,
        evidence = evidence + extra_evidence,
    )


# ── Primary action resolver ───────────────────────────────────────────────────

def _resolve_primary_action(corrections: List[CorrectionItem]) -> tuple[str, str, str]:
    """
    Returns (action_code, text_en, text_pl) for the single most important step.
    Priority: CRITICAL items first, then first AMEND_SAD, then first item.
    """
    if not corrections:
        return "", "No action required — all checks passed.", "Brak wymaganych działań — wszystkie kontrole przeszły."

    # Pick the first CRITICAL, or else the first item
    anchor = next((c for c in corrections if c.severity == "CRITICAL"), corrections[0])

    action_map = {
        "AMEND_SAD":          ("File a SAD amendment", "Złóż korektę SAD"),
        "VERIFY_DOCS":        ("Verify supporting documents", "Zweryfikuj dokumenty"),
        "ESCALATE_CUSTOMS":   ("Escalate to customs authority", "Eskaluj do urzędu celnego"),
        "RESOLVE_INTERNALLY": ("Resolve internally before filing", "Rozwiąż wewnętrznie"),
    }
    en_verb, pl_verb = action_map.get(anchor.next_action, (anchor.next_action, anchor.next_action))
    text_en = f"→ {en_verb}: {anchor.title_en}"
    text_pl = f"→ {pl_verb}: {anchor.title_pl}"
    return anchor.next_action, text_en, text_pl


# ── Main builder ──────────────────────────────────────────────────────────────

def build_corrections(
    audit_data:          Dict[str, Any],
    result:              Dict[str, Any],
    batch_id:            str,
    doc_no:              str                = "",
    freight_checks:      Optional[List[dict]] = None,
    learning_confidence: Optional[Dict[str, float]] = None,
    learning_frozen:     bool               = False,
) -> CorrectionReport:
    """
    Build a CorrectionReport from audit check results.

    Parameters:
        audit_data          dict from audit_agent.build_audit_report()["audit_data"]
        result              full engine result dict
        batch_id            batch identifier
        doc_no              document number
        freight_checks      list from learning_agent.check_freight_against_pattern()
        learning_confidence map of check_key → confidence float from learning agent
        learning_frozen     True when LEARNING_FROZEN env var is active

    Returns:
        CorrectionReport with structured correction items, ordered CRITICAL → WARNING → ADVISORY,
        capped at MAX_CORRECTIONS=5.
    """
    lconf = learning_confidence or {}
    corrections: List[CorrectionItem] = []

    builders = [
        lambda: _fix_identity_mismatch(audit_data, result, lconf),
        lambda: _fix_invoice_missing(audit_data, result, lconf),
        lambda: _fix_value_mismatch(audit_data, result, lconf),
        lambda: _fix_address_inconsistency(audit_data, result, lconf, learning_frozen),
        lambda: _fix_transport_mismatch(audit_data, result, lconf, learning_frozen),
        lambda: _fix_freight_anomalies(audit_data, result, freight_checks or [], lconf, learning_frozen),
    ]

    for builder in builders:
        try:
            item = builder()
            if item is not None:
                # Enforce hard lock: HARD_LOCK_CHECKS are always CRITICAL + auto_override=False
                if item.check_key in HARD_LOCK_CHECKS:
                    item.severity      = "CRITICAL"
                    item.auto_override = False
                    item.confidence    = 1.0
                corrections.append(item)
        except Exception:
            pass  # correction generation is best-effort

    # Sort CRITICAL → WARNING → ADVISORY, track counts before and after cap
    _order = {"CRITICAL": 0, "WARNING": 1, "ADVISORY": 2}
    corrections.sort(key=lambda c: _order.get(c.severity, 9))
    total_count = len(corrections)
    corrections = corrections[:MAX_CORRECTIONS]
    shown_count = len(corrections)

    primary_action, primary_text_en, primary_text_pl = _resolve_primary_action(corrections)

    return CorrectionReport(
        batch_id             = batch_id,
        doc_no               = doc_no,
        generated            = time.strftime("%Y-%m-%dT%H:%M:%S"),
        corrections          = corrections,
        has_critical         = any(c.severity == "CRITICAL" for c in corrections),
        has_warning          = any(c.severity == "WARNING"  for c in corrections),
        primary_action       = primary_action,
        primary_action_text  = primary_text_en,
        primary_action_pl    = primary_text_pl,
        learning_frozen      = learning_frozen,
        total_count          = total_count,
        shown_count          = shown_count,
    )


# ── Amendment draft text generator ───────────────────────────────────────────

def draft_amendment_text(
    corrections:     CorrectionReport,
    doc_no:          str = "",
    settlement_mode: str = "standard",
) -> tuple[str, str]:
    """
    Generate a bilingual amendment memo from a CorrectionReport.
    Returns (en_text, pl_text).
    """
    now = time.strftime("%Y-%m-%d %H:%M")

    # ── English ──────────────────────────────────────────────────────────────
    en_lines = [
        "=" * 72,
        "CUSTOMS DECLARATION AMENDMENT NOTICE",
        f"Document:       {doc_no or 'N/A'}",
        f"Generated:      {now}",
        f"Settlement:     {settlement_mode.upper()}",
        f"Learning freeze:{' YES — pattern-based corrections excluded' if corrections.learning_frozen else ' No'}",
        "=" * 72,
        "",
    ]

    if corrections.primary_action:
        en_lines += [
            "PRIMARY RECOMMENDATION:",
            f"  {corrections.primary_action_text}",
            "",
        ]

    en_lines += [
        "The following discrepancies require resolution before or after release.",
        "Amendment items are listed in order of severity.",
        "",
    ]

    for i, c in enumerate(corrections.corrections, 1):
        sev_label = {
            "CRITICAL": "🔴 CRITICAL — must resolve",
            "WARNING":  "🟡 WARNING  — should verify",
            "ADVISORY": "🔵 ADVISORY — recommended",
        }.get(c.severity, c.severity)
        lock_note = "" if c.auto_override else "  [HARD LOCK — cannot be overridden by learning]"
        conf_pct  = f"{c.confidence * 100:.0f}%"

        en_lines += [
            "─" * 72,
            f"[{i}] {c.title_en}",
            f"    Severity:     {sev_label}{lock_note}",
            f"    Action:       {c.next_action}",
            f"    Confidence:   {conf_pct}",
            f"    Source check: {c.source_check}",
            "",
            "    Problem:",
            *[f"      {line.strip()}." for line in c.problem_en.rstrip(".").split(". ") if line.strip()],
            "",
            "    Suggested fix:",
            *[f"      {line.strip()}." for line in c.fix_en.rstrip(".").split(". ") if line.strip()],
            "",
        ]

        # Structured amendment block
        if c.structured_diff:
            en_lines += [
                "    AMENDMENT DETAILS:",
                f"    {'Field':<40} {'Current':<25} {'Corrected'}",
                "    " + "-" * 70,
            ]
            for row in c.structured_diff:
                f_  = row.get("field", "")[:38]
                cur = row.get("current", "")[:23]
                cor = row.get("corrected", "")
                en_lines.append(f"    {f_:<40} {cur:<25} {cor}")
            en_lines.append("")

        # Impact
        if c.impact:
            en_lines.append("    Impact:")
            for k, v in c.impact.items():
                en_lines.append(f"      {k}: {v}")
            en_lines.append("")

        en_lines.append(f"    Amendment draft: {c.amendment_en}")
        en_lines.append("")

    if not corrections.corrections:
        en_lines.append("No corrections required. All checks passed.")

    en_lines += [
        "=" * 72,
        f"Total: {len(corrections.corrections)} "
        f"| Critical: {len(corrections.by_severity('CRITICAL'))} "
        f"| Warnings: {len(corrections.by_severity('WARNING'))} "
        f"| Advisory: {len(corrections.by_severity('ADVISORY'))}",
        "",
        "This notice was generated automatically. Human verification required",
        "before submitting any amendment to the customs authority.",
        "=" * 72,
    ]

    # ── Polish ────────────────────────────────────────────────────────────────
    action_pl_map = {
        "AMEND_SAD":          "KOREKTA SAD",
        "VERIFY_DOCS":        "WERYFIKACJA DOKUMENTÓW",
        "ESCALATE_CUSTOMS":   "ESKALACJA DO URZĘDU CELNEGO",
        "RESOLVE_INTERNALLY": "ROZWIĄZANIE WEWNĘTRZNE",
    }

    pl_lines = [
        "=" * 72,
        "ZAWIADOMIENIE O KOREKCIE ZGŁOSZENIA CELNEGO",
        f"Dokument:         {doc_no or 'N/A'}",
        f"Wygenerowano:     {now}",
        f"Tryb rozliczenia: {settlement_mode.upper()}",
        f"Zamrożenie nauki: {'TAK — korekty z wzorców wyłączone' if corrections.learning_frozen else 'Nie'}",
        "=" * 72,
        "",
    ]

    if corrections.primary_action:
        pl_lines += [
            "GŁÓWNE ZALECENIE:",
            f"  {corrections.primary_action_pl}",
            "",
        ]

    pl_lines += [
        "Poniższe rozbieżności wymagają rozwiązania przed lub po zwolnieniu towaru.",
        "",
    ]

    for i, c in enumerate(corrections.corrections, 1):
        sev_pl = {
            "CRITICAL": "🔴 KRYTYCZNE — wymagane rozwiązanie",
            "WARNING":  "🟡 OSTRZEŻENIE — zalecana weryfikacja",
            "ADVISORY": "🔵 ZALECENIE — sugerowany przegląd",
        }.get(c.severity, c.severity)
        lock_note_pl = "" if c.auto_override else "  [BLOKADA — nie może być zmieniona przez system uczenia]"
        conf_pct     = f"{c.confidence * 100:.0f}%"

        pl_lines += [
            "─" * 72,
            f"[{i}] {c.title_pl}",
            f"    Priorytet:    {sev_pl}{lock_note_pl}",
            f"    Działanie:    {action_pl_map.get(c.next_action, c.next_action)}",
            f"    Pewność:      {conf_pct}",
            "",
            "    Problem:",
            *[f"      {line.strip()}." for line in c.problem_pl.rstrip(".").split(". ") if line.strip()],
            "",
            "    Sugerowane działanie:",
            *[f"      {line.strip()}." for line in c.fix_pl.rstrip(".").split(". ") if line.strip()],
            "",
        ]

        if c.structured_diff:
            pl_lines += [
                "    SZCZEGÓŁY KOREKTY:",
                f"    {'Pole':<40} {'Aktualne':<25} {'Poprawione'}",
                "    " + "-" * 70,
            ]
            for row in c.structured_diff:
                f_  = row.get("field", "")[:38]
                cur = row.get("current", "")[:23]
                cor = row.get("corrected", "")
                pl_lines.append(f"    {f_:<40} {cur:<25} {cor}")
            pl_lines.append("")

        if c.impact:
            pl_lines.append("    Wpływ:")
            for k, v in c.impact.items():
                pl_lines.append(f"      {k}: {v}")
            pl_lines.append("")

        pl_lines.append(f"    Projekt korekty: {c.amendment_pl}")
        pl_lines.append("")

    if not corrections.corrections:
        pl_lines.append("Brak wymaganych korekt. Wszystkie kontrole przeszły pomyślnie.")

    pl_lines += [
        "=" * 72,
        f"Łącznie: {len(corrections.corrections)} "
        f"| Krytyczne: {len(corrections.by_severity('CRITICAL'))} "
        f"| Ostrzeżenia: {len(corrections.by_severity('WARNING'))} "
        f"| Zalecenia: {len(corrections.by_severity('ADVISORY'))}",
        "",
        "Zawiadomienie wygenerowane automatycznie. Wymagana weryfikacja przez człowieka",
        "przed złożeniem jakiejkolwiek korekty w urzędzie celnym.",
        "=" * 72,
    ]

    return "\n".join(en_lines), "\n".join(pl_lines)


# ── File writer ───────────────────────────────────────────────────────────────

def write_correction_report(
    corrections: CorrectionReport,
    output_dir:  Path,
    batch_id:    str,
    doc_no:      str = "",
    settlement_mode: str = "standard",
) -> Dict[str, Path]:
    """
    Write amendment texts (EN + PL) and structured JSON report to output_dir.
    Returns {"en": Path, "pl": Path, "json": Path}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    en_text, pl_text = draft_amendment_text(corrections, doc_no, settlement_mode)

    en_path   = output_dir / f"amendment_en_{batch_id}.txt"
    pl_path   = output_dir / f"amendment_pl_{batch_id}.txt"
    json_path = output_dir / f"corrections_{batch_id}.json"

    en_path.write_text(en_text,   encoding="utf-8")
    pl_path.write_text(pl_text,   encoding="utf-8")
    json_path.write_text(
        json.dumps(corrections.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return {"en": en_path, "pl": pl_path, "json": json_path}
