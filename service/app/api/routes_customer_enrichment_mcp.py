"""
routes_customer_enrichment_mcp.py — remote MCP surface for Claude Cowork
(Client Master external enrichment research).

Hand-rolled MCP Streamable-HTTP JSON-RPC 2.0 endpoint: system Python 3.9 is
load-bearing and the official `mcp` SDK requires >= 3.10, so this implements
the minimal method set directly — initialize / notifications/initialized /
ping / tools/list / tools/call. POST-only, stateless, no SSE, no sessions.

Security model (DHL-webhook layering, routes_carrier_webhook.py precedent):
  1. customer_enrichment_mcp_enabled False        -> 503 (feature dark)
  2. customer_enrichment_mcp_token unset          -> 503 (never silently open;
     503 not 401 so a probe cannot learn whether a secret exists)
  3. Authorization: Bearer missing/malformed      -> 401
  4. token mismatch (hmac.compare_digest)         -> 401

Exactly THREE tools — no generic SQL, no arbitrary reads. The researcher sees
ONLY the stored allowlist-serialized identity context (11 keys), never a raw
Customer Master row. Submitted results are UNTRUSTED input; the inputSchema
enums are a first filter and validate_enrichment_submission is the server-side
defense regardless.
"""
from __future__ import annotations

import hmac
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..core.config import settings
from ..core.logging import get_logger
from ..services import customer_external_enrichment as enrichment
from ..services.customer_external_enrichment import (
    CONFIDENCE_LEVELS,
    RESEARCHABLE_PHASE_1,
    SOURCE_TYPES,
    EnrichmentValidationError,
    ProposalStateError,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/mcp", tags=["customer-enrichment-mcp"])

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "estrella-atlas-client-enrichment", "version": "1.0.0"}


def _enrich_db():
    return settings.storage_root / "customer_enrichment.sqlite"


def _require_mcp_auth(request: Request) -> None:
    """Layered gate: 503 disabled -> 503 unconfigured -> 401 missing -> 401 mismatch."""
    if not settings.customer_enrichment_mcp_enabled:
        raise HTTPException(
            status_code=503,
            detail="Customer enrichment MCP is not enabled on this server.")
    token = settings.customer_enrichment_mcp_token
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Customer enrichment MCP is not configured on this server.")
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    supplied = header[7:].strip()
    if not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="Not authenticated")


_mcp_auth = Depends(_require_mcp_auth)


# ── Tool definitions (exactly three) ─────────────────────────────────────────

_FIELD_ENUM = sorted(RESEARCHABLE_PHASE_1)

