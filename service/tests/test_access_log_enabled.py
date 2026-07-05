"""
test_access_log_enabled.py — infra health pass d67d3722 finding #4.

Pins that HTTP access logging is EMITTED. The gate (proven by truth-table
boots, PROJECT_STATE DECISIONS "infra hardening #4"): uvicorn's access log
is ON by default, and the only silencer was core/logging.py setting
uvicorn.access to WARNING at app import — which runs AFTER uvicorn's own
dictConfig, so it always won (the NSSM --access-log flag could not override
it). The fix flips that line to INFO.

The positive pin boots a REAL uvicorn server in-process (TestClient cannot
pin this: access lines are emitted by uvicorn's HTTP protocol layer, which
TestClient bypasses), replicating the production ORDER: uvicorn logging
config first (log_config=None here — handlers stay ours), then
configure_logging() as the app import does. If the silencer returns, the
captured record disappears and this test fails.
"""
from __future__ import annotations

import logging
import threading
import time
import urllib.request
from pathlib import Path

import pytest


class _ListHandler(logging.Handler):
    def __init__(self, sink):
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record):  # pragma: no cover - trivial
        self._sink.append(record)


@pytest.mark.timeout(120)
def test_access_line_emitted_with_method_path_status():
    import uvicorn
    from app.main import app as _app
    from app.core.logging import configure_logging

    records: list = []
    access_logger = logging.getLogger("uvicorn.access")
    handler = _ListHandler(records)
    access_logger.addHandler(handler)
    try:
        # PRODUCTION ORDER: the app-side logging config runs AFTER uvicorn's
        # (at app import). Re-run it here so the level under test is exactly
        # what core/logging.py sets — the thing finding #4 fixed.
        configure_logging()

        config = uvicorn.Config(
            _app, host="127.0.0.1", port=0,
            log_config=None,       # keep the test session's handlers
            log_level="info",
            lifespan="off",        # no schedulers in-test
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        deadline = time.time() + 60
        while not server.started:
            if time.time() > deadline:  # pragma: no cover
                pytest.fail("uvicorn did not start within 60s")
            time.sleep(0.1)
        port = server.servers[0].sockets[0].getsockname()[1]

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/openapi.json", timeout=30
        ) as resp:
            assert resp.status == 200

        deadline = time.time() + 10
        while not records and time.time() < deadline:
            time.sleep(0.1)

        server.should_exit = True
        t.join(timeout=30)

        assert records, (
            "no uvicorn.access record captured — the access-log silencer is "
            "back (d67d3722 finding #4 regression)"
        )
        line = records[0].getMessage()
        assert "GET" in line, line
        assert "/openapi.json" in line, line
        assert "200" in line, line
        # remote addr present (client host:port prefix in uvicorn's format)
        assert "127.0.0.1" in line, line
    finally:
        access_logger.removeHandler(handler)


def test_silencer_line_is_gone_and_info_is_pinned():
    """Negative source pin: core/logging.py must not silence uvicorn.access
    back to WARNING, and must set it to INFO explicitly."""
    import app.core.logging as core_logging
    src = Path(core_logging.__file__).read_text(encoding="utf-8", errors="replace")
    assert 'getLogger("uvicorn.access").setLevel(logging.WARNING)' not in src, \
        "the access-log silencer returned (d67d3722 finding #4 regression)"
    assert 'getLogger("uvicorn.access").setLevel(logging.INFO)' in src, \
        "uvicorn.access must be pinned to INFO explicitly"


def test_configure_logging_sets_access_logger_to_info():
    from app.core.logging import configure_logging
    configure_logging()
    assert logging.getLogger("uvicorn.access").level == logging.INFO
