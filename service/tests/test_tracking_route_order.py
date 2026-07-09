"""Phase 2 — tracking route registration order (collision fix).

Two routers share the prefix ``/api/v1/tracking``:
  * ``routes_tracking_db`` exposes the static ``GET /events`` (list all tracking events)
  * ``routes_tracking``    exposes the catch-all ``GET /{tracking_no}`` (single lookup)

FastAPI/Starlette dispatch is first-registered-wins. If ``tracking_router`` is
registered before ``tracking_db_router``, a request to ``/api/v1/tracking/events``
is captured by ``GET /{tracking_no}`` (with ``tracking_no == "events"``) and the real
events endpoint is unreachable — a silent shadowing bug.

These tests pin the fix at the ROUTING layer (no business logic, no DB, no network):
  * ``GET /api/v1/tracking/events`` must resolve to ``get_all_events``.
  * ``GET /api/v1/tracking/{tracking_no}`` must STILL resolve to ``get_tracking``.
  * ``GET /api/v1/tracking/events/{batch_id}`` must resolve to ``get_batch_events``.
  * Structural: the ``/events`` route is registered before the ``/{tracking_no}`` route.
"""
from __future__ import annotations

import sys
from pathlib import Path

from starlette.routing import Match

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.main import app  # noqa: E402


def _first_route(method: str, path: str):
    """Return the first APIRoute (in registration order) that FULL-matches the
    given method+path — i.e. the route Starlette would actually dispatch to."""
    scope = {"type": "http", "method": method, "path": path}
    for route in app.router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue  # skip Mounts / WebSocket routes
        match, _child = route.matches(scope)
        if match == Match.FULL:
            return route
    return None


class TestEventsNotShadowed:
    def test_events_resolves_to_events_handler(self):
        route = _first_route("GET", "/api/v1/tracking/events")
        assert route is not None, "GET /api/v1/tracking/events matched no route"
        assert route.endpoint.__name__ == "get_all_events", (
            f"GET /api/v1/tracking/events resolved to {route.endpoint.__name__!r} "
            "— it is shadowed by the catch-all /{tracking_no}"
        )

    def test_events_batch_resolves_to_batch_handler(self):
        route = _first_route("GET", "/api/v1/tracking/events/BATCH123")
        assert route is not None
        assert route.endpoint.__name__ == "get_batch_events"


class TestTrackingNoStillWorks:
    def test_tracking_no_resolves_to_tracking_handler(self):
        # A real single-segment tracking number must still hit the catch-all.
        route = _first_route("GET", "/api/v1/tracking/1Z999AA10123456784")
        assert route is not None
        assert route.endpoint.__name__ == "get_tracking"


class TestRegistrationOrder:
    def test_events_route_registered_before_catchall(self):
        # Structural proof of the fix: the static /events route index must be
        # strictly less than the catch-all /{tracking_no} route index.
        events_idx = catchall_idx = None
        for i, route in enumerate(app.router.routes):
            endpoint = getattr(route, "endpoint", None)
            if endpoint is None:
                continue
            name = endpoint.__name__
            path = getattr(route, "path", "")
            if name == "get_all_events" and path == "/api/v1/tracking/events":
                events_idx = i
            elif name == "get_tracking" and path == "/api/v1/tracking/{tracking_no}":
                catchall_idx = i
        assert events_idx is not None, "get_all_events /events route not found"
        assert catchall_idx is not None, "get_tracking /{tracking_no} route not found"
        assert events_idx < catchall_idx, (
            f"/events registered at {events_idx} but /{{tracking_no}} at {catchall_idx} "
            "— /events would be shadowed"
        )
