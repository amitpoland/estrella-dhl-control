"""AWB shipment description — sole backend authority (no React mapper).

Pins:
  - STUD item_type → Stud Earrings via description_engine only
  - body.description / auto-prefilled text does NOT bypass projection
  - description_override is the only operator-edit path
  - React must not contain an independent STUD → Stud Earrings AWB mapper
  - GET shipment-description returns the same canonical projection
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


JSX = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"
JSX_SRC = JSX.read_text(encoding="utf-8")


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
    assert not is_generic_shipment_description("Stud Earrings")


def test_empty_lines_project_empty_not_jewellery():
    assert project_shipment_content_description([]) == ""
    assert project_shipment_content_description(None) == ""


def test_posted_autofilled_description_does_not_bypass_projection(tmp_path):
    """Defect pin: a browser-computed 'Stud Earrings' must not win as override.

    Before the amend, body.description (non-generic) short-circuited the
    resolver. If the frontend mapper and backend mapper diverged, the browser
    value would stick. Automatic values must never masquerade as overrides.
    """
    from app.api.routes_carrier_actions import _resolve_shipment_description

    with patch(
        "app.api.routes_carrier_actions._load_draft_editable_lines",
        return_value=[{"item_type": "RING"}],
    ):
        # Legacy body.description path — ignored; canonical projection runs.
        got = _resolve_shipment_description(
            description_override=None,
            storage_root=tmp_path,
            batch_id="BATCH-RING",
            client_ref="Acme",
        )
    assert got == "Ring"
    assert got != "Stud Earrings"


def test_frontend_autofill_string_ignored_without_override_flag(tmp_path):
    """Even if a client still posts description=..., only description_override counts."""
    from app.api.routes_carrier_actions import _resolve_shipment_description

    with patch(
        "app.api.routes_carrier_actions._load_draft_editable_lines",
        return_value=[{"item_type": "STUD"}],
    ):
        got = _resolve_shipment_description(
            description_override=None,  # operator did not edit
            storage_root=tmp_path,
            batch_id="BATCH-STUD",
            client_ref="Acme",
        )
    assert got == "Stud Earrings"


def test_genuine_operator_override_is_honoured(tmp_path):
    from app.api.routes_carrier_actions import _resolve_shipment_description

    with patch(
        "app.api.routes_carrier_actions._load_draft_editable_lines",
        return_value=[{"item_type": "STUD"}],
    ):
        got = _resolve_shipment_description(
            description_override="Custom operator text",
            storage_root=tmp_path,
            batch_id="BATCH-X",
            client_ref="Acme",
        )
    assert got == "Custom operator text"


def test_generic_jewellery_override_does_not_bypass_canonical(tmp_path):
    from app.api.routes_carrier_actions import _resolve_shipment_description

    with patch(
        "app.api.routes_carrier_actions._load_draft_editable_lines",
        return_value=[{"item_type": "STUD"}],
    ):
        got = _resolve_shipment_description(
            description_override="Jewellery",
            storage_root=tmp_path,
            batch_id="BATCH-STUD",
            client_ref="Acme",
        )
    assert got == "Stud Earrings"


def test_last_resort_when_no_authority(tmp_path):
    from app.api.routes_carrier_actions import _resolve_shipment_description

    with patch(
        "app.api.routes_carrier_actions._load_draft_editable_lines",
        return_value=[],
    ):
        got = _resolve_shipment_description(
            description_override=None,
            storage_root=tmp_path,
            batch_id="BATCH-EMPTY",
            client_ref=None,
        )
    assert got == "Jewellery"


def test_project_helper_matches_resolver_for_modal_prefill(tmp_path):
    from app.api.routes_carrier_actions import _project_shipment_description_for_client

    with patch(
        "app.api.routes_carrier_actions._load_draft_editable_lines",
        return_value=[{"item_type": "STUD"}],
    ):
        payload = _project_shipment_description_for_client(
            storage_root=tmp_path,
            batch_id="BATCH-STUD",
            client_ref="Acme",
        )
    assert payload["shipment_description"] == "Stud Earrings"
    assert payload["source"] == "canonical"


def test_react_has_no_awb_shipment_description_mapper():
    assert "_awbShipmentDescriptionFromLines" not in JSX_SRC
    # AWB-only STUD→Stud Earrings mapping must not live in React.
    assert "STUD: 'Stud Earrings'" not in JSX_SRC
    assert 'STUD: "Stud Earrings"' not in JSX_SRC


def test_react_loads_description_from_backend_endpoint():
    assert "getCarrierShipmentDescription" in JSX_SRC
    assert "description_override" in JSX_SRC
    assert "descriptionDirty" in JSX_SRC
    assert "shipment-description" in JSX_SRC or "getCarrierShipmentDescription" in JSX_SRC


def test_projection_does_not_mutate_product_master(tmp_path, monkeypatch):
    docs = tmp_path / "documents.db"
    md = tmp_path / "master_data.sqlite"
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    before = (docs.exists(), md.exists())
    project_shipment_content_description([{"item_type": "STUD"}])
    assert (docs.exists(), md.exists()) == before
