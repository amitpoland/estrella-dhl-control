# Campaign: Shared Description Resolver + Approved Mapping Table

**Status:** PLANNED  
**Depends on:** PR #424 (`fix/polish-desc-pnd-metal-codes`) merged and deployed  
**Branch convention:** `feat/description-resolver`  
**Do not touch:** PR #424 content, `customs_description_engine.py` GOLD_PURITY dict (those are now stable)

---

## Problem

The PT950 fix added platinum to `GOLD_PURITY` in the engine source code.
That works, but it can only grow via code deploys.

When a new supplier uses a token the engine doesn't recognise (`PT960`,
`GOLD-750-HALLMARK`, `AGS14K`, …), the system produces "metal szlachetny",
the AI checker flags it, and the operator approves a fix — but that fix only
lives in `audit["description_corrections"]` (shipment scope).

The next shipment from the same supplier with the same token starts the cycle again.

**The gap:** no persistent, operator-grown, DB-backed resolver that survives
between shipments.

---

## Goal

Build a shared resolver layer that sits between the AI checker and the engine.
Operator-approved mappings are written to a DB table once and resolve correctly
for every future shipment — without code deploys.

---

## Architecture

```
Invoice line description
  ↓
1. resolver.lookup(token)          ← DB-backed, grows via Inbox approvals
   HIT  → use mapping directly     ← no engine call needed
   MISS ↓
2. engine.normalize_item_description(...)   ← GOLD_PURITY fallback (stable)
   OK   → use result
   FAIL (material_pl == "metal szlachetny") ↓
3. checker: emit customs_description_mismatch proposal
   scope_hint = "shipment" | "global_mapping"   ← AI recommends, operator decides
   suggested_output = AI heuristic / LLM result ← advisory only
   ↓
4. Inbox proposal → operator reviews
   Option A: Approve for this shipment only → audit["description_corrections"]
   Option B: Approve + create reusable rule → description_mappings table
   Option C: Edit + approve (either scope)
   Option D: Reject → nothing written
```

**Hard rules:**
- AI never writes to `description_mappings`
- Only an operator-approved Inbox action writes a reusable mapping
- `scope` is chosen by the operator at approval time, not by the AI
- `scope_hint` is the AI's recommendation and is clearly labelled as a suggestion

---

## Components to build

### 1. `description_mappings` table (new — `documents.db` or `master_data.sqlite`)

```sql
CREATE TABLE description_mappings (
    id                 TEXT PRIMARY KEY,
    token              TEXT NOT NULL,         -- raw token: "PT960", "18KT/Y"
    material_pl        TEXT NOT NULL,         -- "platyna próby 960"
    description_pl     TEXT,                  -- full sentence (optional)
    created_at         TEXT NOT NULL,
    created_by         TEXT NOT NULL,         -- operator who approved
    source_proposal_id TEXT,                  -- back-link to Inbox proposal
    confidence         TEXT,                  -- "high" / "medium" / "low"
    supplier_scope     TEXT DEFAULT NULL,     -- NULL = all; "ejl" / "global_jewellery"
    active             INTEGER DEFAULT 1      -- 0 = soft-deleted / superseded
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_dm_token_supplier
    ON description_mappings(token, COALESCE(supplier_scope, ''));
```

Stored in `master_data.sqlite` (consistent with the master-data pattern).

### 2. `description_resolver.py` (new service)

```python
def lookup(token: str, supplier_scope: str = None) -> Optional[Dict[str, str]]:
    """Return {"material_pl": ..., "description_pl": ...} or None."""

def _tokenize(description: str) -> List[str]:
    """Extract lookup tokens from raw invoice description.
    'PCS, PT950 Platinum,Plain Jewel RING' → ['PT950', 'Platinum', 'RING', ...]
    """

def write_mapping(
    token: str,
    material_pl: str,
    description_pl: str,
    created_by: str,
    source_proposal_id: str,
    confidence: str,
    supplier_scope: str = None,
) -> str:
    """Write approved mapping to DB. Returns new mapping id."""
```

### 3. Updated `customs_desc_checker.py`

- Consult `description_resolver.lookup(token)` before running engine
- If resolver HIT: skip engine, no proposal, use mapping
- AI auto-suggest: `_suggest_material_pl(description, token)` — deterministic
  heuristics first, LLM via `ai_gateway` for genuinely novel tokens
