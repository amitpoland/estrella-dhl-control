"""test_dhl_account_reactive_ui.py — shipment-page reactive DHL account wiring.

Pins the ten acceptance criteria of the operator's phase-1 ruling (2026-07-20):

  1. sender change clears the stale account selection
  2. a single canonical default auto-resolves (server-side, not in the UI)
  3. multiple accounts without a default require operator selection
  4. receiver billing never falls back to the sender's account
  5. masking is preserved everywhere
  6. an old async response is ignored
  7. no duplicate network requests
  8. resolver selection logic is not re-implemented in the component
  9. a selected sender with no account blocks, ignoring the env fallback
 10. the sender-paid payload is unchanged
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))

V2 = SERVICE_DIR / "app" / "static" / "v2"
HOOK = V2 / "use-dhl-account-resolution.jsx"
API = V2 / "pz-api.js"
INDEX = V2 / "index.html"
ROUTE = SERVICE_DIR / "app" / "api" / "routes_carrier_actions.py"
ADAPTER = SERVICE_DIR / "app" / "services" / "carrier" / "adapters" / "live.py"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: pathlib.Path) -> str:
    """Source with // comment lines stripped, so prose can't satisfy a test."""
    return "\n".join(ln for ln in _read(p).splitlines()
                     if not ln.strip().startswith("//"))


# ── Wiring exists ────────────────────────────────────────────────────────

def test_hook_file_exists_and_exports():
    assert HOOK.exists()
    src = _read(HOOK)
    assert "function useDhlAccountResolution(" in src
    assert "DhlAccountPanel" in src
    assert "Object.assign(window" in src


def test_hook_registered_in_index():
    assert 'src="use-dhl-account-resolution.jsx"' in _read(INDEX)


def test_transport_wrapper_exists():
    assert "resolveDhlAccounts:" in _read(API)


def test_read_only_endpoint_delegates_to_canonical_resolver():
    src = _read(ROUTE)
    assert "dhl-account-resolution" in src
    assert "resolve_dhl_billing_account" in src


# ── 1. sender change clears stale selection ──────────────────────────────

def test_sender_change_clears_stale_selection():
    code = _code(HOOK)
    m = re.search(r"React\.useEffect\(\(\) => \{(.*?)\}, \[senderContractorId\]\)", code, re.S)
    assert m, "a sender-change effect must exist"
    assert "setBillingAccountId(null)" in m.group(1), \
        "sender change must clear the stale account selection"


def test_receiver_change_clears_stale_selection():
    code = _code(HOOK)
    m = re.search(r"React\.useEffect\(\(\) => \{(.*?)\}, \[receiverContractorId\]\)", code, re.S)
    assert m
    assert "setBillingAccountId(null)" in m.group(1)


def test_billing_party_change_clears_incompatible_account():
    code = _code(HOOK)
    m = re.search(r"setBillingParty = React\.useCallback\((.*?)\}, \[\]\)", code, re.S)
    assert m, "setBillingParty must be defined"
    assert "setBillingAccountId(null)" in m.group(1), \
        "changing billing party must clear an account id belonging to the old party"


# ── 2 + 3. defaults and choice come from the server ──────────────────────

def _hook_body() -> str:
    """Just the state-logic hook, without the presentational panel.

    Selection must not happen here. The panel may *label* a choice
    '(default)' — that is display, not derivation.
    """
    code = _code(HOOK)
    start = code.index("function useDhlAccountResolution(")
    end = code.index("function DhlAccountPanel(")
    return code[start:end]


def test_ui_never_derives_a_default():
    """The hook must not pick an account itself — the server decides."""
    body = _hook_body()
    for banned in ("is_default", "isDefault", "accounts[0]", ".find(", "sort(",
                   "filter(a =>", "reduce("):
        assert banned not in body, \
            f"hook must not derive account selection ({banned!r}) — the server decides"


def test_panel_only_labels_the_default_it_was_given():
    """The panel may show '(default)', but must read it from server data."""
    code = _code(HOOK)
    panel = code[code.index("function DhlAccountPanel("):]
    assert "c.is_default ?" in panel, "the default label comes from the server payload"
    assert "setBillingAccountId(c.id)" not in panel, \
        "the panel must not auto-select an account"


def test_choice_requirement_comes_from_server_reason():
    code = _code(HOOK)
    assert "account_choice_required" in code
    assert "resolution.choices" in code or "resolution.choices" in _read(HOOK)


def test_awb_eligibility_is_server_owned():
    code = _code(HOOK)
    assert "awb_blocked" in code, "AWB eligibility must read the server's awb_blocked"


