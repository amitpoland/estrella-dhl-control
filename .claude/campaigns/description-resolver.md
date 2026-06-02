# Campaign: Shared Description Resolver + Approved Mapping Table

**Status:** PLANNED  
**Depends on:** PR #424 (`fix/polish-desc-pnd-metal-codes`) merged and deployed  
**Branch convention:** `feat/description-resolver`  
**Do not touch:** PR #424 content, `customs_description_engine.py` GOLD_PURITY dict (those are now stable)

**Last reviewed:** 2026-06-02 — operator line-by-line review. All adjustments incorporated below.

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

Build a shared resolver layer that **injects normalised metal/purity facts into
the engine**, so the engine remains the sole description renderer and the mapping
table stores facts — not wording.

---

## Authoritative architecture (operator-reviewed 2026-06-02)

```
Invoice line description
  ↓
1. resolver.lookup(token)
   ├─ HIT  → inject canonical_metal + purity facts into engine call
   │          engine generates wording from facts  (engine is ALWAYS the renderer)
   └─ MISS ↓
2. engine.normalize_item_description(description)   ← GOLD_PURITY fallback (stable)
   ├─ OK   → use result
   └─ FAIL (material_pl == "metal szlachetny") ↓
3. AI auto-suggest (deterministic first, LLM only for genuinely novel tokens)
   ↓
4. customs_desc_checker: emit customs_description_mismatch proposal
   data.scope_hint       = "shipment" | "global_mapping"  ← AI recommends
   data.suggested_output = heuristic / LLM result         ← advisory only
   ↓
5. Inbox proposal → operator reviews
   Option A: Approve for this shipment only  → audit["description_corrections"]
   Option B: Approve + create reusable rule  → description_mappings table
   Option C: Edit + approve (either scope)
   Option D: Reject                          → nothing written
```

**Critical distinction from previous draft:**

| ❌ Previous (incorrect) | ✅ Corrected |
|---|---|
| Resolver HIT → skip engine, use mapping directly | Resolver HIT → inject facts, engine generates wording |
| `description_pl` as primary authority | `description_pl` as override only; engine generates from facts |

The engine is the single description renderer. The resolver injects normalised
facts so the engine can render correctly for tokens it would otherwise miss.

---

## Hard rules (do not violate)

| Rule | Enforcement |
|---|---|
| Engine is the sole description renderer | Resolver never returns a finished description; it injects facts |
| AI never writes to `description_mappings` | Only `write_mapping()` writes; only called from approved Inbox handler |
| AI never auto-approves | `scope` comes from operator request body, never from checker or AI |
| Resolver HIT does not skip engine | `inject_facts()` is called, then engine runs |
| `scope_hint` is advisory only | Label it "AI recommends" in UI; operator makes the final choice |
| AI is last-resort, not first | Deterministic heuristics run first; LLM only for genuinely unknown tokens |
| No supplier-specific metal meaning without explicit `supplier_scope` | See governance rule below |
| Every global_mapping approval stores full audit trail | See auditability rule below |

---

## Governance rule: no implicit supplier-specific metal interpretation

Supplier-specific **parsing** (extracting tokens from PDF formats) is allowed and
already exists (`invoice_packing_extractor.py`, `global_packing_parser.py`).

Supplier-specific **metal interpretation** is **prohibited** unless an approved
mapping explicitly carries `supplier_scope`.

Example of what this prevents:

> "18KT means 750 purity for EJL but means something different for Supplier X"

That must never happen silently. If a token has different meanings per supplier,
two separate mappings must exist with explicit `supplier_scope` values. A mapping
with `supplier_scope = NULL` applies to all suppliers and must represent universal
jewellery industry convention.

This rule prevents the old EJL vs Global Jewellery split from reappearing as
hidden resolver behaviour.

---

## Auditability rule: every global_mapping approval is permanently answerable

Every row written to `description_mappings` with an Inbox approval must store
enough context to answer the question:

> *"Why does PT960 resolve to platyna próby 960?"*

without digging through old shipments or session logs.

Required fields on every `write_mapping()` call:
- `approved_by` — operator identity
- `approved_at` — timestamp
- `source_proposal_id` — back-link to the Inbox proposal that authorised the write
- `source_text` — original invoice description that triggered the proposal
- `confidence` — confidence level at proposal time

