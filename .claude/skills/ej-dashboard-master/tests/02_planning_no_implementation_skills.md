# Test 02 — Planning loads NO implementation skills

## Prompt
> Let's plan out how we'd add a CSV export to the reports page — just the approach for now.

## Rules exercised
- §2 Classify, §3 Discussion-only mode (planning), §4 Minimum Skill Principle

## Expected behavior
- Classify as `Planning` (approach only, no code requested).
- **Do NOT activate implementation skills.** Produce a plan/approach; note which skills *would*
  be activated when implementation begins (UI → design pair; if it hits the backend/export
  endpoint → fullstack-governance), but do not load them now.
- Flag early that a real export may touch document-generation (protected) so approval will be
  needed at implementation time.

## Verified output (against this repo)
> Classification: Planning. No implementation skills loaded yet — you asked for the approach only.
> Plan: the reports page is the canonical surface; a CSV export would add an export action (UI)
> plus a backend export endpoint. When we implement, routing would be UI → `frontend-design` +
> `ej-dashboard-design`, and the endpoint → `ej-dashboard-fullstack-governance` + `clean-code`.
> Heads-up: generating/exporting a document is a protected flow, so implementation will pause for
> approval. Want me to detail the plan further, or move to implementation (which activates those
> skills)?

## Result
PASS — classified as planning, activated no implementation skills, described future routing
without loading it, and pre-flagged the protected-domain approval.
