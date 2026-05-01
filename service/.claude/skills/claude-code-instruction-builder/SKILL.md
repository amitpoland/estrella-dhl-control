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

## Output

Deliver the `CLAUDE.md` content for review, then write it on confirmation.