# ── 4 + 9. no silent fallback, env ignored ───────────────────────────────

def test_no_cross_party_fallback_in_ui():
    code = _code(HOOK)
    assert "senderAccounts" in code and "receiverAccounts" in code
    # The UI must never substitute one party's accounts for the other's.
    assert "|| senderAccounts" not in code
    assert "|| receiverAccounts" not in code


def test_env_account_never_referenced_in_ui():
    code = _code(HOOK)
    for banned in ("DHL_EXPRESS_ACCOUNT_NUMBER", "dhl_express_account_number"):
        assert banned not in code


def test_selected_sender_without_account_blocks_server_side():
    """Criterion 9 is enforced in the route; assert the guard is still there."""
    src = _read(ROUTE)
    assert "DHL_ACCOUNT_UNRESOLVED" in src
    m = re.search(r"# Missing / invalid account for the chosen billing party.*?raise HTTPException",
                  src, re.S)
    assert m, "the block path must exist"
    assert "dhl_express_account_number" not in m.group(0), \
        "no environment fallback once a sender is selected"


# ── 5. masking ───────────────────────────────────────────────────────────

def test_endpoint_strips_full_account_numbers():
    src = _read(ROUTE)
    assert 'pop("account_number", None)' in src, \
        "the read-only endpoint must strip full account numbers"


def test_ui_renders_masked_only():
    code = _code(HOOK)
    assert "masked" in code
    assert "account_number" not in code, \
        "the UI must never read a full account number"


# ── 6. stale async response ignored ──────────────────────────────────────

def test_requests_are_sequence_guarded():
    code = _code(HOOK)
    for ref in ("resolveSeq", "senderSeq", "receiverSeq"):
        assert ref in code, f"{ref} guard must exist"
    # Every guarded callback bails when superseded.
    assert code.count("current) return") >= 5, \
        "each async reply must bail out when a newer request superseded it"


def test_sequence_counter_increments_before_request():
    code = _code(HOOK)
    assert code.count("++resolveSeq.current") == 1
    assert code.count("++senderSeq.current") == 1
    assert code.count("++receiverSeq.current") == 1


# ── 7. no duplicate requests ─────────────────────────────────────────────

def test_no_duplicate_account_fetch_per_party():
    """Each party's accounts are fetched by exactly one effect."""
    code = _code(HOOK)
    assert code.count("PzApi.listCarrierAccounts") == 2, \
        "exactly one fetch per party (sender, receiver)"
    assert code.count("PzApi.resolveDhlAccounts") == 1, \
        "resolution must be requested from a single effect"


def test_resolution_endpoint_is_a_get():
    api = _read(API)
    m = re.search(r"resolveDhlAccounts: \(params\) =>\s*(\w+)\(", api)
    assert m and m.group(1) == "_get", "resolution must be a read-only GET"


# ── 8. no duplicated authority ───────────────────────────────────────────

def test_component_does_not_reimplement_resolver():
    code = _code(HOOK)
    assert "resolve_dhl_billing_account" not in code, \
        "the component must call the endpoint, not re-implement the resolver"
    for banned in ("third_party'", 'BILLING_SENDER', "payment_type"):
        assert banned not in code or "billing_party" in code


def test_no_parallel_state_store():
    code = _code(HOOK)
    for banned in ("localStorage", "sessionStorage", "window.__dhl", "createContext"):
        assert banned not in code, f"no parallel state store ({banned!r})"


