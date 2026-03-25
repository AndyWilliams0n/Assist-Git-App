# Rules For Agents

This document defines agent-facing coding and file-organization rules for the `app` Python codebase.
Apply these rules to all new work and during refactors.

## Core Principles

- Prefer clarity over cleverness.
- Keep modules focused and responsibilities separated.
- Keep runtime logic deterministic and easy to validate.
- Reuse existing patterns in `app` before introducing new ones.

## Required File Separation

Use dedicated file types for each concern.

- Prompts: Markdown files (`.md`) only.
- Rules and policy: Markdown files (`.md`) only.
- Settings and machine-readable config: JSON files (`.json`) only.
- Runtime code: Python files (`.py`) only.

Do not mix these concerns into a single file when a dedicated file type exists.

## Prompt Rules

- Store prompts in separate Markdown files, not inline Python strings.
- Use descriptive names ending in `_prompt.md`.
- Keep prompts near the owning feature or agent.
- Keep shared prompt content in explicit shared Markdown files.

Preferred pattern:

```text
app/<agent_or_feature>/templates/
  *_prompt.md
  shared_*.md
```

## Rules Document Rules

- Keep durable rules in dedicated Markdown documents.
- Use explicit file names such as `RULES.md`, `RULES_FOR_AGENTS.md`, or feature-scoped equivalents.
- Keep rules concise, directive, and implementation-ready.
- Update rules when conventions change to prevent drift.

## Settings Rules

- Store settings in JSON files.
- Use stable, explicit keys and avoid ambiguous naming.
- Keep environment-specific overrides separate when possible.
- Avoid embedding secret values in committed JSON files.

Preferred examples:

- `app/settings.json`
- `app/mcp.json`

## Python Code Standards

- Follow PEP 8 and use type hints for public functions.
- Keep functions small and focused on one concern.
- Group constants near the top of the module.
- Avoid global mutable state unless strictly required.
- Prefer explicit return types and clear error paths.
- Validate external inputs at boundaries.
- Never use `Any` unless there is no practical typed alternative.

## Agent Module Structure

Use a consistent layout for agent packages:

```text
app/<agent_name>/
  __init__.py
  config.py
  runtime.py
  templates/
```

Optional files when needed:

- `types.py` for typed models and payloads.
- `README.md` for usage and operational notes.
- `worker.py` for queue/execution workers.

## Naming Conventions

- Modules/files: `snake_case.py`.
- Classes: `PascalCase`.
- Functions and variables: `snake_case`.
- Constants: `UPPER_SNAKE_CASE`.
- Prompt files: `snake_case_prompt.md`.
- Settings files: `snake_case.json` where practical.

## Implementation Guardrails

- Prefer non-interactive workflows for automation.
- Avoid destructive operations unless explicitly requested.
- Keep changes scoped to the requested task.
- Add or update tests when behavior changes.
- Do not claim completion without validation evidence.

## Pre-Completion Checklist

- Prompts are in separate Markdown files.
- Rules are in dedicated Markdown documents.
- Settings are in JSON files.
- Python code is typed, readable, and modular.
- No unused imports or dead code remain.
- Relevant validation/tests were executed.
