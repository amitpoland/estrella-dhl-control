---
name: frontend-design
description: EJ Dashboard Portal design standard. Governs all UI work on shipment-detail.html, dashboard.html, and any new dashboard pages. Read this before any UI implementation or review.
---

# EJ Dashboard Portal — Frontend Design Standard

**Stack reality**: Vanilla HTML + Babel JSX (inline, no bundler), no TypeScript, no Tailwind, no React import (via CDN). Generic frontend agents default to the wrong stack. This file is the override.

---

## 1. Stack Constraints (absolute)

| Constraint | Rule |
|------------|------|
| Framework | Vanilla HTML + Babel standalone (JSX in `<script type="text/babel">`) |
| No bundler | No webpack, vite, esbuild. Single-file delivery. |
| No TypeScript | `.js` only. No `.ts`, no type annotations. |
| No Tailwind | Use CSS custom properties only (see §3). |
| React source | CDN React 17+ via `<script src="...">` |
| Component library | `dashboard-shared.js` — `Badge`, `Card`, `Btn`, `Sel`, `Toast`, `SessionBanner` |
| Font | Plus Jakarta Sans (Google Fonts CDN) |

---

## 2. File Inventory

| File | Role |
|------|------|
| `service/app/static/shipment-detail.html` | Shipment detail page — ~14,600 lines; ProformaDraftPanel, InventoryCard, CustomerMasterCard, CM workflow cards |
| `service/app/static/dashboard.html` | Main dashboard — batch list, pipeline overview |
| `service/app/static/dashboard-shared.js` | Shared component library — no app-specific config, no backend URLs |

New pages: follow `dashboard.html` structure. New shared components: add to `dashboard-shared.js` only if backend-agnostic and reusable.

---

## 3. Design Token System (CSS Custom Properties)

Defined in both `shipment-detail.html` `:root` and `dashboard.html` `:root`. Use these exclusively — no hardcoded hex values in components.

### Core tokens (`:root` light mode)

```css
--bg: #F4F1EA;             /* page background */
--bg-subtle: #FAF8F2;      /* inset / well backgrounds */
--card: #FFFFFF;            /* card surface */
--row-hover: #F6F2EA;       /* table row hover */
--border: #E5DECF;          /* standard border */
--border-subtle: #EFE9DA;   /* subtle border */
--text: #1B2538;            /* primary text */
--text-2: #4E5A72;          /* secondary text */
--text-3: #8B97AE;          /* muted / placeholder */
--shadow: rgba(27,37,56,0.06);
--shadow-heavy: rgba(27,37,56,0.16);
--overlay: rgba(19,28,46,0.6);
--accent: #B89968;          /* primary accent (gold) */
--accent-light: #D4B884;    /* hover accent */
--accent-text: #1B2538;     /* text on accent backgrounds */
--accent-subtle: #F8EFD8;   /* accent tint */
--accent-border: #CFB178;
/* Surface aliases (C20A) */
--surface-1: var(--bg-subtle);  /* inputs, code, form fields */
--surface-2: var(--bg-subtle);  /* inset containers, alt rows */
```

### Sidebar tokens

```css
--sidebar-bg: #131C2E;
--sidebar-border: #25334C;
--sidebar-active: #1F2A42;
--sidebar-hover: #1A2438;
--sidebar-text: #F2EBD9;
--sidebar-text-muted: #7C89A3;
--sidebar-icon: #B89968;
```

### Badge tokens

```css
--badge-neutral-bg / -text / -border
--badge-blue-bg / -text / -border
--badge-amber-bg / -text / -border
--badge-orange-bg / -text / -border   /* Awaiting DHL Email, Awaiting SAD */
--badge-green-bg / -text / -border
--badge-red-bg / -text / -border
--badge-purple-bg / -text / -border
--badge-accent-bg / -text / -border   /* Exported — dark navy bg with gold text */
```

### Dark mode tokens (`[data-theme="dark"]`)

All tokens above have dark overrides in `[data-theme="dark"]`. **Never hardcode a color that changes between themes** — always use a token.

---

## 4. Shared Component Library (`dashboard-shared.js`)