_TOOLS = [
    {
        "name": "get_customer_enrichment_task",
        "description": (
            "Claim a customer-enrichment research task. Without task_id, the "
            "oldest pending task is claimed; with task_id, that task is "
            "claimed (or returned if already claimed). Returns the read-only "
            "identity context and the list of missing fields to research. "
            "Research ONLY the listed fields, from public sources, and submit "
            "via submit_customer_enrichment_result. Returns null when no task "
            "is pending."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Optional: claim this specific task.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_customer_enrichment_result",
        "description": (
            "Submit research results for a claimed task. One proposal per "
            "field. A proposal with a non-null proposed_value REQUIRES at "
            "least one evidence entry with a public http(s) source URL. If a "
            "field could not be verified from public sources, submit "
            "proposed_value null with confidence 'none' — never invent data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "proposals": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "enum": _FIELD_ENUM},
                            "proposed_value": {
                                "type": ["string", "null"],
                                "maxLength": 500,
                            },
                            "confidence": {
                                "type": "string",
                                "enum": sorted(CONFIDENCE_LEVELS),
                            },
                            "reason": {
                                "type": ["string", "null"],
                                "maxLength": 1000,
                            },
                            "evidence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "source_url": {
                                            "type": "string",
                                            "maxLength": 2048,
                                        },
                                        "source_title": {
                                            "type": ["string", "null"],
                                            "maxLength": 500,
                                        },
                                        "source_type": {
                                            "type": "string",
                                            "enum": sorted(SOURCE_TYPES),
                                        },
                                        "retrieved_at": {
                                            "type": ["string", "null"],
                                        },
                                    },
                                    "required": ["source_url"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["field", "proposed_value", "confidence"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["task_id", "proposals"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_customer_enrichment_task_status",
        "description": (
            "Status of a submitted task: task status plus per-field operator "
            "decisions (pending / accepted / rejected)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
]


# ── Tool implementations ─────────────────────────────────────────────────────

def _tool_get_task(args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    task = enrichment.claim_enrichment_task(
        _enrich_db(), args.get("task_id") or None)
    if task is None:
        return None
    # Disclosure allowlist: identity context + missing fields ONLY.
    return {
        "task_id": task["id"],
        "status": task["status"],
        "missing_fields": task["missing_fields"],
        "identity_context": task["identity_context"],
    }


def _tool_submit_result(args: Dict[str, Any]) -> Dict[str, Any]:
    return enrichment.submit_enrichment_result(
        _enrich_db(), args["task_id"], args.get("proposals"))


def _tool_task_status(args: Dict[str, Any]) -> Dict[str, Any]:
    task = enrichment.get_enrichment_task(_enrich_db(), args["task_id"])
    return {
        "task_id": task["id"],
        "status": task["status"],
        "fields": [
            {
                "field": p["field"],
                "field_status": p["field_status"],
                "conflict_flag": p["conflict_flag"],
            }
            for p in task.get("proposals", [])
        ],
    }


_TOOL_IMPLS = {
    "get_customer_enrichment_task": _tool_get_task,
    "submit_customer_enrichment_result": _tool_submit_result,
    "get_customer_enrichment_task_status": _tool_task_status,
}


# ── JSON-RPC plumbing ────────────────────────────────────────────────────────

def _rpc_result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def _handle_tools_call(req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    impl = _TOOL_IMPLS.get(name)
    if impl is None:
        return _rpc_error(req_id, -32602, f"Unknown tool: {name}")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        return _rpc_error(req_id, -32602, "arguments must be an object")
    try:
        result = impl(args)
    except (EnrichmentValidationError, ProposalStateError) as exc:
        return _rpc_error(req_id, -32602, str(exc))
    except KeyError as exc:
        return _rpc_error(req_id, -32602, str(exc))
    return _rpc_result(req_id, {
        "content": [{"type": "text",
                     "text": json.dumps(result, default=str)}],
        "isError": False,
    })


@router.post("/customer-enrichment", include_in_schema=False,
             dependencies=[_mcp_auth])
async def mcp_endpoint(request: Request):
    """MCP Streamable-HTTP endpoint (JSON-RPC 2.0 over POST, stateless)."""
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(_rpc_error(None, -32700, "Parse error"),
                            status_code=400)
    if not isinstance(body, dict):
        return JSONResponse(_rpc_error(None, -32600,
                                       "Batch requests are not supported"),
                            status_code=400)

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params") or {}

    # Notifications (no id) are acknowledged with 202 and no body.
    if method == "notifications/initialized" or (
            isinstance(method, str) and method.startswith("notifications/")):
        return Response(status_code=202)

    if method == "initialize":
        return JSONResponse(_rpc_result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }))
    if method == "ping":
        return JSONResponse(_rpc_result(req_id, {}))
    if method == "tools/list":
        return JSONResponse(_rpc_result(req_id, {"tools": _TOOLS}))
    if method == "tools/call":
        if not isinstance(params, dict):
            return JSONResponse(_rpc_error(req_id, -32602,
                                           "params must be an object"))
        return JSONResponse(_handle_tools_call(req_id, params))

    return JSONResponse(_rpc_error(req_id, -32601,
                                   f"Method not found: {method}"))
