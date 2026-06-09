"""test_timeline_events.py — Timeline event constant and route emission tests.

Covers:
- EV_COLUMN_MAPPING_LLM_REQUESTED constant exists and is a valid string
- Route emits the constant (not a freeform string)
- Payload shape: advisory_only, write_scope, llm_fallback required fields
- No business mutation event emitted from suggest_column_mapping handler
- AI Bridge filter includes column_mapping_llm_requested
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Paths ────────────────────────────────────────────────────────────────────

_TIMELINE_PY    = Path(__file__).resolve().parents[1] / "app" / "core" / "timeline.py"
_ROUTES_PACKING = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_packing.py"
_SD             = Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html"


# ── Constant existence and value ─────────────────────────────────────────────

def test_ev_column_mapping_llm_requested_constant_exists():
    """timeline.py must export EV_COLUMN_MAPPING_LLM_REQUESTED."""
    from app.core import timeline as tl
    assert hasattr(tl, "EV_COLUMN_MAPPING_LLM_REQUESTED"), (
        "timeline must define EV_COLUMN_MAPPING_LLM_REQUESTED"
    )


def test_ev_column_mapping_llm_requested_value():
    """Constant value must be the canonical snake_case event string."""
    from app.core import timeline as tl
    assert tl.EV_COLUMN_MAPPING_LLM_REQUESTED == "column_mapping_llm_requested", (
        "EV_COLUMN_MAPPING_LLM_REQUESTED must equal 'column_mapping_llm_requested'"
    )


def test_ev_column_mapping_llm_requested_is_string():
    from app.core import timeline as tl
    assert isinstance(tl.EV_COLUMN_MAPPING_LLM_REQUESTED, str)
    assert len(tl.EV_COLUMN_MAPPING_LLM_REQUESTED) > 0


# ── Route uses constant, not freeform string ─────────────────────────────────

def test_route_uses_tl_constant_not_freeform_string():
    """suggest_column_mapping must emit tl.EV_COLUMN_MAPPING_LLM_REQUESTED,
    not the bare uppercase string 'COLUMN_MAPPING_LLM_REQUESTED'."""
    src = _ROUTES_PACKING.read_text(encoding="utf-8")
    # Constant reference must be present.
    assert "tl.EV_COLUMN_MAPPING_LLM_REQUESTED" in src, (
        "routes_packing.py must use tl.EV_COLUMN_MAPPING_LLM_REQUESTED"
    )
    # Freeform uppercase string must NOT be present.
    assert '"COLUMN_MAPPING_LLM_REQUESTED"' not in src, (
        "routes_packing.py must not use the bare string 'COLUMN_MAPPING_LLM_REQUESTED'"
    )


# ── Payload fields ────────────────────────────────────────────────────────────

def test_route_payload_includes_advisory_only():
    """Event detail must include advisory_only: True."""
    src = _ROUTES_PACKING.read_text(encoding="utf-8")
    # Locate the suggest_column_mapping tl.log_event block.
    start = src.find("tl.EV_COLUMN_MAPPING_LLM_REQUESTED")
    assert start != -1
    block = src[start: start + 600]
    assert '"advisory_only"' in block or "'advisory_only'" in block, (
        "Event payload must include advisory_only field"
    )
    assert "True" in block, "advisory_only must be True"


def test_route_payload_includes_write_scope():
    """Event detail must declare write_scope to make audit explicit."""
    src = _ROUTES_PACKING.read_text(encoding="utf-8")
    start = src.find("tl.EV_COLUMN_MAPPING_LLM_REQUESTED")
    block = src[start: start + 600]
    assert "write_scope" in block, (
        "Event payload must include write_scope"
    )
    assert "parser_diagnostic_json_only" in block, (
        "write_scope must be 'parser_diagnostic_json_only'"
    )


def test_route_payload_includes_llm_fallback():
    """Event detail must include llm_fallback: True so the audit is self-describing."""
    src = _ROUTES_PACKING.read_text(encoding="utf-8")
    start = src.find("tl.EV_COLUMN_MAPPING_LLM_REQUESTED")
    block = src[start: start + 600]
    assert "llm_fallback" in block, (
        "Event payload must include llm_fallback field"
    )


def test_route_payload_includes_document_id_and_file_name():
    """Payload must carry document_id and file_name for traceability."""
    src = _ROUTES_PACKING.read_text(encoding="utf-8")
    start = src.find("tl.EV_COLUMN_MAPPING_LLM_REQUESTED")
    block = src[start: start + 600]
    assert "document_id" in block
    assert "file_name" in block


# ── No business mutation events ───────────────────────────────────────────────

def test_suggest_handler_emits_no_business_mutation_events():
    """suggest_column_mapping must not emit PZ/wFirma/invoice/product events."""
    src = _ROUTES_PACKING.read_text(encoding="utf-8")
    start = src.find("async def suggest_column_mapping(")
    assert start != -1
    # Take a generous window for the function body.
    body = src[start: start + 3000]
    for forbidden_event in (
        "EV_PZ_GENERATED",
        "EV_PACKING_LIST_EXTRACTED",
        "EV_PACKING_MATCHED_TO_INVOICE",
        "EV_WFIRMA_JSON",
        "EV_WFIRMA_CLIPBOARD",
        "EV_EMAIL_QUEUED",
        "EV_EMAIL_SENT",
        "EV_PROFORMA_DRAFT_AUTO_CREATED",
    ):
        assert forbidden_event not in body, (
            f"suggest_column_mapping must not emit business event '{forbidden_event}'"
        )


# ── AI Bridge filter ──────────────────────────────────────────────────────────

def test_ai_bridge_events_set_includes_column_mapping():
    """shipment-detail.html AI_BRIDGE_EVENTS Set must include the new event."""
    src = _SD.read_text(encoding="utf-8")
    assert "column_mapping_llm_requested" in src, (
        "shipment-detail.html must include column_mapping_llm_requested in AI_BRIDGE_EVENTS"
    )
    # The Set literal must include it.
    assert "AI_BRIDGE_EVENTS" in src
    # Find the set and verify membership.
    idx = src.find("AI_BRIDGE_EVENTS = new Set(")
    assert idx != -1
    set_snippet = src[idx: idx + 200]
    assert "column_mapping_llm_requested" in set_snippet, (
        "AI_BRIDGE_EVENTS Set must contain 'column_mapping_llm_requested'"
    )


def test_ai_bridge_count_includes_column_mapping():
    """The AI Bridge event count expression must include column_mapping_llm_requested."""
    src = _SD.read_text(encoding="utf-8")
    # The count span already checks startsWith('ai_bridge') for existing events.
    # It must also explicitly include column_mapping_llm_requested.
    assert (
        "column_mapping_llm_requested" in src
    ), "Event string must appear in the count expression or Set"
    # More specific: the count expression (after the filter pill) must reference it.
    idx = src.find("events`\n")
    # Check a window around the event count lines for the new event.
    count_area = src[max(0, idx - 300): idx + 10]
    assert "column_mapping_llm_requested" in count_area, (
        "Timeline event count for AI Bridge filter must include column_mapping_llm_requested"
    )


# ── Constant in the right section ─────────────────────────────────────────────

def test_constant_placed_in_ai_advisory_section():
    """The constant must be in the AI advisory diagnostics section of timeline.py,
    not in the packing upload or clearance sections."""
    src = _TIMELINE_PY.read_text(encoding="utf-8")
    # Find the section comment and the constant — constant must come after it.
    section_pos   = src.find("AI advisory diagnostics events")
    constant_pos  = src.find("EV_COLUMN_MAPPING_LLM_REQUESTED")
    assert section_pos != -1, "timeline.py must have AI advisory diagnostics section"
    assert constant_pos != -1, "EV_COLUMN_MAPPING_LLM_REQUESTED must exist in timeline.py"
    assert constant_pos > section_pos, (
        "EV_COLUMN_MAPPING_LLM_REQUESTED must be placed after the AI advisory section header"
    )


def test_constant_value_is_lowercase_snake_case():
    """Event string values must be lowercase snake_case (convention check)."""
    from app.core import timeline as tl
    val = tl.EV_COLUMN_MAPPING_LLM_REQUESTED
    assert val == val.lower(), f"Event value must be lowercase: {val!r}"
    assert " " not in val, "Event value must not contain spaces"


# ── Human-readable timeline label ─────────────────────────────────────────────

def test_event_labels_map_exists_in_html():
    """shipment-detail.html must contain an EVENT_LABELS map."""
    src = _SD.read_text(encoding="utf-8")
    assert "EVENT_LABELS" in src, (
        "shipment-detail.html must define an EVENT_LABELS lookup map"
    )


def test_event_labels_contains_column_mapping_label():
    """EVENT_LABELS must map column_mapping_llm_requested to the human-readable label."""
    src = _SD.read_text(encoding="utf-8")
    assert "AI: column mapping suggestions requested" in src, (
        "shipment-detail.html must contain the human-readable label "
        "'AI: column mapping suggestions requested'"
    )


def test_event_labels_key_matches_constant_value():
    """The key in EVENT_LABELS must exactly match EV_COLUMN_MAPPING_LLM_REQUESTED's value."""
    from app.core import timeline as tl
    src = _SD.read_text(encoding="utf-8")
    key_literal = f"'{tl.EV_COLUMN_MAPPING_LLM_REQUESTED}'"
    assert key_literal in src, (
        f"EVENT_LABELS must contain key {key_literal} matching the timeline constant value"
    )


def test_label_resolution_uses_event_labels_map():
    """The label const must fall back through EVENT_LABELS before using e.event."""
    src = _SD.read_text(encoding="utf-8")
    assert "EVENT_LABELS[e.event]" in src, (
        "Label resolution must use EVENT_LABELS[e.event] as a fallback lookup"
    )
