"""AWB shipment description — canonical description authority (not Jewellery).

Pins:
  - STUD item_type → Stud Earrings via description_engine projection
  - generic Jewellery/Jewelry body values yield to draft projection
  - explicit non-generic operator override is preserved
  - empty draft → last-resort Jewellery only (DHL non-empty contract)
  - no Product Master mutation
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.description_engine import (
    is_generic_shipment_description,
    project_shipment_content_description,
    _english_description_from_item_type,
)


def test_stud_item_type_projects_stud_earrings_noun():
    assert _english_description_from_item_type("STUD") == "Stud Earrings"
    assert project_shipment_content_description(
        [{"item_type": "STUD", "product_code": "EJL/26-27/1-1"}]
    ) == "Stud Earrings"


def test_mixed_item_types_unique_nouns():
    out = project_shipment_content_description([
        {"item_type": "STUD"},
        {"item_type": "STUD"},
        {"item_type": "RING"},
    ])
    assert out == "Stud Earrings, Ring"


def test_jewellery_generic_detected():
    assert is_generic_shipment_description("Jewellery")
    assert is_generic_shipment_description("Jewelry")
    assert is_generic_shipment_description("")
    assert is_generic_shipment_description(None)
    assert not is_generic_shipment_description("Stud Earrings")
    assert not is_generic_shipment_description("Gold rings")


def test_empty_lines_project_empty_not_jewellery():
    assert project_shipment_content_description([]) == ""
    assert project_shipment_content_description(None) == ""
    assert "Jewellery" not in project_shipment_content_description(
        [{"item_type": ""}]
    )


def test_description_en_fallback_when_item_type_missing():
    out = project_shipment_content_description([
        {"description_en": "Diamond 14KT Gold Stud Earrings"},
    ])
    assert out == "Diamond 14KT Gold Stud Earrings"


def test_resolve_shipment_description_uses_projection_over_jewellery(tmp_path):
    from app.api.routes_carrier_actions import _resolve_shipment_description

    with patch(
        "app.api.routes_carrier_actions._load_draft_editable_lines",
        return_value=[{"item_type": "STUD"}],
    ):
        got = _resolve_shipment_description(
            body_description="Jewellery",
            storage_root=tmp_path,
            batch_id="BATCH-STUD",
            client_ref="Acme",
        )
    assert got == "Stud Earrings"


def test_resolve_shipment_description_keeps_operator_override(tmp_path):
    from app.api.routes_carrier_actions import _resolve_shipment_description

    with patch(
        "app.api.routes_carrier_actions._load_draft_editable_lines",
        return_value=[{"item_type": "STUD"}],
    ):
        got = _resolve_shipment_description(
            body_description="Custom operator text",
            storage_root=tmp_path,
            batch_id="BATCH-X",
            client_ref="Acme",
        )
    assert got == "Custom operator text"


def test_resolve_shipment_description_last_resort_when_no_authority(tmp_path):
    from app.api.routes_carrier_actions import _resolve_shipment_description

    with patch(
        "app.api.routes_carrier_actions._load_draft_editable_lines",
        return_value=[],
    ):
        got = _resolve_shipment_description(
            body_description=None,
            storage_root=tmp_path,
            batch_id="BATCH-EMPTY",
            client_ref=None,
        )
    assert got == "Jewellery"


def test_projection_does_not_mutate_product_master(tmp_path, monkeypatch):
    """Read-only projection — no writes into master_data / documents DBs."""
    docs = tmp_path / "documents.db"
    md = tmp_path / "master_data.sqlite"
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    before = (docs.exists(), md.exists())
    project_shipment_content_description([{"item_type": "STUD"}])
    assert (docs.exists(), md.exists()) == before