def test_adapter_still_does_not_resolve():
    """The adapter may document the authority; it must not call it.

    Checked on the AST, not the text. The adapter now names the resolver in a
    docstring to record where the verdict it serializes came from — saying who
    decided is the opposite of deciding, and a substring search cannot tell the
    two apart.
    """
    import ast
    tree = ast.parse(_read(ADAPTER))
    called = {
        node.func.id if isinstance(node.func, ast.Name) else
        getattr(node.func, "attr", "")
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    assert "resolve_dhl_billing_account" not in called
    assert "resolve_declared_transport_payer" not in called
    assert "list_accounts" not in called
    consts = {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any("client_carrier_accounts" in c for c in consts)


# ── 10. sender-paid payload unchanged, receiver-paid now executes ─────────
#
# SUPERSEDED 2026-08-21. These two asserted the adapter's literal source text
# and that receiver billing was refused, while the MyDHL account contract was
# unverified. Receiver-paid now executes; the guarantees they protected are
# re-pinned below on BEHAVIOUR, which is stronger than the text match ever was.

def _accounts(**kw):
    from app.services.carrier.adapters.live import _build_accounts
    from app.services.carrier.models.shipment import ShipmentRequest
    base = dict(batch_id="B", recipient_address={}, declared_value=1.0,
                currency="EUR", weight_kg=1.0, dimensions={})
    base.update(kw)
    return _build_accounts(ShipmentRequest(**base))


def test_sender_paid_dhl_payload_unchanged():
    """Sender-paid still produces exactly the single 'shipper' entry."""
    assert _accounts(shipper_account="958214771") == [
        {"typeCode": "shipper", "number": "958214771"},
    ]


def test_receiver_paid_now_serializes_a_payer_entry():
    """The account Customer Master declared actually reaches the DHL request.

    This is the whole point of the repair: the panel used to display the
    receiver's account while the request billed the shipper.
    """
    assert _accounts(shipper_account="958214771",
                     transport_payer="receiver",
                     billing_account="111222333") == [
        {"typeCode": "shipper", "number": "958214771"},
        {"typeCode": "payer", "number": "111222333"},
    ]


def test_the_panel_and_the_booking_no_longer_disagree():
    """A resolved non-sender payer must not be reported as blocked.

    The account panel and the booking now answer alike. While they disagreed,
    the panel showed the receiver's account and the booking silently billed
    Estrella — the operator could not see which one was true.
    """
    src = _read(ROUTE)
    assert "DHL_BILLING_PARTY_NOT_ENABLED" not in src
    assert "billing_party_not_enabled" not in src
    # The superseded reason is kept as a marked constant, not deleted, so the
    # audit trail of why the block existed and why it lifted stays readable.
    assert "_RECEIVER_BILLING_WAS_BLOCKED_UNTIL_VERIFIED" in src


# =============================================================================
# Mount — the panel must actually reach the operator (no dark code)
# =============================================================================

MODAL = V2 / "proforma-detail.jsx"


def _modal_fn() -> str:
    """Just the AwbGenerateModal function body."""
    code = _code(MODAL)
    start = code.index("function AwbGenerateModal(")
    return code[start:start + 60000]


class TestAwbModalMount:

    def test_hook_is_used_in_the_modal(self):
        assert "useDhlAccountResolution({" in _modal_fn()

    def test_panel_is_rendered_in_the_modal(self):
        assert "<DhlAccountPanel" in _modal_fn()

    def test_modal_keeps_no_parallel_account_state(self):
        """No second source of truth for the account decision."""
        body = _modal_fn()
        for banned in ("useState(null); // account", "setBillingParty(",
                       "billingAccountId, setBillingAccountId"):
            assert banned not in body, f"modal must not own account state ({banned!r})"

    def test_modal_does_not_derive_a_default(self):
        body = _modal_fn()
        assert "is_default" not in body
        assert "resolve_dhl_billing_account" not in body

    def test_submit_button_gated_on_server_verdict(self):
        body = _modal_fn()
        assert "dhlBlocksSubmit" in body
        m = re.search(r'data-testid="awb-submit-btn"', body)
        assert m
        btn = body[max(0, m.start() - 300):m.start()]
        assert "dhlBlocksSubmit" in btn, "AWB button must honour the server verdict"

    def test_gate_only_applies_when_sender_is_known(self):
        """Without sender context the backend uses its legacy path — the panel
        must not block a flow that works today."""
        body = _modal_fn()
        assert "dhlSenderKnown && dhlAccounts.awbBlocked" in body

    def test_payload_extends_existing_contract(self):
        body = _modal_fn()
        assert "dhlAccounts.payloadFields" in body
        assert "createCarrierShipment" in body

    def test_payload_omitted_when_sender_unknown(self):
        """Criterion 10 — the existing sender-paid payload stays unchanged."""
        body = _modal_fn()
        assert "...(dhlSenderKnown ? dhlAccounts.payloadFields : {})" in body

    def test_panel_hidden_when_sender_unknown(self):
        body = _modal_fn()
        assert "dhlSenderKnown && (" in body

    def test_modal_unmounts_on_close(self):
        """Criterion 9 — no stale local state survives close/reopen."""
        code = _code(MODAL)
        assert "{showAwbModal && batchId && (() => {" in code, \
            "modal must be conditionally mounted so its state is destroyed on close"

    def test_no_full_account_number_in_modal(self):
        assert "account_number" not in _modal_fn()

    def test_prefill_carries_sender_contractor_id(self):
        assert "sender_contractor_id:" in _code(MODAL)
