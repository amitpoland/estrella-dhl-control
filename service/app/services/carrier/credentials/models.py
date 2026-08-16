"""Neutral credential identity types — no vendor field names."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


CARRIERS = frozenset({"dhl", "fedex", "ups"})
ENVIRONMENTS = frozenset({"production", "sandbox"})
CAPABILITIES = frozenset(
    {
        "ship",
        "track",
        "epod",
        "documents",
        "ship_rate",
        "return",
        "webhook",
    }
)


class CapabilityState(str, Enum):
    READY = "ready"
    NOT_PROVISIONED = "not_provisioned"
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"
    AUTH_FAILED = "auth_failed"
    BLOCKED_GLOBAL = "blocked_global"
    # Candidate sealed on disk; active credential unchanged; not validated.
    STORED_UNVALIDATED = "stored_unvalidated"


@dataclass(frozen=True)
class CredentialIdentity:
    carrier: str
    environment: str
    capability: str

    def __post_init__(self) -> None:
        c = self.carrier.lower().strip()
        e = self.environment.lower().strip()
        cap = self.capability.lower().strip()
        if c not in CARRIERS:
            raise ValueError(f"unknown carrier: {self.carrier!r}")
        if e not in ENVIRONMENTS:
            raise ValueError(f"unknown environment: {self.environment!r}")
        if cap not in CAPABILITIES:
            raise ValueError(f"unknown capability: {self.capability!r}")
        object.__setattr__(self, "carrier", c)
        object.__setattr__(self, "environment", e)
        object.__setattr__(self, "capability", cap)

    @property
    def key(self) -> str:
        return f"{self.carrier}/{self.environment}/{self.capability}"


@dataclass(frozen=True)
class CredentialMeta:
    """Safe-for-GET projection — never contains raw secrets."""

    identity: CredentialIdentity
    configured: bool
    active: bool
    fingerprint: str | None = None
    masked_suffix: str | None = None
    last_validated_at: str | None = None
    last_rotated_at: str | None = None
    updated_by: str | None = None
    state: CapabilityState = CapabilityState.NOT_CONFIGURED


@dataclass(frozen=True)
class CredentialBundle:
    """Resolved secrets for an adapter. Never log or serialize to HTTP."""

    identity: CredentialIdentity
    fields: Mapping[str, str] = field(default_factory=dict)
    fingerprint: str | None = None
    slot: str | None = None  # "A" | "B"