These are non-nullable for `global_mapping` scope writes. Shipment-scope writes
(`audit["description_corrections"]`) already carry `approved_by` and `approved_at`.

---

## Components to build

### 1. `description_mappings` table (`master_data.sqlite`)

Stores **normalised facts**, not finished descriptions.
`description_pl` exists as an override field but is not the primary authority.

```sql
CREATE TABLE IF NOT EXISTS description_mappings (
    id                 TEXT PRIMARY KEY,
    token              TEXT NOT NULL,         -- raw token: "PT960", "18KT/Y"
    canonical_metal    TEXT,                  -- "platinum" | "gold" | "silver"
    purity             TEXT,                  -- "960" | "750" | "925"
    material_pl        TEXT NOT NULL,         -- "platyna próby 960"  (engine input)
    description_pl     TEXT DEFAULT NULL,     -- finished sentence override (rare)
    created_at         TEXT NOT NULL,
    approved_by        TEXT NOT NULL,         -- operator who approved (non-nullable)
    approved_at        TEXT NOT NULL,         -- timestamp (non-nullable)
    source_proposal_id TEXT NOT NULL,         -- back-link to Inbox proposal (non-nullable)
    source_text        TEXT NOT NULL,         -- original invoice line that triggered proposal
    confidence         TEXT NOT NULL,         -- "high" | "medium" | "low"
    supplier_scope     TEXT DEFAULT NULL,     -- NULL = all; "ejl" / "global_jewellery"
    active             INTEGER DEFAULT 1      -- 0 = soft-deleted / superseded
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_dm_token_supplier
    ON description_mappings(token, COALESCE(supplier_scope, ''));
```

### 2. `description_resolver.py` (new service)

```python
def lookup(token: str, supplier_scope: str = None) -> Optional[Dict[str, str]]:
    """Return {"canonical_metal": ..., "purity": ..., "material_pl": ...} or None.
    
    Returns normalised facts, not a finished description.
    Caller passes result to engine as injection facts.
    Never returns a finished description_pl unless the mapping has an explicit override.
    
    Lookup order:
      1. Exact match: token + supplier_scope
      2. Exact match: token + supplier_scope=NULL (global rule)
      3. None → caller falls through to engine
    """

def inject_facts(description: str, facts: Dict[str, str]) -> str:
    """Return a modified description string that the engine will parse correctly.
    
    Injects resolved canonical_metal + purity tokens into the raw description
    so that engine.normalize_item_description() produces the correct material_pl.
    
    Example:
      description = "PCS, PT960 Premium Platinum, Plain RING"
      facts = {"canonical_metal": "platinum", "purity": "960",
               "material_pl": "platyna próby 960"}
      → engine-compatible: "PCS, PT960, Plain RING [resolved: platyna próby 960]"
    
    The injection strategy is engine-specific and must be validated against the
    engine's normalize_item_description() to confirm the output is correct.
    """

def write_mapping(
    token:              str,
    canonical_metal:    str,
    purity:             str,
    material_pl:        str,
    approved_by:        str,
    approved_at:        str,
    source_proposal_id: str,
    source_text:        str,
    confidence:         str,
    description_pl:     str = None,
    supplier_scope:     str = None,
) -> str:
    """Write approved global mapping. Returns new mapping id.
    All audit fields are non-nullable. Never called without an approved proposal_id.
    """

def _tokenize(description: str) -> List[str]:
    """Extract candidate lookup tokens from raw invoice description.
    'PCS, PT960 Premium Platinum,Plain RING' → ['PT960', 'Platinum']
    Tokens are normalised to UPPER CASE. Order: most-specific first.
    """
```

### 3. Updated `customs_desc_checker.py`

Flow per invoice line:

```
token = _tokenize(description)
facts = resolver.lookup(token, supplier_scope)
if facts:
    enriched = resolver.inject_facts(description, facts)
    norm = engine.normalize_item_description(enriched, ...)
    # norm.material_pl should now be correct — no proposal needed
else:
    norm = engine.normalize_item_description(description, ...)
    if norm.material_pl in FORBIDDEN_MATERIAL_PL:
        suggestion = _suggest_material_pl(description, token)  # deterministic first
        # LLM via ai_gateway ONLY if deterministic returns None
        emit proposal with suggestion + scope_hint
```

**AI auto-suggest order (non-negotiable):**
1. Deterministic heuristics (pattern matching on token: `PT\d{3}` → platinum, `\d{2}KT` → gold, …)
2. LLM via `ai_gateway` only if (1) returns None

