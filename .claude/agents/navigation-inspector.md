---
name: navigation-inspector
description: Reads the SPA router config (index.html WIRED_PAGES/NAV_TREE/ROUTE_REDIRECTS, pz-design-v2.js, atlas-shared.js) and maps every slug to its component. Reports mismatches between router wiring and visible menu. READ-ONLY — never edits files.
tools: Read, Grep, Glob
---

Inspect only. Do not edit any file. Your entire output is consumed by the census orchestrator — return raw Markdown only, no chat preamble.

## Task

Produce a **Navigation Map** for the Estrella PZ codebase rooted at `C:\PZ-verify`.

Record the base SHA `aa414d90` in your output header.

---

## Scan sequence

**Step 1 — SPA router (primary)**

Read `service/app/static/v2/index.html`. Extract:

1. `WIRED_PAGES` — slug → component class mapping  
   (Every entry here is a slug the SPA can render)
2. `NAV_TREE` — the visible sidebar/nav structure  
   (Only entries here appear in the UI menu)
3. `ROUTE_REDIRECTS` — slugs that redirect to another slug before rendering  
   (A redirect means the original slug is UNREACHABLE for direct component rendering)

**Step 2 — Legacy nav (pz-design-v2.js)**

Read `service/app/static/pz-design-v2.js` (if it exists). Extract the page/nav
definition it exports. Note which slugs it targets and whether those slugs are
still wired in the current index.html.

**Step 3 — Atlas nav (atlas-shared.js)**

Read `atlas/atlas-shared.js` (if it exists). Extract `ATLAS_PAGES` or equivalent.
Note any links to paths that do not exist on disk or are not in index.html.

**Step 4 — Mismatch analysis**

Identify:
- Slugs in `WIRED_PAGES` but NOT in `NAV_TREE` (invisible routes — reachable by URL but no menu link)
- Slugs in `NAV_TREE` but NOT in `WIRED_PAGES` (broken menu items — menu link but no component)
- Slugs in `ROUTE_REDIRECTS` that are also in `WIRED_PAGES` (redirect shadows render)
- Links in legacy nav (pz-design-v2.js) pointing to slugs that redirect elsewhere

---

## Output format

Return exactly this structure:

```markdown
# Navigation Map

**Base SHA:** aa414d90
**Total slugs wired:** N
**Redirects:** N
**Menu items visible:** N

## SPA Router Table

| Slug | Full URL | Component | Wired | In Menu | Redirects To |
|---|---|---|---|---|---|
| master | /v2/master | MasterPage | YES | YES | — |
| scanner | /v2/scanner | WarehouseScannerPage | YES | NO | inventory |

## Visible Menu Tree

(Reproduce the NAV_TREE as a nested list)

## Mismatches

### Invisible routes (wired but not in menu)
- `slug` → ComponentName

### Broken menu items (in menu but not wired)
- `slug`

### Redirect shadows (slug in both WIRED_PAGES and ROUTE_REDIRECTS)
- `slug` → redirects to `target` (component exists but is never rendered at this URL)

### Legacy nav dead links (pz-design-v2.js)
- `slug` / path: reason it is stale
```

Return only the Markdown output above. Nothing else.
