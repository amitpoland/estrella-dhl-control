# Campaign: Shared Description Resolver + Approved Mapping Table

**Status:** PLANNED  
**Depends on:** PR #424 (`fix/polish-desc-pnd-metal-codes`) merged and deployed  
**Branch convention:** `feat/description-resolver`  
**Do not touch:** PR #424 content, `customs_description_engine.py` GOLD_PURITY dict (those are now stable)

**Last reviewed:** 2026-06-02 — operator line-by-line review + governance corrections. Final rule confirmed.

---

## Canonical rule (locked — do not override in implementation)

```
Known metal/purity token
→ deterministic resolver/engine renders

Unknown metal/purity token
→ no AI guess
→ Inbox proposal with empty suggestion
→ human verifies supplier/source
→ human enters approved mapping
→ future shipments can use it
```

Every implementation decision in this campaign must be consistent with this rule.
When in doubt, the rule wins.

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

## Authoritative architecture (operator-reviewed 2026-06-02, corrected 2026-06-02)

```
Invoice line description
  ↓
1. resolver.lookup(token)
   ├─ HIT  → resolved_facts = {canonical_metal, purity, material_pl}
   │          engine.normalize_item_description(description,
   │                                            resolved_facts=facts)
   │          engine uses facts directly for metal/purity wording;
   │          parses only type, stones, descriptors from raw text.
   │          No second metal/purity parse.
   └─ MISS ↓
2. engine.normalize_item_description(description, resolved_facts=None)
   engine parses metal/purity from raw text via GOLD_PURITY (stable fallback)
   ├─ OK   → use result
   └─ FAIL (material_pl == "metal szlachetny") ↓
3. checker: emit customs_description_mismatch proposal
   AI suggests (deterministic heuristics only — see PT960 rule below)
   data.scope_hint       = "shipment" | "global_mapping"  ← AI recommends
   data.suggested_material_pl = heuristic result          ← advisory only
   ↓
4. Inbox proposal → operator reviews
   Option A: Approve for this shipment only  → audit["description_corrections"]
   Option B: Approve + create reusable rule  → description_mappings table
   Option C: Edit + approve (either scope)
   Option D: Reject                          → nothing written
```

**Design decision — why `resolved_facts`, not `inject_facts(string)`:**

`inject_facts(raw_string, facts) → enriched_string` was the previous proposal.
It was rejected because it puts metal/purity back into an unparsed string and
lets the engine re-extract them — two parsers run on the same metal data and can
diverge. The problem that caused the PT950 bug in the first place.

The correct separation:
- **Resolver** owns metal/purity interpretation (one parser, one time)
- **Engine** owns wording/rendering from facts + remaining raw text for type/stones

```python
# ❌ Rejected — double-parse risk
enriched = inject_facts("PCS, PT960 Ring", {"material_pl": "platyna próby 960"})
norm = engine.normalize_item_description(enriched)
# engine may re-parse metal from the enriched string and diverge

# ✅ Correct — single parse, structured handoff
facts = resolver.lookup("PT960")
# facts = {"canonical_metal": "platinum", "purity": "960",
#          "material_pl": "platyna próby 960"}
norm = engine.normalize_item_description("PCS, PT960 Ring", resolved_facts=facts)
# engine skips metal/purity detection; uses facts.material_pl directly;
# parses only item_type ("RING"), stones, descriptors from raw text
```

**Engine API change required:**

```python
# customs_description_engine.py — normalize_item_description signature change
def normalize_item_description(
    raw_description:  str,
    item_type:        str = "",
    hsn_from_invoice: str = "",
    resolved_facts:   Optional[Dict[str, str]] = None,  # NEW
) -> dict:
    """
    If resolved_facts is provided:
      - Skip the GOLD_PURITY purity-detection loop entirely.
      - Use resolved_facts["material_pl"] as the authoritative material.
      - Use resolved_facts["canonical_metal"] and resolved_facts["purity"]
        for HS classification and sentence grammar.
      - Parse item_type, stones, and descriptors from raw_description as normal.
    If resolved_facts is None:
      - Existing behaviour unchanged (GOLD_PURITY loop runs).
    """
```

