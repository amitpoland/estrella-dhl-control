"""test_customer_resolution_authority.py — packing-upload Customer Master
selection outranks proforma free-text name matching.

When the operator selects a Customer Master client during sales packing
upload, that selection is persisted in ``packing_contractor_resolution``
(status=confirmed, role=client, matched_master_type=customer_master,
matched_master_id=<wFirma bill_to_contractor_id>). Subsequent readiness
checks for a proforma draft on the same batch MUST honor that selection
as authority — VAT/NIP and wFirma contractor_id outrank display name.

These tests pin the operator's [TASK] requirements:
  1. Selected Customer Master contractor resolves readiness even if
     proforma name differs.
  2. Display-name mismatch becomes advisory, not blocker.
  3. Genuinely missing customer remains blocker.
  4. Fuzzy-only match remains review-needed (legacy behaviour preserved).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services.customer_resolution_authority import (
    derive_customer_resolution_via_packing,
)


# ── fixture: minimal customer_master + packing_resolutions schemas ──────────


def _make_dbs(tmp_path: Path) -> tuple[Path, Path]:
    """Create the two SQLite DBs with just enough schema for the helper."""
    cm = tmp_path / "customer_master.sqlite"
    pr = tmp_path / "packing_resolutions.sqlite"

    # customer_master subset
    with sqlite3.connect(str(cm)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
                id                      INTEGER PRIMARY KEY,
                bill_to_contractor_id   TEXT,
                bill_to_name            TEXT,
                country                 TEXT,
                nip                     TEXT,
                vat_eu_number           TEXT,
                vat_eu_valid            INTEGER,
                vat_eu_validated_at     TEXT
            )
        """)

    # packing_contractor_resolution subset (mirrors packing_resolution_db schema)
    with sqlite3.connect(str(pr)) as conn:
        conn.execute("""
            CREATE TABLE packing_contractor_resolution (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id             TEXT NOT NULL,
                role                 TEXT NOT NULL,
                parsed_name          TEXT,
                parsed_tax_id        TEXT,
                parsed_country       TEXT,
                matched_master_type  TEXT,
                matched_master_id    TEXT,
                matched_wfirma_id    TEXT,
                tier                 INTEGER,
                confidence           REAL,
                reason               TEXT,
                evidence_json        TEXT,
                candidates_json      TEXT,
                status               TEXT NOT NULL,
                operator_override    INTEGER,
                operator_user        TEXT,
                operator_at          TEXT,
                created_at           TEXT,
                updated_at           TEXT,
                UNIQUE(batch_id, role)
            )
        """)
    return cm, pr


def _seed_customer_master(
    cm: Path, *, id_: int, contractor_id: str, name: str,
    nip: str = "", country: str = "",
) -> None:
    with sqlite3.connect(str(cm)) as conn:
        conn.execute(
            "INSERT INTO customer_master "
            "(id, bill_to_contractor_id, bill_to_name, country, nip) "
            "VALUES (?, ?, ?, ?, ?)",
            (id_, contractor_id, name, country, nip),
        )


def _seed_packing_resolution(
    pr: Path, *, batch_id: str, role: str, status: str,
    matched_master_type: str = "customer_master",
    matched_master_id: str = "",
    parsed_name: str = "", parsed_tax_id: str = "",
    parsed_country: str = "",
) -> None:
    with sqlite3.connect(str(pr)) as conn:
        conn.execute(
            "INSERT INTO packing_contractor_resolution "
            "(batch_id, role, parsed_name, parsed_tax_id, parsed_country, "
            "matched_master_type, matched_master_id, status, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-05-22', '2026-05-22')",
            (batch_id, role, parsed_name, parsed_tax_id, parsed_country,
             matched_master_type, matched_master_id, status),
        )


BATCH = "SHIPMENT_4218922912_2026-05_9040dd39"


# ── 1. Packing-master selection resolves even when proforma name differs ────


