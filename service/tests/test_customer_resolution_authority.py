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


# ── 13. Lesson-A real-shape test: INTEGER matched_master_id (production) ────


def test_integer_matched_master_id_resolves_correctly(tmp_path):
    """Lesson A real-shape pin.

    Production ``packing_resolutions.sqlite`` rows carry
    ``matched_master_id`` as INTEGER (SQLite affinity from the
    operator's selection pipeline). The earlier hand-built test rows
    used TEXT strings — those passed but masked an ``AttributeError``
    when the helper called ``.strip()`` on an int. Caught at PR #296
    post-deploy verification on SHIPMENT_4218922912 (matched_master_id
    = 52808306 as int).

    This test pins the polymorphic-input normaliser ``_normalise_matched_
    master_id`` against the actual production type. If the column ever
    flips back to TEXT (or any other type), the normaliser must still
    return a usable str for the customer_master lookup.
    """
    cm, pr = _make_dbs(tmp_path)
    _seed_customer_master(
        cm, id_=34, contractor_id="52808306", name="DG GmbH",
        nip="DE266491614", country="DE",
    )
    # Write the packing row with an INTEGER matched_master_id (not a
    # string) — matches production data.
    with sqlite3.connect(str(pr)) as conn:
        conn.execute(
            "INSERT INTO packing_contractor_resolution "
            "(batch_id, role, parsed_name, parsed_tax_id, parsed_country, "
            "matched_master_type, matched_master_id, status, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-05-22', '2026-05-22')",
            (BATCH, "client", "DG GmbH", "DE266491614", "DE",
             "customer_master", 52808306,  # INT, not "52808306"
             "confirmed"),
        )

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="DiamondGroup GmbH",
        customer_master_db_path=cm, packing_resolution_db_path=pr,
    )
    assert r is not None, (
        "INTEGER matched_master_id must resolve via the normaliser; "
        "if this fails, the .strip() call leaked back into the path"
    )
    assert r["wfirma_customer_id"]   == "52808306"
    assert r["resolved_master_name"] == "DG GmbH"
    assert r["customer_master_id"]   == 34
    assert r["match_strategy"]       == "packing_master"


def test_normaliser_handles_str_int_none_and_other_types():
    """Direct unit test for _normalise_matched_master_id.

    Polymorphic-input normaliser must produce a usable string for
    every shape the column has ever held in production, dev, or test:
      - str (TEXT affinity, original test shape)
      - int (INTEGER affinity, current production shape)
      - None (no match yet)
      - empty string (no match)
      - whitespace-padded string (operator/import artifact)
    """
    from app.services.customer_resolution_authority import (
        _normalise_matched_master_id,
    )
    assert _normalise_matched_master_id(52808306)   == "52808306"
    assert _normalise_matched_master_id("52808306") == "52808306"
    assert _normalise_matched_master_id("  52808306  ") == "52808306"
    assert _normalise_matched_master_id(None) == ""
    assert _normalise_matched_master_id("")   == ""
    # Defensive: anything else still produces a str
    assert _normalise_matched_master_id(b"52808306") == "b'52808306'" or \
           _normalise_matched_master_id(b"52808306").endswith("52808306")


