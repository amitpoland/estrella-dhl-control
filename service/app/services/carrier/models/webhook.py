"""
DHL Express webhook payload model.

Defines the expected shape of inbound DHL webhook events.
Unknown future DHL fields are accepted (extra="allow") so the model
does not break on API additions.

Tracking identifiers are never stored in logs — log_safe() strips them.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


_TRACKING_KEYS: frozenset = frozenset(
    {
        "trackingNumber",
        "shipmentTrackingNumber",
        "awbNumber",
        "masterTrackingNumber",
        "pieceTrackingNumber",
    }
)


class DhlWebhookPayload(BaseModel):
    """
    Minimal validated fields from a DHL Express webhook event.

    Extra fields from DHL are accepted and preserved in .model_extra.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    eventId: Optional[str] = None
    event: Optional[str] = None
    timestamp: Optional[str] = None
    batchId: Optional[str] = None

    def extract_event_id(self) -> Optional[str]:
        """Return the best available event identifier, or None."""
        return (
            self.eventId
            or (self.model_extra or {}).get("event_id")
            or (self.model_extra or {}).get("id")
        )

    def extract_event_type(self) -> str:
        """Return the event type string, defaulting to 'unknown'."""
        return (
            self.event
            or (self.model_extra or {}).get("eventType")
            or (self.model_extra or {}).get("event_type")
            or "unknown"
        )

    def extract_batch_id(self) -> str:
        """Return batch_id if present, or empty string."""
        return self.batchId or (self.model_extra or {}).get("batch_id") or ""


def make_log_safe(raw_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of the raw webhook dict with DHL tracking identifiers removed.

    Always call this before persisting or logging webhook payload data.
    """
    return {k: v for k, v in raw_dict.items() if k not in _TRACKING_KEYS}
