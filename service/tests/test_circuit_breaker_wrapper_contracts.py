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
import time as _time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.circuit_breaker import CircuitState, get_circuit_breaker, reset_all


# ── Test isolation ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_circuits():
    """Each test starts with every named circuit CLOSED and the cliq token state
    cleared.

    These tests drive cliq_service via asyncio.run(), which creates and closes a
    fresh event loop per call. cliq_service._token_lock is a lazily-created
    module-global asyncio.Lock; dropping it here forces a re-bind to each test's
    loop, avoiding "bound to a different event loop" when a later test reuses a
    Lock created on an already-closed loop.
    """
    from app.services import cliq_service
    cliq_service._token_lock = None
    cliq_service._access_token = ""
    reset_all()
    # Neutralise the breaker's real time.sleep() retry backoff so failure-path
    # tests (which exhaust retry_attempts on a failing probe) don't add seconds.
    with patch("app.core.circuit_breaker.time.sleep", lambda *_a, **_k: None):
        yield
    cliq_service._token_lock = None
    cliq_service._access_token = ""
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
    """post_to_channel CLOSED-success path returns bool (True).

    Since the stuck-OPEN fix, the POST is routed through CircuitBreaker.call()
    via asyncio.to_thread using a SYNCHRONOUS httpx.Client — so the transport
    boundary is patched at httpx.Client (not AsyncClient), with a sync post().
    """
    from app.services import cliq_service

    resp = MagicMock()
    resp.status_code = 204
    resp.text = ""

    sync_client = MagicMock()
    sync_client.post = MagicMock(return_value=resp)
    sync_client.__enter__ = MagicMock(return_value=sync_client)
    sync_client.__exit__  = MagicMock(return_value=False)

    settings_stub = MagicMock()
    settings_stub.cliq_channel_api_url     = "https://cliq.example/api/message"
    settings_stub.cliq_channel_webhook_url = ""

    with patch.object(cliq_service, "settings", settings_stub), \
         patch.object(cliq_service, "_get_access_token", return_value="tok"), \
         patch("app.services.cliq_service.httpx.Client", return_value=sync_client):
        result = asyncio.run(cliq_service.post_to_channel("hello"))

    assert isinstance(result, bool), (
        f"post_to_channel must return bool on success; got {type(result).__name__}"
    )
    assert result is True


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


# ── cliq_service stuck-OPEN recovery (the fixed defect) ───────────────────────
#
# Regression suite for the stuck-OPEN defect at cliq_service.py (2026-07-30):
# admission used to be gated on the breaker's RAW .state, which returned before
# CircuitBreaker.call() ever ran — so _maybe_transition() never fired and the
# zoho_cliq circuit could never leave OPEN until the process restarted, silently
# suppressing EVERY batch-completion notification for the process lifetime.
#
# The fix routes both post_to_channel and _refresh_access_token through
# breaker.call() (via asyncio.to_thread + a sync httpx.Client). These tests
# drive the recovery deadline deterministically by back-dating _last_failure
# past recovery_timeout — no real sleeps — and assert through the REAL cliq
# wrappers that a probe is (a) rejected inside the window and (b) admitted once
# the window elapses. Mirrors the wfirma wrapper-contract recovery tests and
# tests/test_circuit_breaker.py::TestRecoveryTimeoutFakeClock.