def test_real_shape_via_upsert_resolution_int_master_id(tmp_path):
    """Lesson A integration test: write the packing-resolution row through
    the REAL production helper ``packing_resolution_db.upsert_resolution``
    (not a hand-built SQL INSERT). The verdict carries an INT
    ``matched_master_id`` exactly as ``packing_contractor_resolver``
    would produce it in production.
    """
    from app.services import packing_resolution_db as prdb

    cm, _pr = _make_dbs(tmp_path)
    _seed_customer_master(
        cm, id_=34, contractor_id="52808306", name="DG GmbH",
        nip="DE266491614", country="DE",
    )
    # Use a fresh DB path for upsert_resolution — it calls init_db itself.
    pr_real = tmp_path / "packing_resolutions_real.sqlite"
    verdict = {
        "parsed_name":         "DG GmbH",
        "parsed_tax_id":       "DE266491614",
        "parsed_country":      "DE",
        "matched_master_type": "customer_master",
        "matched_master_id":   52808306,           # INT, like the real resolver
        "matched_wfirma_id":   None,
        "tier":                1,
        "confidence":          1.0,
        "reason":              "atlas_intake_dropdown_pick",
        "evidence":            {"source": "intake_dropdown"},
        "candidates":          [],
        "status":              "confirmed",
    }
    prdb.upsert_resolution(
        pr_real, batch_id=BATCH, role="client", verdict=verdict,
        operator_user="test", status_override="confirmed",
    )

    r = derive_customer_resolution_via_packing(
        batch_id=BATCH, client_name="DiamondGroup GmbH",
        customer_master_db_path=cm, packing_resolution_db_path=pr_real,
    )
    assert r is not None
    assert r["match_strategy"]     == "packing_master"
    assert r["wfirma_customer_id"] == "52808306"
    assert r["customer_master_id"] == 34


# ── 14. PER-DOCUMENT authority chain — primary fix for multi-client batches ─


from app.services.customer_resolution_authority import (
    derive_customer_authority_for_draft,
)


def _make_documents_db(tmp_path):
    """Create a minimal documents.db with sales_documents + shipment_documents."""
    path = tmp_path / "documents.db"
    with sqlite3.connect(str(path)) as conn:
        conn.execute("""
            CREATE TABLE sales_documents (
                id              TEXT PRIMARY KEY,
                batch_id        TEXT,
                document_id     TEXT,
                client_name     TEXT,
                document_type   TEXT,
                source_file_path TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE shipment_documents (
                id                       TEXT PRIMARY KEY,
                batch_id                 TEXT,
                document_type            TEXT,
                file_name                TEXT,
                client_contractor_id     TEXT,
                supplier_contractor_id   TEXT
            )
        """)
    return path


def _seed_sales_packing_doc(
    docs_db, *, batch_id, client_name, ship_doc_id,
    client_contractor_id, file_name, sales_doc_id=None,
):
    """Seed a sales packing list — both sales_documents AND shipment_documents."""
    import uuid
    sd_id = sales_doc_id or str(uuid.uuid4())
    with sqlite3.connect(str(docs_db)) as conn:
        conn.execute(
            "INSERT INTO sales_documents (id, batch_id, document_id, client_name, "
            "document_type, source_file_path) VALUES (?, ?, ?, ?, ?, ?)",
            (sd_id, batch_id, ship_doc_id, client_name,
             "sales_packing_list", file_name),
        )
        conn.execute(
            "INSERT INTO shipment_documents (id, batch_id, document_type, "
            "file_name, client_contractor_id) VALUES (?, ?, ?, ?, ?)",
            (ship_doc_id, batch_id, "sales_packing_list", file_name,
             client_contractor_id),
        )
    return sd_id


