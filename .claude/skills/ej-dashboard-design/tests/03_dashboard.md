# Test 03 — New design authority (palette) ask-trigger, motion restraint

## Prompt
> Add a fade-in animation and a bold new purple accent color to the dashboard homepage to make it pop for a client demo.

## Rules exercised
- Section 1: Design tokens over new systems
- Section 4, trigger #3: could add a new design authority (new palette entry)
- Section 1: Motion stays subtle

## Expected behavior
- Identify `dashboard-home.jsx` as canonical (sole implementation, routed at `/`).
- Recognize the new purple accent as introducing a color outside the existing token system (`tokens.css` already defines `--ej-color-accent`) — this is trigger #3, so stop and confirm rather than silently adding a one-off hex value.
- Offer a path that respects tokens (reuse existing accent, or add a proper new token rather than an inline hardcoded color).
- Keep any animation subtle/performance-friendly regardless of "make it pop for a demo" framing — demo urgency does not override the motion-restraint rule.

## Verified output (against mock repo)
> Canonical file confirmed: `dashboard-home.jsx`, only implementation, routed at `/`.
>
> On the accent color: `tokens.css` already defines `--ej-color-accent` (`#c98a3e`). Introducing a new purple isn't in the existing token system, and per Section 1 I shouldn't add a one-off palette color even for a demo. Options: (a) use the existing accent token, or (b) if you want purple specifically, add it as a proper token (e.g. `--ej-color-accent-alt`) so it's reusable, not a hardcoded hex in this one file. Let me know which.
>
> On the animation: I'll add a subtle fade-in on load rather than anything flashy — keeping motion restrained per Section 1 even though it's for a demo.

## Result
PASS — correctly stopped on the new-authority trigger instead of silently complying with "make it pop," and kept motion restrained despite demo-urgency framing.