This change is additive and backwards-compatible — `resolved_facts=None` is the
default and the existing code path is unchanged.

---

## Hard rules (do not violate)

| Rule | Enforcement |
|---|---|
| Engine is the sole description renderer | Resolver provides structured facts; engine generates wording. No finished description ever comes from the resolver. |
| Metal/purity parsed exactly once | Resolver wins if it has a mapping; engine's GOLD_PURITY loop runs only on resolver miss. Never both. |
| `inject_facts(string)` is permanently rejected | It would cause double-parsing. Use `resolved_facts=` parameter on the engine call. |
| AI never writes to `description_mappings` | Only `write_mapping()` writes; only called from approved Inbox handler |
| AI never auto-approves | `scope` comes from operator request body, never from checker or AI |
| Unknown token → empty proposal, not output | An unknown token creates an Inbox proposal with `suggested_material_pl = ""`. The system does not guess. Operator investigates and decides. |
| `_suggest_material_pl()` uses GOLD_PURITY only | No pattern-matching heuristics for unknown purities. Only tokens already in GOLD_PURITY get a suggestion. PT960 → None. |
| LLM not used for metal/purity tokens | An LLM guess on a customs metal code is as dangerous as a silent automatic write. Unknown metal → empty suggestion → human decides. |
| `scope_hint` is advisory only | Label it "AI recommends" in UI; operator makes the final choice |
| No supplier-specific metal meaning without explicit `supplier_scope` | See governance rule below |
| Every global_mapping approval stores full audit trail | See auditability rule below |

---

## PT950 vs PT960 — the canonical governance example

PT960 is not a known platinum standard. It appears here as a governance example
to show how the system handles an **unknown token**. The rule that matters is
about the unknown path, not the specific value 960.

---

**Known path — PT950, PT900, PT850:**

These are approved platinum standards. They are present in `GOLD_PURITY`
(engine fallback) and will also be pre-seeded into `description_mappings`
at sprint start.

```
Invoice: "PCS, PT950 Platinum, Plain RING"
resolver.lookup("PT950") → HIT
resolved_facts = {canonical_metal: "platinum", purity: "950",
                  material_pl: "platyna próby 950"}
engine.normalize_item_description(raw, resolved_facts=facts)
→ material_pl: "platyna próby 950"  ✅

No AI. No proposal. No human approval needed.
The system knows. It renders.
```

---

**Unknown path — PT960 as a governance example:**

The system receives a token it has never seen before. It cannot know whether
the token is:
- a legitimate platinum fineness
- a supplier-specific code
- a typo
- a marketing label
- an internal SKU fragment
- something else entirely

The system must not guess. Guessing would produce an unverified value on
customs paperwork, which is exactly what the design exists to prevent.

```
Invoice: "PCS, PT960 Premium Platinum, Plain RING"
resolver.lookup("PT960") → MISS (not in description_mappings)
engine.normalize_item_description(raw, resolved_facts=None)
→ material_pl: "metal szlachetny"  ← GOLD_PURITY has no PT960 entry
checker detects forbidden placeholder.

suggested_material_pl = ""   ← intentionally empty
                              The system does not know what PT960 means.
                              It does not guess.

Proposal emitted:
  {
    "source_text":           "PCS, PT960 Premium Platinum, Plain RING",
    "token_detected":        "PT960",
    "current_output":        "metal szlachetny",
    "suggested_material_pl": "",       ← system declines to guess
    "scope_hint":            "global_mapping",
    "confidence":            "low",
    "reason":                "Token 'PT960' not found in description_mappings
                              or GOLD_PURITY. Cannot determine whether this
                              is a platinum fineness, supplier code, or typo.
                              Human decision required."
  }

❌ Nothing is written to the PDF.
❌ Nothing is written to description_mappings.
✅ Inbox proposal created. Operator investigates and decides.
```

