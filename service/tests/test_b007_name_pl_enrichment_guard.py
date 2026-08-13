"""B-007: enrich_lines_from_product_descriptions must not overwrite operator name_pl.

Backlog claim (PRE-EXISTING at PR-2 challenge): enrichment unconditionally
overwrote ``name_pl`` from product_descriptions even when a line carried an
operator-confirmed non-blank value — the ``_birth_resolve_name_pl`` guard was
not replicated.

Current authority (already on main): provenance, not mere non-blankness.
Only ``name_pl_source == operator`` freezes the commercial name; machine /
PD / blank rows remain replaceable. This pin names B-007 explicitly so the
backlog cannot reopen without a failing test.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services import proforma_invoice_link_db as pildb


def _pd(code: str) -> Optional[Dict[str, Any]]:
    if code != "RNG-100":
        return None
    return {
        "product_code": "RNG-100",
        "item_type": "ring",
        "name_pl": "Pierścionek złoty",
        "description_pl": "Pierścionek złoty 585",
        "description_en": "Gold ring 585",
        "confidence": "high",
    }


def test_b007_enrichment_preserves_operator_confirmed_name_pl():
    """Operator-stamped non-blank name_pl survives PD enrichment (B-007)."""
    lines = [{
        "product_code": "RNG-100",
        "name_pl": "Nazwa ustalona z klientem",
        "name_pl_source": pildb.NAME_PL_SOURCE_OPERATOR,
        "qty": 1,
        "unit_price": 100.0,
    }]
    out, hit, miss = pildb.enrich_lines_from_product_descriptions(lines, _pd)
    assert hit == 1 and miss == 0
    assert out[0]["name_pl"] == "Nazwa ustalona z klientem"
    assert out[0]["name_pl_source"] == pildb.NAME_PL_SOURCE_OPERATOR


def test_b007_enrichment_still_replaces_machine_birth_from_pd():
    """Asymmetry pin: machine_birth remains replaceable (not frozen like operator)."""
    lines = [{
        "product_code": "RNG-100",
        "name_pl": "Stale Machine Text",
        "name_pl_source": pildb.NAME_PL_SOURCE_MACHINE_BIRTH,
        "qty": 1,
        "unit_price": 100.0,
    }]
    out, hit, miss = pildb.enrich_lines_from_product_descriptions(lines, _pd)
    assert hit == 1 and miss == 0
    assert out[0]["name_pl"] == "Pierścionek złoty 585"
    assert out[0]["name_pl_source"] == pildb.NAME_PL_SOURCE_PD
