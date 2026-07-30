"""
test_circuit_breaker_wrapper_contracts.py — Lesson A boundary tests.

These tests exercise the real wrapper code paths in cliq_service,
wfirma_client, and workdrive_uploader and assert the return-shape
contract holds in BOTH:

- CLOSED-success state (real success-path return type)
- OPEN-fallback state  (circuit-breaker fallback return type)

The contract must be identical in both states so downstream callers
do not need special-case handling. The HTTP boundary is mocked at the
transport layer (httpx / requests); the wrapper code itself is real.

Per Lesson A (network-bound carve-out): substitute a contract test
against the real wrapper signature; mock only the network boundary.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.circuit_breaker import CircuitState, get_circuit_breaker, reset_all


# ── Test isolation ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_circuits():
    """Each test starts with every named circuit CLOSED."""
    reset_all()
    yield
    reset_all()


# ── cliq_service.post_to_channel ──────────────────────────────────────────────

def test_post_to_channel_returns_bool_on_circuit_open():
    """post_to_channel MUST return bool (False) when zoho_cliq circuit is OPEN.

    Downstream callers in batch_manager + dashboard render branch on truthiness;
    a None or tuple here would TypeError or quietly proceed as if posted.
    """
    from app.services import cliq_service

    breaker = get_circuit_breaker("zoho_cliq")
    breaker.force_open()

    result = asyncio.run(cliq_service.post_to_channel("test message"))

    assert isinstance(result, bool), (
        f"post_to_channel must return bool when circuit OPEN; "
        f"got {type(result).__name__}"
    )
    assert result is False


def test_post_to_channel_returns_bool_on_success():
    """post_to_channel CLOSED-success path returns bool (True)."""
    from app.services import cliq_service

    # Stub the inner OAuth + HTTP boundary; wrapper code itself runs.
    async def _ok_post(*_a, **_kw):
        resp = MagicMock()
        resp.status_code = 204
        resp.text = ""
        return resp

    with patch.object(cliq_service, "_get_access_token", return_value="tok"):
        async_ctx = MagicMock()
        async_ctx.__aenter__ = MagicMock(side_effect=lambda: _fake_client())
        # Patch httpx.AsyncClient at the wrapper boundary.
        client_mock = MagicMock()
        client_mock.post = _ok_post

        async def _fake_aenter(self):
            return client_mock

        async def _fake_aexit(self, *a):
            return False

        with patch("app.services.cliq_service.httpx.AsyncClient") as ac:
            ac.return_value.__aenter__ = _fake_aenter
            ac.return_value.__aexit__  = _fake_aexit

            result = asyncio.run(cliq_service.post_to_channel("hello"))

    assert isinstance(result, bool), (
        f"post_to_channel must return bool on success; got {type(result).__name__}"
    )
    assert result is True


def _fake_client():
    """Helper unused by the async-context patcher above; kept for symmetry."""
    return MagicMock()


# ── wfirma_client._http_request ───────────────────────────────────────────────

def test_http_request_returns_tuple_on_circuit_open():
    """_http_request MUST return tuple[int, str] when wfirma circuit is OPEN.

    Every wFirma caller (probe_endpoint, get_product, contractors_find, etc.)
    destructures status, body = _http_request(...). A None or scalar return
    would raise TypeError at the destructure site across dozens of call sites.
    """
    from app.services import wfirma_client

    breaker = get_circuit_breaker("wfirma")
    breaker.force_open()

    # Admission now flows through breaker.call() (the raw ``.state`` fast-path was
    # removed so the breaker can evaluate its recovery timeout), and header
    # construction runs before admission. Stub _headers_for_module so a
    # no-credential test env surfaces the OPEN rejection rather than a missing-
    # cred ValueError. The route is NOT weakened — a forced-OPEN breaker still
    # returns the (503, "circuit_breaker_open") fallback shape asserted below.
    with patch.object(wfirma_client, "_headers_for_module", return_value={}):
        result = wfirma_client._http_request("GET", "contractors", "find")

    assert isinstance(result, tuple), (
        f"_http_request must return tuple when circuit OPEN; "
        f"got {type(result).__name__}"
    )
    assert len(result) == 2
    status, body = result
    assert status == 503
    assert body == "circuit_breaker_open"


def test_http_request_returns_tuple_on_success():
    """_http_request CLOSED-success path returns tuple[int, str]."""
    from app.services import wfirma_client

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = "<api><status><code>OK</code></status></api>"

    # _http_request reads credentials from settings; stub _headers_for_module
    # to avoid requiring real env credentials in unit tests.
    with patch.object(wfirma_client, "_headers_for_module", return_value={}):
        with patch("app.services.wfirma_client._requests.request",
                   return_value=fake_resp):
            result = wfirma_client._http_request(
                "GET", "contractors", "find"
            )

    assert isinstance(result, tuple), (
        f"_http_request must return tuple on success; got {type(result).__name__}"
    )
    assert len(result) == 2
    status, body = result
    assert isinstance(status, int)
    assert isinstance(body, str)
    assert status == 200
    assert "OK" in body


# ── workdrive_uploader.upload_file ────────────────────────────────────────────

def test_upload_file_returns_none_on_circuit_open():
    """upload_file MUST return None when zoho_workdrive circuit is OPEN.

    Downstream callers check `if resource_id:` — a non-None falsy value
    (empty string, 0, False) would also pass the check; only None signals
    upload failure consistently.
    """
    from app.services import workdrive_uploader

    breaker = get_circuit_breaker("zoho_workdrive")
    breaker.force_open()

    result = workdrive_uploader.upload_file(
        file_path=Path("dummy.pdf"),
        folder_id="folder123",
        token="tok",
    )

    assert result is None, (
        f"upload_file must return None when circuit OPEN; got {result!r}"
    )


def test_upload_file_returns_str_on_success():
    """upload_file CLOSED-success path returns str (resource_id)."""
    from app.services import workdrive_uploader

    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "data": [{
            "attributes": {"resource_id": "wd_resource_xyz"},
            "id":         "wd_resource_xyz",
        }],
    }

    # open() the file path — patch builtins.open to avoid touching disk.
    fake_file = MagicMock()
    fake_file.__enter__ = MagicMock(return_value=MagicMock())
    fake_file.__exit__  = MagicMock(return_value=False)

    with patch("builtins.open", return_value=fake_file):
        with patch("app.services.workdrive_uploader.requests.post",
                   return_value=fake_resp):
            result = workdrive_uploader.upload_file(
                file_path=Path("dummy.pdf"),
                folder_id="folder123",
                token="tok",
            )

    assert isinstance(result, str), (
        f"upload_file must return str on success; got {type(result).__name__}"
    )
    assert result == "wd_resource_xyz"


# ── Round-trip: identical shape in CLOSED and OPEN states ─────────────────────

def test_wfirma_shape_identical_closed_vs_open():
    """The destructure pattern `status, body = _http_request(...)` must work
    in both CLOSED and OPEN states. This is the strict Lesson A contract:
    fallback shape MUST match success shape."""
    from app.services import wfirma_client

    # OPEN. Admission now flows through breaker.call() (the raw ``.state``
    # fast-path was removed so the breaker can evaluate its recovery timeout),
    # and header construction precedes admission uniformly. Stub
    # _headers_for_module so a no-credential test env surfaces the OPEN
    # rejection — (503, "circuit_breaker_open") — rather than a ValueError from
    # missing creds. The route is NOT weakened: a forced-OPEN breaker still
    # returns the 503 fallback shape below.
    get_circuit_breaker("wfirma").force_open()
    with patch.object(wfirma_client, "_headers_for_module", return_value={}):
        open_result = wfirma_client._http_request("GET", "contractors", "find")
    status_open, body_open = open_result  # must not raise
    assert (status_open, body_open) == (503, "circuit_breaker_open")

    # CLOSED
    reset_all()
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = "ok"
    with patch.object(wfirma_client, "_headers_for_module", return_value={}):
        with patch("app.services.wfirma_client._requests.request",
                   return_value=fake_resp):
            closed_result = wfirma_client._http_request(
                "GET", "contractors", "find"
            )
    status_closed, body_closed = closed_result  # must not raise

    # Same arity, same element types.
    assert type(open_result) is type(closed_result)
    assert isinstance(status_open, int) and isinstance(status_closed, int)
    assert isinstance(body_open, str)   and isinstance(body_closed, str)


# ── wFirma-client recovery through the breaker (stuck-OPEN regression) ─────────
#
# Before the fix, wfirma_client._http_request read the breaker's raw ``.state``
# and returned (503, "circuit_breaker_open") BEFORE ever calling
# ``breaker.call()``. Because OPEN→HALF_OPEN only happens inside ``call()``, the
# recovery timeout was never evaluated and the wFirma breaker stayed OPEN until
# PZService restarted (live incident 2026-07-30: 3,704 fast-fails over 15h, zero
# recovery attempts). These two tests pin the corrected behaviour at the client
# boundary: OPEN pre-recovery still fast-fails without touching wFirma, but once
# the recovery window elapses the next request is admitted as a probe that
# actually reaches wFirma and closes the circuit on success.


def test_wfirma_client_rejects_while_open_before_recovery():
    """OPEN + still inside recovery_timeout → fast-fail (503) WITHOUT contacting
    wFirma. Proves the fix does not weaken the OPEN protection."""
    from app.services import wfirma_client

    breaker = get_circuit_breaker("wfirma")
    breaker.force_open()                        # _last_failure = now → window open

    contacted = {"n": 0}

    def _must_not_contact(*_a, **_kw):
        contacted["n"] += 1
        raise AssertionError("wFirma must not be contacted while OPEN pre-recovery")

    with patch.object(wfirma_client, "_headers_for_module", return_value={}):
        with patch("app.services.wfirma_client._requests.request",
                   side_effect=_must_not_contact):
            status, body = wfirma_client._http_request("GET", "contractors", "find")

    assert contacted["n"] == 0
    assert (status, body) == (503, "circuit_breaker_open")
    assert breaker.state == CircuitState.OPEN


def test_wfirma_client_probes_after_recovery_timeout():
    """OPEN + recovery_timeout elapsed → the next request is admitted as a
    HALF_OPEN probe that ACTUALLY reaches wFirma (not a fast-fail), and a
    successful probe closes the circuit. This is the end-to-end regression for
    the stuck-OPEN defect.

    The elapsed window is simulated deterministically by back-dating the
    breaker's last-failure timestamp past recovery_timeout — the real-time
    equivalent of waiting, with no sleep.
    """
    import time as _time
    from app.services import wfirma_client

    breaker = get_circuit_breaker("wfirma")
    breaker.force_open()
    # Back-date the failure so recovery_timeout has "elapsed" — deterministic,
    # no real wait. force_open set _last_failure = now; move it into the past.
    with breaker._lock:
        breaker._last_failure = _time.time() - (breaker.config.recovery_timeout + 1)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = "<api><status><code>OK</code></status></api>"
    contacted = {"n": 0}

    def _probe_request(*_a, **_kw):
        contacted["n"] += 1
        return fake_resp

    with patch.object(wfirma_client, "_headers_for_module", return_value={}):
        with patch("app.services.wfirma_client._requests.request",
                   side_effect=_probe_request):
            status, body = wfirma_client._http_request("GET", "contractors", "find")

    assert contacted["n"] == 1, (
        "recovery probe must reach wFirma through breaker.call(); "
        "a fast-fail on raw .state would never contact wFirma"
    )
    assert status == 200
    assert "OK" in body
    assert breaker.state == CircuitState.CLOSED, (
        "a successful recovery probe must close the wFirma circuit"
    )
