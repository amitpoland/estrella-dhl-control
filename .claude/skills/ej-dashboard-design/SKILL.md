---
name: ej-dashboard-design
metadata:
  version: 1.0.0
description: >
  Project governance layer for the EJ Dashboard Portal (Estrella Jewels / Atlas-v2 frontend, 25+ module ERP). Enforces V2 authority resolution, routing-based canonical file identification, API/business-logic preservation, and design-system consistency. Use whenever the user invokes /frontend-design on this codebase, or mentions the EJ Dashboard, EJ Portal, Estrella Jewels frontend, V2 pages, inventory-detail, or any .jsx file under service/app/static/. Also trigger on "redesign," "restyle," "polish," "clean up," or "modernize" requests for any page here, even without the words "design" or "frontend" — e.g. "make the inventory page look better" or "the reports page looks dated." Supplements the general frontend-design skill rather than replacing its visual-craft guidance; constrains it with this project's single-authority architecture, existing tokens, and no-duplicate-page rules. Always consult both together — there's no automatic inheritance, so both must be active.
---

# EJ Dashboard Portal — Design Governance

This skill layers project-specific guardrails on top of the general `frontend-design` skill. Use both together:

- **`frontend-design`** governs craft — typography pairing, layout rhythm, motion, avoiding generic AI-design tells.
- **This skill** governs *safety and consistency* on this specific codebase — it can override `frontend-design`'s instinct to take aesthetic risks or introduce new type/color systems. On the EJ Dashboard Portal, **consistency across 25+ modules beats novelty on any single page.** If the two skills conflict, this skill wins for anything touching architecture, tokens, or existing business logic; `frontend-design` still wins for micro-decisions within a page (spacing, motion detail, copy tone) as long as they respect the tokens below.

## 0. Before touching any code: identify the canonical page

This codebase has a known failure mode: duplicate/competing page definitions (e.g. the `pages.jsx` vs `pages-v2.jsx` collision, where `pages-v2.jsx` is the intentional override). Before editing anything:

1. Search for all files that could plausibly own the page in question (check both a `v2`/legacy split and any naming variants).
2. If more than one candidate exists, inspect the router/entry point to see which one is actually imported/served — that's the canonical version, not the most recently touched one. This is a default you apply directly, not something to ask the user about (see Section 3).
3. State the canonical file path back to the user before making changes: *"Editing `service/app/static/v2/inventory-detail.jsx` — confirmed this is the routed V2 authority."*
4. If the target page/file can't be found at all, or the router inspection itself is inconclusive (see Section 4), stop and ask rather than guessing or creating something new.
5. Never create a new page/component when an existing authoritative one already covers that surface, even if the existing file is messy. Refactor in place.

## 1. Hard rules (do not violate without explicit, written user override)

- **Single authority**: never create a duplicate page, duplicate route, or duplicate state store for something that already has a canonical owner.
- **Preserve API wiring**: do not change endpoints, request/response shapes, hooks, or data-fetching logic as a side effect of a visual change. If a visual change genuinely requires a wiring change, flag it separately and get confirmation first.
- **Preserve business logic**: never simplify, remove, or "clean up" working business logic in the name of a visual improvement. Visual and logic changes are separate changes.
- **No placeholder data**: every value rendered must come from real data wiring already in place. Never hardcode sample values to make a mockup look finished.
- **Design tokens over new systems**: reuse this project's existing design tokens, color variables, spacing scale, and shared components. Do not introduce a new palette, a new type scale, or a one-off component when an existing shared one covers the need.
- **Typography**: respect the existing design system and typography. Introduce a new font only when the user explicitly requests it — this overrides `frontend-design`'s general instinct to pick deliberate, unusual type pairings per page. Consistency across modules matters more than per-page typographic personality here.
- **Match approved references exactly**: if a Figma file or wireframe is provided as the source of truth, match it exactly — layout, spacing, states — unless the user explicitly says to deviate.
- **Accessibility is non-negotiable**: keyboard navigation and visible focus states must work; verify tab order for any interactive element touched.
- **Responsive across three breakpoints**: desktop, tablet, and mobile must all be checked, not just desktop.
- **Motion stays subtle**: transitions/animations should be performance-friendly and restrained — this is an internal ERP tool, not a marketing site. Prefer no animation over a flashy one.

**Component naming:**
- Reuse existing component names and exports — don't rename a component as part of a styling pass.
- Never rename a routed component unless the router and every importing file are updated in the same change. A rename that isn't propagated everywhere is effectively a silent duplicate authority.
- Don't introduce parallel components (`InventoryDetailNew`, `ReportsPageModern`, `SettingsV2`, etc.) alongside an existing one unless the user has explicitly approved creating a new authority. This is a specific instance of the single-authority rule above, called out because it's the most common way duplicate authorities get created accidentally.