| Component | Props | Usage |
|-----------|-------|-------|
| `Badge` | `status` (STATUS_MAP key) OR `label` (freeform text), `small`, `title` | Status chips, coverage indicators |
| `Card` | `children`, `style`, `onClick` | Section wrappers |
| `Btn` | `variant`, `small`, `disabled`, `onClick`, `...rest` (forwarded to `<button>`) | All buttons |
| `Sel` | `value`, `onChange`, `children`, `...rest` | Dropdowns |
| `Toast` | `msg`, `type` (success/info/error/warn) | Transient feedback |
| `SessionBanner` | `type` (auth/network), `onDismiss` | Top-of-page session error banner |

**Btn variants** (all available):

| Variant | Style | Use for |
|---------|-------|---------|
| `primary` | Gold/accent fill | Primary CTA — approve, save, dispatch |
| `gold` | Gold/accent fill | Alias for primary |
| `default` | Dark fill (`--text` bg) | Default actions |
| `outline` | Transparent, `--border` border | Secondary actions |
| `ghost` | Transparent, no border | Tertiary / minor actions |
| `danger` | Red badge style | Destructive actions |
| `success` | Green badge style | Confirmation actions |

**Badge usage**:
- `<Badge status="Customs Verified" />` — looks up STATUS_MAP, renders with semantic color
- `<Badge label="Complete" />` — freeform text, renders with neutral color fallback
- STATUS_MAP keys: Draft, In Transit, Pre-check Pending/Completed, Awaiting DHL Email, DHL Email Received, Reply Sent/Queued, SAD Pending/Uploaded, Customs Parsed/Verified, Verification Needed, Locked, Ready for PZ, Generated, Ready for Booking, Exported, Awaiting DHL/SAD, Action Required, In Preparation, Completed, Pending, Live, Awaiting Clearance, Processing, Reply Package Prepared

Rules:
- Use `Btn` not `<button>`. Use `Badge` not `<span className="badge...">`.
- Every `Btn` must have a `data-testid` (forwarded via `...rest` to `<button>`).
- `Btn disabled={true}` is valid; the reason why must appear as tooltip or adjacent text.
- Never add app-specific backend URLs or config to `dashboard-shared.js`.

---

## 5. UI Design Principles

### 5.1 Backend truth first

Every value displayed must come from a verified API response or audit record. Placeholder / loading state is allowed. Fabricated/estimated values are not.

- Show `—` or a shimmer skeleton while data loads.
- Show an error state if the fetch fails — do not silently show stale data as current.
- If a field has no value: show `—`, not `0`, not `null`, not blank.

### 5.2 Operator clarity over visual novelty

The operator is a logistics user under time pressure. Design choices in priority order:
1. Is the action available? (show it)
2. Is the action blocked? (show why — disabled + reason text)
3. Is the data correct? (show source/timestamp)
4. Does it look nice? (last priority)

Never make a blocking reason invisible. Never style away a warning to reduce visual noise.

### 5.3 No hidden write actions

Every button that triggers a write (save, create, submit, dispatch, approve) must:
- Be explicitly labeled with what it writes (e.g. "Save to Customer Master", not "Save")
- Require an operator click — no auto-save on blur, no auto-submit on timeout
- Show a success/error toast after the write completes

### 5.4 No duplicate renderers

One authoritative render path per data domain. Examples:
- Proforma draft: `ProformaDraftPanel` only — no secondary render in tab headers or summary cards
- Customer Master: `CustomerMasterCard` / CM workflow cards only
- Inventory: `InventoryCard` only

If a second render of the same domain is needed for a different context (summary, tooltip), it reads from the same state object — it does not fetch independently.

### 5.5 Legacy sections: `<details>` collapse

Legacy, raw, or debug sections that remain for reference (not primary workflow) must be wrapped in `<details><summary>Legacy: ...</summary>...</details>`. Never show legacy content expanded by default.

Examples: `legacy-pz-details`, `legacy-reservation-details`.

---

## 6. Component Patterns

### 6.1 Buttons