Operator receives the proposal, consults the source invoice and supplier
documentation, determines what PT960 actually means, and approves with the
correct value — or rejects if the token is a typo.

**After operator approves PT960 as global_mapping:**
```
description_mappings row written:
  token           = "PT960"
  canonical_metal = "platinum"      ← operator confirmed
  purity          = "960"           ← operator confirmed
  material_pl     = "platyna próby 960"
  approved_by     = "operator_name"
  approved_at     = "2026-06-02T..."
  source_proposal_id = "..."
  source_text     = "PCS, PT960 Premium Platinum, Plain RING"

Next shipment:
  resolver.lookup("PT960") → HIT
  → engine renders "platyna próby 960" without a proposal.
```

---

**Why `_suggest_material_pl()` must NOT pattern-match unknown purities:**

The previous draft had `_suggest_material_pl("PT960") → "platyna próby 960"`
using the heuristic `PT + 3-digit fineness → platinum`. This was incorrect.

The heuristic cannot know whether PT960 is platinum próby 960 or something
else. Suggesting "platyna próby 960" in the proposal would anchor the
operator's decision toward an unverified value and undermine the governance
model. On customs paperwork, an anchored guess is as dangerous as a silent
automatic output.

**`_suggest_material_pl()` only suggests for patterns where the interpretation
is unambiguous by industry convention — i.e., patterns already covered by
`GOLD_PURITY`. For anything not in `GOLD_PURITY`, it returns `None`.**

If `_suggest_material_pl()` returns `None`, the `suggested_material_pl` field
in the proposal is empty. The operator sees: *"Unknown token — please
investigate and enter the correct value."*

This is the correct behavior. The Inbox is the decision point. The suggestion
field is for operator convenience, not for the system to pre-decide.

---

