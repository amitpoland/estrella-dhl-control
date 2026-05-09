"""
test_carrier_routes_read_only.py — DL-C read-only routes for the
outbound carrier registry + label store.

Required coverage:
  1. Route file contains only ``@router.get`` decorators (source-grep).
  2. No ``@router.post/put/patch/delete`` in route file (source-grep).
  3. ``main.py`` mounts ``carrier_router``.
  4. Empty shipment list returns count 0 with ``shipments: []``.
  5. Get shipment by id returns the registry row.
  6. Missing shipment id returns 404.
  7. Get-by-batch returns only that batch.
  8. Transitions endpoint returns the recorded transitions.
  9. Label download returns saved PDF bytes from the label store.
  10. Missing label returns 404.
  11. Path traversal attempt in sha256 is rejected (400 or 404).
  12. Source-grep proves routes_carrier does NOT import the DHL adapter
      or the dhl_express_stub.
  13. Source-grep proves no write-verb decorators appear in the route
      file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_carrier as rc
from app.services.carrier import carrier_label_store as cls
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse


_ROUTE_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "api" / "routes_carrier.py"
)
_MAIN_FILE = (
    Path(__file__).resolve().parents[1] / "app" / "main.py"
)


@pytest.fixture(scope="module")
def route_src() -> str:
    return _ROUTE_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def main_src() -> str:
    return _MAIN_FILE.read_text(encoding="utf-8")


@pytest.fixture()
def client(tmp_path):
    """A FastAPI TestClient with isolated carrier DB + label store."""
    csdb.init_db(tmp_path / "carrier.db")
    cls.init_store(tmp_path / "carrier_labels")
    app = FastAPI()
    app.include_router(rc.router)
    return TestClient(app, raise_server_exceptions=True)


# ── 1+13. Route file is read-only by source-grep ────────────────────────────

def test_route_file_only_has_get_decorators(route_src):
    """Every ``@router.<verb>`` in the route file must be ``.get``."""
    decorators = re.findall(r"@router\.(get|post|put|patch|delete)\b", route_src)
    assert decorators, "no @router.* decorators found in routes_carrier.py"
    for verb in decorators:
        assert verb == "get", (
            f"non-GET verb @router.{verb} found in routes_carrier.py — "
            f"DL-C must remain read-only."
        )


@pytest.mark.parametrize("verb", ["post", "put", "patch", "delete"])
def test_route_file_has_no_write_verbs(route_src, verb):
    pattern = re.compile(rf"@router\.{verb}\b")
    assert not pattern.search(route_src), (
        f"@router.{verb} found in routes_carrier.py — DL-C is read-only."
    )


# ── 2. Adapter independence ─────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "dhl_express_stub",
    "DHLExpressStubAdapter",
    "from ..services.carrier.adapters",
    "from .services.carrier.adapters",
    "import dhl",
    "from dhl",
])
def test_route_file_does_not_import_adapter(route_src, forbidden):
    assert forbidden not in route_src, (
        f"routes_carrier.py contains {forbidden!r} — read-only routes "
        f"must not depend on any carrier adapter (live or stub)."
    )


# ── 3. main.py mounts the router ────────────────────────────────────────────

def test_main_imports_carrier_router(main_src):
    assert "from .api.routes_carrier import router as carrier_router" in main_src


def test_main_includes_carrier_router(main_src):
    assert "app.include_router(carrier_router)" in main_src


def test_main_initialises_carrier_db_and_label_store(main_src):
    assert "init_carrier_db" in main_src
    assert "init_carrier_label_store" in main_src


# ── 4. Empty list ──────────────────────────────────────────────────────────

def test_empty_shipments_list(client):
    r = client.get("/api/v1/carrier/shipments")
    assert r.status_code == 200
    body = r.json()
    assert body["shipments"] == []
    assert body["count"] == 0


# ── 5. Get by id ────────────────────────────────────────────────────────────

def test_get_shipment_by_id(client):
    row = csdb.upsert_shipment(
        carrier="dhl", awb="DHLSTUB000001",
        state=cse.PRE_AWB, batch_id="B-DLC-1",
    )
    r = client.get(f"/api/v1/carrier/shipments/{row['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == row["id"]
    assert body["awb"] == "DHLSTUB000001"
    assert body["state"] == cse.PRE_AWB
    assert body["batch_id"] == "B-DLC-1"


# ── 6. 404 on unknown id ────────────────────────────────────────────────────

def test_missing_shipment_returns_404(client):
    r = client.get("/api/v1/carrier/shipments/not-a-uuid")
    assert r.status_code == 404


# ── 7. Get by batch ────────────────────────────────────────────────────────

def test_get_shipments_by_batch(client):
    csdb.upsert_shipment(carrier="dhl", awb="A1", state=cse.PRE_AWB, batch_id="X")
    csdb.upsert_shipment(carrier="dhl", awb="A2", state=cse.PRE_AWB, batch_id="X")
    csdb.upsert_shipment(carrier="dhl", awb="A3", state=cse.PRE_AWB, batch_id="Y")
    r = client.get("/api/v1/carrier/shipments/by-batch/X")
    assert r.status_code == 200
    body = r.json()
    assert body["batch_id"] == "X"
    assert body["count"] == 2
    assert sorted(s["awb"] for s in body["shipments"]) == ["A1", "A2"]


def test_get_shipments_by_batch_empty(client):
    r = client.get("/api/v1/carrier/shipments/by-batch/no-such-batch")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["shipments"] == []


# ── 8. Transitions endpoint ────────────────────────────────────────────────

def test_transitions_endpoint_returns_recorded_history(client):
    row = csdb.upsert_shipment(
        carrier="dhl", awb="T-1", state=cse.PRE_AWB, batch_id="BT",
    )
    csdb.record_transition(
        shipment_id=row["id"], from_state="", to_state=cse.PRE_AWB,
        reason="created",
    )
    csdb.record_transition(
        shipment_id=row["id"], from_state=cse.PRE_AWB,
        to_state=cse.AWB_ISSUED, reason="adapter-ok",
    )
    r = client.get(f"/api/v1/carrier/shipments/{row['id']}/transitions")
    assert r.status_code == 200
    body = r.json()
    assert body["shipment_id"] == row["id"]
    assert body["count"] == 2
    moves = [(t["from_state"], t["to_state"]) for t in body["transitions"]]
    assert moves == [("", cse.PRE_AWB), (cse.PRE_AWB, cse.AWB_ISSUED)]


def test_transitions_404_for_unknown_shipment(client):
    r = client.get("/api/v1/carrier/shipments/no-such-id/transitions")
    assert r.status_code == 404


# ── 9. Label download ──────────────────────────────────────────────────────

def test_label_download_returns_pdf_bytes(client):
    payload = b"%PDF-1.4\nDL-C label test\n%%EOF\n"
    art = cls.save_attachment(payload, suffix="pdf")
    r = client.get(f"/api/v1/carrier/labels/{art.sha256}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == payload
    assert r.headers.get("x-carrier-label-sha256") == art.sha256


def test_label_download_zpl_content_type(client):
    payload = b"^XA^FO50,50^A0N,40,40^FDdl-c^FS^XZ"
    art = cls.save_attachment(payload, suffix="zpl")
    r = client.get(f"/api/v1/carrier/labels/{art.sha256}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.content == payload


def test_label_download_unknown_extension_falls_back(client):
    payload = b"raw bytes no extension"
    art = cls.save_attachment(payload)  # no suffix
    r = client.get(f"/api/v1/carrier/labels/{art.sha256}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"


# ── 10. Missing label returns 404 ──────────────────────────────────────────

def test_missing_label_returns_404(client):
    sha = "0" * 64  # valid hex, no file with this sha
    r = client.get(f"/api/v1/carrier/labels/{sha}")
    assert r.status_code == 404


# ── 11. Path-traversal attempts rejected ───────────────────────────────────

@pytest.mark.parametrize("bad_sha", [
    "../etc/passwd",
    "..%2Fetc%2Fpasswd",
    "/etc/passwd",
    "abcd",                 # too short
    "Z" * 64,               # not hex
    "ABCDEF" + "0" * 58,    # uppercase
    "0" * 63 + "g",         # non-hex char
])
def test_path_traversal_or_bad_shape_rejected(client, bad_sha):
    r = client.get(f"/api/v1/carrier/labels/{bad_sha}")
    # Either 400 (rejected by sha shape check) or 404 (route not
    # matched / not found) is acceptable. NEVER 200.
    assert r.status_code in (400, 404)
    # And the response body MUST NOT contain the bytes of /etc/passwd
    # or any other unexpected disk content.
    assert b"root:" not in r.content
    assert b":/bin/" not in r.content


def test_label_download_state_filter_rejects_unknown_state(client):
    r = client.get("/api/v1/carrier/shipments?state=garbage")
    assert r.status_code == 400


# ── 12. Adapter-import isolation already covered by 2; extra source-grep ──

def test_route_file_does_not_use_requests_or_httpx(route_src):
    for forbidden in ["import requests", "import httpx",
                      "from requests", "from httpx"]:
        assert forbidden not in route_src, (
            f"routes_carrier.py contains {forbidden!r} — read-only "
            f"routes must not perform outbound HTTP."
        )
