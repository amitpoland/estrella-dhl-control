"""
test_fetch_warehouse_pz_fullnumber.py — Pin the PZ number tag-priority
in wfirma_client.fetch_warehouse_pz.

Live wFirma read response carries ``<fullnumber>PZ 4/5/2026</fullnumber>``
(no underscore) plus a separate ``<number>4</number>`` (per-month
sequence). The previous parser only looked for ``full_number`` (with
underscore), missed the canonical tag, and fell through to ``<number>``
— so refresh-mapping stamped ``"4"`` instead of ``"PZ 4/5/2026"``.

Pins:
  1. ``<fullnumber>`` is preferred and returns the canonical value.
  2. ``<full_number>`` is honoured as a secondary spelling
     (defensive — wFirma's query body uses this form).
  3. Bare ``<number>`` is the fallback only when neither of the above
     is present.
  4. Empty / missing → ``""``.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import wfirma_client as wc


# ── Reusable fixture builders ──────────────────────────────────────────────

_OK = """<?xml version="1.0" encoding="UTF-8"?>
<api>
  <warehouse_documents>
    <warehouse_document>
      <id>183484963</id>
      {tags}
      <date>2026-05-08</date>
      <type>PZ</type>
    </warehouse_document>
  </warehouse_documents>
  <status><code>OK</code></status>
</api>"""


def _stub(http_status: int, xml: str):
    return patch.object(
        wc, "_http_request",
        return_value=(http_status, xml),
    )


# ── 1. Canonical <fullnumber> wins ─────────────────────────────────────────

def test_fullnumber_tag_returns_canonical_pz_number():
    xml = _OK.format(tags=(
        "<fullnumber>PZ 4/5/2026</fullnumber>"
        "<number>4</number>"
    ))
    with _stub(200, xml):
        r = wc.fetch_warehouse_pz("183484963")
    assert r.ok is True
    assert r.pz_doc_id == "183484963"
    assert r.pz_number == "PZ 4/5/2026"


def test_fullnumber_wins_over_number_when_only_fullnumber_present():
    xml = _OK.format(tags="<fullnumber>PZ 12/3/2026</fullnumber>")
    with _stub(200, xml):
        r = wc.fetch_warehouse_pz("X")
    assert r.pz_number == "PZ 12/3/2026"


# ── 2. <full_number> (underscored) is a recognised secondary spelling ──────

def test_full_number_underscore_form_also_works():
    xml = _OK.format(tags=(
        "<full_number>PZ 1/2/2026</full_number>"
        "<number>1</number>"
    ))
    with _stub(200, xml):
        r = wc.fetch_warehouse_pz("X")
    assert r.pz_number == "PZ 1/2/2026"


# ── 3. <number> fallback when neither full-number variant exists ───────────

def test_bare_number_fallback_when_no_fullnumber_tag():
    xml = _OK.format(tags="<number>42</number>")
    with _stub(200, xml):
        r = wc.fetch_warehouse_pz("X")
    assert r.pz_number == "42"


def test_fullnumber_priority_over_full_number_when_both_present():
    """Defensive: if a future wFirma response carries both spellings,
    the canonical concatenated form wins."""
    xml = _OK.format(tags=(
        "<fullnumber>PZ 4/5/2026</fullnumber>"
        "<full_number>WRONG/UNDERSCORED</full_number>"
        "<number>4</number>"
    ))
    with _stub(200, xml):
        r = wc.fetch_warehouse_pz("X")
    assert r.pz_number == "PZ 4/5/2026"


# ── 4. Empty / missing tags → empty string ─────────────────────────────────

def test_no_number_tags_returns_empty_pz_number():
    xml = _OK.format(tags="")
    with _stub(200, xml):
        r = wc.fetch_warehouse_pz("X")
    assert r.ok is True
    assert r.pz_number == ""


# ── Regression for AWB 6049349806 doc 183484963 ────────────────────────────

def test_awb_6049349806_pz_returns_full_number_not_4():
    """The exact failure shape from the live PZ refresh attempt:
    ``<fullnumber>PZ 4/5/2026</fullnumber>`` co-exists with ``<number>4</number>``.
    The pre-fix parser returned ``"4"``; the fix returns
    ``"PZ 4/5/2026"``."""
    xml = _OK.format(tags=(
        "<fullnumber>PZ 4/5/2026</fullnumber>"
        "<number>4</number>"
    ))
    with _stub(200, xml):
        r = wc.fetch_warehouse_pz("183484963")
    assert r.pz_number == "PZ 4/5/2026"
    assert r.pz_number != "4"


# ── Source-grep guard against regression ───────────────────────────────────

def test_parser_priority_locked_in_source():
    """If a future refactor reorders or drops one of the lookups,
    catch it before it ships."""
    from pathlib import Path
    src = Path(wc.__file__).read_text(encoding="utf-8")
    # The fetch_warehouse_pz function must contain the three lookups in
    # the canonical priority order: fullnumber → full_number → number.
    fn_idx = src.find("def fetch_warehouse_pz(")
    assert fn_idx > 0
    body = src[fn_idx: fn_idx + 4000]
    fn_pos     = body.find('"fullnumber"')
    full_pos   = body.find('"full_number"')
    number_pos = body.find('"number"')
    assert 0 < fn_pos < full_pos < number_pos, (
        "fetch_warehouse_pz must try <fullnumber> before <full_number> "
        "before <number>"
    )
