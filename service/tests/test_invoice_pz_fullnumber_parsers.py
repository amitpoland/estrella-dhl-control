"""
test_invoice_pz_fullnumber_parsers.py — Pin the operator-facing read
parsers for Proforma/Invoice and PZ documents to the canonical
``<fullnumber>`` tag (no underscore). The wFirma read response uses
``<fullnumber>``; the find/edit query body uses ``<full_number>``.
A historical mismatch caused the PZ doc viewer to display "4" instead
of "PZ 4/5/2026" and the Proforma viewer to display "92" instead of
"PROF 92/2026" — the parser fell through to bare ``<number>``.

Pins:
  1. ``_parse_proforma_from_xml`` returns ``PROF 92/2026`` (not ``92``)
  2. ``_parse_pz_doc_from_xml``    returns ``PZ 4/5/2026``  (not ``4``)
  3. ``find_warehouse_pz_by_number`` returns ``PZ 4/5/2026`` (not ``4``)
  4. Existing ``<full_number>`` fixtures still pass (defensive secondary)
  5. Bare ``<number>`` fallback still resolves
  6. Source-grep guards: lookup priority is locked at all three sites
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────

_PROFORMA_OK = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>467236963</id>
      <type>proforma</type>
      <fullnumber>PROF 92/2026</fullnumber>
      <number>92</number>
      <date>2026-05-08</date>
      <currency>EUR</currency>
      <contractor><id>128515865</id></contractor>
      <invoicecontents>
        <invoicecontent><id>1</id><name>RING</name><count>1</count></invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


_PROFORMA_UNDERSCORED = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>X</id>
      <type>proforma</type>
      <full_number>PROF/05/2026/001</full_number>
      <number>1</number>
      <currency>USD</currency>
      <contractor><id>9</id></contractor>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


_PROFORMA_BARE_NUMBER_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <invoice>
      <id>X</id>
      <type>proforma</type>
      <number>42</number>
      <currency>PLN</currency>
      <contractor><id>9</id></contractor>
    </invoice>
  </invoices>
  <status><code>OK</code></status>
</api>"""


_PZ_OK = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <warehouse_documents>
    <warehouse_document>
      <id>183484963</id>
      <fullnumber>PZ 4/5/2026</fullnumber>
      <number>4</number>
      <date>2026-05-08</date>
      <type>PZ</type>
      <contractor><id>38142296</id></contractor>
      <warehouse><id>347088</id></warehouse>
    </warehouse_document>
  </warehouse_documents>
  <status><code>OK</code></status>
</api>"""


_PZ_UNDERSCORED = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <warehouse_documents>
    <warehouse_document>
      <id>X</id>
      <full_number>PZ 1/4/2026</full_number>
      <number>1</number>
      <type>PZ</type>
    </warehouse_document>
  </warehouse_documents>
  <status><code>OK</code></status>
</api>"""


_PZ_BARE_NUMBER_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <warehouse_documents>
    <warehouse_document>
      <id>X</id>
      <number>17</number>
      <type>PZ</type>
    </warehouse_document>
  </warehouse_documents>
  <status><code>OK</code></status>
