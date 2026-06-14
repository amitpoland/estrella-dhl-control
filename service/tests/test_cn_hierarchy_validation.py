"""
test_cn_hierarchy_validation.py — CN ↔ HSN hierarchy policy + evidence persistence.

Origin: SHIPMENT_7123231135 (2026-06-12). SAD CN 71131900 aggregated six
invoice HSN codes including one silver line (71131141, Invoice EJL/26-27/255).
The legacy parent-prefix check in pz_import_processor emitted cn_match=False
("failed_parent_mismatch") for a heading-level aggregation that the agreed
policy (service/app/services/cn_hsn_classifier.py) scores as non-blocking.
export_service then promoted the False into failed_checks → status='blocked'
→ every wFirma surface (preview / create / adopt) locked — while ALSO
dropping the compared HSN list from the persisted audit (ver_scalar strips
lists), so the classification panel rendered "Cannot compare" and hid the
operator decision buttons. Workflow class: mixed-metal HSN aggregation under
one aggregated SAD CN must verify with a note, never auto-block, and the
comparison evidence must survive into the audit.

Pins:
  1. Engine hierarchy outcomes (exact/HS6/heading verify; chapter-only soft
     block at medium risk; foreign chapter hard block at high risk;
     unparseable codes are a verify-gap None, never False).
  2. Engine ↔ cn_hsn_classifier blocking-parity on a shared matrix.
  3. _write_audit persists top-level invoice_hsn_codes (real builder, no stub
     — Lesson A) while verification stays scalar-only.
"""

import json
from pathlib import Path

import pytest

import pz_import_processor as eng

from app.services import cn_hsn_classifier as cn
from app.services.export_service import _write_audit


# ── helpers ───────────────────────────────────────────────────────────────────

INCIDENT_HSNS = [
    "71131913", "71131919", "71131141", "71131911", "71131921", "71131923",
]


def _verify(sad_cn, hsns):
    """Run the real engine verification with a minimal but valid shape."""
    invoices = [{
        "invoice_no": "EJL/26-27/254",
        "cif_usd": 100.0,
        "items": [{"hsn": h} for h in hsns],
    }]
    zc429 = {
        "cn_code": sad_cn,
        "invoice_refs": ["EJL/26-27/254"],
        "total_cif_usd": 100.0,
    }
    return eng.verify_sad_invoice_match(invoices, zc429)


# ── 1. Engine hierarchy outcomes ──────────────────────────────────────────────

def test_mixed_silver_gold_aggregation_verifies_with_note():
    """THE incident regression: silver 711311xx + gold 711319xx under one
    aggregated SAD CN 71131900 agree at heading 7113 → verified, low risk."""
    v = _verify("71131900", INCIDENT_HSNS)
    assert v["cn_match"] is True
    assert v["cn_status"] == "verified_heading_aggregated"
    assert v["cn_risk_level"] == "low"
    assert v["invoice_hsn_codes"] == INCIDENT_HSNS


def test_strict_children_keep_legacy_label():
    v = _verify("71131900", ["71131910", "71131930"])
    assert v["cn_match"] is True
    assert v["cn_status"] == "verified_parent_aggregated"
    assert v["cn_risk_level"] == "low"


def test_exact_match_verifies():
    v = _verify("71131900", ["71131900"])
    assert v["cn_match"] is True
    assert v["cn_risk_level"] == "low"


def test_chapter_only_agreement_soft_blocks_medium():
    """Heading differs (7117 imitation vs 7113 precious) but chapter 71
    agrees → confirmed mismatch at medium risk → operator decision."""
    v = _verify("71131900", ["71171900"])
    assert v["cn_match"] is False
    assert v["cn_status"] == "failed_parent_mismatch"
    assert v["cn_risk_level"] == "medium"


def test_foreign_chapter_hard_blocks_high():
    v = _verify("71131900", ["90031900"])
    assert v["cn_match"] is False
    assert v["cn_status"] == "failed_parent_mismatch"
    assert v["cn_risk_level"] == "high"


