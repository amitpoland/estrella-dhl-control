"""B-003 — replace_sales_packing_lines reports actual DELETE rowcount."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import document_db as ddb


BATCH = "BATCH_B003"


@pytest.fixture()
def storage(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _seed_doc(client: str = "ACME") -> str:
    doc_id = f"doc-{client}"
    ddb.ensure_sales_document_id(BATCH, doc_id, client_name=client)
    return doc_id


def _seed_lines(sd: str, n: int) -> None:
    lines = [
        {
            "client_name": "ACME",
            "client_ref": "R",
            "product_code": f"PC-{i}",
            "design_no": f"D-{i}",
            "bag_id": "",
            "quantity": 1.0,
            "remarks": "",
            "unit_price": 10.0,
            "currency": "EUR",
            "total_value": 10.0,
            "price_source": "packing_list",
        }
        for i in range(n)
    ]
    ddb.replace_sales_packing_lines(sd, BATCH, lines)


def test_deleted_equals_rows_actually_removed(storage):
    sd = _seed_doc()
    _seed_lines(sd, 4)
    r = ddb.replace_sales_packing_lines(sd, BATCH, [
        {
            "client_name": "ACME",
            "client_ref": "R",
            "product_code": "PC-NEW",
            "design_no": "D-NEW",
            "bag_id": "",
            "quantity": 1.0,
            "remarks": "",
            "unit_price": 1.0,
            "currency": "EUR",
            "total_value": 1.0,
            "price_source": "packing_list",
        }
    ])
    assert r == {"deleted": 4, "inserted": 1}


def test_deleted_zero_when_no_prior_rows(storage):
    sd = _seed_doc("EMPTY")
    r = ddb.replace_sales_packing_lines(sd, BATCH, [])
    assert r == {"deleted": 0, "inserted": 0}


def test_source_uses_changes_not_precount():
    """Pin B-003: deleted comes from SELECT changes() after DELETE."""
    src = Path(ddb.__file__).read_text(encoding="utf-8")
    start = src.index("def replace_sales_packing_lines")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    assert "SELECT changes()" in body
    assert "SELECT COUNT(*) FROM sales_packing_lines" not in body
