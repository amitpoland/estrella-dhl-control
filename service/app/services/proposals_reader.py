"""proposals_reader.py — Shared cross-batch audit scanner for action proposals.

Single traversal authority used by both routes_action_proposals (lookup by ID)
and routes_inbox (collect by status).  Neither caller needs to own the file-scan
loop; both delegate here and apply their own filter on the yielded proposals list.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List


def _iter_batch_proposals(
    outputs_dir: Path,
) -> Iterator[tuple[str, Dict[str, Any], List[Dict[str, Any]]]]:
    """Yield (batch_id, audit, proposals_list) for each batch dir with proposals.

    Silently skips:
      - outputs_dir that doesn't exist or isn't a directory
      - batch dirs without an audit.json
      - audit.json files that can't be parsed as JSON
      - batches whose action_proposals list is absent or empty

    The caller decides what to do with each tuple — filter by proposal_id for a
    lookup, filter by status for aggregation, etc.
    """
    if not outputs_dir.is_dir():
        return
    for batch_dir in outputs_dir.iterdir():
        if not batch_dir.is_dir():
            continue
        ap = batch_dir / "audit.json"
        if not ap.exists():
            continue
        try:
            audit = json.loads(ap.read_text(encoding="utf-8"))
        except Exception:
            continue
        proposals: List[Dict[str, Any]] = audit.get("action_proposals") or []
        if proposals:
            yield batch_dir.name, audit, proposals
