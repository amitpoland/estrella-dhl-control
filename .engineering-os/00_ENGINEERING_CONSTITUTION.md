# 00 — Engineering Constitution

**EJ Engineering OS v1.0** · docs-only framework · created 2026-07-08
Status: **REFERENCE** — this is an execution framework, not application code. It changes no
behavior on its own. It composes with, and is subordinate to, `CLAUDE.md` GATES 1–6, the
Engineering Lessons, and the 7-agent deploy gate.

---

## 0. What this OS is

The EJ Engineering OS is a **reusable execution framework** for running work packages on the
EJ Dashboard (the one application; "PZ" is a workflow inside it, per the Application Authority
Rule). It does not replace any existing authority. It **organizes** the authorities that
already exist — GATES 1–6, the 7-agent deploy gate, the skills in `SKILL_REGISTRY.md`, and the
agents in `.claude/agents/AGENT_REGISTRY.md` — into one predictable flow so that every package
is routed, reviewed, made operable, deployed, and recorded the same way.

**It is docs. It authorizes nothing.** Production mutation is owned by the 7-agent deploy gate
and the operator. Skills inform; agents execute within skill contracts; councils review;
the Executive Coordinator sequences. Nothing here overrides `CLAUDE.md`.

---

## 0.1 Primary objective (overrides everything else in this OS)

**Execution speed, correctness, and low token usage are mandatory.** The Engineering OS exists
to **reduce discussion, not increase it.** Every rule below is subordinate to this objective:
if applying a rule would generate discussion that does not change the outcome, apply the rule
silently and execute. The OS is a fast lane, not a committee.

## 1. First principles (non-negotiable)

0. **Speed is a first principle.** Reduce discussion. Default to execution when information is
   sufficient (`06 §Default Execution Mode`). Councils, agents, and skills run **internally** —
   report decisions, findings, blockers, implementation, and verification, not deliberation.
1. **Business capabilities first, not pages.** Work is scoped to a *business capability*
   (master-data, warehouse, returns-qc, manufacturing, commercial, integrations, platform),
   never to "a page" or "a file." A capability owns its authority, page, API, DB, and service.
   See `05_CAPABILITY_REGISTRY.md`.
2. **One Executive Coordinator.** Exactly one orchestration role sequences a package. It
   classifies, loads the manifest, routes, and gates — it never implements. See `01`.
3. **Skills define standards.** How a thing is done correctly is owned by a skill
   (`SKILL_REGISTRY.md`). Agents may not invent craft rules that a skill already owns.
4. **Agents execute within skill contracts.** An agent acts only inside the standard its
   governing skill defines, and only within its declared capability class (inspect-only,
   runtime write-capable, or guarded scoped-implementer). See `03`.
5. **Councils review, they do not implement.** Review bodies (Architecture, Backend,
   Frontend, Security, Test, Deploy, Governance) issue verdicts. They never mutate. See `02`.
6. **The Business Operability gate is mandatory.** No capability is "complete" without all
   four layers — Automation, Business API, Business UI, Observability — and the four
   operator questions answered. See `07`.
7. **No implementation starts until the capability manifest is loaded.** The manifest
   (`capabilities/<name>/manifest.md`) names the authority, page, API, DB, and service to be
   extended. If any is unnamable, **STOP** (mirrors CLAUDE.md §20 "prove the chain").
8. **Fast Path vs Deep Path is explicit.** Every package declares which path it runs. See
   `06`.
9. **Token economy is a first-class constraint.** Load the minimum manifest, the minimum
   skills, the minimum agents. See `09`.
10. **Deployment references the existing gate.** This OS never defines a new deploy path;
    it points to the 7-agent deploy gate. See `08`.

---

## 2. The authority chain (immutable — from the Phase-C Constitution)

```
wFirma (external ERP)
  → Mirror Layer (sync-only; 6 columns; never business logic)
  → EJ Dashboard Masters (Product Master, Customer Master, Warehouse, Invoice, Packing, Inventory)
  → All business capabilities
```

No capability bypasses this chain. Inventory/Sales/Returns/etc. read product & customer facts
only from the Masters, never directly from wFirma or the Mirror (Master Consumption Rule).

---

## 3. Layered model of the OS

```
Constitution (00)            ← non-negotiable principles + precedence
      │
Executive Coordinator (01)   ← the single orchestrator (classify → route → gate)
      │
      ├── Council Registry (02)        ← review bodies (verdict-only)
      ├── Agent Router (03)            ← who executes (AGENT_REGISTRY.md source)
      ├── Skill Router (04)            ← which standards apply (SKILL_REGISTRY.md source)
      ├── Capability Registry (05)     ← what business capability is in scope
      ├── Package Lifecycle (06)       ← Fast/Deep path stages + gates
      ├── Business Operability (07)    ← mandatory 4-layer completeness gate
      ├── Deployment Governance (08)   ← references the 7-agent deploy gate
      ├── Token Controller (09)        ← token economy
      └── Knowledge Engine (10)        ← state, memory, lessons, scorecards
```

---

## 4. Precedence (which authority wins)

When two rules appear to conflict, resolve top-down:

1. `CLAUDE.md` **GATES 1–6** and the **Engineering Lessons** (A–N).
2. The **7-agent deploy gate** for anything that syncs to `C:\PZ`.
3. **Protected-domain** stop-and-ask (financial, customs, accounting, inventory, shipment,
   fiscal writes) and **Lesson N** (advisory-vs-blocker) for readiness/gating.
4. The **owning skill** (`SKILL_REGISTRY.md`) for craft/authority within its domain.
5. This **Engineering OS** framework (sequencing, routing, operability, token economy).

The OS never sits above GATES 1–6 or the deploy gate. Where this framework appears to conflict
with them, they win — full stop.

---

## 5. What the OS explicitly does NOT do

- It does not authorize a deploy (the 7-agent gate does).
- It does not create or modify agents or skills (they are frozen per their own policies).
- It does not recompute financials (only `process_batch()` does).
- It does not create duplicate authority (one page/API/route/state per module).
- It does not promote an advisory signal to a hard blocker without a named fiscal risk
  (Lesson N).

## 6. Freeze rule

**Engineering OS v1.0 is FROZEN as of this amendment (2026-07-08).** It is deliberately minimal
and additive. No further change lands in v1.0. Future changes go into **v1.1 only after evidence
from real packages** — a change must be justified by an observed failure or friction in an
actual package run, not by speculation. Extensions are a separate, separately-approved package —
never silent sprawl.