def _recording_sync_client(recorder, *, status=204, text="", json_data=None):
    """A stand-in httpx.Client whose sync post() appends to *recorder* and
    returns a MagicMock response. Lets a test assert whether the HTTP layer was
    actually reached (probe admitted) vs short-circuited (rejected while OPEN)."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()  # 2xx: no-op

    client = MagicMock()

    def _post(*_a, **_kw):
        recorder.append(True)
        return resp

    client.post = MagicMock(side_effect=_post)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__  = MagicMock(return_value=False)
    return client


def _channel_settings_stub():
    s = MagicMock()
    s.cliq_channel_api_url     = "https://cliq.example/api/message"
    s.cliq_channel_webhook_url = ""
    return s


def _oauth_settings_stub():
    s = MagicMock()
    s.cliq_refresh_token = "rt"
    s.cliq_client_id     = "cid"
    s.cliq_client_secret = "csec"
    return s


def _expire_recovery_window(breaker):
    """Back-date the breaker's last failure past recovery_timeout so the NEXT
    admission must transition OPEN → HALF_OPEN (mirrors the wfirma tests)."""
    with breaker._lock:
        breaker._last_failure = _time.time() - (breaker.config.recovery_timeout + 1)


def test_post_to_channel_rejects_while_open_before_recovery():
    """Inside the recovery window an OPEN circuit rejects the post and NO HTTP
    call is made — but crucially now via breaker.call(), which keeps the
    recovery clock alive (unlike the old raw-.state fast-path)."""
    from app.services import cliq_service

    breaker = get_circuit_breaker("zoho_cliq")
    breaker.force_open()  # _last_failure = now → inside the 60s window

    reached: list = []
    client = _recording_sync_client(reached, status=204)

    with patch.object(cliq_service, "settings", _channel_settings_stub()), \
         patch.object(cliq_service, "_get_access_token", return_value="tok"), \
         patch("app.services.cliq_service.httpx.Client", return_value=client):
        result = asyncio.run(cliq_service.post_to_channel("hi"))

    assert result is False
    assert reached == [], "no HTTP post may run while the circuit is OPEN pre-recovery"
    assert breaker.state == CircuitState.OPEN


def test_post_to_channel_probes_after_recovery_timeout():
    """THE core regression: once recovery_timeout elapses, post_to_channel must
    admit a HALF_OPEN probe that actually reaches the HTTP layer and — on a 2xx —
    CLOSES the circuit. Before the fix the raw-.state gate made this unreachable
    and the breaker stayed OPEN until the process restarted."""
    from app.services import cliq_service

    breaker = get_circuit_breaker("zoho_cliq")
    breaker.force_open()
    _expire_recovery_window(breaker)

    reached: list = []
    client = _recording_sync_client(reached, status=204)

    with patch.object(cliq_service, "settings", _channel_settings_stub()), \
         patch.object(cliq_service, "_get_access_token", return_value="tok"), \
         patch("app.services.cliq_service.httpx.Client", return_value=client):
        result = asyncio.run(cliq_service.post_to_channel("hi"))

    assert reached == [True], "recovery probe must reach the HTTP layer exactly once"
    assert result is True
    assert breaker.state == CircuitState.CLOSED, "a successful probe must CLOSE the circuit"


def test_refresh_access_token_rejects_while_open_before_recovery():
    """_refresh_access_token inside the recovery window returns the cached token
    without reaching the OAuth endpoint (rejected via breaker.call())."""
    from app.services import cliq_service

    cliq_service._access_token = "cached-tok"
    try:
        breaker = get_circuit_breaker("zoho_cliq")
        breaker.force_open()  # inside window

        reached: list = []
        client = _recording_sync_client(reached, status=200,
                                        json_data={"access_token": "fresh"})

        with patch.object(cliq_service, "settings", _oauth_settings_stub()), \
             patch("app.services.cliq_service.httpx.Client", return_value=client):
            tok = asyncio.run(cliq_service._refresh_access_token())

        assert tok == "cached-tok", "OPEN circuit must fall back to the cached token"
        assert reached == [], "no OAuth call may run while the circuit is OPEN pre-recovery"
        assert breaker.state == CircuitState.OPEN
    finally:
        cliq_service._access_token = ""


def test_refresh_access_token_probes_after_recovery_timeout():
    """_refresh_access_token after recovery_timeout admits a probe that reaches
    the OAuth endpoint, stores the refreshed token, and CLOSES the circuit."""
    from app.services import cliq_service

    cliq_service._access_token = ""
    try:
        breaker = get_circuit_breaker("zoho_cliq")
        breaker.force_open()
        _expire_recovery_window(breaker)

        reached: list = []
        client = _recording_sync_client(reached, status=200,
                                        json_data={"access_token": "fresh-tok-xyz"})

        with patch.object(cliq_service, "settings", _oauth_settings_stub()), \
             patch("app.services.cliq_service.httpx.Client", return_value=client):
            tok = asyncio.run(cliq_service._refresh_access_token())

        assert reached == [True], "recovery probe must reach the OAuth endpoint exactly once"
        assert tok == "fresh-tok-xyz"
        assert cliq_service._access_token == "fresh-tok-xyz"
        assert breaker.state == CircuitState.CLOSED, "a successful probe must CLOSE the circuit"
    finally:
        cliq_service._access_token = ""


# ── probe FAILURE, transport vs server error, and the 401 retry loop ──────────
#
# The recovery tests above cover the happy path (probe succeeds → CLOSED). These
# cover the failure edges that the raw-.state gate used to hide, plus the classic
# 401→refresh→retry loop that now has to survive breaker-routed admission.

def test_post_to_channel_probe_failure_reopens_circuit():
    """A HALF_OPEN probe that FAILS at the transport layer must reopen the circuit
    AND release the single probe slot. If the slot leaked, HALF_OPEN would wedge
    into permanent 'probe in flight' rejection — a second stuck-OPEN class bug."""
    from app.services import cliq_service

    breaker = get_circuit_breaker("zoho_cliq")
    breaker.force_open()
    _expire_recovery_window(breaker)

    reached: list = []
    client = MagicMock()

    def _post(*_a, **_kw):
        reached.append(True)
        raise httpx.ConnectError("connection refused")

    client.post = MagicMock(side_effect=_post)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__  = MagicMock(return_value=False)

    with patch.object(cliq_service, "settings", _channel_settings_stub()), \
         patch.object(cliq_service, "_get_access_token", return_value="tok"), \
         patch("app.services.cliq_service.httpx.Client", return_value=client):
        result = asyncio.run(cliq_service.post_to_channel("hi"))

    assert result is False
    assert reached, "the probe must actually reach the HTTP layer"
    assert breaker.state == CircuitState.OPEN, "a failed probe must reopen the circuit"
    assert breaker._probe_in_flight is False, "the probe slot must be released after a failed probe"


def test_post_to_channel_401_triggers_refresh_then_retries():
    """First POST 401 → _refresh_access_token is awaited → second POST 204 →
    returns True. The retry-once-on-401 loop must still work now that the POST is
    routed through breaker.call() (CLOSED circuit — this is the happy retry path)."""
    from app.services import cliq_service

    statuses = [401, 204]
    calls: list = []

    def _post(*_a, **_kw):
        resp = MagicMock()
        resp.status_code = statuses[len(calls)]
        resp.text = ""
        resp.raise_for_status = MagicMock()
        calls.append(True)
        return resp

    client = MagicMock()
    client.post = MagicMock(side_effect=_post)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__  = MagicMock(return_value=False)

    with patch.object(cliq_service, "settings", _channel_settings_stub()), \
         patch.object(cliq_service, "_get_access_token", return_value="tok"), \
         patch.object(cliq_service, "_refresh_access_token", return_value="refreshed") as refresh_mock, \
         patch("app.services.cliq_service.httpx.Client", return_value=client):
        result = asyncio.run(cliq_service.post_to_channel("hi"))

    assert result is True
    assert len(calls) == 2, "must POST twice: first 401, then the post-refresh retry (204)"
    assert refresh_mock.await_count == 1, "a 401 must trigger exactly one token refresh"


def test_post_to_channel_server_error_does_not_trip_breaker():
    """A 5xx is a REACHABLE server (transport success): breaker.call() records a
    success, the circuit stays CLOSED, and no failure is accrued. post_to_channel
    still returns False because the delivery didn't land — mirrors wfirma's
    transport-reachability model (only connection errors are breaker failures)."""
    from app.services import cliq_service

    breaker = get_circuit_breaker("zoho_cliq")  # CLOSED via _reset_circuits

    reached: list = []
    client = _recording_sync_client(reached, status=500, text="upstream boom")

    with patch.object(cliq_service, "settings", _channel_settings_stub()), \
         patch.object(cliq_service, "_get_access_token", return_value="tok"), \
         patch("app.services.cliq_service.httpx.Client", return_value=client):
        result = asyncio.run(cliq_service.post_to_channel("hi"))

    assert result is False
    assert reached == [True], "the request must reach the server (transport OK)"
    assert breaker.state == CircuitState.CLOSED
    assert breaker.get_stats().failure_count == 0, "a 5xx must NOT accrue a breaker failure"


def test_refresh_access_token_http_error_counts_as_breaker_failure():
    """The OAuth-refresh asymmetry: unlike post_to_channel, _do_refresh calls
    raise_for_status(), so a non-2xx OAuth response DOES raise → breaker failure.
    One failed refresh accrues exactly one failure and (below threshold) leaves
    the circuit CLOSED; the caller gets ""."""
    from app.services import cliq_service

    cliq_service._access_token = ""
    breaker = get_circuit_breaker("zoho_cliq")  # CLOSED

    resp = MagicMock()
    resp.status_code = 401
    resp.text = "unauthorized"
    resp.json.return_value = {}
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=MagicMock())
    )
    client = MagicMock()
    client.post = MagicMock(return_value=resp)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__  = MagicMock(return_value=False)

    with patch.object(cliq_service, "settings", _oauth_settings_stub()), \
         patch("app.services.cliq_service.httpx.Client", return_value=client):
        tok = asyncio.run(cliq_service._refresh_access_token())

    assert tok == ""
    assert breaker.state == CircuitState.CLOSED, "one OAuth failure stays below the threshold of 5"
    assert breaker.get_stats().failure_count == 1, "the non-2xx OAuth response must accrue exactly one breaker failure"


def test_refresh_access_token_http_error_does_not_leak_credentials(caplog):
    """SECURITY REGRESSION: OAuth credentials must ride in the request BODY (data=),
    never the query string (params=). If they were in the URL, a non-2xx
    raise_for_status() builds an httpx.HTTPStatusError whose str() embeds that URL,
    and the generic error handler logs it verbatim. Drives a REAL httpx transport so
    the request URL is built from the real _do_refresh call, then asserts the
    credential sentinels are absent from both the URL and every log record."""
    import logging
    from app.services import cliq_service

    cliq_service._access_token = ""

    s = MagicMock()
    s.cliq_refresh_token = "REFRESHTOK_SENTINEL_a1"
    s.cliq_client_id     = "CLIENTID_SENTINEL_b2"
    s.cliq_client_secret = "CLIENTSECRET_SENTINEL_c3"
    sentinels = (s.cliq_refresh_token, s.cliq_client_id, s.cliq_client_secret)

    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["url"]  = str(request.url)
        captured["body"] = request.content.decode("utf-8", "replace")
        return httpx.Response(401, text="unauthorized")

    real_client = httpx.Client

    def _client_factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(_handler)
        return real_client(*a, **kw)

    with caplog.at_level(logging.DEBUG, logger="app.services.cliq_service"), \
         patch.object(cliq_service, "settings", s), \
         patch("app.services.cliq_service.httpx.Client", side_effect=_client_factory):
        tok = asyncio.run(cliq_service._refresh_access_token())

    assert tok == ""
    assert captured, "the OAuth endpoint must actually be reached"
    # data= keeps every secret OUT of the request URL …
    for secret in sentinels:
        assert secret not in captured["url"], f"credential leaked into the request URL: {secret!r}"
    # … and puts them in the form-encoded body instead (proves data= was used).
    assert s.cliq_refresh_token in captured["body"] and s.cliq_client_id in captured["body"]
    # … so the logged HTTPStatusError (which carries the URL) exposes no secret.
    full_log = "\n".join(rec.getMessage() for rec in caplog.records)
    for secret in sentinels:
        assert secret not in full_log, f"credential leaked into logs: {secret!r}"