def test_packing_master_selection_resolves_with_name_mismatch(tmp_path):
    """The DiamondGroup GmbH ↔ DG GmbH scenario from production.

    Proforma draft client_name: "DiamondGroup GmbH"
    Packing-upload selection:   "DG GmbH" (NIP DE266491614)
    customer_master row:        bill_to_name="DG GmbH", bill_to_contractor_id="52808306"

    Expected: resolved via packing_master, wfirma_customer_id="52808306",
    advisory note describing the name mismatch.
    """
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(
        cm, id_=34, contractor_id="52808306", name="DG GmbH",
        nip="DE266491614", country="DE",
    )
    _seed_packing_resolution(
        pr, batch_id=BATCH, role="client", status="confirmed",
        matched_master_id="52808306",
        parsed_name="DG GmbH", parsed_tax_id="DE266491614", parsed_country="DE",
    )

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="DiamondGroup GmbH",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is not None
    assert r["wfirma_customer_id"]   == "52808306"
    assert r["resolved_master_name"] == "DG GmbH"
    assert r["customer_master_id"]   == 34
    assert r["match_strategy"]       == "packing_master"
    assert r["advisory"], "expected an advisory note for proforma↔master name mismatch"


# ── 2. Display-name mismatch advisory includes both names + contractor_id ───


def test_display_name_mismatch_advisory_names_both_sides_and_contractor(tmp_path):
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(
        cm, id_=34, contractor_id="52808306", name="DG GmbH",
        nip="DE266491614", country="DE",
    )
    _seed_packing_resolution(
        pr, batch_id=BATCH, role="client", status="confirmed",
        matched_master_id="52808306",
        parsed_name="DG GmbH", parsed_tax_id="DE266491614",
    )

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="DiamondGroup GmbH",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is not None
    adv = r["advisory"]
    assert "DiamondGroup GmbH" in adv  # proforma side
    assert "DG GmbH"            in adv  # master side
    assert "52808306"           in adv  # wFirma contractor_id
    assert "DE266491614"        in adv  # NIP (authority signal)
    assert "VAT/contractor_id outrank display name" in adv


# ── 3. Names match exactly → no advisory ────────────────────────────────────


def test_no_advisory_when_proforma_name_matches_master_exactly(tmp_path):
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(
        cm, id_=29, contractor_id="104677702", name="Verhoeven Joaillier",
        nip="FR90333134013", country="FR",
    )
    _seed_packing_resolution(
        pr, batch_id=BATCH, role="client", status="confirmed",
        matched_master_id="104677702",
        parsed_name="Verhoeven Joaillier",
    )

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="Verhoeven Joaillier",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is not None
    assert r["wfirma_customer_id"] == "104677702"
    assert r["advisory"] == "", (
        f"no advisory expected when names match exactly; got {r['advisory']!r}"
    )


# ── 4. Genuinely missing customer (no packing row) → returns None ───────────


def test_returns_none_when_no_packing_resolution_for_batch(tmp_path):
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(
        cm, id_=99, contractor_id="999", name="Some Other Co",
    )
    # No packing_contractor_resolution row for this batch.

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="Panakas",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is None, (
        "missing packing row must return None so callers fall through "
        "to name-based resolution (and ultimately blocker if nothing matches)"
    )


# ── 5. Packing row exists but status is NOT confirmed → returns None ────────


def test_packing_resolution_pending_status_does_not_short_circuit(tmp_path):
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(
        cm, id_=34, contractor_id="52808306", name="DG GmbH",
    )
    _seed_packing_resolution(
        pr, batch_id=BATCH, role="client", status="pending",
        matched_master_id="52808306",
        parsed_name="DG GmbH",
    )

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="DiamondGroup GmbH",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is None, "only status='confirmed' may assert packing-master authority"


# ── 6. Supplier-role packing row does NOT resolve a client ──────────────────


def test_supplier_role_packing_row_does_not_resolve_client(tmp_path):
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(cm, id_=5, contractor_id="111", name="Estrella Jewels LLP.")
    _seed_packing_resolution(
        pr, batch_id=BATCH, role="supplier", status="confirmed",
        matched_master_id="111",
        parsed_name="ESTRELLA JEWELS LLP.",
    )

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="Estrella Jewels LLP.",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is None, "supplier-role rows must not resolve client identity"