PT950 and any token matching existing engine patterns must never reach the LLM.

### 4. Updated proposal `data` block

```json
{
  "source_text":       "PCS, PT960 Premium Platinum,Plain RING",
  "current_output":    "metal szlachetny",
  "suggested_output":  "platyna próby 960",
  "suggested_canonical_metal": "platinum",
  "suggested_purity":  "960",
  "confidence":        "high",
  "reason":            "PT + 3-digit fineness → platinum pattern; 960 = próby 960",
  "scope_hint":        "global_mapping",
  "token_detected":    "PT960",
  "pattern_family":    "platinum",
  "evidence":          "Token 'PT960' matched PT\\d{3} platinum pattern"
}
```

### 5. Updated `routes_action_proposals.py` — approval write path

```python
class DescriptionCorrection(BaseModel):
    material_pl:        Optional[str] = None
    description_pl:     Optional[str] = None
    canonical_metal:    Optional[str] = None   # NEW: "platinum" | "gold" | "silver"
    purity:             Optional[str] = None   # NEW: "960" | "750" | "925"
    supplier_scope:     Optional[str] = None   # NEW: None = global; "ejl" = scoped

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
    canonical_metal    = body.correction.canonical_metal or "",
    purity             = body.correction.purity or "",
    material_pl        = body.correction.material_pl,
    approved_by        = body.approved_by,
    approved_at        = _now(),
    source_proposal_id = proposal_id,
    source_text        = proposal["data"]["source_text"],
    confidence         = proposal["data"].get("confidence", "medium"),
    description_pl     = body.correction.description_pl or None,
    supplier_scope     = body.correction.supplier_scope or None,
)
```

### 6. Tests required

- `PT960` not in GOLD_PURITY + not in DB → engine fails → proposal emitted
- `PT960` approved as `global_mapping` → DB row written with all audit fields
- Future lookup of `PT960` hits resolver → `inject_facts` called → engine renders correctly → no proposal
- PT950 hits engine directly (GOLD_PURITY) → no resolver lookup needed → no proposal
- Approve scope=shipment → `audit["description_corrections"]` written, DB NOT written
- Reject → nothing written anywhere
- Supplier-scoped mapping (supplier_scope="ejl") → miss for Global Jewellery supplier → falls through to engine
- Global mapping (supplier_scope=NULL) → hit for both EJL and Global Jewellery suppliers
- Deterministic heuristic covers PT + 3-digit fineness → LLM never called for that pattern
- `write_mapping()` with missing `approved_by` raises (non-nullable enforcement)
- `write_mapping()` with missing `source_proposal_id` raises (auditability enforcement)
- Soft-deleted mapping (active=0) returns None from lookup → falls through to engine

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

## What this unlocks long-term

```
Supplier parsers (EJL, Global Jewellery, future)
      ↓
Shared resolver (description_mappings — operator-grown, fact-based)
      ↓
Engine (GOLD_PURITY fallback — stable, code-deployed)
      ↓
AI validator → Inbox proposals for unknown tokens
      ↓
Human approval → shipment or global_mapping scope

EJL, Global Jewellery, and future suppliers all use
the same description authority.
```

The mapping table grows continuously from real shipments without code deploys.
Novel tokens create proposals; approvals expand the resolver.
The engine remains the sole description renderer.
The AI suggests; humans approve; only approval writes.

---

## To start this sprint

Open a fresh Claude Code session and paste:

```
ROLE: estrella-dhl-control
CAMPAIGN: description-resolver (see .claude/campaigns/description-resolver.md)
GATE: Confirm PR #424 is merged before proceeding.
BUILD: Shared description resolver + approved mapping table per campaign doc.
SCOPE: description_mappings table in master_data.sqlite, description_resolver.py,
       inject_facts() pattern, updated checker (resolver before engine),
       updated approval path (scope + audit fields), full test suite.
DO NOT TOUCH: customs_description_engine.py GOLD_PURITY,
              audit["description_corrections"] path (keep as-is).
ARCHITECTURE RULE: Engine is the sole description renderer.
                   Resolver injects facts; engine generates wording.
                   description_pl in DB is an override, not the primary authority.
AI RULE: Deterministic heuristics first. LLM only for genuinely novel tokens.
         PT950 and patterns already in GOLD_PURITY must never reach the LLM.
```