def test_one_foreign_line_among_good_lines_is_worst_wins_high():
    """A single foreign-chapter line is the structural risk even when every
    other line agrees at heading level (worst-per-line drives the outcome)."""
    v = _verify("71131900", INCIDENT_HSNS + ["90031900"])
    assert v["cn_match"] is False
    assert v["cn_risk_level"] == "high"


def test_no_invoice_hsn_is_verify_gap_not_block():
    v = _verify("71131900", [])
    assert v["cn_match"] is None
    assert v["cn_status"] == "invoice_hsn_not_parsed"
    assert v["cn_risk_level"] is None


def test_garbage_hsn_is_verify_gap_not_block():
    """Unparseable codes (no digits) must be a verify-gap (None), never a
    confirmed mismatch — three-state semantics."""
    v = _verify("71131900", ["N/A", "-"])
    assert v["cn_match"] is None
    assert v["cn_status"] == "invoice_hsn_not_parsed"


def test_no_sad_cn_is_verify_gap():
    v = _verify("", ["71131913"])
    assert v["cn_match"] is None
    assert v["cn_status"] == "sad_cn_not_parsed"


# ── 2. Engine ↔ service classifier parity ────────────────────────────────────

PARITY_MATRIX = [
    ("71131900", ["71131900"]),                  # exact
    ("71131910", ["71131999"]),                  # HS6
    ("71131900", INCIDENT_HSNS),                 # heading (mixed metals)
    ("71131900", ["71171900"]),                  # chapter only
    ("71131900", ["90031900"]),                  # different chapter
    ("71131900", ["71131913", "90031900"]),      # worst-wins foreign line
    ("71131900", ["7113"]),                      # short heading-level code
]


@pytest.mark.parametrize("sad_cn,hsns", PARITY_MATRIX)
def test_engine_blocking_parity_with_classifier(sad_cn, hsns):
    """cn_match=False in the engine ⇔ is_blocking=True in cn_hsn_classifier.
    The two implementations must stay in lock-step (single CN authority)."""
    v = _verify(sad_cn, hsns)
    c = cn.classify(sad_cn, hsns)
    assert (v["cn_match"] is False) == bool(c["is_blocking"]), (
        f"engine cn_match={v['cn_match']} cn_risk={v['cn_risk_level']} but "
        f"classifier worst_level={c['worst_level']} is_blocking={c['is_blocking']}"
    )
    # Risk-band alignment for the blocking levels
    if c["worst_level"] == "chapter_match":
        assert v["cn_risk_level"] == "medium"
    if c["worst_level"] == "different_chapter":
        assert v["cn_risk_level"] == "high"


def test_classifier_scores_incident_as_nonblocking_accept_with_note():
    c = cn.classify("71131900", INCIDENT_HSNS)
    assert c["worst_level"] == "heading_match"
    assert c["is_blocking"] is False
    assert c["recommendation"] == "accept_with_note"
    assert c["mixed_metals_detected"] is True


# ── 3. Audit persistence (real builder — Lesson A, no stub) ──────────────────