def test_per_document_diamond_point_resolves_to_own_contractor(tmp_path):
    """Multi-client batch regression — Diamond Point must resolve to its own
    wFirma contractor (90484280), NOT DG GmbH's contractor (52808306).
    Pinned against the actual SHIPMENT_4218922912 production scenario."""
    cm = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
                id INTEGER PRIMARY KEY, bill_to_contractor_id TEXT,
                bill_to_name TEXT, country TEXT, nip TEXT
            )
        """)
        conn.execute(
            "INSERT INTO customer_master VALUES (7, '90484280', 'Diamond Point B.V.', 'NL', 'NL008494162B01')"
        )
    docs = _make_documents_db(tmp_path)
    _seed_sales_packing_doc(
        docs, batch_id=BATCH, client_name="Diamond Point",
        ship_doc_id="ship-doc-dp", client_contractor_id="90484280",
        file_name="EJL-26-27-177-Shipment packing list-Client.xlsx",
    )

    r = derive_customer_authority_for_draft(
        batch_id=BATCH, client_name="Diamond Point",
        documents_db_path=docs, customer_master_db_path=cm,
    )
    assert r is not None
    assert r["wfirma_customer_id"]   == "90484280", (
        f"Diamond Point must resolve to 90484280 (its own contractor), "
        f"not {r['wfirma_customer_id']!r} — multi-client bug regression"
    )
    assert r["resolved_master_name"] == "Diamond Point B.V."
    assert r["customer_master_id"]   == 7
    assert r["match_strategy"]       == "per_document_upload"


def test_per_document_multi_client_batch_resolves_each_independently(tmp_path):
    """The full SHIPMENT_4218922912 production scenario in one test:
    5 clients on one batch, 5 different sales packing list documents,
    each with its own operator-selected client_contractor_id. Each
    proforma draft must resolve to ITS OWN contractor, not the
    contractor of whichever client happened to be saved in
    packing_contractor_resolution."""
    cm = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
                id INTEGER PRIMARY KEY, bill_to_contractor_id TEXT,
                bill_to_name TEXT, country TEXT, nip TEXT
            )
        """)
        # The 4 production clients that have customer_master rows
        rows = [
            (7,  '90484280',  'Diamond Point B.V.',     'NL', 'NL008494162B01'),
            (34, '52808306',  'DG GmbH',                'DE', 'DE266491614'),
            (60, '145607516', 'Dream Rings, s.r.o.',    'SK', 'SK2023917434'),
            (29, '104677702', 'Verhoeven Joaillier',    'FR', 'FR90333134013'),
        ]
        for r in rows:
            conn.execute("INSERT INTO customer_master VALUES (?,?,?,?,?)", r)

    docs = _make_documents_db(tmp_path)
    seeds = [
        ("Diamond Point",       "ship-dp",  "90484280",   "EJL-26-27-177.xlsx"),
        ("DiamondGroup GmbH",   "ship-dg",  "52808306",   "EJL-26-27-178.xlsx"),
        ("Dream Ring",          "ship-dr",  "145607516",  "EJL-26-27-180-DR.xlsx"),
        ("Verhoeven Joaillier", "ship-vj",  "104677702",  "EJL-26-27-179.xlsx"),
    ]
    for cn, sid, cid, fn in seeds:
        _seed_sales_packing_doc(
            docs, batch_id=BATCH, client_name=cn,
            ship_doc_id=sid, client_contractor_id=cid, file_name=fn,
        )

    expected = {
        "Diamond Point":       "90484280",
        "DiamondGroup GmbH":   "52808306",
        "Dream Ring":          "145607516",
        "Verhoeven Joaillier": "104677702",
    }
    for client_name, expected_contractor in expected.items():
        r = derive_customer_authority_for_draft(
            batch_id=BATCH, client_name=client_name,
            documents_db_path=docs, customer_master_db_path=cm,
        )
        assert r is not None, (
            f"{client_name!r} must resolve via per_document_upload"
        )
        assert r["wfirma_customer_id"] == expected_contractor, (
            f"{client_name!r} expected {expected_contractor}, "
            f"got {r['wfirma_customer_id']!r} — multi-client mis-routing"
        )
        assert r["match_strategy"] == "per_document_upload"


