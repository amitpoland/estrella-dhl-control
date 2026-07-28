"""dhl_account_resolver.py — the ONE account-resolution authority for DHL.

Operator directive 2026-07-20. Authority split, exactly as ratified:

    Client Master / Carrier tab  = business authority for DHL account ownership
    Shipment pipeline            = resolves WHICH account to use
    DHL adapter                  = only sends the resolved account to DHL

The DHL adapter must never decide which customer account to bill. Every DHL
workflow — Rate Quote, Create Shipment, Generate AWB, Pickup Booking, future
Label Reprint, future Return Shipment — calls ``resolve_dhl_billing_account()``
so there is a single source of truth for the decision.

SHIPPING ACCOUNT vs BILLING ACCOUNT are separate concepts (operator refinement
2026-07-20). Being the sender does NOT mean being charged. The resolver returns
both, independently:

    shipping_account  — the account the shipment moves on (sender's)
    billing_account   — the account transport charges land on (billing party's)

Resolution order (operator-specified):

    sender → resolve sender account
           → resolve receiver account
           → determine billing party
           → select account

Default rules (operator-specified, no hard-coded account numbers anywhere):

  * exactly one active account for the party        → auto-select it
  * several active, one flagged is_default          → auto-select the default
  * several active, none flagged default            → operator must choose
  * none                                            → block shipment creation

Reads the existing Client Master carrier-account store
(``client_carrier_accounts_db``). Creates no table, no endpoint, no second
source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .client_carrier_accounts_db import CarrierAccount, list_accounts

# Billing party — who transport charges are billed to.
BILLING_SENDER = "sender"
BILLING_RECEIVER = "receiver"
BILLING_THIRD_PARTY = "third_party"

BILLING_PARTIES = (BILLING_SENDER, BILLING_RECEIVER, BILLING_THIRD_PARTY)

# Normal outbound default (operator-specified): Sender pays. Receiver-paid is
# never inferred merely because the receiver happens to own a DHL account.
DEFAULT_BILLING_PARTY = BILLING_SENDER

# Carrier key in the Client Master account store.
CARRIER_DHL = "dhl"

# Blocking reason codes — stable identifiers the UI and tests can assert on.
REASON_NO_SENDER = "sender_not_selected"
REASON_NO_SENDER_ACCOUNT = "sender_account_missing"
REASON_NO_RECEIVER = "receiver_not_selected"
REASON_NO_RECEIVER_ACCOUNT = "receiver_account_missing"
REASON_NO_THIRD_PARTY_ACCOUNT = "third_party_account_missing"
REASON_AMBIGUOUS = "account_choice_required"
REASON_BAD_BILLING_PARTY = "billing_party_invalid"


@dataclass
class AccountChoice:
    """One selectable account, in business terms only.

    Deliberately carries no credentials, API keys or technical metadata —
    operational screens show business information only.
    """
    id: int
    account_number: str
    account_name: Optional[str] = None
    billing_role: Optional[str] = None      # payment_type: shipper|receiver|third_party
    is_default: bool = False

    @property
    def masked(self) -> str:
        """Business-safe display, e.g. 'DHL account •••• 6789'."""
        tail = (self.account_number or "")[-4:]
        return f"DHL account •••• {tail}" if tail else "DHL account —"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "account_number": self.account_number,
            "account_name": self.account_name,
            "billing_role": self.billing_role,
            "is_default": self.is_default,
            "masked": self.masked,
        }


@dataclass
class ResolvedAccounts:
    """Outcome of resolution. ``ok`` gates AWB creation."""
    ok: bool
    billing_party: str
    shipping_account: Optional[AccountChoice] = None
    billing_account: Optional[AccountChoice] = None
    # Populated when the operator must choose between several active accounts.
    choices: List[AccountChoice] = field(default_factory=list)
    choice_for: Optional[str] = None        # which party needs the choice
    reason: Optional[str] = None            # REASON_* code
    message: Optional[str] = None           # operator-facing business message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "billing_party": self.billing_party,
            "shipping_account": self.shipping_account.to_dict() if self.shipping_account else None,
            "billing_account": self.billing_account.to_dict() if self.billing_account else None,
            "choices": [c.to_dict() for c in self.choices],
            "choice_for": self.choice_for,
            "reason": self.reason,
            "message": self.message,
        }


def _to_choice(acct: CarrierAccount) -> AccountChoice:
    return AccountChoice(
        id=acct.id or 0,
        account_number=acct.account_number,
        account_name=acct.account_name,
        billing_role=acct.payment_type,
        is_default=bool(acct.is_default),
    )


def list_dhl_accounts(db_path: Path, contractor_id: Optional[str]) -> List[AccountChoice]:
    """Active DHL accounts for a contractor, default first.

    Reuses the existing Client Master store — the business authority for
    account ownership. No second lookup path.
    """
    if not contractor_id:
        return []
    accts = list_accounts(db_path, contractor_id, active=True)
    return [_to_choice(a) for a in accts
            if (a.carrier or "").strip().lower() == CARRIER_DHL]


def _select(choices: List[AccountChoice]):
    """Apply the operator's default rules to one party's accounts.

    Returns ``(chosen, needs_choice)``. ``chosen`` is None when the operator
    must pick, or when the party owns no active account at all.
    """
    if not choices:
        return None, False
    if len(choices) == 1:
        return choices[0], False
    defaults = [c for c in choices if c.is_default]
    if len(defaults) == 1:
        return defaults[0], False
    # Several active accounts and no single default — operator must choose.
    return None, True


def resolve_dhl_billing_account(
    db_path: Path,
    sender_contractor_id: Optional[str],
    receiver_contractor_id: Optional[str],
    billing_party: Optional[str] = None,
    *,
    third_party_contractor_id: Optional[str] = None,
    selected_billing_account_id: Optional[int] = None,
) -> ResolvedAccounts:
    """Resolve the shipping account and the billing (payer) account.

    This is the single entry point every DHL workflow must call. It decides;
    the DHL adapter only transmits.

    ``selected_billing_account_id`` lets the operator's explicit pick win when
    several active accounts exist — the resolver never guesses in that case.
    """
    party = (billing_party or DEFAULT_BILLING_PARTY).strip().lower()
    if party not in BILLING_PARTIES:
        return ResolvedAccounts(
            ok=False, billing_party=party, reason=REASON_BAD_BILLING_PARTY,
            message=(f"Unknown billing party {billing_party!r}. "
                     f"Expected one of: {', '.join(BILLING_PARTIES)}."),
        )

    if not sender_contractor_id:
        return ResolvedAccounts(
            ok=False, billing_party=party, reason=REASON_NO_SENDER,
            message="No sender is selected for this shipment.",
        )

    # ── Step 1: sender account (the shipping account) ────────────────────
    sender_choices = list_dhl_accounts(db_path, sender_contractor_id)
    shipping, sender_ambiguous = _select(sender_choices)

    if not sender_choices:
        return ResolvedAccounts(
            ok=False, billing_party=party, reason=REASON_NO_SENDER_ACCOUNT,
            message="No active DHL sender account is configured for the selected sender.",
        )
    if sender_ambiguous and party == BILLING_SENDER and selected_billing_account_id is None:
        return ResolvedAccounts(
            ok=False, billing_party=party, choices=sender_choices,
            choice_for=BILLING_SENDER, reason=REASON_AMBIGUOUS,
            message="Several active DHL accounts exist for this sender. Choose which account to use.",
        )
    if sender_ambiguous and shipping is None:
        # Sender is not the payer, but we still need a shipping account.
        # An explicit pick (below) may resolve it; otherwise ask.
        pass

    # ── Step 2: receiver account ─────────────────────────────────────────
    receiver_choices = list_dhl_accounts(db_path, receiver_contractor_id)

    # ── Step 3 + 4: billing party → billing account ──────────────────────
    if party == BILLING_SENDER:
        pool, missing_reason, missing_msg = (
            sender_choices, REASON_NO_SENDER_ACCOUNT,
            "No active DHL sender account is configured for the selected sender.")
    elif party == BILLING_RECEIVER:
        if not receiver_contractor_id:
            return ResolvedAccounts(
                ok=False, billing_party=party, reason=REASON_NO_RECEIVER,
                message="Receiver billing is selected, but no receiver is chosen.",
            )
        pool, missing_reason, missing_msg = (
            receiver_choices, REASON_NO_RECEIVER_ACCOUNT,
            "Receiver billing is selected, but no active DHL account "
            "is registered for this receiver.")
    else:  # third party
        pool, missing_reason, missing_msg = (
            list_dhl_accounts(db_path, third_party_contractor_id),
            REASON_NO_THIRD_PARTY_ACCOUNT,
            "Third-party billing is selected, but no approved active DHL "
            "account is registered for that party.")

    if not pool:
        return ResolvedAccounts(ok=False, billing_party=party,
                                reason=missing_reason, message=missing_msg)

    if selected_billing_account_id is not None:
        billing = next((c for c in pool if c.id == selected_billing_account_id), None)
        if billing is None:
            return ResolvedAccounts(
                ok=False, billing_party=party, choices=pool, choice_for=party,
                reason=REASON_AMBIGUOUS,
                message="The selected DHL account is not an active account for the billing party.",
            )
    else:
        billing, ambiguous = _select(pool)
        if ambiguous or billing is None:
            return ResolvedAccounts(
                ok=False, billing_party=party, choices=pool, choice_for=party,
                reason=REASON_AMBIGUOUS,
                message=("Several active DHL accounts exist for the billing party. "
                         "Choose which account to bill."),
            )

    # Shipping account falls back to the billing account only when the sender
    # side was ambiguous and the operator already made an explicit pick for a
    # sender-billed shipment; otherwise the sender's own selection stands.
    if shipping is None:
        if party == BILLING_SENDER:
            shipping = billing
        else:
            return ResolvedAccounts(
                ok=False, billing_party=party, choices=sender_choices,
                choice_for=BILLING_SENDER, reason=REASON_AMBIGUOUS,
                message="Several active DHL accounts exist for this sender. "
                        "Choose which account the shipment moves on.",
            )

    return ResolvedAccounts(ok=True, billing_party=party,
                            shipping_account=shipping, billing_account=billing)
