"""Short CMR document number — ADR-proforma-cmr-short-number (2026-07-16).

Pins format, determinism, rebook-stability, honest-missing, and collision
resistance across a large synthetic sha256 sample.
"""
from __future__ import annotations

import hashlib

from app.services.carrier.cmr_number import cmr_document_number, short_export_id


def test_format_matches_operator_example():
    # The referenced production idempotency_key prefix → CMR-EJ-92BD984DBD.
    export_id = "92bd984dbdb70c24f5c1bbe5440a7f4bb19253da303974a7ab6045f9e92fc1ae"
    assert cmr_document_number(export_id) == "CMR-EJ-92BD984DBD"
    assert short_export_id(export_id) == "92BD984DBD"


def test_deterministic_and_rebook_stable():
    export_id = hashlib.sha256(b"same-shipment").hexdigest()
    assert cmr_document_number(export_id) == cmr_document_number(export_id)


def test_independent_of_awb():
    # The number derives only from export_shipment_id; an AWB is not an input.
    a = cmr_document_number(hashlib.sha256(b"ship-1").hexdigest())
    b = cmr_document_number(hashlib.sha256(b"ship-2").hexdigest())
    assert a != b  # different shipments → different numbers


def test_honest_missing():
    assert cmr_document_number(None) is None
    assert cmr_document_number("") is None
    assert cmr_document_number("   ") is None
    assert short_export_id(None) is None


def test_no_collisions_over_large_sample():
    """40-bit prefix — zero collisions across 20k synthetic sha256 ids."""
    numbers = {
        cmr_document_number(hashlib.sha256(f"shipment-{i}".encode()).hexdigest())
        for i in range(20_000)
    }
    assert len(numbers) == 20_000


def test_prefix_and_length():
    n = cmr_document_number(hashlib.sha256(b"x").hexdigest())
    assert n.startswith("CMR-EJ-")
    assert len(n) == len("CMR-EJ-") + 10
