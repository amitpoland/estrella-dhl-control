"""
Box Profile master authority tests.

The canonical Box Master is the existing box_types table in master_data.sqlite
(master_data_db.py) + routes_box_types.py — this suite pins the 2026-07-06
extension: carrier / max_weight_kg / package_type / sort_order fields, the
insert-only default seed, sort ordering, deactivate-not-delete, and the
Master Data management UI + AWB modal source contracts.

No live DHL calls. All DBs under tmp_path.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from app.api import routes_box_types as rbt
from app.services.master_data_db import (
    DEFAULT_BOX_PROFILES,
    init_db,
    get_box_type_by_code,
    list_box_types,
    seed_default_box_types,
    upsert_box_type,
)

V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "master_data.sqlite"
    init_db(p)
    return p


# ── extended fields roundtrip ─────────────────────────────────────────────────


class TestExtendedFields:
    def test_new_fields_roundtrip(self, db):
        upsert_box_type(db, {
            "code": "DHL-TEST", "name": "Test Box", "carrier": "DHL",
            "length_cm": 25, "width_cm": 20, "height_cm": 3,
            "tare_weight_kg": 0.1, "max_weight_kg": 2.0,
            "package_type": "jewellery", "sort_order": 5,
        })
        rec = get_box_type_by_code(db, "DHL-TEST")
        assert rec.carrier == "DHL"
        assert rec.max_weight_kg == 2.0
        assert rec.package_type == "jewellery"
        assert rec.sort_order == 5

    def test_update_preserves_new_fields(self, db):
        upsert_box_type(db, {"code": "B1", "carrier": "DHL", "sort_order": 3,
                             "package_type": "ring", "max_weight_kg": 1.5})
        upsert_box_type(db, {"code": "B1", "carrier": "DHL", "sort_order": 4,
                             "package_type": "ring", "max_weight_kg": 1.5,
                             "name": "Renamed"})
        rec = get_box_type_by_code(db, "B1")
        assert rec.name == "Renamed"
        assert rec.sort_order == 4

    def test_migration_adds_columns_to_legacy_table(self, tmp_path):
        """A pre-extension box_types table gains the new columns at init_db."""
        p = tmp_path / "legacy.sqlite"
        with sqlite3.connect(str(p)) as conn:
            conn.execute("""
                CREATE TABLE box_types (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE, name TEXT,
                    length_cm REAL, width_cm REAL, height_cm REAL,
                    tare_weight_kg REAL, active INTEGER NOT NULL DEFAULT 1,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
            conn.execute("INSERT INTO box_types (code, name) VALUES ('OLD', 'Legacy row')")
        init_db(p)
        cols = [c[1] for c in sqlite3.connect(str(p)).execute("PRAGMA table_info(box_types)")]
        for c in ("carrier", "max_weight_kg", "package_type", "sort_order"):
            assert c in cols
        rec = get_box_type_by_code(p, "OLD")   # legacy row preserved
        assert rec is not None and rec.sort_order == 0


# ── ordering + deactivate ─────────────────────────────────────────────────────


class TestListOrdering:
    def test_list_orders_by_sort_order_then_code(self, db):
        upsert_box_type(db, {"code": "ZZZ", "sort_order": 1})
        upsert_box_type(db, {"code": "AAA", "sort_order": 2})
        upsert_box_type(db, {"code": "MMM", "sort_order": 1})
        codes = [b.code for b in list_box_types(db)]
        assert codes == ["MMM", "ZZZ", "AAA"]

    def test_deactivate_keeps_row_but_leaves_active_list(self, db):
        upsert_box_type(db, {"code": "GONE", "active": True})
        upsert_box_type(db, {"code": "GONE", "active": False})
        assert all(b.code != "GONE" for b in list_box_types(db, active=True))
        assert any(b.code == "GONE" for b in list_box_types(db, active=None))


# ── seed defaults ─────────────────────────────────────────────────────────────


class TestSeedDefaults:
    def test_seed_creates_all_four_profiles(self, db):
        created = seed_default_box_types(db)
        assert sorted(created) == sorted(
            [p["code"] for p in DEFAULT_BOX_PROFILES]
        )
        assert {"DHL-JEWEL-S", "DHL-RING", "DHL-BRACELET", "CUSTOM"} <= set(created)

    def test_seed_is_idempotent(self, db):
        seed_default_box_types(db)
        assert seed_default_box_types(db) == []

    def test_seed_never_overwrites_operator_edits(self, db):
        seed_default_box_types(db)
        upsert_box_type(db, {"code": "DHL-RING", "name": "Operator renamed",
                             "length_cm": 99})
        seed_default_box_types(db)
        rec = get_box_type_by_code(db, "DHL-RING")
        assert rec.name == "Operator renamed"
        assert rec.length_cm == 99

    def test_seed_skips_inactive_existing_rows(self, db):
        upsert_box_type(db, {"code": "CUSTOM", "active": False})
        created = seed_default_box_types(db)
        assert "CUSTOM" not in created
        # still inactive — operator's choice untouched
        assert all(b.code != "CUSTOM" for b in list_box_types(db, active=True))

    def test_custom_profile_has_no_dims(self, db):
        seed_default_box_types(db)
        rec = get_box_type_by_code(db, "CUSTOM")
        assert rec.length_cm is None and rec.width_cm is None and rec.height_cm is None


# ── route contract ────────────────────────────────────────────────────────────


class TestRouteContract:
    def test_list_response_includes_extended_fields(self, db):
        seed_default_box_types(db)
        with patch.object(rbt, "_DB_PATH", db):
            resp = rbt.list_box_types_endpoint(active=None, limit=200)
        import json
        data = json.loads(resp.body)
        assert data["count"] == 4
        first = data["box_types"][0]
        for key in ("code", "name", "carrier", "length_cm", "width_cm", "height_cm",
                    "tare_weight_kg", "max_weight_kg", "package_type", "sort_order",
                    "active", "notes"):
            assert key in first

    @pytest.mark.anyio
    async def test_seed_endpoint_insert_only(self, db):
        class _Req:  # minimal Request stand-in for audit_safe
            headers = {}
            client = None
            url = type("U", (), {"path": "/api/v1/box-types/seed-defaults"})()
            method = "POST"
        with patch.object(rbt, "_DB_PATH", db), \
             patch.object(rbt, "audit_safe", lambda *a, **k: None):
            r1 = await rbt.seed_default_box_types_endpoint(_Req())
            r2 = await rbt.seed_default_box_types_endpoint(_Req())
        import json
        assert json.loads(r1.body)["count"] == 4
        assert json.loads(r2.body)["count"] == 0


# ── frontend source pins ──────────────────────────────────────────────────────


class TestMasterPagePins:
    def _src(self):
        return (V2 / "master-page.jsx").read_text(encoding="utf-8")

    def test_box_profiles_entity_registered(self):
        src = self._src()
        assert "'box_profiles'" in src
        assert "Box Profiles" in src

    def test_management_loads_all_records_from_backend(self):
        assert "PzApi.listBoxTypes('all')" in self._src()

    def test_edit_modal_and_save_wired(self):
        src = self._src()
        assert "BoxProfileEditModal" in src
        assert "PzApi.upsertBoxType" in src
        assert 'data-testid="btn-save-box-profile"' in src

    def test_seed_button_present(self):
        assert 'data-testid="btn-seed-box-defaults"' in self._src()

    def test_new_box_profile_button_enabled_path(self):
        assert "+ New Box Profile" in self._src()


class TestAwbModalPins:
    def _src(self):
        return (V2 / "proforma-detail.jsx").read_text(encoding="utf-8")

    def test_modal_loads_profiles_from_backend_authority(self):
        src = self._src()
        assert "PzApi.listBoxTypes" in src        # backend Box Master
        assert "handleBoxSelect" in src           # selection auto-fills dims

    def test_manual_override_supported(self):
        src = self._src()
        assert "handleDimChange" in src           # manual dim edits allowed
        assert "boxOverridden" in src

    def test_box_code_persisted_with_shipment(self):
        assert "box_type_code:" in self._src()

    def test_no_hardcoded_size_options(self):
        """Profiles must come from the backend — never a hardcoded S/M/L list."""
        src = self._src()
        for hardcoded in ("Small (", "Medium (", "Large (",
                          ">Small<", ">Medium<", ">Large<"):
            assert hardcoded not in src

    def test_logistics_tab_shows_box_profile(self):
        src = self._src()
        assert "pf-logistics-awb-box" in src
        assert "box_type_code" in src
