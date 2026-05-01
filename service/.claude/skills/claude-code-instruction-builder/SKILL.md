---
name: claude-code-instruction-builder
description: Generate and validate CLAUDE.md instruction files for Claude Code projects. Use when creating, auditing, or updating project-level Claude Code instructions.
triggers:
  - create CLAUDE.md
  - write claude code instructions
  - set up project instructions
  - audit CLAUDE.md
  - update project config for claude
tools:
  - Read
  - Write
  - Edit
  - Bash(find:*)
  - Bash(ls:*)
  - Bash(grep:*)
concurrency_safe: false
---

# Claude Code Instruction Builder

Generate, validate, and update `CLAUDE.md` files that configure Claude Code behavior for a project.

## When to Use

- User wants to create a new `CLAUDE.md` from scratch.
- User wants to audit an existing `CLAUDE.md` for completeness or correctness.
- User wants to update project instructions after a codebase change.

## Process

1. **Discover** — read the project structure, `package.json`, language config files, and existing `CLAUDE.md` if present.
2. **Draft** — generate a `CLAUDE.md` covering: project overview, tech stack, build/test/lint commands, code conventions, and any project-specific rules.
3. **Validate** — check that referenced commands actually exist and paths are correct.
4. **Write** — save the file only after user confirmation.

## Rules

- Never overwrite an existing `CLAUDE.md` without user approval.
- Keep instructions concise — one line per rule where possible.
- Do not include secrets, tokens, or credentials in generated instructions.
- Do not add instructions that bypass safety checks or disable hooks.

## Write Discipline (Phase 3b)

### Allowed write targets

Write and Edit tools may **only** target these file patterns:

- `**/CLAUDE.md`
- `**/AGENTS.md`
- `.claude/**/*.md` (skill and agent instruction files)

### Forbidden write targets

**Never** write, edit, or create files in:

- `app/` (production code)
- `tests/` (test code)
- `storage/` or `outputs/` (runtime data)
- `.env`, `.env.*`, `credentials.*`, `*.key`, `*.pem` (secrets)
- `*.py`, `*.js`, `*.ts` (application source)

If a task requires changes outside the allowed targets, **stop and tell the user** to use the appropriate skill or make the change manually.

### Pre-write checklist

Before any Write or Edit operation:

1. **User approval** — confirm the user has explicitly requested the change.
2. **Git status awareness** — note whether the target file has uncommitted changes. If it does, warn the user before proceeding.
3. **Diff awareness** — read the current file content and describe what will change before writing.

### Post-write checklist

After any Write or Edit operation:

1. **Re-read the file** — verify the written content is complete and not truncated.
2. **Report the diff** — show the user what changed (before vs. after).
3. **Recommend commit** — suggest the user commit the change.

### Concurrent edit safety

- This skill has `concurrency_safe: false` — it must **never** run in parallel with any other skill.
- If there is any indication that another skill or process is modifying the same file, **abort and ask the user to retry** after the other operation completes.
- This is a documentation-level discipline rule. Actual file-level locking is not yet implemented in code.

## Output

Deliver the `CLAUDE.md` content for review, then write it on confirmation.
