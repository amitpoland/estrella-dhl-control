# Authority Census — Report Schemas

Every report file MUST begin with this standard header:

```markdown
# <Report Title>

**Base SHA:** aa414d90
**Census timestamp:** <UTC stamp>
**Scanned by:** /authority-census v1.0 (Phase-1 inspector pack)
**Mode:** READ-ONLY — no app code was modified
```

---

## Report 01 — Frontend Authority Map

**Filename:** `01-frontend-authority-map.md`

**Table schema:**

| Column | Type | Description |
|---|---|---|
| `#` | int | Row number |
| `Module` | string | Feature name (e.g. "Customer Master") |
| `Canonical URL` | string | SPA slug (e.g. `/v2/master`) or legacy path |
| `Authority File` | string | The ONE file that owns this URL |
| `Status` | enum | `AUTHORITY` / `DUPLICATE` / `LEGACY` / `DEAD` / `UNREACHABLE` / `ORPHAN` / `FRAGMENTED` |
| `Legacy/Duplicate Files` | string | Other files competing for this URL (comma-separated) |

---

## Report 02 — Backend Authority Map

**Filename:** `02-backend-authority-map.md`

**Summary block** (before table):
```
Total active route files: N
Router objects registered: N
Duplicate-prefix groups: N
```

**Table schema:**

| Column | Type | Description |
|---|---|---|
| `Domain` | string | Business domain (e.g. "Customer Master") |
| `Prefix` | string | APIRouter prefix (e.g. `/api/v1/customer-master`) |
| `Route Files` | string | File(s) contributing to this prefix |
| `# Endpoints` | int | Count of @router.get/post/put/delete decorators |
| `Registered in main.py` | bool | YES / NO / PARTIAL |
| `Collision Risk` | enum | `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` / `NONE` |
| `Notes` | string | Key finding |

**After table — DEAD ROUTES section:**
List any route file that exists on disk but is NOT imported in main.py.
Note whether its corresponding service is still started at startup (contradiction).

---

## Report 03 — Duplicate Feature Matrix

**Filename:** `03-duplicate-matrix.md`

**Three sub-sections:**

### A. Frontend UI Duplication

| Column | Description |
|---|---|
| `Duplicate Group` | Feature name |
| `Active Authority` | The file that should win |
| `Legacy/Redundant Files` | Files to retire |
| `Why Duplicates Exist` | One-line explanation |
| `Merge Effort` | `LOW` / `MEDIUM` / `HIGH` |
| `Migration Risk` | `LOW` / `MEDIUM` / `HIGH` |

### B. Backend API Duplication (same-prefix fragmentation)

| Column | Description |
|---|---|
| `Risk` | `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` |
| `Prefix` | Shared prefix |
| `# Files` | How many files share it |
| `Issue` | One-line description |

### C. API Client Duplication

Compare `static/pz-api.js` vs `static/v2/pz-api.js`:
- Methods only in root
- Methods only in v2
- Methods in both
- Total counts

---

## Report 04 — Dead Code Report

**Filename:** `04-dead-code.md`

**Three sub-sections:**

### Frontend Dead Code

| Column | Description |
|---|---|
| `File` | Path relative to repo root |
| `Why Dead` | Specific reason (not in script list, overridden, etc.) |
| `Action` | `DELETE` / `CONSOLIDATE` / `ACTIVATE` |

### Backend Dead Code

Same columns as frontend, applied to route files not in main.py.
Add: note if the corresponding service is still started at startup.

### Dead Navigation Links

| Column | Description |
|---|---|
| `Location` | Which nav config file |
| `Dead Link` | The broken path/URL |
| `Reason` | Why it's dead (file does not exist, slug redirected, etc.) |

---

## Report 05 — Navigation Map

**Filename:** `05-nav-map.md`

**Three sub-sections:**

### SPA Router Table

| Column | Description |
|---|---|
| `Slug` | SPA route (e.g. `master`) |
| `Full URL` | `/v2/master` |
| `Component` | JSX component class/function name |
| `Status` | `WIRED` / `REDIRECTS_TO:<slug>` / `UNWIRED` |

### Visible Menu Tree

Nested list reflecting `NAV_TREE`:
```
Section: Operations
  └─ Shipments → /v2/shipments
  └─ Inbox → /v2/inbox
  ...
```

### Mismatches

- Slugs wired in the router but not in the menu (invisible routes)
- Menu items pointing to slugs that are not wired or redirect elsewhere

---

## Report 06 — Orphan Registry

**Filename:** `06-orphans.md`

| Column | Description |
|---|---|
| `File` | Path relative to repo root |
| `Type` | `HTML` / `JSX` / `JS` / `ROUTE` / `SERVICE` |
| `Why Orphan` | Not in index.html / not in main.py / no menu link / etc. |
| `Last Commit` | `git log --follow -1 --format="%as %s" -- <file>` |
| `Recommendation` | `RETIRE` / `ACTIVATE` / `INVESTIGATE` |

---

## Report 07 — Retirement Plan

**Filename:** `07-retirement-plan.md`

**Ordered list — safest first:**

| Column | Description |
|---|---|
| `Priority` | 1 = retire first |
| `File` | Path relative to repo root |
| `Safe to Delete After` | Prerequisite (e.g. "PR #809 merges") |
| `Risk` | `LOW` / `MEDIUM` / `HIGH` |

**DO NOT RETIRE section:**
Files that appear dead/orphan but must stay because they are still
linked from backend routes, emails, or external systems.

---

## Report 08 — Risk Score

**Filename:** `08-risk-score.md`

**Per-module scoring:**

| Axis | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **Fragmentation** | Single authority | 2 files | 3 files | 4+ files |
| **Duplication risk** | No shared prefix | LOW collision | MEDIUM | CRITICAL |
| **Dead code burden** | Nothing dead | Minor dead code | Significant | Majority dead |

**Total score** = sum of 3 axes (0–9).

**Output table:**

| Module | Fragmentation | Duplication | Dead Code | Total | Recommended Action |
|---|---|---|---|---|---|

**Top 5 Highest Risk** section: name each module and give a one-line fix recommendation.
