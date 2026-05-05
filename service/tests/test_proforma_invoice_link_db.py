"""
test_proforma_invoice_link_db.py — unit tests for the proforma↔invoice
local link table. NEVER hits wFirma — pure SQLite + Decimal handling.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.services.proforma_invoice_link_db import (    # noqa: E402
    ProformaInvoiceLink, ProformaAlreadyConverted,
    VALID_STATUSES, validate, init_db, create_pending_link,
    mark_issued, mark_failed, get_link_by_proforma,
    get_link_by_invoice, list_links,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _pending(**overrides) -> ProformaInvoiceLink:
    base = dict(
        proforma_id     = "98712989",
        proforma_number = "PROF 90/2026",
        converted_at    = "",
        operator        = "amit",
        source_total    = Decimal("1234.56"),
        currency        = "USD",
        status          = "pending",
    )
    base.update(overrides)
    return ProformaInvoiceLink(**base)


# ── Validation ────────────────────────────────────────────────────────────────

def test_validate_accepts_minimal_pending():
    assert validate(_pending()) == []


def test_validate_blocks_missing_proforma_id():
    assert "proforma_id is required" in validate(_pending(proforma_id=""))


def test_validate_blocks_missing_proforma_number():
    assert "proforma_number is required" in validate(_pending(proforma_number=""))


def test_validate_blocks_missing_operator():
    assert "operator is required" in validate(_pending(operator="  "))


@pytest.mark.parametrize("bad", ["JPY", "GBP", "INR", ""])
def test_validate_blocks_unsupported_currency(bad):
    blockers = validate(_pending(currency=bad))
    assert any("currency" in b for b in blockers)


@pytest.mark.parametrize("bad", ["draft", "issuing", "cancelled", ""])
def test_validate_blocks_invalid_status(bad):
    blockers = validate(_pending(status=bad))
    assert any("status must be" in b for b in blockers)


def test_validate_blocks_zero_source_total():
    blockers = validate(_pending(source_total=Decimal("0")))
    assert any("source_total" in b for b in blockers)


def test_validate_issued_requires_invoice_fields():
    link = _pending(status="issued")
    blockers = validate(link)
    assert "status=issued requires invoice_id" in blockers
    assert "status=issued requires invoice_number" in blockers
    assert "status=issued requires invoice_total" in blockers


def test_validate_issued_with_all_fields_passes():
    link = _pending(
        status         = "issued",
        invoice_id     = "98712990",
        invoice_number = "FV 12/2026",
        invoice_total  = Decimal("1234.56"),
    )
    assert validate(link) == []


# ── DB lifecycle ─────────────────────────────────────────────────────────────

def test_init_db_creates_table_idempotent(tmp_path: Path):
    db = tmp_path / "links.db"
    init_db(db)
    init_db(db)   # second call must not raise
    assert db.exists()


def test_create_pending_then_get_by_proforma(tmp_path: Path):
    db = tmp_path / "links.db"
    new_id = create_pending_link(db, _pending())
    assert new_id > 0
    got = get_link_by_proforma(db, "98712989")
    assert got is not None
    assert got.id == new_id
    assert got.status == "pending"
    assert got.invoice_id is None
    assert got.source_total == Decimal("1234.56")


def test_create_pending_auto_fills_converted_at(tmp_path: Path):
    db = tmp_path / "links.db"
    create_pending_link(db, _pending(converted_at=""))
    got = get_link_by_proforma(db, "98712989")
    assert got.converted_at and got.converted_at.endswith("Z")


def test_create_pending_blocks_validation_failure(tmp_path: Path):
    db = tmp_path / "links.db"
    with pytest.raises(ValueError, match="validation failed"):
        create_pending_link(db, _pending(currency="JPY"))


def test_get_returns_none_for_unknown(tmp_path: Path):
    db = tmp_path / "links.db"
    init_db(db)
    assert get_link_by_proforma(db, "00000") is None
    assert get_link_by_invoice(db, "00000") is None


def test_get_returns_none_when_db_missing(tmp_path: Path):
    """No file exists yet → None, not crash."""
    assert get_link_by_proforma(tmp_path / "missing.db", "X") is None
    assert get_link_by_invoice(tmp_path / "missing.db", "X") is None
    assert list_links(tmp_path / "missing.db") == []


# ── Duplicate-conversion guard ───────────────────────────────────────────────

def test_duplicate_conversion_raises(tmp_path: Path):
    db = tmp_path / "links.db"
    create_pending_link(db, _pending())
    with pytest.raises(ProformaAlreadyConverted) as exc:
        create_pending_link(db, _pending())
    assert "98712989" in str(exc.value)
    assert exc.value.existing.proforma_id == "98712989"
    assert exc.value.existing.status == "pending"


def test_duplicate_after_issued_still_blocks(tmp_path: Path):
    """Once issued, never re-convert."""
    db = tmp_path / "links.db"
    create_pending_link(db, _pending())
    mark_issued(db, "98712989",
                invoice_id="111", invoice_number="FV 1/2026",
                invoice_total=Decimal("1000"))
    with pytest.raises(ProformaAlreadyConverted) as exc:
        create_pending_link(db, _pending())
    assert exc.value.existing.status == "issued"


# ── Status transitions ──────────────────────────────────────────────────────

def test_mark_issued_promotes_pending(tmp_path: Path):
    db = tmp_path / "links.db"
    create_pending_link(db, _pending())
    mark_issued(db, "98712989",
                invoice_id="98712990", invoice_number="FV 12/2026",
                invoice_total=Decimal("1234.56"))
    got = get_link_by_proforma(db, "98712989")
    assert got.status == "issued"
    assert got.invoice_id == "98712990"
    assert got.invoice_number == "FV 12/2026"
    assert got.invoice_total == Decimal("1234.56")


def test_mark_issued_blocks_zero_total(tmp_path: Path):
    db = tmp_path / "links.db"
    create_pending_link(db, _pending())
    with pytest.raises(ValueError, match="invoice_total"):
        mark_issued(db, "98712989",
                    invoice_id="X", invoice_number="X",
                    invoice_total=Decimal("0"))


def test_mark_issued_unknown_proforma_raises(tmp_path: Path):
    db = tmp_path / "links.db"
    init_db(db)
    with pytest.raises(KeyError):
        mark_issued(db, "00000",
                    invoice_id="X", invoice_number="X",
                    invoice_total=Decimal("1"))


def test_mark_failed_records_reason(tmp_path: Path):
    db = tmp_path / "links.db"
    create_pending_link(db, _pending())
    mark_failed(db, "98712989", notes="wFirma rejected: missing series")
    got = get_link_by_proforma(db, "98712989")
    assert got.status == "failed"
    assert "missing series" in (got.notes or "")
    assert got.invoice_id is None


def test_mark_failed_requires_notes(tmp_path: Path):
    db = tmp_path / "links.db"
    create_pending_link(db, _pending())
    with pytest.raises(ValueError):
        mark_failed(db, "98712989", notes="")


# ── Lookup by invoice + listing ─────────────────────────────────────────────

def test_get_link_by_invoice_after_issued(tmp_path: Path):
    db = tmp_path / "links.db"
    create_pending_link(db, _pending())
    mark_issued(db, "98712989",
                invoice_id="98712990", invoice_number="FV 12/2026",
                invoice_total=Decimal("1234.56"))
    got = get_link_by_invoice(db, "98712990")
    assert got is not None
    assert got.proforma_id == "98712989"


def test_list_links_filters_by_status(tmp_path: Path):
    db = tmp_path / "links.db"
    create_pending_link(db, _pending())
    create_pending_link(db, _pending(proforma_id="X1", proforma_number="PROF 1/2026"))
    create_pending_link(db, _pending(proforma_id="X2", proforma_number="PROF 2/2026"))
    mark_issued(db, "X1", invoice_id="I1", invoice_number="N1",
                invoice_total=Decimal("1"))
    mark_failed(db, "X2", notes="boom")
    assert len(list_links(db, status="pending")) == 1
    assert len(list_links(db, status="issued"))  == 1
    assert len(list_links(db, status="failed"))  == 1
    assert len(list_links(db)) == 3


def test_list_links_status_validation(tmp_path: Path):
    db = tmp_path / "links.db"
    init_db(db)
    with pytest.raises(ValueError):
        list_links(db, status="bogus")


# ── No I/O leak ──────────────────────────────────────────────────────────────

def test_module_does_not_import_wfirma_client():
    """Storage layer must stay wFirma-free."""
    import app.services.proforma_invoice_link_db as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "wfirma_client" not in src
    assert "import requests" not in src
