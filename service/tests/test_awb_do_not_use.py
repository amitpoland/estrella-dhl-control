"""
Local AWB do-not-use / duplicate-label control — 2026-07-06.

This is a LOCAL operational status, explicitly NOT a DHL cancellation or
void (no DHL cancellation API exists for these shipments and none is called).

Pins:
  - mark_do_not_use stores reason + timestamp + operator (audit trail) and
    touches NOTHING else — tracking_ref, state, mode all unchanged
  - the mark endpoint requires a reason, 404s on unknown AWBs, and reports
    dhl_api_called=False; no httpx client is ever constructed while marking
  - primary label/waybill/receipt downloads return 409 once marked;
    ?archived=true still serves the PDF (audit) with an ARCHIVED-DUPLICATE
    filename; the PDF file itself is never deleted
  - a different, unmarked AWB in the same batch stays downloadable
  - GET + replayed POST shipment responses carry the do_not_use fields
  - UI pins: exact confirmation text, red badge text, mark buttons, and the
    archived-download variant in Logistics / Documents / AWB modal

No live DHL calls. All storage under tmp_path.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api import routes_carrier_actions as rca
from app.services.carrier.adapters.live import _save_shipment_documents
from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
)
from app.services.carrier.persistence import shipment_db


JSX = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"
API_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "pz-api.js"

BATCH = "SHIPMENT_DNU_2026-07_abcd1234"
REF = "7010522735"
OTHER_REF = "6354321691"
_B64 = base64.b64encode(b"%PDF-1.4 dnu test doc").decode()

CONFIRM_TEXT = (
    "This does not cancel anything at DHL. "
    "It only marks this label as not to be used or handed to courier."
)
BADGE_TEXT = "DO NOT USE — duplicate/unused label"


def _fake_settings(tmp_path):
    mock = MagicMock()
    mock.carrier_storage_root = None
    mock.storage_root = tmp_path
    return mock


@contextmanager
def _storage(tmp_path):
    with patch("app.core.config.settings", _fake_settings(tmp_path)):
        yield


def _db(tmp_path) -> Path:
    root = tmp_path / "carrier"
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "carrier_shipments.db"
    shipment_db.init_db(db_path)
    return db_path


def _seed_shipment(db_path: Path, key: str, ref: str) -> None:
    """One recorded SHADOW→COMPLETE shipment whose tracking_ref is stored."""
    result = ShipmentResult(
        idempotency_key=key, mode=ShipmentMode.SHADOW,
        state=ShipmentState.PENDING, simulated=True,
    )
    shipment_db.insert_shipment(db_path, result, BATCH)
    shipment_db.update_state(
        db_path, key, ShipmentState.COMPLETE, tracking_ref=ref,
    )


def _dhl_response(ref=REF):
    return {
        "shipmentTrackingNumber": ref,
        "documents": [
            {"typeCode": t, "imageFormat": "PDF", "content": _B64}
            for t in ("label", "waybillDoc", "receipt")
        ],
    }


# ── DB layer ──────────────────────────────────────────────────────────────────


class TestMarkDoNotUseDb:
    def test_mark_stores_reason_timestamp_operator(self, tmp_path):
        db = _db(tmp_path)
        _seed_shipment(db, "key-1", REF)
        marked = shipment_db.mark_do_not_use(db, BATCH, REF, "duplicate of other AWB",
                                             operator="amit")
        assert marked == 1
        info = shipment_db.get_do_not_use(db, BATCH, REF)
        assert info["do_not_use"] == 1
        assert info["do_not_use_reason"] == "duplicate of other AWB"
        assert info["do_not_use_at"]            # timestamp written
        assert info["do_not_use_by"] == "amit"

    def test_mark_preserves_tracking_ref_state_mode(self, tmp_path):
        """Audit trail: marking must not alter the real booking record."""
        db = _db(tmp_path)
        _seed_shipment(db, "key-1", REF)
        before = shipment_db.get_shipment(db, "key-1")
        shipment_db.mark_do_not_use(db, BATCH, REF, "duplicate")
        after = shipment_db.get_shipment(db, "key-1")
        assert after["tracking_ref"] == before["tracking_ref"] == REF
        assert after["state"] == before["state"]
        assert after["mode"] == before["mode"]

    def test_empty_reason_marks_nothing(self, tmp_path):
        db = _db(tmp_path)
        _seed_shipment(db, "key-1", REF)
        assert shipment_db.mark_do_not_use(db, BATCH, REF, "   ") == 0
        assert shipment_db.get_do_not_use(db, BATCH, REF)["do_not_use"] == 0

    def test_unknown_ref_marks_nothing(self, tmp_path):
        db = _db(tmp_path)
        _seed_shipment(db, "key-1", REF)
        assert shipment_db.mark_do_not_use(db, BATCH, "9999999999", "x") == 0

    def test_other_awb_in_same_batch_not_marked(self, tmp_path):
        db = _db(tmp_path)
        _seed_shipment(db, "key-1", REF)
        _seed_shipment(db, "key-2", OTHER_REF)
        shipment_db.mark_do_not_use(db, BATCH, REF, "duplicate")
        assert shipment_db.get_do_not_use(db, BATCH, OTHER_REF)["do_not_use"] == 0


# ── Mark endpoint ─────────────────────────────────────────────────────────────


class TestMarkEndpoint:
    def test_mark_returns_flag_and_never_calls_dhl(self, tmp_path):
        db = _db(tmp_path)
        _seed_shipment(db, "key-1", REF)
        with _storage(tmp_path), patch("httpx.Client") as mock_cls:
            resp = rca.mark_shipment_do_not_use(
                BATCH, REF, rca.DoNotUseBody(reason="duplicate label", operator="amit"),
                _auth=None, db_path=db,
            )
        import json
        payload = json.loads(resp.body)
        assert payload["do_not_use"] is True
        assert payload["do_not_use_reason"] == "duplicate label"
        assert payload["do_not_use_by"] == "amit"
        assert payload["dhl_api_called"] is False
        assert payload["tracking_ref"] == REF        # real AWB unchanged
        mock_cls.assert_not_called()                 # no DHL API call, ever

    def test_reason_required(self, tmp_path):
        db = _db(tmp_path)
        _seed_shipment(db, "key-1", REF)
        with _storage(tmp_path):
            with pytest.raises(HTTPException) as exc:
                rca.mark_shipment_do_not_use(
                    BATCH, REF, rca.DoNotUseBody(reason="  "), _auth=None, db_path=db,
                )
        assert exc.value.status_code == 422

    def test_unknown_shipment_404(self, tmp_path):
        db = _db(tmp_path)
        with _storage(tmp_path):
            with pytest.raises(HTTPException) as exc:
                rca.mark_shipment_do_not_use(
                    BATCH, "9999999999", rca.DoNotUseBody(reason="x"),
                    _auth=None, db_path=db,
                )
        assert exc.value.status_code == 404


# ── Download gating ───────────────────────────────────────────────────────────


class TestDownloadGating:
    def _seed(self, tmp_path):
        db = _db(tmp_path)
        _seed_shipment(db, "key-1", REF)
        _seed_shipment(db, "key-2", OTHER_REF)
        _save_shipment_documents(_dhl_response(REF), BATCH, REF, _fake_settings(tmp_path))
        _save_shipment_documents(_dhl_response(OTHER_REF), BATCH, OTHER_REF,
                                 _fake_settings(tmp_path))
        return db

    @pytest.mark.parametrize("fn", [
        rca.download_label, rca.download_waybill_doc, rca.download_shipment_receipt,
    ])
    def test_primary_download_blocked_when_marked(self, tmp_path, fn):
        db = self._seed(tmp_path)
        shipment_db.mark_do_not_use(db, BATCH, REF, "duplicate")
        with _storage(tmp_path):
            with pytest.raises(HTTPException) as exc:
                fn(BATCH, REF, _auth=None)
        assert exc.value.status_code == 409
        assert "DO NOT USE" in str(exc.value.detail)
        assert "archived" in str(exc.value.detail)

    def test_archived_download_still_served_for_audit(self, tmp_path):
        db = self._seed(tmp_path)
        shipment_db.mark_do_not_use(db, BATCH, REF, "duplicate")
        with _storage(tmp_path):
            resp = rca.download_label(BATCH, REF, archived=True, _auth=None)
        assert resp.media_type == "application/pdf"
        assert resp.body.startswith(b"%PDF")
        assert f'filename="ARCHIVED-DUPLICATE-AWB-{REF}.pdf"' in resp.headers["content-disposition"]
        assert "no-store" in resp.headers["cache-control"]

    def test_label_pdf_never_deleted_by_marking(self, tmp_path):
        db = self._seed(tmp_path)
        label = tmp_path / "carrier" / "labels" / f"{BATCH}-{REF}.pdf"
        assert label.is_file()
        shipment_db.mark_do_not_use(db, BATCH, REF, "duplicate")
        assert label.is_file()                      # preserved for audit

    def test_active_awb_still_downloadable(self, tmp_path):
        """Marking one duplicate must not touch the batch's real AWB."""
        db = self._seed(tmp_path)
        shipment_db.mark_do_not_use(db, BATCH, REF, "duplicate")
        with _storage(tmp_path):
            resp = rca.download_label(BATCH, OTHER_REF, _auth=None)
        assert resp.media_type == "application/pdf"
        assert f'filename="AWB-{OTHER_REF}.pdf"' in resp.headers["content-disposition"]

    def test_unmarked_download_unchanged(self, tmp_path):
        self._seed(tmp_path)
        with _storage(tmp_path):
            resp = rca.download_label(BATCH, REF, _auth=None)
        assert resp.media_type == "application/pdf"
        assert f'filename="AWB-{REF}.pdf"' in resp.headers["content-disposition"]