```jsx
// Correct
<Btn
  variant="primary"
  disabled={!canSave}
  onClick={handleSave}
  data-testid="btn-save-customer-master"
>
  Save to Customer Master
</Btn>
{!canSave && <span className="text-muted">Complete required fields first</span>}

// Wrong — bare HTML button
<button onClick={handleSave}>Save</button>

// Wrong — no disabled reason
<Btn variant="primary" disabled={true}>Save</Btn>
```

### 6.2 Status badges

```jsx
// Correct
<Badge color="amber">Pending arrival</Badge>
<Badge color="green">Cleared</Badge>

// Wrong — hardcoded colors
<span style={{background:'#FBF5E0',color:'#92600A'}}>Pending</span>
```

### 6.3 Loading / empty states

```jsx
// Loading
{loading && <div className="skeleton-row" />}

// Empty
{items.length === 0 && (
  <div data-testid="empty-hint">
    No items yet. <Btn variant="ghost" onClick={reload}>Reload from warehouse</Btn>
  </div>
)}

// Wrong — silent
{items.length === 0 && <span>(no items)</span>}
```

### 6.4 Error states

```jsx
// Correct
{error && (
  <div className="error-banner" data-testid="fetch-error">
    {error.message} — <Btn variant="ghost" small onClick={retry}>Retry</Btn>
  </div>
)}
```

---

## 7. Safety Rules (EJ-specific overrides — non-negotiable)

These override generic frontend-ui agent defaults:

| Rule | Detail |
|------|--------|
| No fake warehouse stock | Never display a piece count that isn't confirmed by the API |
| No fake readiness | Never set a readiness banner to "ready" unless all gate checks returned true |
| No hidden blockers | Never use CSS/styling to hide a blocking condition — operator must see it |
| Save = explicit click only | No auto-save, no debounced background write, no save-on-unmount |
| Save to CM only | Write buttons that touch Customer Master must be labeled "Save to Customer Master only" — never "Save" alone |
| No wFirma write flags | UI must not expose any wFirma write toggle or enable-write checkbox |
| No PZ / invoice creation from UI | No "Create PZ", "Post invoice", "Submit to wFirma" buttons — these go through backend gates |
| Legacy must be collapsed | Any section with `legacy-*` testid must be inside `<details>` with summary text |
| No ZC429/customs gate bypass | No "override" or "force-clear" buttons on fiscal/customs gate fields |

---

## 8. `data-testid` Naming Convention

Format: `{component}-{entity}-{qualifier}`

| Context | Example |
|---------|---------|
| Button | `btn-save-customer-master`, `btn-cm-edit-{id}` |
| Panel | `draft-visibility-panel`, `workflow-cm-card-{id}` |
| Empty hint | `draft-lines-empty-hint` |
| Error banner | `fetch-error-{context}` |
| Legacy section | `legacy-pz-details`, `legacy-reservation-details` |
| Badge/status | `status-badge-{field}` |

Rules:
- Every interactive element must have a `data-testid`.
- Every panel / card root must have a `data-testid`.
- Test IDs must be stable across re-renders (no index-based IDs like `item-0`).
- Use `{entity}-{id}` for list items where id is a real record id, not a list index.

---

## 9. What NOT to use

| Forbidden | Reason |
|-----------|--------|
| Tailwind classes | Not in stack |
| TypeScript annotations | Not in stack |
| CSS modules / styled-components | Not in stack |
| `className="badge-..."` custom classes not in shared stylesheet | Use `Badge` component |
| Hardcoded hex colors | Use CSS custom properties |
| `display:none` to hide blocking state | Use disabled + reason text |
| localStorage for state persistence | Backend is source of truth |
| window.location.reload() to refresh data | Call API and re-render |

---

## 10. When this skill applies

Invoke before any of:
- Adding a new UI component or section to `shipment-detail.html` or `dashboard.html`
- Adding a new page to `service/app/static/`
- Adding to `dashboard-shared.js`
- Reviewing a UI PR for design compliance
- Running `frontend-flow-reviewer` (it should reference this skill for design standards)

**Do NOT redesign existing UI** based on this skill alone. This skill governs new additions and bug fixes. Design changes to existing surfaces require an explicit operator instruction.