def test_write_audit_persists_invoice_hsn_codes_top_level(tmp_path):
    """The real _write_audit must persist the compared HSN list at the
    top-level audit key that _cn_panel / _record_cn_decision /
    cn_hsn_classifier consumers read — and must NOT regress ver_scalar
    (verification stays scalar-only, no list/dict values)."""
    pdf = tmp_path / "pz.pdf"
    xlsx = tmp_path / "pz.xlsx"
    pdf.write_bytes(b"%PDF-1.4 test")
    xlsx.write_bytes(b"xlsx test")

    verification = eng.verify_sad_invoice_match(
        [{
            "invoice_no": "EJL/26-27/254",
            "cif_usd": 100.0,
            "items": [{"hsn": h} for h in INCIDENT_HSNS],
        }],
        {
            "cn_code": "71131900",
            "invoice_refs": ["EJL/26-27/254"],
            "total_cif_usd": 100.0,
            "mrn": "26PL44302D00E0TEST",
        },
    )

    result = {
        "verification":   verification,
        "corrections_log": [],
        "zc429":          {"mrn": "26PL44302D00E0TEST", "cn_code": "71131900",
                           "duty_pln": 0.0},
        "nbp":            {"usd_rate": 3.64, "table_no": "107/A/NBP/2026"},
        "rows":           [],
        "totals":         {},
        "invoice_totals": {},
        "total_net":      0.0,
        "total_gross":    0.0,
        "duty_pln":       0.0,
        "line_count":     0,
    }

    _write_audit(
        output_dir = tmp_path,
        batch_id   = "SHIPMENT_1234567890_2026-06_cafebabe",
        doc_no     = "PZ TEST/2026",
        result     = result,
        pdf_path   = pdf,
        xlsx_path  = xlsx,
    )

    audit = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))

    # Evidence persisted at the designed fallback key
    assert audit["invoice_hsn_codes"] == INCIDENT_HSNS

    # ver_scalar contract unchanged: verification carries scalars only
    assert "invoice_hsn_codes" not in audit["verification"]
    for val in audit["verification"].values():
        assert not isinstance(val, (list, dict))

    # And the incident outcome end-to-end: heading aggregation must not block
    assert audit["verification"]["cn_match"] is True
    assert audit["verification"]["cn_status"] == "verified_heading_aggregated"
    assert "cn_match" not in audit["failed_checks"]


def test_engine_edge_short_sad_cn_rstrip_fallback():
    """SAD CN '7100': rstrip('0') → '71' (<4 chars) → fallback parent '7100'.
    A strict child verifies under the legacy label."""
    v = _verify("7100", ["71001000"])
    assert v["cn_match"] is True
    assert v["cn_status"] == "verified_parent_aggregated"
    assert v["cn_risk_level"] == "low"


def test_engine_edge_two_digit_sad_cn_is_chapter_level():
    """A chapter-level SAD declaration ('71') vs full HSNs agrees only at
    chapter → soft block at medium, in parity with the classifier."""
    v = _verify("71", ["71131913"])
    assert v["cn_match"] is False
    assert v["cn_risk_level"] == "medium"
    c = cn.classify("71", ["71131913"])
    assert c["worst_level"] == "chapter_match"
    assert c["is_blocking"] is True


def test_engine_edge_integer_hsn_values():
    """Parsers may deliver HSN as int — must normalize, never crash."""
    v = _verify("71131900", [71131913, 71131141])
    assert v["cn_match"] is True
    assert v["cn_status"] == "verified_heading_aggregated"


def test_engine_edge_items_with_and_without_hsn_key():
    """Items lacking 'hsn' are skipped; present codes drive the outcome."""
    invoices = [{
        "invoice_no": "EJL/26-27/254",
        "cif_usd": 100.0,
        "items": [{"hsn": "71131913"}, {"qty": 2}, {"hsn": None}],
    }]
    zc429 = {"cn_code": "71131900", "invoice_refs": ["EJL/26-27/254"],
             "total_cif_usd": 100.0}
    v = eng.verify_sad_invoice_match(invoices, zc429)
    assert v["cn_match"] is True
    assert v["invoice_hsn_codes"] == ["71131913"]


def test_engine_edge_multiple_invoices_aggregate():
    """Codes from ALL invoices participate (the incident had 7 invoices)."""
    invoices = [
        {"invoice_no": "EJL/26-27/254", "cif_usd": 50.0,
         "items": [{"hsn": "71131913"}]},
        {"invoice_no": "EJL/26-27/255", "cif_usd": 50.0,
         "items": [{"hsn": "71131141"}]},
    ]
    zc429 = {"cn_code": "71131900",
             "invoice_refs": ["EJL/26-27/254", "EJL/26-27/255"],
             "total_cif_usd": 100.0}
    v = eng.verify_sad_invoice_match(invoices, zc429)
    assert v["cn_match"] is True
    assert v["cn_status"] == "verified_heading_aggregated"
    assert v["invoice_hsn_codes"] == ["71131913", "71131141"]


def test_engine_edge_dotted_code_formats_label_consistent():
    """Dotted code formats ('7113.19.00') must normalize identically for the
    blocking decision AND the label — raw/normalized divergence was a
    merge-gate finding (label must not downgrade on formatting noise)."""
    v = _verify("7113.19.00", ["7113.19.13", "7113.19.19"])
    assert v["cn_match"] is True
    assert v["cn_status"] == "verified_parent_aggregated"
    assert v["cn_risk_level"] == "low"