def test_per_document_advisory_on_display_name_mismatch(tmp_path):
    """The DiamondGroup GmbH ↔ DG GmbH case: proforma name differs from
    customer_master.bill_to_name → advisory text MUST mention both names,
    contractor_id, NIP, and the source file (per-document context)."""
    cm = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
                id INTEGER PRIMARY KEY, bill_to_contractor_id TEXT,
                bill_to_name TEXT, country TEXT, nip TEXT
            )
        """)
        conn.execute(
            "INSERT INTO customer_master VALUES (34, '52808306', 'DG GmbH', 'DE', 'DE266491614')"
        )
    docs = _make_documents_db(tmp_path)
    _seed_sales_packing_doc(
        docs, batch_id=BATCH, client_name="DiamondGroup GmbH",
        ship_doc_id="ship-dg", client_contractor_id="52808306",
        file_name="EJL-26-27-178-Client.xlsx",
    )

    r = derive_customer_authority_for_draft(
        batch_id=BATCH, client_name="DiamondGroup GmbH",
        documents_db_path=docs, customer_master_db_path=cm,
    )
    assert r is not None
    adv = r["advisory"]
    assert "DiamondGroup GmbH" in adv
    assert "DG GmbH" in adv
    assert "52808306" in adv
    assert "DE266491614" in adv
    assert "per-document upload selection" in adv
    assert "EJL-26-27-178" in adv  # source file_name surfaces in advisory


def test_per_document_no_advisory_when_names_match(tmp_path):
    """Verhoeven Joaillier: proforma name == master name → no advisory."""
    cm = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
                id INTEGER PRIMARY KEY, bill_to_contractor_id TEXT,
                bill_to_name TEXT, country TEXT, nip TEXT
            )
        """)
        conn.execute(
            "INSERT INTO customer_master VALUES (29, '104677702', 'Verhoeven Joaillier', 'FR', 'FR90333134013')"
        )
    docs = _make_documents_db(tmp_path)
    _seed_sales_packing_doc(
        docs, batch_id=BATCH, client_name="Verhoeven Joaillier",
        ship_doc_id="ship-vj", client_contractor_id="104677702",
        file_name="EJL-26-27-179-Client.xlsx",
    )
    r = derive_customer_authority_for_draft(
        batch_id=BATCH, client_name="Verhoeven Joaillier",
        documents_db_path=docs, customer_master_db_path=cm,
    )
    assert r is not None
    assert r["advisory"] == "", (
        f"no advisory expected when names match; got {r['advisory']!r}"
    )


def test_per_document_no_selection_returns_none(tmp_path):
    """Document exists but operator skipped client selection
    (client_contractor_id is NULL) → must return None so caller falls
    through to name-based resolution."""
    cm = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
                id INTEGER PRIMARY KEY, bill_to_contractor_id TEXT,
                bill_to_name TEXT, country TEXT, nip TEXT
            )
        """)
    docs = _make_documents_db(tmp_path)
    _seed_sales_packing_doc(
        docs, batch_id=BATCH, client_name="UnSelected Client",
        ship_doc_id="ship-x", client_contractor_id="",  # operator skipped
        file_name="some.xlsx",
    )
    r = derive_customer_authority_for_draft(
        batch_id=BATCH, client_name="UnSelected Client",
        documents_db_path=docs, customer_master_db_path=cm,
    )
    assert r is None, "missing client_contractor_id must return None"


def test_per_document_no_sales_doc_returns_none(tmp_path):
    """No sales_packing_list document exists for (batch, client) → None."""
    cm = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
                id INTEGER PRIMARY KEY, bill_to_contractor_id TEXT,
                bill_to_name TEXT, country TEXT, nip TEXT
            )
        """)
    docs = _make_documents_db(tmp_path)
    # No sales packing doc seeded
    r = derive_customer_authority_for_draft(
        batch_id=BATCH, client_name="Some Client",
        documents_db_path=docs, customer_master_db_path=cm,
    )
    assert r is None