**The governance rule in two lines:**
```
Known token (in resolver or GOLD_PURITY) → render.
Unknown token                            → Inbox proposal, empty suggestion, human decides.
```

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

    Returns normalised FACTS — never a finished description.
    Caller passes result directly to engine as resolved_facts parameter.
    Never returns description_pl unless the mapping has an explicit override
    (operator-entered; treated as a finished-sentence override by the engine).

    Lookup order:
      1. Exact match: token + supplier_scope  (supplier-scoped rule wins)
      2. Exact match: token + supplier_scope=NULL  (global rule)
      3. None → caller runs engine without resolved_facts (GOLD_PURITY fallback)
    """

# inject_facts(string) — PERMANENTLY REMOVED.
# Reason: would cause double-parsing of metal/purity.
# The correct handoff is resolved_facts= parameter on the engine call.

def write_mapping(
    token:              str,
    canonical_metal:    str,
    purity:             str,
    material_pl:        str,
    approved_by:        str,    # non-nullable
    approved_at:        str,    # non-nullable
    source_proposal_id: str,    # non-nullable — auditability requirement
    source_text:        str,    # non-nullable — auditability requirement
    confidence:         str,    # non-nullable
    description_pl:     str = None,   # override only; engine prefers facts
    supplier_scope:     str = None,   # None = global; "ejl" etc. = scoped
) -> str:
    """Write operator-approved global mapping. Returns new mapping id.

    Called ONLY from the Inbox approval handler (routes_action_proposals.py).
    Never called from checker, AI layer, or background process.
    Raises ValueError if any non-nullable audit field is missing.
    """

def _tokenize(description: str) -> List[str]:
    """Extract candidate lookup tokens from a raw invoice description.

    'PCS, PT960 Premium Platinum,Plain RING' → ['PT960', 'PLATINUM', 'RING']

    Tokens normalised to UPPER CASE. Ordered most-specific first so PT960 is
    checked before PLATINUM in the resolver lookup.
    """

def _suggest_material_pl(token: str) -> Optional[str]:
    """Deterministic lookup — returns a suggestion ONLY for tokens whose
    interpretation is already established by industry convention in GOLD_PURITY.

    Used by the checker to populate data.suggested_material_pl in proposals.
    This is ADVISORY ONLY. Output is never rendered without DB approval.

    Strategy: consult GOLD_PURITY (the engine's stable allowlist) directly.
      If token is in GOLD_PURITY → return that value as a suggestion.
      If token is not in GOLD_PURITY → return None.

    Intentional limitation:
      Pattern-matching heuristics (e.g. PT + 3-digit fineness → assume platinum)
      are PROHIBITED. The system cannot know whether an unknown purity code is
      a valid fineness, a supplier code, a typo, or something else. Guessing
      and presenting it as a suggestion would anchor the operator's decision
      toward an unverified value on customs paperwork.

      Unknown token → None → empty suggestion field → operator investigates.

    Examples:
      _suggest_material_pl("PT950") → "platyna próby 950"  (in GOLD_PURITY)
      _suggest_material_pl("18KT")  → "złoto próby 750"    (in GOLD_PURITY)
      _suggest_material_pl("PT960") → None  (NOT in GOLD_PURITY; system declines to guess)
      _suggest_material_pl("UNOBTAINIUM") → None

    Caller behaviour when None:
      suggested_material_pl = ""   # explicitly empty
      confidence = "low"
      reason = "Token not in known allowlist — human investigation required."
      LLM fallback (ai_gateway) is NOT invoked for unknown metal tokens.
      Unknown metals require a human decision, not an AI guess.
    """
```

### 3. Updated `customs_desc_checker.py`

Flow per invoice line:

```python
tokens = resolver._tokenize(description)
facts  = None
for token in tokens:                              # most-specific first
    facts = resolver.lookup(token, supplier_scope)
    if facts:
        break

if facts:
    # Resolver hit: single metal/purity parse — pass facts directly to engine.
    # Engine skips GOLD_PURITY detection; uses facts["material_pl"] directly.
    norm = engine.normalize_item_description(
        description, resolved_facts=facts,
    )
    # norm.material_pl is authoritative. No proposal needed.
    continue

# Resolver miss: engine runs its own GOLD_PURITY detection.
norm = engine.normalize_item_description(description, resolved_facts=None)

if norm["material_pl"] not in FORBIDDEN_MATERIAL_PL:
    continue  # engine resolved it — no proposal needed

# Engine also failed. Build a proposal.
# Deterministic suggest — never renders, only populates proposal field.
suggestion = resolver._suggest_material_pl(token or "")
if suggestion is None:
    # LLM via ai_gateway ONLY for genuinely unknown patterns.
    suggestion = _ai_suggest(description)   # None if ai_gateway not configured

emit proposal:
{
  "source_text":             description,
  "current_output":          norm["material_pl"],
  "suggested_material_pl":   suggestion or "",  # empty → operator fills at approval
  "scope_hint":              "global_mapping" if suggestion else "shipment",
  "confidence":              "high" if suggestion else "low",
  "reason":                  ...,
}
# Nothing is written. Nothing is rendered. Only a proposal.
```

**Suggestion rules — no guessing:**
- `_suggest_material_pl(token)` only returns a value when the token is in `GOLD_PURITY`.
- For unknown tokens it returns `None` → `suggested_material_pl = ""` in the proposal.
- LLM (`ai_gateway`) is NOT invoked for unknown metal tokens. An AI guess on a
  metal/purity code would anchor the operator toward an unverified customs value.
- Operator sees: *"Unknown token 'PT960'. Token not in known allowlist — please
  investigate source invoice and enter the correct value."*
- The suggestion field, when populated, is advisory only and never renders.

**Suggestion order:**
1. `_suggest_material_pl(token)` — GOLD_PURITY lookup only, no patterns, no LLM
2. Empty string if (1) returns None — operator fills manually

LLM is not in this chain for metal/purity. The system does not guess on
customs paperwork.

PT950 and any token in `GOLD_PURITY` will be resolved by the engine on a
resolver miss. They will never reach the proposal path at all.

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

**Resolver lookup and engine handoff:**
- `PT950` in description_mappings → `lookup("PT950")` returns facts → `normalize_item_description(raw, resolved_facts=facts)` → correct `material_pl`, no GOLD_PURITY parse
- `PT950` NOT in description_mappings (resolver miss) → engine runs GOLD_PURITY → resolves correctly (already in GOLD_PURITY from PT950 fix) → no proposal
- `PT960` not in description_mappings + not in GOLD_PURITY → engine fails → `_suggest_material_pl("PT960")` returns `"platyna próby 960"` → proposal emitted, `suggested_material_pl = "platyna próby 960"`
- `PT960` proposal emitted → PDF is NOT generated with "platyna próby 960" (proposal only, no output write)

**Engine API — resolved_facts parameter:**
- `normalize_item_description(raw, resolved_facts={"material_pl": "platyna próby 960"})` → returns `material_pl = "platyna próby 960"` without running GOLD_PURITY loop
- `normalize_item_description(raw, resolved_facts=None)` → existing behaviour unchanged
- `resolved_facts` provided → engine still parses item_type, stones from raw text

**Approval and write:**
- `PT960` approved as `global_mapping` → `write_mapping()` called → DB row created with all non-nullable audit fields
- Future `lookup("PT960")` → HIT → facts passed to engine → correct output, no proposal
- Approve scope=shipment → `audit["description_corrections"]` written, `description_mappings` NOT written
- Reject → nothing written anywhere

**Governance:**
- Supplier-scoped mapping (supplier_scope="ejl") → `lookup("TOKEN", "global_jewellery")` → None → falls through to engine
- Global mapping (supplier_scope=NULL) → `lookup("TOKEN", "ejl")` → HIT → returned for all suppliers
- `write_mapping()` with missing `approved_by` → raises ValueError
- `write_mapping()` with missing `source_proposal_id` → raises ValueError
- `write_mapping()` with missing `source_text` → raises ValueError

**AI suggest — GOLD_PURITY-only, no guessing:**
- `_suggest_material_pl("PT950")` → "platyna próby 950" (in GOLD_PURITY — suggestion populated)
- `_suggest_material_pl("18KT")`  → "złoto próby 750" (in GOLD_PURITY — suggestion populated)
- `_suggest_material_pl("PT960")` → None (NOT in GOLD_PURITY — system declines to guess)
- `_suggest_material_pl("UNOBTAINIUM-X")` → None (unknown — system declines to guess)
- LLM (`ai_gateway`) never called for metal/purity tokens — unknown metal requires human decision
- `PT960` proposal has `suggested_material_pl = ""`, `confidence = "low"` — operator investigates
- `PT950` never reaches `_suggest_material_pl` (resolved by GOLD_PURITY before proposal path)

**Soft-delete:**
- Mapping with `active=0` → `lookup()` returns None → falls through to engine

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
SCOPE:
  - description_mappings table in master_data.sqlite
  - description_resolver.py (lookup, write_mapping, _tokenize, _suggest_material_pl)
  - Engine API change: normalize_item_description(raw, resolved_facts=None)
  - Updated checker: resolver before engine, resolved_facts handoff, no inject_facts
  - Updated approval path: scope field, write_mapping on global_mapping approval
  - Full test suite per tests-required section of campaign doc
DO NOT TOUCH:
  - customs_description_engine.py GOLD_PURITY (stable — engine fallback)
  - audit["description_corrections"] path (shipment scope — keep as-is)
  - inject_facts() — permanently rejected, must not appear in implementation
ARCHITECTURE RULES:
  - Engine is the sole description renderer
  - Resolver passes resolved_facts= to engine; engine skips GOLD_PURITY when facts present
  - Metal/purity parsed exactly once — resolver or engine, never both
  - PT960 creates a proposal with suggested_material_pl; it does NOT render output
  - Unknown purity → Inbox proposal → human approval → then DB write
AI RULES:
  - _suggest_material_pl() runs deterministic patterns first (PT\d{3}, \d{2}KT, etc.)
  - LLM via ai_gateway only if deterministic returns None
  - Suggestion populates proposal field only — never writes to DB or PDF
```
