"""
test_purchase_packing_variant_capture.py — purchase-side variant capture fix.

Root cause (confirmed against production data): the purchase intake mapping and
the reprocess mapping dropped 5 variant fields (metal_color, quality_string,
size, diamond_weight, color_weight), and the extractor never derived `karat`
from a combined `metal` (e.g. "18KT/Y") — so packing_lines variant fields were
empty for intake-uploaded batches and the variant signature collapsed to
`design_no|||||||`.

This pins:
  1. _derive_karat_from_metal — lifts the purity token from combined metal,
     digit-guarded, preserves metal, never mistakes a colour for a karat.
  2. upsert_packing_lines round-trips all 7 variant fields (DB persistence).
  3. INVARIANT source pins: every packing line_records mapping that forwards
     `karat` also forwards the 5 variant fields (no karat-but-drop-variant
     mapping can return) — in routes_intake.py AND routes_packing.py.

Guardrail respected: no product_code minting change; the fix only forwards
existing extracted fields and derives karat.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from pathlib import Path

import pytest

from app.services.invoice_packing_extractor import _derive_karat_from_metal
from app.services import packing_db as pdb
from app.api import routes_intake as _ri
from app.api import routes_packing as _rp

_VARIANT_FIELDS = ("metal_color", "quality_string", "size",
                   "diamond_weight", "color_weight")


# ── 1. _derive_karat_from_metal ──────────────────────────────────────────────

@pytest.mark.parametrize("metal,expected", [
    ("18KT/Y", "18KT"),      # combined karat/color (the dominant real shape)
    ("14KT/W", "14KT"),
    ("18KT", "18KT"),        # karat only
    ("PT950/W", "PT950"),    # platinum purity
    ("585/RG", "585"),       # numeric purity
    ("W", ""),               # colour only — no digit -> not a karat
    ("Y", ""),
    ("", ""),
    (None, ""),
])
def test_derive_karat(metal, expected):
    assert _derive_karat_from_metal(metal) == expected


# ── 2. upsert_packing_lines round-trips all 7 variant fields ─────────────────

def test_packing_lines_persist_variant_fields(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    con = sqlite3.connect(str(tmp_path / "packing.db"))
    con.execute(
        "INSERT INTO packing_documents (id, batch_id, invoice_no, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        ("DOC1", "BATCH_P", "EJL/26-27/244", "2026-07-07T00:00:00Z", "2026-07-07T00:00:00Z"),
    )
    con.commit(); con.close()

    rec = {
        "packing_document_id": "DOC1", "batch_id": "BATCH_P",
        "invoice_no": "EJL/26-27/244", "invoice_line_position": 1,
        "product_code": "EJL/26-27/244-1", "design_no": "CSTR001",
        "item_type": "RNG", "metal": "18KT/Y", "karat": "18KT",
        "metal_color": "Y", "quality_string": "G-VS", "stone_type": "DIAMOND",
        "size": "7", "diamond_weight": 0.5, "color_weight": 0.2, "quantity": 1.0,
    }
    pdb.upsert_packing_lines([rec])
    rows = pdb.get_packing_lines_for_batch("BATCH_P")
    assert len(rows) == 1
    r = rows[0]
    assert r["karat"] == "18KT"
    assert r["metal"] == "18KT/Y"          # metal preserved
    assert r["metal_color"] == "Y"
    assert r["quality_string"] == "G-VS"
    assert r["stone_type"] == "DIAMOND"
    assert r["size"] == "7"
    assert r["diamond_weight"] == pytest.approx(0.5)
    assert r["color_weight"] == pytest.approx(0.2)


# ── 3. INVARIANT source pins — no karat-but-drop-variant mapping may exist ───

def _key_count(src: str, key: str) -> int:
    # Count only line_records-style forwardings (the packing-persistence dicts),
    # i.e. `"key": str(...)` / `float(...)` / `_safe_float(...)`. This excludes
    # unrelated reads like the scan/barcode record's bare `"karat": ln.get(...)`.
    return len(re.findall(rf'"{key}":\s*(?:str|float|_safe_float)\(', src))


def test_routes_intake_forwards_variant_with_karat():
    """Every packing line_records mapping in routes_intake that forwards `karat`
    must also forward all 5 variant fields (the fix + #837 sales fix)."""
    src = Path(_ri.__file__).read_text(encoding="utf-8", errors="replace")
    karat_n = _key_count(src, "karat")
    assert karat_n >= 2
    for f in _VARIANT_FIELDS:
        assert _key_count(src, f) == karat_n, (
            f"{f} forwarded {_key_count(src, f)}x but karat {karat_n}x — a "
            f"mapping forwards karat while dropping {f} (the original bug)"
        )


def test_routes_packing_forwards_variant_with_karat():
    """Upload + reprocess mappings in routes_packing must both forward the 5
    variant fields alongside karat."""
    src = Path(_rp.__file__).read_text(encoding="utf-8", errors="replace")
    karat_n = _key_count(src, "karat")
    assert karat_n >= 2
    for f in _VARIANT_FIELDS:
        assert _key_count(src, f) == karat_n, (
            f"{f} forwarded {_key_count(src, f)}x but karat {karat_n}x in "
            f"routes_packing — a mapping drops {f}"
        )