</api>"""


# ── 1. Proforma parser ──────────────────────────────────────────────────────

def test_proforma_parser_returns_canonical_fullnumber():
    from app.api.routes_proforma import _parse_proforma_from_xml
    parsed = _parse_proforma_from_xml(_PROFORMA_OK)
    assert parsed["full_number"] == "PROF 92/2026"
    assert parsed["full_number"] != "92"
    assert parsed["currency"]    == "EUR"


def test_proforma_parser_honours_underscored_fixture():
    """Defensive: legacy/test fixtures using <full_number> still work."""
    from app.api.routes_proforma import _parse_proforma_from_xml
    parsed = _parse_proforma_from_xml(_PROFORMA_UNDERSCORED)
    assert parsed["full_number"] == "PROF/05/2026/001"


def test_proforma_parser_falls_back_to_bare_number():
    from app.api.routes_proforma import _parse_proforma_from_xml
    parsed = _parse_proforma_from_xml(_PROFORMA_BARE_NUMBER_ONLY)
    assert parsed["full_number"] == "42"


# ── 2. PZ document parser ───────────────────────────────────────────────────

def test_pz_doc_parser_returns_canonical_fullnumber():
    from app.api.routes_wfirma import _parse_pz_doc_from_xml
    parsed = _parse_pz_doc_from_xml(_PZ_OK)
    assert parsed["pz_number"] == "PZ 4/5/2026"
    assert parsed["pz_number"] != "4"


def test_pz_doc_parser_honours_underscored_fixture():
    from app.api.routes_wfirma import _parse_pz_doc_from_xml
    parsed = _parse_pz_doc_from_xml(_PZ_UNDERSCORED)
    assert parsed["pz_number"] == "PZ 1/4/2026"


def test_pz_doc_parser_falls_back_to_bare_number():
    from app.api.routes_wfirma import _parse_pz_doc_from_xml
    parsed = _parse_pz_doc_from_xml(_PZ_BARE_NUMBER_ONLY)
    assert parsed["pz_number"] == "17"


# ── 3. find_warehouse_pz_by_number parser ───────────────────────────────────

def _stub(http_status: int, xml: str):
    from app.services import wfirma_client as wc
    return patch.object(wc, "_http_request",
                         return_value=(http_status, xml))


def test_find_by_number_parser_returns_canonical_fullnumber():
    from app.services import wfirma_client as wc
    with _stub(200, _PZ_OK):
        r = wc.find_warehouse_pz_by_number("PZ 4/5/2026")
    assert r.ok is True
    assert r.pz_number == "PZ 4/5/2026"
    assert r.pz_number != "4"


def test_find_by_number_parser_honours_underscored_fixture():
    from app.services import wfirma_client as wc
    with _stub(200, _PZ_UNDERSCORED):
        r = wc.find_warehouse_pz_by_number("PZ 1/4/2026")
    assert r.pz_number == "PZ 1/4/2026"


def test_find_by_number_parser_falls_back_to_bare_number():
    from app.services import wfirma_client as wc
    with _stub(200, _PZ_BARE_NUMBER_ONLY):
        r = wc.find_warehouse_pz_by_number("17")
    assert r.pz_number == "17"


# ── 6. Source-grep priority guards ──────────────────────────────────────────

def test_routes_proforma_parser_priority_locked():
    """If a future refactor reorders or drops one of the lookups in
    ``_parse_proforma_from_xml``, catch it before it ships."""
    src = Path("app/api/routes_proforma.py").read_text(encoding="utf-8")
    fn_idx = src.find("def _parse_proforma_from_xml(")
    assert fn_idx > 0
    body = src[fn_idx: fn_idx + 4000]
    fn_pos     = body.find('"fullnumber"')
    full_pos   = body.find('"full_number"')
    number_pos = body.find('"number"')
    assert 0 < fn_pos < full_pos < number_pos, (
        "_parse_proforma_from_xml must try fullnumber → full_number → number"
    )


def test_routes_wfirma_pz_doc_parser_priority_locked():
    """Scope the grep to the `pz_number = ...` lookup chain only —
    other ``_txt("number")`` calls in the same function (e.g. as a
    description fallback) would otherwise confuse a flat positional check."""
    src = Path("app/api/routes_wfirma.py").read_text(encoding="utf-8")
    fn_idx = src.find("def _parse_pz_doc_from_xml(")
    assert fn_idx > 0
    body = src[fn_idx: fn_idx + 4000]
    chain_idx = body.find("pz_number")
    assert chain_idx > 0
    chain = body[chain_idx: chain_idx + 400]
    fn_pos     = chain.find('"fullnumber"')
    full_pos   = chain.find('"full_number"')
    number_pos = chain.find('"number"')
    assert 0 < fn_pos < full_pos < number_pos, (
        "_parse_pz_doc_from_xml's pz_number lookup must try "
        "fullnumber → full_number → number"
    )


def test_find_warehouse_pz_by_number_response_parser_priority_locked():
    """The query body in find_warehouse_pz_by_number uses ``full_number``
    (wFirma-supported searchable field) — that must NOT change. Only the
    RESPONSE parser is in scope; pin its lookup priority."""
    src = Path("app/services/wfirma_client.py").read_text(encoding="utf-8")
    fn_idx = src.find("def find_warehouse_pz_by_number(")
    assert fn_idx > 0
    body = src[fn_idx: fn_idx + 6000]
    # Query body is preserved.
    assert "<field>full_number</field>" in body
    # Response parser tries fullnumber first.
    fn_pos     = body.find('"fullnumber"')
    full_pos   = body.find('_find_text(wd_node, "full_number")')
    number_pos = body.find('_find_text(wd_node, "number")')
    assert 0 < fn_pos < full_pos < number_pos, (
        "find_warehouse_pz_by_number response parser must try fullnumber "
        "→ full_number → number"
    )
