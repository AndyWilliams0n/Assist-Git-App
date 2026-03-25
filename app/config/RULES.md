# Rules

Use this file for durable rules that apply only to the all agent workflows.

## Routing Rules
- `chat`: Default conversational response — no tool execution required.
- `read_only_fs`: List, show, or find files and folders only; do not modify files.
- `run_commands`: Execute only explicit user-requested CLI work.
- `research_mcp`: Use MCP search/fetch tools and provide evidence with sources.
- `jira_api`: Perform Jira ticket operations via REST or MCP.
- `code_build`: Implement or modify code/artifacts with full validation.

## Build Rules
- Prefer autonomous execution with sensible defaults.
- Prefer non-interactive command variants.
- If the workspace is a git repository and `.gitignore` is missing, create it from the standard template before other changes.
- Keep generated test artifacts under `.assist/test/` and do not commit them.
- Prefer unit tests over browser or end-to-end suites unless broader coverage is required.
- Do not claim "done" without evidence from command output and/or review pass.
- If review fails, feed notes/instructions into the next attempt.
- Keep each attempt summary concise and factual.

## Command Safety Rules
- Limit commands to local workspace scope.
- Avoid destructive commands unless explicitly requested.
- Favor deterministic commands that can run unattended.

## Output Rules
- Final responses must include:
  - What was executed
  - What changed
  - Validation status
  - Risks or gaps
  - Next steps

## HTML, CSS, JS, TS Rules
- Use `//` for comments, not `#` style in JS/TS
- Single line comment above code functions
- JSDoc for APIs
- Only comment complicated functions
- New line between elements in HTML/JSX for readability
- Group consts first, then lets at top of functions
- Material UI: No inline SX styling - use const at bottom of file
- Prefers systematic, well-structured solutions
- Appreciates organized file structures

## Jira Rules & Guardrails
- If a prompt requests subtask updates, parent/top-level tickets must be excluded unless explicitly requested.
- Do not map raw user prompts directly into Jira `description` fields.
- For bulk subtask updates, generate issue-specific descriptions using each ticket `title`/`summary` AND the parent tickets `description` so updates are distinct per issue.
- Generate Jira ticket descriptions using the exact predefined section headings required by the active Jira content template. For create-ticket output, follow the create template headings exactly. For edit-ticket output, follow the edit template headings exactly. No additional sections are allowed.
- Follow these rules when creating or editing existing epics/tasks/subtasks or issues.
