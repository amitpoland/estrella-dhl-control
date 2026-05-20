# EJ Dashboard Portal — Project Overrides for ui-ux-pro-max

**Status**: These overrides are BINDING for all EJ frontend work.  
They supersede ui-ux-pro-max defaults wherever there is a conflict.  
Full EJ design standard: `.claude/skills/frontend-design.md`

---

## 1. Stack Override (Critical)

| ui-ux-pro-max default | EJ actual |
|-----------------------|-----------|
| html-tailwind (default stack) | **Vanilla HTML + Babel JSX — no Tailwind** |
| Tailwind utility classes | **CSS custom properties only** (`--bg`, `--text-*`, `--badge-*`, `--accent`) |
| TypeScript | **Plain JS only** |
| npm/bundler | **No bundler — single-file CDN delivery** |
| Heroicons / Lucide (npm) | **Inline SVG or existing icon pattern in file** |
| shadcn components | **dashboard-shared.js** (`Btn`, `Badge`, `Card`, `Sel`, `Toast`) |

When ui-ux-pro-max returns stack-specific code, translate to EJ stack before applying.  
When ui-ux-pro-max recommends `html-tailwind` patterns, extract the semantic/structural guidance only — discard Tailwind class names.

---

## 2. Design System Partial-Apply Rules

ui-ux-pro-max design system output is used for:

| Domain | Apply? | Notes |
|--------|--------|-------|
| Accessibility rules (WCAG AA, contrast, focus, aria) | ✅ Yes | Fully applicable |
| UX guidelines (touch targets, loading states, error feedback) | ✅ Yes | Fully applicable |
| Layout & responsive principles | ✅ Yes | Translate to CSS custom properties |
| Typography mood / font pairing recommendations | ⚠️ Partial | EJ uses Plus Jakarta Sans — consider suggestions only |
| Color palette hex values | ❌ No | Use EJ token system; never hardcode hex from search output |
| Stack-specific component code | ❌ No | Translate to EJ vanilla/Babel JSX + dashboard-shared.js |
| Animation / glassmorphism / claymorphism / style trends | ⚠️ Operator clarity > aesthetics | Only apply if it does not obscure data or state |

---

## 3. Absolute Prohibitions (override any ui-ux-pro-max suggestion)

These cannot be unlocked by any design recommendation:

| Prohibition | Reason |
|-------------|--------|
| Fake placeholder data or skeleton text with mock values | Backend is source of truth — show loading state, not fake data |
| Duplicate workflow cards / renderers for the same domain | One authority per domain (ProformaDraftPanel, InventoryCard, etc.) |
| Auto-save / save-on-blur / background write | Every write requires explicit operator click |
| Decorative-only changes that obscure blocking state | Operator must see blockers — never style them away |
| New fetch from frontend that bypasses existing service layer | API calls must go through existing route patterns |
| Unsafe POST/write buttons without disabled-reason text | Every disabled write button must show why |
| wFirma / DHL / customs / inventory API calls from new UI | Backend gates own this; UI is read-only on those domains |
| Changes to proforma calculation, PZ creation, fiscal gates | Out of scope for frontend campaigns |
| Parallel frontend authority (second renderer for same data) | Replace old renderer; never run two in parallel |

---

## 4. Workflow Sequence for EJ Frontend Tasks

When applying ui-ux-pro-max to any EJ frontend change:

1. **Identify authority owner** — which component owns this data? (ProformaDraftPanel, InventoryCard, CustomerMasterCard, etc.)
2. **Run `--design-system` search** with EJ-specific keywords (operations, customs, warehouse, proforma, logistics)
3. **Filter output** — apply accessibility + UX rules; discard color hex, Tailwind classes, font recommendations unless explicitly needed
4. **Implement changes** using EJ stack (CSS custom properties, Babel JSX, dashboard-shared.js components)
5. **Verify no duplicate renderer** was created — if replacing, delete the old one in the same PR
6. **Verify backend payload truth preserved** — displayed values still come from API response
7. **Run existing tests** (`pytest service/tests/test_c1*.py -x`) to confirm no regression

---

## 5. Applicable ui-ux-pro-max Rules (pre-filtered for EJ)

These rules from SKILL.md apply directly to EJ work without modification:

**Accessibility (CRITICAL — apply always)**
- `color-contrast` — 4.5:1 minimum for all text
- `focus-states` — visible focus rings on every interactive element
- `aria-labels` — icon-only buttons must have `aria-label`
- `keyboard-nav` — tab order matches visual order
- `form-labels` — every `<input>` needs an associated `<label>`

**Touch & Interaction (CRITICAL)**
- `touch-target-size` — 44×44px minimum
- `loading-buttons` — disable `Btn` during async operations (use `disabled={loading}`)
- `error-feedback` — error toast/banner near the problem element, not just top-of-page
- `cursor-pointer` — all `Btn` and clickable cards

**Performance (HIGH)**
- `content-jumping` — reserve space for async content (skeleton rows, not blank collapse)
- `reduced-motion` — respect `prefers-reduced-motion` for any transition added

**UX (MEDIUM)**
- `loading-states` — skeleton screens or shimmer for data loading (not spinners over content)
- `duration-timing` — 150–300ms for micro-interactions
- `no-emoji-icons` — inline SVG only

---

## 6. Applying the Skill in Practice

```bash
# Correct usage — EJ keywords, get design system
python3 .claude/skills/ui-ux-pro-max/scripts/search.py \
  "operations dashboard customs warehouse proforma logistics" \
  --design-system -p "EJ Dashboard Portal"

# Supplemental accessibility check
python3 .claude/skills/ui-ux-pro-max/scripts/search.py \
  "accessibility focus keyboard" --domain ux

# Chart guidance (for analytics/pipeline views)
python3 .claude/skills/ui-ux-pro-max/scripts/search.py \
  "timeline funnel data table" --domain chart
```

**After running**: extract accessibility + UX rules. Discard raw hex colors and Tailwind classes. Map recommendations to EJ token system and dashboard-shared.js components.

---

*Last updated: 2026-05-20. Governed by `.claude/skills/frontend-design.md` §§1–9.*