# ── Response contract ─────────────────────────────────────────────────────────


class TestResponseContract:
    def test_get_shipment_carries_do_not_use_fields(self, tmp_path):
        db = _db(tmp_path)
        _seed_shipment(db, "key-1", REF)
        shipment_db.mark_do_not_use(db, BATCH, REF, "duplicate", operator="amit")
        with _storage(tmp_path):
            resp = rca.get_shipment(BATCH, _auth=None, _config=None, db_path=db)
        import json
        payload = json.loads(resp.body)
        assert payload["do_not_use"] is True
        assert payload["do_not_use_reason"] == "duplicate"
        assert payload["do_not_use_by"] == "amit"
        assert payload["do_not_use_at"]

    def test_replayed_post_carries_flag_without_dhl_call(self, tmp_path):
        """Replay of a marked shipment reports the flag with zero rebooking."""
        (tmp_path / "carrier").mkdir(parents=True, exist_ok=True)
        coord = CarrierCoordinator(CoordinatorConfig(
            carrier_config=CarrierConfig(
                status="live", api_key="k", api_secret="s",
                api_url="https://express.api.dhl.com", use_sandbox=False,
                account_number="427294774", live_allowlist="*",
            ),
            shipment_db_path=tmp_path / "carrier" / "carrier_shipments.db",
            shadow_log_db_path=tmp_path / "carrier" / "shadow_log.db",
        ))
        req = ShipmentRequest(
            batch_id=BATCH, shipper_account="427294774",
            recipient_address={
                "name": "Test", "street": "Gedimino 1", "city": "Vilnius",
                "postal_code": "01000", "country_code": "LT",
                "phone": "+37060000000",
            },
            declared_value=100.0, currency="EUR", weight_kg=1.0,
            dimensions={"length_cm": 10, "width_cm": 10, "height_cm": 10},
            product_code="U",
        )
        rates = MagicMock(); rates.is_success = True
        rates.json.return_value = {"products": [{"productCode": "U"}]}
        ship = MagicMock(); ship.is_success = True
        ship.json.return_value = _dhl_response()

        with _storage(tmp_path), patch("httpx.Client") as mock_cls:
            client = mock_cls.return_value.__enter__.return_value
            client.get.return_value = rates
            client.post.return_value = ship
            first = coord.create_shipment(req)
            shipment_db.mark_do_not_use(
                tmp_path / "carrier" / "carrier_shipments.db",
                BATCH, first.tracking_ref, "duplicate",
            )
            replay = coord.create_shipment(req)
            info = rca._do_not_use_info(BATCH, replay.tracking_ref)

        assert client.post.call_count == 1           # no rebooking, no DHL void
        assert replay.replayed is True
        assert info["do_not_use"] is True
        assert info["do_not_use_reason"] == "duplicate"


# ── UI source pins ────────────────────────────────────────────────────────────


class TestUiPins:
    def _src(self):
        return JSX.read_text(encoding="utf-8")

    def test_exact_confirmation_text(self):
        assert CONFIRM_TEXT in self._src()

    def test_red_badge_text_on_all_surfaces(self):
        src = self._src()
        assert src.count(BADGE_TEXT) >= 3            # modal + logistics + documents
        assert "awb-dnu-badge" in src                # modal result card
        assert "pf-logistics-awb-dnu-badge" in src   # Logistics tab
        assert "pf-doc-dnu-" in src                  # Documents tab rows

    def test_mark_button_present(self):
        src = self._src()
        assert "Mark as Do Not Use" in src
        assert "pf-logistics-awb-mark-dnu" in src
        assert "awb-mark-dnu" in src

    def test_archived_download_variant(self):
        src = self._src()
        assert "Archived duplicate label" in src
        assert "?archived=true" in src

    def test_api_wrapper_is_local_only(self):
        api = API_JS.read_text(encoding="utf-8")
        assert "markCarrierShipmentDoNotUse" in api
        assert "/do-not-use" in api

    def test_reason_prompt_required_for_audit(self):
        assert "Reason (required, stored for audit" in self._src()
