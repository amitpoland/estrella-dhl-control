"""The Control Tower drawer must read the PzApi envelope, not guess its shape.

Production incident: the backend composed timeline was correct (54 merged
workflow + carrier events for inbound 6696117050), and the drawer still showed
only the 8 narrow workflow milestones. The consumer read ``d.events`` off the
value PzApi returns, but ``_call`` wraps every response as ``{ok, data}`` -- so
``d.events`` was always undefined, the composed stream silently became ``[]``,
and the drawer fell back to milestones.

Worse, ``_call`` RESOLVES on failure (``{ok:false, ...}``) rather than
rejecting, so the ``.catch()`` the consumer relied on could never fire and the
degraded notice never appeared. A real API failure and a successful-but-unread
response were indistinguishable on screen.

These tests pin the PRODUCER shape and the CONSUMER that reads it together.
Pinning only the backend composition is what let this ship: those tests passed
while the feature was invisible in the browser.
"""
from __future__ import annotations

import pathlib
import re

_V2 = pathlib.Path(__file__).parent.parent / "app" / "static" / "v2"
_PAGES = _V2 / "pages-v2.jsx"
_API = _V2 / "pz-api.js"


def _pages() -> str:
    return _PAGES.read_text(encoding="utf-8", errors="replace")


def _api() -> str:
    return _API.read_text(encoding="utf-8", errors="replace")


# ── the producer ─────────────────────────────────────────────────────────────


def test_pzapi_call_wraps_every_response_in_an_ok_data_envelope():
    """If this contract ever changes, the consumer test below must change too."""
    src = _api()
    assert "return { ok: true, data };" in src, (
        "PzApi._call no longer returns {ok:true, data} -- the Control Tower "
        "drawer reads result.data.events and must be updated with it"
    )
    assert "ok:     false," in src, "the failure envelope shape changed"


def test_pzapi_call_resolves_on_failure_instead_of_rejecting():
    """Why branching on `ok` is mandatory and .catch() alone is not enough."""
    src = _api()
    call = src[src.index("async function _call("):]
    call = call[:call.index("async function _callM(")]
    assert "catch (err)" in call and "return {" in call, (
        "_call must catch and RETURN a failure envelope; if it starts throwing, "
        "the consumer's error handling has to be revisited"
    )
    assert "throw" not in call.split("catch (err)")[1], (
        "_call re-throws on failure -- consumers relying on the {ok:false} "
        "envelope would silently stop seeing failures"
    )


def test_get_dhl_logistics_shipment_goes_through_the_wrapped_call():
    src = _api()
    assert "getDhlLogisticsShipment" in src
    idx = src.index("getDhlLogisticsShipment")
    assert "_get(" in src[idx:idx + 200], (
        "getDhlLogisticsShipment must use _get so its response is the "
        "{ok, data} envelope the drawer expects"
    )


# ── the consumer ─────────────────────────────────────────────────────────────


def _drawer_effect() -> str:
    """The DhlTowerDrawer fetch effect, isolated."""
    src = _pages()
    start = src.index("function DhlTowerDrawer(")
    end = src.index("}, [row && row.awb]);", start)
    return src[start:end]


def test_the_drawer_reads_events_from_the_envelope_data():
    effect = _drawer_effect()
    assert re.search(r"result\.data\.events", effect), (
        "the drawer must read the composed stream from result.data.events"
    )


def test_the_drawer_does_not_read_events_off_the_envelope_itself():
    """The exact defect: `d.events` on a {ok, data} envelope is always undefined."""
    effect = _drawer_effect()
    assert not re.search(r"\bd\s*&&\s*d\.events\b", effect), (
        "reading .events directly off the PzApi envelope silently yields an "
        "empty timeline -- read result.data.events"
    )


def test_the_drawer_branches_on_ok_so_a_real_failure_is_visible():
    """_call resolves on failure, so only an explicit ok check can detect it."""
    effect = _drawer_effect()
    assert re.search(r"!result\.ok", effect), (
        "the drawer must branch on the envelope's ok flag; .catch() alone "
        "cannot see a failure because _call resolves rather than rejects"
    )
    assert "setComposedFailed(true)" in effect, (
        "a failed or malformed envelope must raise the degraded state"
    )


def test_a_successful_envelope_is_never_conflated_with_a_failure():
    """Success + empty events is legitimate; it must NOT set the failed flag."""
    effect = _drawer_effect()
    ok_branch = effect[effect.index("if (!result"):]
    assert "Array.isArray(result.data.events)" in ok_branch, (
        "a successful envelope must be read defensively but still treated as "
        "success -- an empty event list is data, not an error"
    )


def test_the_degraded_state_is_rendered_not_just_recorded():
    """A silent fallback is what made the original defect invisible."""
    src = _pages()
    assert 'data-testid="dhl-tower-timeline-degraded"' in src, (
        "the drawer must SHOW that it is displaying workflow milestones only"
    )


def test_outbound_legs_skip_the_fetch_by_design():
    """project_outbound_row already appends every carrier checkpoint."""
    effect = _drawer_effect()
    assert "row.direction === 'outbound'" in effect


def test_the_previous_rows_stream_is_cleared_before_any_early_return():
    """Cross-leg mixing, reintroduced one layer up.

    The outbound guard returns without fetching. If the state reset sits AFTER
    it, opening an inbound row (which populates `composed`) and then an outbound
    row leaves the outbound drawer rendering the inbound leg's carrier events —
    precisely the contamination this repair exists to prevent.
    """
    effect = _drawer_effect()
    reset = effect.index("setComposed(null)")
    outbound_guard = effect.index("row.direction === 'outbound'")
    wrapper_guard = effect.index("!window.PzApi")
    assert reset < outbound_guard, (
        "setComposed(null) must run BEFORE the outbound early return, or an "
        "outbound drawer can show the previously-opened inbound leg's events"
    )
    assert reset < wrapper_guard, (
        "the reset must also precede the wrapper-availability early return"
    )


def test_milestones_remain_the_fallback_and_the_stage_authority():
    """The composed stream is presentation only; it must not replace milestones."""
    src = _pages()
    assert "const milestones = row.milestones || [];" in src
    # The render picks composed when present, milestones otherwise.
    assert ": milestones.map((m) => ({" in src or "milestones.map((m) => ({" in src, (
        "milestones must remain the fallback source for the timeline render"
    )