def test_per_document_contractor_without_master_record_returns_none(tmp_path):
    """The Panakas case: operator picked a wFirma contractor (128515865)
    but customer_master has no row for it. Must return None — caller falls
    through to name-based resolver which produces a meaningful blocker.
    Operator signal: 'Panakas needs to be added to customer_master'."""
    cm = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
                id INTEGER PRIMARY KEY, bill_to_contractor_id TEXT,
                bill_to_name TEXT, country TEXT, nip TEXT
            )
        """)
        # Note: NO row for contractor 128515865
    docs = _make_documents_db(tmp_path)
    _seed_sales_packing_doc(
        docs, batch_id=BATCH, client_name="Panakas",
        ship_doc_id="ship-panakas", client_contractor_id="128515865",
        file_name="EJL-26-27-180-Panakas.xlsx",
    )
    r = derive_customer_authority_for_draft(
        batch_id=BATCH, client_name="Panakas",
        documents_db_path=docs, customer_master_db_path=cm,
    )
    assert r is None, (
        "wFirma contractor selected but not in customer_master → must "
        "return None so name-based fallback runs (and produces a "
        "meaningful operator-facing blocker)"
    )


def test_per_document_only_sales_packing_list_documents_resolve(tmp_path):
    """Non-sales-packing-list documents (e.g. purchase_invoice) MUST NOT
    resolve via this path — even if they're in sales_documents by accident."""
    cm = tmp_path / "customer_master.sqlite"
    with sqlite3.connect(str(cm)) as conn:
        conn.execute("""
            CREATE TABLE customer_master (
                id INTEGER PRIMARY KEY, bill_to_contractor_id TEXT,
                bill_to_name TEXT, country TEXT, nip TEXT
            )
        """)
        conn.execute(
            "INSERT INTO customer_master VALUES (7, '90484280', 'Diamond Point B.V.', 'NL', 'NL008494162B01')"
        )
    docs = _make_documents_db(tmp_path)
    # Seed an entry with document_type != sales_packing_list
    with sqlite3.connect(str(docs)) as conn:
        conn.execute(
            "INSERT INTO sales_documents (id, batch_id, document_id, "
            "client_name, document_type, source_file_path) "
            "VALUES ('sd-1', ?, 'ship-1', 'Diamond Point', "
            "'commercial_invoice', 'invoice.pdf')",
            (BATCH,)
        )
        conn.execute(
            "INSERT INTO shipment_documents (id, batch_id, document_type, "
            "file_name, client_contractor_id) "
            "VALUES ('ship-1', ?, 'commercial_invoice', 'invoice.pdf', '90484280')",
            (BATCH,)
        )
    r = derive_customer_authority_for_draft(
        batch_id=BATCH, client_name="Diamond Point",
        documents_db_path=docs, customer_master_db_path=cm,
    )
    assert r is None, "only document_type='sales_packing_list' resolves"


def test_per_document_routes_proforma_wires_new_authority():
    """Source-grep: routes_proforma._resolve_customer imports and calls
    the new per-document helper BEFORE the per-batch fallback."""
    routes = _svc / "app" / "api" / "routes_proforma.py"
    src = routes.read_text(encoding="utf-8")
    # Imports new helper
    assert "derive_customer_authority_for_draft" in src
    # New match_strategy value
    assert '"per_document_upload"' in src
    # per-document path is BEFORE per-batch packing-master path
    i_per_doc  = src.find("derive_customer_authority_for_draft")
    i_per_batch = src.find("derive_customer_resolution_via_packing")
    assert 0 < i_per_doc < i_per_batch, (
        "per-document authority must execute BEFORE per-batch fallback "
        "(per-batch is the bug-prone path; per-document is correct)"
    )


def test_per_document_helper_is_read_only():
    """The new helper must never INSERT/UPDATE/DELETE anything."""
    helper = _svc / "app" / "services" / "customer_resolution_authority.py"
    src = helper.read_text(encoding="utf-8")
    # Grep ONLY the per-document function body
    i_start = src.find("def derive_customer_authority_for_draft")
    i_end   = src.find("\n__all__", i_start)
    body = src[i_start:i_end]
    for forbidden in ("INSERT", "UPDATE ", "DELETE ", "DROP ", "REPLACE INTO"):
        assert forbidden not in body.upper(), (
            f"per-document helper must be read-only; found {forbidden!r}"
        )