def test_engine_edge_letter_noise_never_crashes_or_upgrades():
    """Letter noise inside a code ('71A13913' → digits '7113913') degrades to
    a weaker agreement level at worst — never a crash, never an exception,
    outcome stays within the three-state contract."""
    v = _verify("71131900", ["71A13913"])
    assert v["cn_match"] in (True, False, None)
    assert v["cn_status"] in (
        "verified_parent_aggregated", "verified_heading_aggregated",
        "failed_parent_mismatch", "invoice_hsn_not_parsed",
    )
    # Same heading after normalization → must remain non-blocking
    assert v["cn_match"] is True


def test_invalid_input_asymmetry_engine_none_classifier_review():
    """Documented asymmetry: unparseable codes are reported differently
    (engine: cn_match=None verify-gap; classifier: invalid_input review)
    but BOTH are non-blocking — three-state semantics on each side."""
    v = _verify("71131900", ["N/A"])
    assert v["cn_match"] is None                      # not False — no block
    c = cn.classify("71131900", ["N/A"])
    assert c["worst_level"] == "invalid_input"
    assert c["is_blocking"] is False


def test_source_grep_export_service_persists_hsn_key():
    """Contract pin: a future ver_scalar refactor must not silently re-drop
    the evidence key (the original incident's second root cause)."""
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "services" / "export_service.py"
    ).read_text(encoding="utf-8")
    assert '"invoice_hsn_codes": list(v.get("invoice_hsn_codes") or [])' in src


def test_hardening_caps_heading_aggregation_as_partial():
    """Scoring symmetry: the weaker heading-level aggregation must cap at
    PARTIAL (≤85) exactly like the stricter parent aggregation — it must
    never score ABOVE it."""
    import audit_scoring as sc

    ok = {"result": True}
    c1 = {"result": True, "sad_value_present": True}
    c5 = {"cif_result": True}

    score_heading, _, status_heading = sc._resolve_hardening_status(
        100, c1, ok, c5, ok,
        qty_status=None, cn_status="verified_heading_aggregated",
        nip_source=None,
    )
    score_parent, _, status_parent = sc._resolve_hardening_status(
        100, c1, ok, c5, ok,
        qty_status=None, cn_status="verified_parent_aggregated",
        nip_source=None,
    )
    assert status_heading == status_parent == "PARTIAL"
    assert score_heading == score_parent == 85


def test_write_audit_empty_hsn_list_persists_empty(tmp_path):
    """No HSN evidence → key present and empty (never missing), cn verify-gap."""
    pdf = tmp_path / "pz.pdf"
    xlsx = tmp_path / "pz.xlsx"
    pdf.write_bytes(b"%PDF-1.4 test")
    xlsx.write_bytes(b"xlsx test")

    verification = eng.verify_sad_invoice_match(
        [{"invoice_no": "EJL/26-27/254", "cif_usd": 100.0, "items": []}],
        {"cn_code": "71131900", "invoice_refs": ["EJL/26-27/254"],
         "total_cif_usd": 100.0},
    )
    result = {
        "verification":   verification,
        "corrections_log": [],
        "zc429":          {"mrn": "", "cn_code": "71131900", "duty_pln": 0.0},
        "nbp":            {},
        "rows":           [],
        "totals":         {},
        "invoice_totals": {},
        "total_net":      0.0,
        "total_gross":    0.0,
        "duty_pln":       0.0,
        "line_count":     0,
    }
    _write_audit(
        output_dir = tmp_path,
        batch_id   = "SHIPMENT_1234567890_2026-06_cafebabe",
        doc_no     = "PZ TEST/2026",
        result     = result,
        pdf_path   = pdf,
        xlsx_path  = xlsx,
    )
    audit = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    assert audit["invoice_hsn_codes"] == []
    assert audit["verification"]["cn_match"] is None
    assert "cn_match" not in audit["failed_checks"]
