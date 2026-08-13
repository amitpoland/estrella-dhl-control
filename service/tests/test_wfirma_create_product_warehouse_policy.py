"""wFirma goods/add must reuse Atlas warehouse authority, not force simple mode.

No live goods/add. HTTP is mocked. Create remains flag-gated elsewhere.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services import reservation_db as rdb
from app.services import wfirma_client as wfc
from app.services.wfirma_client import (
    _build_create_product_xml,
    _resolve_goods_add_warehouse_id,
    create_product,
)


_XML_ADD_OK = """<api>
  <goods>
    <good>
      <id>51619999</id>
      <name>Test good</name>
      <code>EJL/26-27/519-1</code>
      <unit>szt.</unit>
    </good>
  </goods>
  <status><code>OK</code></status>
</api>"""


def _full_settings(**overrides):
    base = {
        "wfirma_access_key": "ACC-KEY-001",
        "wfirma_secret_key": "SEC-KEY-001",
        "wfirma_app_key": "APP-KEY-001",
        "wfirma_company_id": "123456",
        "wfirma_warehouse_module_enabled": True,
        "wfirma_warehouse_id": "WH-CFG-1",
        "wfirma_create_product_allowed": False,
    }
    base.update(overrides)
    return patch.multiple(settings, **base)


def test_create_product_source_does_not_hardcode_warehouse_mode_or_id():
    xml_src = inspect.getsource(_build_create_product_xml)
    emitted = xml_src.split("return f", 1)[1]
    assert "<warehouse_type>" not in emitted
    assert "347088" not in inspect.getsource(create_product)
    assert "347088" not in xml_src
    sig = inspect.signature(create_product)
    assert sig.parameters["warehouse_type"].default is None
    assert sig.parameters["netto"].default == 0.0


def test_xml_omits_warehouse_type_and_stock_qty():
    xml = _build_create_product_xml(
        product_code="EJL/26-27/519-1",
        name="Pierścionek test",
        unit="szt.",
        netto=0.0,
        vat_code_id="222",
        description="locked block",
        warehouse_id="WH-CFG-1",
    )
    assert "<warehouse_type>" not in xml
    assert "<count>" not in xml
    assert "<netto>0.00</netto>" in xml
    assert "<unit>szt.</unit>" in xml
    assert "<code>EJL/26-27/519-1</code>" in xml
    assert "<vat_code><id>222</id></vat_code>" in xml
    assert "<warehouse><id>WH-CFG-1</id></warehouse>" in xml
    assert "simple" not in xml
    assert "extended" not in xml


def test_xml_omits_warehouse_when_id_empty():
    xml = _build_create_product_xml(
        product_code="EJL/X",
        name="Name",
        unit="szt.",
        netto=0.0,
        vat_code_id=None,
        description="",
        warehouse_id="",
    )
    assert "<warehouse>" not in xml
    assert "<warehouse_type>" not in xml


def test_resolve_warehouse_id_uses_settings_not_a_new_constant():
    with _full_settings(wfirma_warehouse_id="WH-CFG-1"):
        assert _resolve_goods_add_warehouse_id(None) == "WH-CFG-1"
        assert _resolve_goods_add_warehouse_id("") == "WH-CFG-1"
        assert _resolve_goods_add_warehouse_id("WH-OVERRIDE") == "WH-OVERRIDE"


def test_create_product_refuses_when_warehouse_module_has_no_id():
    with _full_settings(wfirma_warehouse_id="", wfirma_warehouse_module_enabled=True):
        with pytest.raises(ValueError, match="warehouse"):
            create_product("EJL/26-27/519-1", "Name")


def test_create_product_posts_configured_warehouse_and_ignores_simple():
    captured = {}

    def fake_http(method, module, action, body="", **kwargs):
        captured["method"] = method
        captured["module"] = module
        captured["action"] = action
        captured["body"] = body
        return 200, _XML_ADD_OK

    with _full_settings():
        with patch.object(wfc, "_http_request", side_effect=fake_http):
            result = create_product(
                "EJL/26-27/519-1",
                "Pierścionek test",
                unit="szt.",
                netto=0.0,
                vat_code_id="222",
                warehouse_type="simple",
                description="locked block",
            )

    assert captured["method"] == "POST"
    assert captured["module"] == "goods"
    assert captured["action"] == "add"
    body = captured["body"]
    assert "<warehouse_type>" not in body
    assert "simple" not in body
    assert "extended" not in body
    assert "<warehouse><id>WH-CFG-1</id></warehouse>" in body
    assert "<netto>0.00</netto>" in body
    assert "<count>" not in body
    assert result.wfirma_id == "51619999"


def test_create_product_explicit_warehouse_id_overrides_settings():
    captured = {}

    def fake_http(method, module, action, body="", **kwargs):
        captured["body"] = body
        return 200, _XML_ADD_OK

    with _full_settings(wfirma_warehouse_id="WH-CFG-1"):
        with patch.object(wfc, "_http_request", side_effect=fake_http):
            create_product(
                "EJL/X",
                "Name",
                warehouse_id="WH-OVERRIDE",
            )
    assert "<warehouse><id>WH-OVERRIDE</id></warehouse>" in captured["body"]
    assert "WH-CFG-1" not in captured["body"]


def test_passthrough_does_not_force_simple_and_forwards_warehouse_id():
    fake = MagicMock()
    fake.wfirma_id = "1"
    with patch("app.services.wfirma_client.create_product", return_value=fake) as mock:
        rdb.create_wfirma_product(
            "EJL/26-27/519-1",
            "Name",
            netto=0.0,
            warehouse_id="WH-CFG-1",
        )
    kwargs = mock.call_args.kwargs
    assert kwargs.get("warehouse_type") in (None, "")
    assert kwargs["warehouse_id"] == "WH-CFG-1"
    assert kwargs["netto"] == 0.0
    assert kwargs["unit"] == "szt."