**Legacy files:**
- Never edit a legacy file unless it is still routed (i.e., actually imported/served — not just present in the repo).
- Don't delete legacy files as part of design work, even ones that look clearly superseded. Deletion is a separate decision from a styling task.
- When legacy and V2 versions both exist, resolve authority through the router/imports, never through filename age or which one was touched more recently.

## 2. Workflow for a design task on this codebase

1. **Scope check**: restate which file(s) you'll touch, confirmed against step 0. If the request is ambiguous in one of the ways covered by Section 3's table, apply the default and state it — don't stop to ask. Only stop if one of Section 4's four triggers applies.
2. **Inventory existing tokens/components**: before writing new CSS or JSX, check for existing shared components/utility classes that already solve the need (buttons, cards, table shells, form fields, etc.). Reuse them.
3. **Draft the change**: apply `frontend-design`'s craft guidance for the specific micro-decisions (spacing, hierarchy, motion) inside the constraints above.
4. **Self-check against the hard rules in Section 1** before presenting the result — explicitly go down the list.
5. **Report back**: tell the user what you changed, what you deliberately left untouched (API wiring, business logic), and flag anything that seemed like it needed a decision beyond the stated scope.

## 3. Ambiguity resolution — default interpretations

Most ambiguity should be resolved by proceeding with the safest bounded interpretation and *stating the assumption*, not by stopping to ask. Only one case below requires stopping. Always state which default you applied in the report-back step.

| Ambiguous signal | Default interpretation | Ask first? |
|---|---|---|
| Request is "visual only" / "cosmetic" / "styling" language ("clean up," "polish," "modernize," "make it pop") | No API/state/business-logic changes. Styling and layout only. | No — state the assumption |
| Multiple candidate files could own a page (e.g. `pages.jsx` vs `pages-v2.jsx`) | Inspect the router/entry point first; whichever file is actually routed/imported there is canonical | No — inspect, then state which file is canonical |
| No Figma/wireframe/reference provided | Use existing tokens and shared components only; no new visual language, no new palette/type entries | No — state the assumption and offer to adjust if a reference shows up later |
| The target page/file cannot be found anywhere in the codebase | — | **Yes — stop and ask** (this is trigger #1 in Section 4). Do not create a new page/file as a guess for what the user meant. |

## 4. When to actually stop and ask

**Default posture: prefer proceeding with a narrow, safe edit over asking a broad design question.** Most requests, including ambiguous ones, should be resolved via Section 3's defaults and narrowed to the smallest edit that satisfies what was asked. Escalating to a question is the exception, not the habit.

Ask — and only ask — when the action **could**:

1. **Create a new page or component.** Includes the missing-file case (Section 3) and any situation where the safe move would require introducing a new file rather than editing an existing one.
2. **Change API behavior.** Any endpoint, request/response shape, hook contract, or data-fetching logic — not just an intentional change, but anything where the visual work as requested can't be done *without* touching it.
3. **Add a new design authority.** A second implementation of something that already has one, a rename that isn't fully propagated, a new parallel component (`*New`, `*Modern`, `*V2` alongside an existing version), a new token system, or a routing ambiguity that can't be resolved by inspecting the router/imports.
4. **Touch financial, customs, or accounting logic.** Even if the request frames it as a display/formatting change (e.g. "just reformat this VAT total"), treat any change to figures, calculations, or logic in these domains as requiring confirmation first.

Anything else — ambiguous wording, missing polish direction, unclear "cleanup" scope, no Figma reference — gets a stated default and a narrow edit, not a question.

## 5. Quick reference checklist (use before calling a task done)

- [ ] Edited only the canonical file(s), confirmed up front
- [ ] No duplicate page/route/state created
- [ ] No parallel/renamed component introduced without explicit approval
- [ ] Legacy files left untouched (and undeleted) unless they're still routed
- [ ] API wiring unchanged (or explicitly flagged and confirmed if changed)
- [ ] Business logic unchanged, including financial/customs/accounting logic
- [ ] No placeholder/hardcoded data
- [ ] Used existing tokens/components, no new ad-hoc palette or font
- [ ] Matches approved Figma/wireframe if one was provided
- [ ] Keyboard accessible, visible focus states
- [ ] Checked desktop, tablet, mobile
- [ ] Animation (if any) is subtle and justified

## 6. Test cases

`tests/` in this skill folder contains six worked examples exercising the rules above (canonical-file resolution, API/business-logic preservation, token-only defaults, the missing-file ask-first exception, and the financial-logic and duplicate-authority ask-triggers). Consult them if you need a concrete example of how a rule applies in practice, or when re-validating this skill after an edit — each file documents the prompt, the rules exercised, expected behavior, and a verified sample output.
