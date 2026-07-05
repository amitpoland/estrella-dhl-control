# Navigation Map

**Base SHA:** aa414d90
**Census timestamp:** {{STAMP}}
**Inspector agent:** navigation-inspector
**Mode:** READ-ONLY — no app code was modified
**Total slugs wired:** {{N}}
**Redirects:** {{R}}
**Menu items visible:** {{M}}

---

## SPA Router Table

| Slug | Full URL | Component | Wired | In Menu | Redirects To |
|---|---|---|---|---|---|
| master | `/v2/master` | MasterPage | YES | YES | — |
| scanner | `/v2/scanner` | WarehouseScannerPage | YES | NO | inventory |
| … | … | … | … | … | … |

---

## Visible Menu Tree

```
(Reproduce NAV_TREE as a nested list)
Section: ...
  └─ Module → /v2/slug
```

---

## Mismatches

### Invisible routes (wired but not in menu)

- `slug` → ComponentName

### Broken menu items (in menu but not wired)

- `slug`

### Redirect shadows (in WIRED_PAGES AND ROUTE_REDIRECTS)

- `slug` → redirects to `target` — component exists but never rendered at this URL

### Legacy nav dead links (pz-design-v2.js)

- `slug` / path: reason