# ── 7. Packing matched_master_type other than customer_master → None ────────


def test_non_customer_master_type_does_not_resolve(tmp_path):
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(cm, id_=34, contractor_id="52808306", name="DG GmbH")
    _seed_packing_resolution(
        pr, batch_id=BATCH, role="client", status="confirmed",
        matched_master_type="suppliers",  # wrong table
        matched_master_id="52808306",
        parsed_name="DG GmbH",
    )

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="DiamondGroup GmbH",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is None


# ── 8. customer_master row missing bill_to_contractor_id → None ─────────────


def test_missing_wfirma_contractor_id_does_not_assert_authority(tmp_path):
    """Without a wFirma contractor_id the proforma cannot post anywhere;
    the resolver must NOT assert packing-master authority in that case —
    falls through so the name-based resolver and downstream review path
    can surface a meaningful blocker."""
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(
        cm, id_=99, contractor_id="", name="No-wFirma-Yet GmbH",
    )
    _seed_packing_resolution(
        pr, batch_id=BATCH, role="client", status="confirmed",
        matched_master_id="",  # also empty
        parsed_name="No-wFirma-Yet GmbH",
    )

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="No-wFirma-Yet GmbH",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is None


# ── 9. Missing batch_id / missing DB file → None (defensive) ────────────────


def test_empty_batch_id_returns_none(tmp_path):
    cm, pr = _make_dbs(tmp_path)
    r = derive_customer_resolution_via_packing(
        batch_id="", client_name="X",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is None


def test_missing_packing_db_returns_none(tmp_path):
    cm, _ = _make_dbs(tmp_path)
    missing = tmp_path / "does-not-exist.sqlite"
    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="X",
        customer_master_db_path=cm, packing_resolution_db_path=missing,
    )
    assert r is None


# ── 10. matched_master_id as numeric customer_master.id fallback ────────────


def test_numeric_master_id_fallback_to_customer_master_pk(tmp_path):
    """Defensive: if packing_resolution stores customer_master.id (the PK
    surrogate) rather than the bill_to_contractor_id, the helper still
    resolves by trying the PK lookup as fallback."""
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(cm, id_=34, contractor_id="52808306", name="DG GmbH")
    _seed_packing_resolution(
        pr, batch_id=BATCH, role="client", status="confirmed",
        matched_master_id="34",  # PK, not bill_to_contractor_id
        parsed_name="DG GmbH",
    )
    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="DiamondGroup GmbH",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is not None
    assert r["customer_master_id"]   == 34
    assert r["wfirma_customer_id"]   == "52808306"


# ── 11. Source-grep: routes_proforma._resolve_customer wires the authority ──


def test_routes_proforma_resolve_customer_wires_packing_authority():
    """Pin that _resolve_customer in routes_proforma.py imports + calls the
    new authority helper. Without this wiring the helper is dead code."""
    routes = _svc / "app" / "api" / "routes_proforma.py"
    src = routes.read_text(encoding="utf-8")
    # 1. Imports the helper
    assert "from ..services.customer_resolution_authority import" in src
    assert "derive_customer_resolution_via_packing" in src
    # 2. _resolve_customer signature accepts batch_id
    assert "def _resolve_customer(\n    client_name: str,\n    batch_id" in src
    # 3. New match_strategy value is in the output path
    assert '"packing_master"' in src
    # 4. The result dict carries an "advisory" field
    assert '"advisory":' in src
    # 5. _build_preview passes batch_id into _resolve_customer
    assert "_resolve_customer(client_name, batch_id=batch_id)" in src


# ── 12. Source-grep: helper never writes ────────────────────────────────────


def test_authority_helper_is_read_only():
    """The helper must never INSERT/UPDATE/DELETE anything. Pure read."""
    helper = _svc / "app" / "services" / "customer_resolution_authority.py"
    src = helper.read_text(encoding="utf-8")
    for forbidden in ("INSERT", "UPDATE ", "DELETE ", "DROP ", "REPLACE INTO"):
        assert forbidden not in src.upper(), (
            f"customer_resolution_authority must be read-only; found {forbidden!r}"
        )
