---
name: zoho-context-research
description: Read-only research skill that inspects Zoho integration code (WorkDrive, Cliq, Mail, Auth) to answer questions about token flows, API endpoints, retry patterns, and configuration requirements. Does not call external APIs.
triggers:
  - zoho integration question
  - workdrive API check
  - cliq bot review
  - zoho auth flow
  - email sending config
tools:
  - Read
  - Bash(find:*)
  - Bash(grep:*)
  - Bash(ls:*)
---

# Zoho Context Research

Read-only research skill that inspects Zoho integration source code to answer questions about how the application interacts with Zoho services.

## Purpose

Provide accurate, code-grounded answers about the application's Zoho integrations — WorkDrive file sync, Cliq bot messaging, Zoho Mail sending, and OAuth token management — without calling any external APIs or touching credentials.

## When to Use

- Debugging Zoho token refresh failures by inspecting the auth flow in code.
- Understanding which WorkDrive API endpoints the app calls and how uploads work.
- Reviewing Cliq bot message formatting before making changes.
- Answering questions about email sending configuration (SMTP vs. Zoho Mail API, retry patterns).
- Checking what environment variables a Zoho integration requires.
- Understanding retry and error handling patterns in WorkDrive sync.

## When NOT to Use

- Actually calling Zoho APIs or refreshing tokens — this skill does not make network requests.
- Modifying Zoho integration code — this skill is read-only.
- Working on non-Zoho features (customs, tracking, AI Bridge, dashboard).
- Debugging issues that require live API responses — direct the user to test manually.
- Reading or extracting actual credential values from config or environment.

## Workflow

1. **Identify scope** — determine which Zoho service the question relates to: WorkDrive, Cliq, Mail, or Auth.
2. **Locate source files** — find the relevant service files:
   - Auth: `app/services/zoho_auth.py`, `app/core/config.py`
   - WorkDrive: `app/services/workdrive_*.py`
   - Cliq: `app/services/cliq_*.py`
   - Mail: `app/services/email_sender.py`, `app/services/email_service.py`
3. **Read and analyze** — read the relevant code sections to answer the question. Focus on:
   - API endpoint URLs and HTTP methods used.
   - Token refresh flow and expiration handling.
   - Retry patterns and error handling.
   - Required configuration variables (without reading actual values).
   - Request/response structure.
4. **Cross-reference routes** — if relevant, check `app/api/routes_*.py` for how the service is exposed via API.
5. **Cross-reference tests** — check `tests/test_zoho_auth.py` and other relevant test files for expected behavior.
6. **Report** — return a structured research summary.

## Safety Rules

- This skill is strictly read-only. It never creates, edits, or deletes any file.
- It never makes network requests or calls external APIs.
- It never reads, logs, or displays actual credential values (API keys, tokens, secrets, passwords).
- When listing required config variables, it reports the variable names only — never their values.
- It does not modify configuration files or environment settings.
- If the question requires live API interaction to answer, it reports that and stops.

## Output Format

```
## Zoho Integration Research — {service}
- **Service:** (WorkDrive / Cliq / Mail / Auth)
- **Files inspected:** (list with line ranges)
- **API endpoints used:** (list of URLs and methods)
- **Auth flow:** (summary of token lifecycle)
- **Config required:** (list of env variable names — no values)
- **Retry/error handling:** (summary)
- **Answer:** (direct answer to the question)
- **Limitations:** (what this analysis cannot determine without live testing)
```
