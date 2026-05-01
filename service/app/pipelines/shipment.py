"""
shipment.py — Shipment batch pipeline
======================================
Handles: batch creation → invoice/SAD/AWB intake → ready state
Trigger sources: bot (Cliq commands), dashboard (upload UI)
"""
from __future__ import annotations
from pathlib import Path
from ..core import timeline as tl
from ..core.guards import guard_batch_is_primary_unit, guard_trigger_declared


async def receive_invoice(
    audit: dict,
    audit_path: Path,
    file_name: str,
    trigger_source: str,
    actor: str,
) -> dict:
    guard_batch_is_primary_unit(audit)
    guard_trigger_declared(trigger_source)
    tl.log_event(audit_path, tl.EV_INVOICE_UPLOADED, trigger_source, actor,
                 detail={"file": file_name})
    return {"status": "ok", "event": tl.EV_INVOICE_UPLOADED, "file_name": file_name}


async def receive_sad(
    audit: dict,
    audit_path: Path,
    file_name: str,
    trigger_source: str,
    actor: str,
) -> dict:
    guard_batch_is_primary_unit(audit)
    guard_trigger_declared(trigger_source)
    tl.log_event(audit_path, tl.EV_SAD_UPLOADED, trigger_source, actor,
                 detail={"file": file_name})
    return {"status": "ok", "event": tl.EV_SAD_UPLOADED, "file_name": file_name}


async def receive_awb(
    audit: dict,
    audit_path: Path,
    file_name: str,
    trigger_source: str,
    actor: str,
) -> dict:
    guard_batch_is_primary_unit(audit)
    guard_trigger_declared(trigger_source)
    tl.log_event(audit_path, tl.EV_AWB_UPLOADED, trigger_source, actor,
                 detail={"file": file_name})
    return {"status": "ok", "event": tl.EV_AWB_UPLOADED, "file_name": file_name}
