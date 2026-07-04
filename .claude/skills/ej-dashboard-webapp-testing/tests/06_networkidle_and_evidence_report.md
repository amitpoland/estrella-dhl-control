# Test 06 — Wait for networkidle, capture evidence, produce the report

## Prompt
> Verify the dashboard home renders correctly.

## Rules exercised
- §4 Wait for networkidle before DOM inspection; capture screenshots + console errors + failed
  network requests
- §7 Structured report output

## Expected behavior
- Navigate to `/v2/dashboard` (renders `DashboardKanban`); **wait for networkidle before
  inspecting** — the shell compiles JSX in-browser via Babel and fetches
  `GET /api/v1/dashboard/batches`, so an early snapshot reads a half-rendered tree.
- Capture: a screenshot of the settled state, console errors (expect none), and failed network
  requests (any 4xx/5xx is a finding).
- Confirm expected surface (KPI strip, kanban lanes, no MOCK banner where wired).
- Produce a report with route · server · actions · result · evidence · failures · skipped.

## Verified output (against this repo)
> Navigating to `/v2/dashboard` (`DashboardKanban`). The shell Babel-compiles in-browser and
> fetches `/api/v1/dashboard/batches`, so I wait for networkidle before inspecting — no
> half-rendered snapshot. Then I capture: screenshot of the settled board, console errors (should
> be zero red), and the network summary (flag any 4xx/5xx). I'll confirm the KPI strip + six
> kanban lanes render with live counts and no MOCK banner, then write the report —
> route `/v2/dashboard`, server `preview:pz-service-verify:8135`, actions, PASS/FAIL, screenshot
> path + console/network capture, failures, and anything deliberately skipped.

## Result
PASS — awaited networkidle before inspection, captured screenshot + console + failed-request
evidence, verified the expected surface, and produced a structured report.
