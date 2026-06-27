"""test_proforma_intelligence.py — Phase 6 AI intelligence service unit tests.

Coverage:
  - detect_line_anomalies: zero price, negative price, missing HS, missing names
  - detect_line_anomalies: price outlier detection with corpus
  - detect_line_anomalies: line with no product_code → ANOMALY_MISSING_PC
  - detect_line_anomalies: clean line → no anomalies
  - infer_missing_fields: no master_db → empty suggestions
  - infer_missing_fields: language policy — name_sk never surfaced
  - build_corpus_stats: non-existent db → empty corpus
  - build_corpus_stats: posted-only rows included; draft rows excluded
  - score_draft_confidence: all-filled → high score
  - score_draft_confidence: no company profile → 0.0 company sub-score
  - score_draft_confidence: no lines → 0.0 lines sub-score
  - company_profile_completeness: None profile → present=False, score=0.0
  - company_profile_completeness: full profile → score near 1.0
  - company_profile_completeness: missing mandatory fields flagged
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.services.proforma_intelligence import (
    ANOMALY_MISSING_HS,
    ANOMALY_MISSING_NAME_EN,
    ANOMALY_MISSING_PC,
    ANOMALY_NEGATIVE_PRICE,
    ANOMALY_PRICE_OUTLIER,
    ANOMALY_ZERO_PRICE,
    CorpusStats,
    DraftConfidence,
    FieldSuggestion,
    LineAnomaly,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    build_corpus_stats,
    company_profile_completeness,
    detect_line_anomalies,
    infer_missing_fields,
    score_draft_confidence,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_line(**kw) -> Dict[str, Any]:
    defaults = {
        "line_id":      "L1",
        "product_code": "P001",
        "unit_price":   100.0,
        "hs_code":      "7113191000",
        "name_pl":      "Pierścień srebrny",
        "name_en":      "Silver ring",
        "qty":          1,
    }
    defaults.update(kw)
    return defaults


class _FakeProfile:
    """Minimal object mimicking CompanyProfile."""
    def __init__(self, **fields):
        defaults = {
            "legal_name": "Estrella Jewels Sp. z o.o.",
            "nip":        "1234567890",
            "country":    "PL",
            "iban_eur":   "PL00000000000000000000000001",
            "swift":      "BPKOPLPW",
            "street":     "ul. Złota 1",
            "postal_city": "00-001 Warszawa",
            "email":      "info@estrellajewels.eu",
            "bank_name":  "PKO BP",
            "place_of_issue": "Warszawa",
            "signatory_name": "Amit Gupta",
        }
        defaults.update(fields)
        for k, v in defaults.items():
            setattr(self, k, v)


# ── detect_line_anomalies ─────────────────────────────────────────────────────

def test_no_anomalies_for_clean_line():
    lines = [_make_line()]
    result = detect_line_anomalies(lines)
    assert result == []


def test_zero_price_flagged():
    lines = [_make_line(unit_price=0)]
    result = detect_line_anomalies(lines)
    types = [a.anomaly_type for a in result]
    assert ANOMALY_ZERO_PRICE in types
    zero = next(a for a in result if a.anomaly_type == ANOMALY_ZERO_PRICE)
    assert zero.severity == SEVERITY_HIGH
    assert zero.confidence == 1.0


def test_negative_price_flagged():
    lines = [_make_line(unit_price=-5.0)]
    result = detect_line_anomalies(lines)
    types = [a.anomaly_type for a in result]
    assert ANOMALY_NEGATIVE_PRICE in types
    neg = next(a for a in result if a.anomaly_type == ANOMALY_NEGATIVE_PRICE)
    assert neg.severity == SEVERITY_HIGH


def test_missing_hs_code_flagged():
    lines = [_make_line(hs_code="", hsn_code="")]
    result = detect_line_anomalies(lines)
    types = [a.anomaly_type for a in result]
    assert ANOMALY_MISSING_HS in types
    hs_a = next(a for a in result if a.anomaly_type == ANOMALY_MISSING_HS)
    assert hs_a.severity == SEVERITY_MEDIUM


def test_missing_name_en_flagged():
    lines = [_make_line(name_en="")]
    result = detect_line_anomalies(lines)
    types = [a.anomaly_type for a in result]
    assert ANOMALY_MISSING_NAME_EN in types
    en_a = next(a for a in result if a.anomaly_type == ANOMALY_MISSING_NAME_EN)
    assert en_a.severity == SEVERITY_LOW


def test_missing_product_code_flagged_and_stops_other_checks():
    lines = [_make_line(product_code="")]
    result = detect_line_anomalies(lines)
    types = [a.anomaly_type for a in result]
    assert ANOMALY_MISSING_PC in types
    # When product_code is absent we `continue` — no price/hs checks
    assert ANOMALY_ZERO_PRICE not in types


def test_price_outlier_with_corpus():
    corpus = CorpusStats(product_avg_price={"P001": 10.0})
    # 3× threshold, price = 35 → ratio 3.5
    lines = [_make_line(unit_price=35.0)]
    result = detect_line_anomalies(lines, corpus=corpus, price_outlier_threshold=3.0)
    types = [a.anomaly_type for a in result]
    assert ANOMALY_PRICE_OUTLIER in types
    outlier = next(a for a in result if a.anomaly_type == ANOMALY_PRICE_OUTLIER)
    assert outlier.severity == SEVERITY_MEDIUM
    assert outlier.confidence == 0.75


def test_no_price_outlier_below_threshold():
    corpus = CorpusStats(product_avg_price={"P001": 10.0})
    lines = [_make_line(unit_price=25.0)]  # ratio 2.5 < 3.0
    result = detect_line_anomalies(lines, corpus=corpus, price_outlier_threshold=3.0)
    types = [a.anomaly_type for a in result]
    assert ANOMALY_PRICE_OUTLIER not in types


def test_anomalies_for_multiple_lines():
    lines = [
        _make_line(product_code="A", unit_price=0),
        _make_line(product_code="B", hs_code=""),
    ]
    result = detect_line_anomalies(lines)
    zero_a = [a for a in result if a.anomaly_type == ANOMALY_ZERO_PRICE]
    hs_a   = [a for a in result if a.anomaly_type == ANOMALY_MISSING_HS]
    assert zero_a
    assert hs_a


# ── infer_missing_fields ──────────────────────────────────────────────────────

def test_infer_no_suggestions_when_no_master_db(tmp_path):
    """No master_db_path → empty suggestions (no crash)."""
    import app.services.document_db as _ddb_mod
    orig = _ddb_mod._db_path
    _ddb_mod._db_path = None
    try:
        lines = [_make_line(hs_code="", name_pl="")]
        result = infer_missing_fields(lines, master_db_path=None)
    finally:
        _ddb_mod._db_path = orig
    assert result == []


def test_infer_hs_from_product_local(tmp_path):
    from app.services.master_data_db import init_db, upsert_product_local
    db = tmp_path / "master.db"
    init_db(db)
    upsert_product_local(db, {"product_code": "P001", "hs_code_override": "7113191000"})

    import app.services.document_db as _ddb_mod
    orig = _ddb_mod._db_path
    _ddb_mod._db_path = None
    try:
        lines = [_make_line(hs_code="")]  # missing HS
        result = infer_missing_fields(lines, master_db_path=db)
    finally:
        _ddb_mod._db_path = orig

    hs_suggestions = [s for s in result if s.field == "hs_code"]
    assert hs_suggestions, "Expected HS code suggestion"
    assert hs_suggestions[0].suggested_value == "7113191000"
    assert hs_suggestions[0].source == "product_local.hs_code_override"


def test_infer_does_not_overwrite_existing_hs(tmp_path):
    """If line already has hs_code, no suggestion is produced."""
    from app.services.master_data_db import init_db, upsert_product_local
    db = tmp_path / "master.db"
    init_db(db)
    upsert_product_local(db, {"product_code": "P001", "hs_code_override": "9999"})

    import app.services.document_db as _ddb_mod
    orig = _ddb_mod._db_path
    _ddb_mod._db_path = None
    try:
        lines = [_make_line(hs_code="7113191000")]  # already has HS
        result = infer_missing_fields(lines, master_db_path=db)
    finally:
        _ddb_mod._db_path = orig

    hs_suggestions = [s for s in result if s.field == "hs_code"]
    assert hs_suggestions == [], "Should not suggest HS when already present"


def test_infer_language_policy_no_name_sk(tmp_path):
    """name_sk must NEVER appear in suggestions (language policy: PL+EN only)."""
    from app.services.master_data_db import init_db, upsert_product_local
    db = tmp_path / "master.db"
    init_db(db)
    upsert_product_local(db, {"product_code": "P001"})

    import app.services.document_db as _ddb_mod
    orig = _ddb_mod._db_path
    _ddb_mod._db_path = None
    try:
        lines = [_make_line(name_pl="", name_en="")]
        result = infer_missing_fields(lines, master_db_path=db)
    finally:
        _ddb_mod._db_path = orig

    sk_fields = [s for s in result if s.field == "name_sk"]
    assert sk_fields == [], "name_sk must never be suggested (language policy)"


def test_infer_empty_lines():
    result = infer_missing_fields([], master_db_path=None)
    assert result == []


# ── build_corpus_stats ────────────────────────────────────────────────────────

def test_build_corpus_stats_nonexistent_db(tmp_path):
    stats = build_corpus_stats(tmp_path / "no_such.db")
    assert stats.corpus_size == 0
    assert stats.product_avg_price == {}
    assert stats.product_hs_codes == {}


def test_build_corpus_stats_posted_only(tmp_path):
    """Only drafts with draft_state='posted' contribute to corpus."""
    from app.services.proforma_invoice_link_db import init_db as pil_init
    db = tmp_path / "p.db"
    pil_init(db)

    with sqlite3.connect(str(db)) as conn:
        now = "2026-01-01T00:00:00"
        # posted draft — must be included
        conn.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, draft_state, editable_lines_json, "
            " created_at, updated_at) "
            "VALUES (?, ?, 'issued', 'posted', ?, ?, ?)",
            (
                "B001", "ClientA",
                json.dumps([{"product_code": "P001", "unit_price": 50.0,
                             "hs_code": "7113", "qty": 1}]),
                now, now,
            ),
        )
        # draft state — must NOT be included
        conn.execute(
            "INSERT INTO proforma_drafts "
            "(batch_id, client_name, status, draft_state, editable_lines_json, "
            " created_at, updated_at) "
            "VALUES (?, ?, 'pending_local', 'draft', ?, ?, ?)",
            (
                "B002", "ClientB",
                json.dumps([{"product_code": "P002", "unit_price": 999.0,
                             "hs_code": "9999", "qty": 1}]),
                now, now,
            ),
        )
        conn.commit()

    stats = build_corpus_stats(db)
    assert stats.corpus_size == 1
    assert "P001" in stats.product_avg_price
    assert abs(stats.product_avg_price["P001"] - 50.0) < 0.001
    assert "P002" not in stats.product_avg_price


def test_build_corpus_stats_average_price(tmp_path):
    from app.services.proforma_invoice_link_db import init_db as pil_init
    db = tmp_path / "p.db"
    pil_init(db)

    with sqlite3.connect(str(db)) as conn:
        now = "2026-01-01T00:00:00"
        for i, price in enumerate([100.0, 200.0]):
            conn.execute(
                "INSERT INTO proforma_drafts "
                "(batch_id, client_name, status, draft_state, editable_lines_json, "
                " created_at, updated_at) VALUES (?, ?, 'issued', 'posted', ?, ?, ?)",
                (f"B{i}", "C",
                 json.dumps([{"product_code": "P001", "unit_price": price,
                              "hs_code": "7113", "qty": 1}]),
                 now, now),
            )
        conn.commit()

    stats = build_corpus_stats(db)
    assert stats.corpus_size == 2
    assert abs(stats.product_avg_price["P001"] - 150.0) < 0.001


# ── score_draft_confidence ────────────────────────────────────────────────────

def test_confidence_full_profile_and_good_lines():
    lines = [_make_line()]  # all fields populated
    conf = score_draft_confidence(
        lines=lines,
        company_profile_present=True,
        company_profile_fields_filled=11,
        company_profile_fields_total=11,
        has_shipment_awb=True,
    )
    assert conf.overall > 0.9
    assert conf.company == 1.0
    assert conf.lines == 1.0
    assert conf.shipment == 1.0


def test_confidence_no_company_profile():
    lines = [_make_line()]
    conf = score_draft_confidence(
        lines=lines,
        company_profile_present=False,
        company_profile_fields_filled=0,
        company_profile_fields_total=11,
        has_shipment_awb=True,
    )
    assert conf.company == 0.0
    assert conf.overall < 0.8  # penalised


def test_confidence_no_lines():
    conf = score_draft_confidence(
        lines=[],
        company_profile_present=True,
        company_profile_fields_filled=11,
        company_profile_fields_total=11,
        has_shipment_awb=True,
    )
    assert conf.lines == 0.0


def test_confidence_no_awb():
    lines = [_make_line()]
    conf = score_draft_confidence(
        lines=lines,
        company_profile_present=True,
        company_profile_fields_filled=11,
        company_profile_fields_total=11,
        has_shipment_awb=False,
    )
    assert conf.shipment == 0.3


def test_confidence_partial_lines():
    lines = [
        _make_line(product_code="A", unit_price=100, hs_code="7113", name_pl="ok"),
        _make_line(product_code="B", unit_price=0),   # zero price → not OK
    ]
    conf = score_draft_confidence(
        lines=lines,
        company_profile_present=True,
        company_profile_fields_filled=11,
        company_profile_fields_total=11,
        has_shipment_awb=True,
    )
    assert 0.0 < conf.lines < 1.0


def test_confidence_returns_dataclass():
    conf = score_draft_confidence(
        lines=[_make_line()],
        company_profile_present=True,
        company_profile_fields_filled=5,
        company_profile_fields_total=11,
        has_shipment_awb=False,
    )
    assert isinstance(conf, DraftConfidence)
    assert 0.0 <= conf.overall <= 1.0


# ── company_profile_completeness ──────────────────────────────────────────────

def test_completeness_none_profile():
    result = company_profile_completeness(None)
    assert result["present"] is False
    assert result["score"] == 0.0
    assert result["missing_mandatory"]
    assert result["missing_recommended"] == []


def test_completeness_full_profile():
    profile = _FakeProfile()
    result = company_profile_completeness(profile)
    assert result["present"] is True
    assert result["score"] == 1.0
    assert result["missing_mandatory"] == []
    assert result["missing_recommended"] == []


def test_completeness_missing_mandatory_iban():
    profile = _FakeProfile(iban_eur="")
    result = company_profile_completeness(profile)
    assert "iban_eur" in result["missing_mandatory"]
    assert result["score"] < 1.0


def test_completeness_missing_recommended_email():
    profile = _FakeProfile(email="")
    result = company_profile_completeness(profile)
    assert "email" in result["missing_recommended"]
    # mandatory fields all present → no mandatory missing
    assert result["missing_mandatory"] == []


def test_completeness_fields_dict_structure():
    profile = _FakeProfile()
    result = company_profile_completeness(profile)
    assert isinstance(result["fields"], dict)
    assert "legal_name" in result["fields"]
    assert "iban_eur"   in result["fields"]
    assert result["fields"]["legal_name"] is True
