"""B-011: proforma_invoice_link_db public exports for PR-2/PR-3 helpers.

``migrate_draft_to_canonical_name`` and the draft-birth block helpers are
imported by attribute / named import today, so omitting them from ``__all__``
does not break runtime. Static export checks and star-import consumers still
need them listed.

Run: python -m pytest tests/test_b011_proforma_public_exports.py -q
"""
from __future__ import annotations

from app.services import proforma_invoice_link_db as pildb

# Exact symbols named by BACKLOG B-011.
B011_PUBLIC_EXPORTS = (
    "migrate_draft_to_canonical_name",
    "record_draft_birth_block",
    "resolve_draft_birth_block",
    "list_draft_birth_blocks",
)


def test_b011_draft_birth_and_canonical_migrate_are_in_all():
    missing = [n for n in B011_PUBLIC_EXPORTS if n not in pildb.__all__]
    assert missing == [], f"B-011 symbols missing from __all__: {missing}"


def test_b011_exports_are_callable_attributes():
    for name in B011_PUBLIC_EXPORTS:
        assert hasattr(pildb, name), name
        assert callable(getattr(pildb, name)), name
