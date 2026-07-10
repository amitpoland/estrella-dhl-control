"""
test_proforma_wireframe_layout.py — Proforma wireframe rebuild Slice 3.

Pins for the render-layer rebuild of proforma-detail.jsx:

  1. PREFIX-AWARE full testid inventory (Slice 3 GATE-1 precondition): every
     data-testid a test file references with the proforma-page prefixes must
     still exist in the static sources. Ids ending in '-' are DYNAMIC template
     prefixes (e.g. "pf-doc-dnu-", "reservation-save-btn-") — a naive quoted
     pin false-fails on those, so they are asserted as prefix occurrences.
  2. Wireframe structure markers — eyebrow, Currency & Payment card, summary
     StatTiles, wireframe Items columns + charge footer, timeline audit trail.
  3. Lesson M toolbar guard — all 17 action testids stay in source.
  4. AwbGenerateModal integrity — signature + booking endpoint call untouched.
"""
from __future__ import annotations

import re
from pathlib import Path

SERVICE = Path(__file__).resolve().parent.parent
STATIC = SERVICE / "app" / "static"
JSX = STATIC / "v2" / "proforma-detail.jsx"
TESTS = Path(__file__).resolve().parent

# Prefixes owned by the proforma detail/list/search surfaces.
PIN_PREFIXES = ("tb-", "proforma-", "party-", "pf-", "reservation-",
                "mapping-", "line-row", "lines-add-line", "select-draft",
                "match-chip", "addr-", "btn-load-from-cm", "btn-edit-bill-to")

TOOLBAR_TESTIDS = (
    "tb-edit", "tb-edit-save", "tb-edit-cancel", "tb-delete", "tb-purge",
    "tb-duplicate", "tb-approve", "tb-post", "tb-convert", "tb-preview",
    "proforma-detail-download-pdf", "tb-send", "tb-generate",
    "tb-awb-generate", "tb-invoice-history", "tb-more", "tb-back",
)


def _static_sources() -> str:
    parts = []
    for p in list(STATIC.rglob("*.jsx")) + list(STATIC.rglob("*.html")) + list(STATIC.rglob("*.js")):
        try:
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "\n".join(parts)


def _pinned_ids_from_tests():
    """Collect quoted testid-shaped strings with proforma prefixes from tests."""
    ids = set()
    pat = re.compile(r'"((?:%s)[a-z0-9_-]*)"' % "|".join(re.escape(p) for p in PIN_PREFIXES))
    for tf in TESTS.glob("test_*.py"):
        if tf.name == Path(__file__).name:
            continue
        try:
            text = tf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pat.finditer(text):
            ids.add(m.group(1))
    return ids


# Ids referenced by tests as REMOVED surfaces (deletion pins assert their
# ABSENCE — e.g. test_c27_1_proforma_surface_deletions). They are correctly
# absent from static sources and must not fail the presence inventory.
DELETED_SURFACE_IDS = {
    "proforma-create", "proforma-draft-1", "tb-cmr",
    "proforma-not-linked-panel-",
}


def test_pinned_testids_survive_rebuild():
    src = _static_sources()
    missing = []
    for tid in sorted(_pinned_ids_from_tests() - DELETED_SURFACE_IDS):
        if tid.endswith("-"):
            # Dynamic template prefix — asserted as an occurrence anywhere
            # (template literal `${...}` usage or a longer static id).
            if f"{tid}" not in src:
                missing.append(f"{tid}* (dynamic prefix)")
        else:
            if tid not in src:
                missing.append(tid)
    assert not missing, (
        "data-testids pinned by tests are missing from static sources after "
        f"the wireframe rebuild: {missing}"
    )


def test_slice3_wireframe_structure():
    src = JSX.read_text(encoding="utf-8")
    for marker in (
        'data-testid="pf-draft-eyebrow"',           # toolbar eyebrow
        'data-testid="party-currency-payment"',     # Currency & Payment card
        'data-testid="pf-summary-line-items"',      # Overview StatTiles
        'data-testid="pf-summary-total-pln"',
        "Grand total",                              # Items charge footer
        'data-testid="pf-lines-freight"',
        'data-testid="pf-lines-insurance"',
        "Client PO",                                # wireframe Items columns
        "Dia Wt",
        'data-testid="pf-logistics-tile-gross"',    # Logistics StatTiles
        "Activity history",                         # Audit timeline
    ):
        assert marker in src, f"wireframe structure marker missing: {marker!r}"
    # Ctg stays display-only — derived, never a schema column.
    assert "derived display-only" in src


def test_lesson_m_toolbar_actions_all_visible():
    """Operator decision 2026-07-10: ALL toolbar actions stay visible.
    Removal of any action testid from source = capability suppression
    (Lesson M) and fails here."""
    src = JSX.read_text(encoding="utf-8")
    missing = [t for t in TOOLBAR_TESTIDS if f'"{t}"' not in src]
    assert not missing, f"toolbar action testids missing (Lesson M): {missing}"


def test_awb_generate_modal_untouched():
    src = JSX.read_text(encoding="utf-8")
    assert "function AwbGenerateModal(" in src
    # The booking call and the Customer-Master save-confirmation gate are the
    # protected core of the AWB flow — pinned as source markers.
    assert "createCarrierShipment" in src
    assert re.search(r"masterState", src), "AWB Customer-Master gate missing"
    # Trigger keeps its gate: disabled when no batch is loaded.
    m = re.search(r'data-testid="tb-awb-generate"', src)
    assert m, "AWB trigger testid missing"
    window = src[max(0, m.start() - 600):m.start() + 200]
    assert "!batchId" in window, "AWB trigger lost its !batchId disable gate"
