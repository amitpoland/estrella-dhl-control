"""A contractor is identified by contractor/id, never by contractor_detail/id.

wFirma exposes the party on a document twice. ``contractor`` points at the CRM
record. ``contractor_detail`` is a SNAPSHOT of how that party looked when the
document was issued, and it carries its own id which differs from document to
document for the same real party.

Falling back to the snapshot id does not recover a missing identity -- it invents
a new party per document. That is the documented mechanism behind duplicate
contractors, and the effect is already visible in production: SYNINVEST/Synalia
(NIP FR58479048548) and Goto Jewellery (BG202532349) each appear as two customer
positions, so a credit recorded under one id can never offset an invoice under
the other.

An absent contractor/id is a real condition -- a document raised against a party
with no CRM record -- and must stay visible rather than be papered over.
"""
from __future__ import annotations

import pytest

from app.services.accounting_documents import (
    WAREHOUSE_TYPES_SUPPORTED,
    normalize_invoice_node,
    normalize_warehouse_node,
)


import xml.etree.ElementTree as ET


def _node(tag, contractor_id=None, detail_id="999999"):
    """These normalisers take ElementTree nodes straight off the wFirma XML."""
    crm = ("<contractor><id>%s</id><name>CRM Name</name></contractor>"
           % contractor_id) if contractor_id is not None else ""
    return ET.fromstring(
        "<%s><id>x-1</id><fullnumber>FV 1/2026</fullnumber>"
        "<date>2026-08-22</date><currency>EUR</currency>%s"
        "<contractor_detail><id>%s</id><name>Snapshot Name</name>"
        "</contractor_detail></%s>" % (tag, crm, detail_id, tag))


def _invoice(contractor_id=None, detail_id="999999"):
    return _node("invoice", contractor_id, detail_id)


def _warehouse(contractor_id=None, detail_id="999999"):
    """A warehouse document is rejected without a supported <type>."""
    node = _node("warehouse_document", contractor_id, detail_id)
    ET.SubElement(node, "type").text = sorted(WAREHOUSE_TYPES_SUPPORTED)[0]
    return node


def test_the_crm_id_is_used_when_present():
    out = normalize_invoice_node(_invoice(contractor_id="38533073"))
    assert out["contractor_id"] == "38533073"


def test_the_snapshot_id_is_never_substituted_for_a_missing_crm_id():
    """THE regression. The snapshot id changes per document, so using it as a
    fallback creates one 'contractor' per invoice."""
    out = normalize_invoice_node(_invoice(contractor_id=None, detail_id="999999"))
    assert out["contractor_id"] != "999999"
    assert not out["contractor_id"], (
        "a document with no CRM contractor must report an EMPTY id, not a "
        "snapshot id that identifies nothing")


def test_two_documents_for_one_party_do_not_become_two_parties():
    """The failure in the shape it actually takes: same real party, two
    documents, two different snapshot ids."""
    a = normalize_invoice_node(_invoice(contractor_id=None, detail_id="111"))
    b = normalize_invoice_node(_invoice(contractor_id=None, detail_id="222"))
    assert a["contractor_id"] == b["contractor_id"], (
        "the same party split into two identities because the snapshot id "
        "differed between documents")


def test_the_snapshot_NAME_is_still_usable():
    """Only the id is dangerous. The name is not a key, and the snapshot name is
    often the better display value, so it must survive this change."""
    out = normalize_invoice_node(_invoice(contractor_id=None))
    assert "Snapshot" in (out.get("party_name") or out.get("party") or "")


def test_warehouse_documents_follow_the_same_rule():
    assert normalize_warehouse_node(
        _warehouse(contractor_id="38533073"))["contractor_id"] == "38533073"
    assert not normalize_warehouse_node(
        _warehouse(contractor_id=None, detail_id="999999"))["contractor_id"]


def test_no_module_reintroduces_the_fallback():
    """Source guard. The fallback was in two places and would be easy to add
    back as a 'fix' for an empty column."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "contractor_detail/id" in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, (
        "contractor_detail/id is a per-document snapshot id and must never key "
        "a contractor: %r" % offenders)