- Populate `data.suggested_output`, `data.confidence`, `data.reason`, `data.scope_hint`

### 4. Updated `routes_action_proposals.py` — approval write path

```python
# ApproveBody already has correction field.
# Add scope field:
class ApproveBody(BaseModel):
    approved_by:  str
    note:         Optional[str] = None
    correction:   Optional[DescriptionCorrection] = None
    scope:        Literal["shipment", "global_mapping"] = "shipment"  # NEW
```

On approve with `scope="global_mapping"`:
```python
description_resolver.write_mapping(
    token              = proposal["data"]["token_detected"],
    material_pl        = body.correction.material_pl,
    description_pl     = body.correction.description_pl or "",
    created_by         = body.approved_by,
    source_proposal_id = proposal_id,
    confidence         = proposal["data"].get("confidence", "medium"),
    supplier_scope     = body.correction.supplier_scope or None,
)
```

### 5. Updated proposal schema (`data` block)

```json
{
  "source_text":      "PCS, PT960 Premium Platinum,Plain RING",
  "current_output":   "metal szlachetny",
  "suggested_output": "platyna próby 960",
  "confidence":       "high",
  "reason":           "PT + 3-digit fineness → platinum pattern; 960 = próby 960",
  "scope_hint":       "global_mapping",
  "token_detected":   "PT960",
  "pattern_family":   "platinum",
  "evidence":         "Token 'PT960' found in position 2 of description"
}
```

### 6. Tests required

- `PT950` hits resolver (from DB after being written) → no engine call
- Unknown `PT960` → miss → engine fails → proposal with scope_hint="global_mapping"
- Approve scope=shipment → `audit["description_corrections"]` written, NOT DB
- Approve scope=global_mapping → `description_mappings` row written
- Future lookup of `PT960` hits resolver → no proposal
- Reject → nothing written anywhere
- Supplier-scoped mapping: EJL-specific token returns None for Global Jewellery supplier
- Resolver soft-delete (active=0) falls through to engine
- Duplicate token+supplier_scope raises or supersedes cleanly

---

## Sprint boundary rule

**This campaign is BLOCKED until PR #424 is merged.**  
Reason: PR #424 stabilises the engine baseline (PT950/PT900/PT850 in GOLD_PURITY
and the AI checker). This campaign builds ON TOP of that stable foundation.
Starting before #424 merges risks double-patching the same files.

Once PR #424 merges:
1. Create branch `feat/description-resolver` from main
2. Run sprint from this document
3. Do not modify `customs_description_engine.py::GOLD_PURITY` in this sprint —
   the engine tables are now correct; the resolver supplements them, not replaces them

---

## Key invariants (do not violate)

| Invariant | Enforcement |
|---|---|
| AI never writes to `description_mappings` | Only `description_resolver.write_mapping()` writes; only called from approved Inbox action handler |
| AI never auto-approves | `scope` field comes from operator request body, not from checker |
| Shipment scope stays fast | `audit["description_corrections"]` path unchanged |
| Engine stays as fallback | Resolver consults engine on miss; engine is not removed |
| Approval is mandatory | `write_mapping` is never called without a `proposal_id` from an approved proposal |

---

## What this unlocks long-term

```
Supplier parsers
      ↓
Shared resolver (description_mappings DB, operator-grown)
      ↓
Engine (GOLD_PURITY fallback, code-deployed)
      ↓
AI validator → Inbox proposals for unknowns
      ↓
Human approval → choose shipment or global_mapping scope

EJL, Global Jewellery, and future suppliers all use
the same description authority.
```

The mapping table grows continuously from real shipments without code changes.
Novel tokens create proposals; approvals expand the resolver.
The engine becomes the last-resort fallback, not the primary authority.

---

## To start this sprint

Open a fresh Claude Code session and paste:

```
ROLE: estrella-dhl-control
CAMPAIGN: description-resolver (see .claude/campaigns/description-resolver.md)
GATE: Confirm PR #424 is merged before proceeding.
BUILD: Shared description resolver + approved mapping table per campaign doc.
SCOPE: description_mappings table, description_resolver.py, updated checker,
       updated approval path, full test suite.
DO NOT TOUCH: customs_description_engine.py GOLD_PURITY,
              audit["description_corrections"] path (keep as-is).
```
