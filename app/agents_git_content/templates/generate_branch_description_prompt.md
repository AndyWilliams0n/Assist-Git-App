Generate a branch/PR description markdown document.

Use this exact section structure and order as the base layout reference:

{{branch_description_layout}}

Context:
- Workflow type: {{workflow_type}}
- Ticket/spec key: {{ticket_key}}
- Current branch: {{branch_name}}
- Original request: {{original_request}}
- Execution/review summary: {{execution_summary}}
- Changed files:
{{changed_files_block}}

Requirements:
- Return markdown only. Do not wrap the entire response in code fences.
- Keep section headings exactly as in the layout.
- Include both Mermaid blocks as valid Mermaid syntax.
- In "Brief", summarize the original Jira/spec ask.
- In "Changes", describe concrete completed work.
- In "Test Report", only report what is known from context; otherwise write "Not available in this run".
- Keep output concise and reviewer-friendly.
