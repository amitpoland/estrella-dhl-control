"""Fixture-driven regression for SAD invoice-reference authority (2026-05-22).

Companion to ``test_sad_invoice_authority.py``. Where that file pins behaviour
with hand-constructed dicts, this file loads real-shaped ``audit.json`` files
from ``service/tests/fixtures/sad_authority/`` so the authority function is
exercised against the full dict shape a production ZC429 ingest produces — not
a hand-stripped minimum.

The fixtures use synthetic batch / AWB / MRN / LRN identifiers. No production
contractor or customs identifier is committed.

Coverage (one fixture per branch of ``derive_sad_invoice_authority``):

    n935_match.json          → matched_structured_n935
    n935_absent.json         → n935_absent
    inferred_free_text.json  → unverified_no_structured_reference (advisory)
    n935_mismatch.json       → n935_present_mismatch
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services.sad_invoice_authority import derive_sad_invoice_authority

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sad_authority"


def _load(name: str) -> Dict[str, Any]:
    path = FIXTURE_DIR / f"{name}.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ── Per-fixture authority assertions ─────────────────────────────────────────

def test_fixture_dir_exists_and_holds_four_fixtures():
    assert FIXTURE_DIR.is_dir(), f"Fixture dir missing: {FIXTURE_DIR}"
    names = sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))
    assert names == sorted([
        "inferred_free_text",
        "n935_absent",
        "n935_match",
        "n935_mismatch",
    ]), f"Unexpected fixture set: {names}"


def test_n935_match_fixture_yields_matched_structured_n935():
    audit = _load("n935_match")
    r = derive_sad_invoice_authority(audit)
    assert r["status"] == "matched_structured_n935"
    assert r["source"] == "n935"
    assert r["references"] == ["EJL/26-27/039"]
    assert r["matched_invoice_ids"] == ["039"]
    assert r["warning"] is None
    assert r["review_reason"] is None


def test_n935_absent_fixture_yields_n935_absent():
    audit = _load("n935_absent")
    r = derive_sad_invoice_authority(audit)
    assert r["status"] == "n935_absent"
    assert r["source"] == "none"
    assert r["references"] == []
    assert r["matched_invoice_ids"] == []
    assert r["warning"] is None
    assert r["review_reason"] is not None and "N935" in r["review_reason"]


def test_inferred_free_text_fixture_yields_advisory_text_no_refs():
    audit = _load("inferred_free_text")
    r = derive_sad_invoice_authority(audit)
    assert r["status"] == "unverified_no_structured_reference"
    assert r["source"] == "advisory_text"
    assert r["references"] == [], (
        "Free-text inferred_refs must never enter authority.references"
    )
    assert r["matched_invoice_ids"] == []
    assert r["warning"] is None
    assert r["review_reason"] is not None


def test_n935_mismatch_fixture_yields_present_mismatch():
    audit = _load("n935_mismatch")
    r = derive_sad_invoice_authority(audit)
    assert r["status"] == "n935_present_mismatch"
    assert r["source"] == "n935"
    assert r["references"] == ["EJL/26-27/039"]
    assert r["matched_invoice_ids"] == ["040"]
    assert r["warning"] is not None
    assert r["review_reason"] is not None


# ── Cross-fixture invariants ─────────────────────────────────────────────────

def test_noise_tokens_never_surface_in_any_fixture_references():
    """Garbage tokens from inferred_refs must NEVER appear in any fixture's
    authority.references output. Inferred refs in the audit are advisory."""
    noise = {"3322", "121", "088", "2026", "2027", "585"}
    for fixture_name in ["n935_match", "n935_absent",
                         "inferred_free_text", "n935_mismatch"]:
        audit = _load(fixture_name)
        r = derive_sad_invoice_authority(audit)
        for ref in r["references"]:
            assert ref not in noise, (
                f"Noise token '{ref}' leaked into "
                f"{fixture_name}.authority.references"
            )


def test_intact_invoice_ids_never_split_across_fixtures():
    """An N935 reference like 'EJL/26-27/039' must stay intact — never split
    into ['EJL', '26', '27', '039'] across any fixture's output."""
    split_parts = {"EJL", "26", "27", "26-27", "039"}
    for fixture_name in ["n935_match", "n935_mismatch"]:
        audit = _load(fixture_name)
        r = derive_sad_invoice_authority(audit)
        for ref in r["references"]:
            assert ref not in split_parts, (
                f"Split component '{ref}' surfaced in "
                f"{fixture_name}.authority.references — invoice IDs must "
                f"remain intact"
            )


def test_all_fixtures_carry_real_shape_top_level_keys():
    """Every fixture must carry the top-level identity keys a real audit
    carries, so the authority function is exercised against a realistic
    dict, not a hand-stripped minimum."""
    required = {"batch_id", "shipment_id", "awb", "invoice_names",
                "clearance_status", "zc429", "verification"}
    for fixture_name in ["n935_match", "n935_absent",
                         "inferred_free_text", "n935_mismatch"]:
        audit = _load(fixture_name)
        missing = required - set(audit.keys())
        assert not missing, (
            f"{fixture_name}.json missing real-shape keys: {missing}"
        )


def test_fixture_batch_ids_are_synthetic_not_real():
    """Sanity guard: no fixture may commit a real production batch_id.
    Real batch_ids begin with an AWB; synthetic fixtures must use the
    TEST prefix in their AWB-position segment."""
    for fixture_name in ["n935_match", "n935_absent",
                         "inferred_free_text", "n935_mismatch"]:
        audit = _load(fixture_name)
        bid = audit.get("batch_id", "")
        assert "TEST" in bid, (
            f"{fixture_name}.json batch_id '{bid}' is not synthetic — "
            f"every fixture must use a TEST-prefixed batch_id"
        )


def test_all_zc429_blocks_carry_parser_neighbours():
    """The zc429 block must include realistic neighbour keys (mrn, lrn,
    cn_code, _parse_meta) — not just the three fields the authority reads.
    This protects against accidentally trimming fixtures to a synthetic
    minimum that would mask shape regressions."""
    neighbour_keys = {"mrn", "lrn", "cn_code", "goods_description",
                      "_parse_meta", "transport_refs"}
    for fixture_name in ["n935_match", "n935_absent",
                         "inferred_free_text", "n935_mismatch"]:
        audit = _load(fixture_name)
        zc = audit.get("zc429") or {}
        missing = neighbour_keys - set(zc.keys())
        assert not missing, (
            f"{fixture_name}.json zc429 missing parser-neighbour keys: "
            f"{missing}"
        )


# ── Parametrised contract sweep ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "fixture_name,expected_status,expected_source",
    [
        ("n935_match",         "matched_structured_n935",            "n935"),
        ("n935_absent",        "n935_absent",                        "none"),
        ("inferred_free_text", "unverified_no_structured_reference", "advisory_text"),
        ("n935_mismatch",      "n935_present_mismatch",              "n935"),
    ],
)
def test_authority_status_and_source_per_fixture(fixture_name,
                                                  expected_status,
                                                  expected_source):
    r = derive_sad_invoice_authority(_load(fixture_name))
    assert r["status"] == expected_status, (
        f"{fixture_name}.json expected status={expected_status}, "
        f"got status={r['status']}"
    )
    assert r["source"] == expected_source, (
        f"{fixture_name}.json expected source={expected_source}, "
        f"got source={r['source']}"
    )
