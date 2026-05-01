from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ProcessParams(BaseModel):
    """
    Non-file parameters for POST /api/v1/pz/process.
    Delivered as form fields alongside the multipart file uploads.
    """
    doc_no:          str  = Field(default="", description="Document number, e.g. 'PZ 12/3/2026'")
    carrier:         str  = Field(default="", description="Carrier name (optional)")
    settlement_mode: Literal["standard", "art33a"] = "standard"
    strict_match:    bool = False
    nbp_rate:        Optional[float] = Field(default=None, description="Manual USD/PLN rate; fetched from NBP if omitted")

    # Cliq delivery
    post_to_cliq:      bool = False
    target_type:       Literal["bot", "chat", "user"] = "bot"
    target_id:         str  = Field(default="", description="Bot name / chat ID / user email")
