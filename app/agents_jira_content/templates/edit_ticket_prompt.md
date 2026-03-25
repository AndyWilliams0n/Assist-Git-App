Revise Jira ticket content for an existing software delivery issue.

Return output in exactly this format:
SUMMARY: <single-line ticket title>
DESCRIPTION:
## User Story
...
## Requirements
...
## Acceptance Criteria
...
## Agent Context
N/A
## Agent Prompt
N/A

Description heading order:
{{headings_block}}

Editing rules:
- Use the existing issue context and the new request together.
- Preserve the ticket intent while improving clarity and delivery readiness.
- Do not invent unrelated scope.
- The `Requirements` section must describe the concrete software delivery expectations for the revised ticket.
- Keep acceptance criteria aligned to the requested change and verifiable by engineering or QA.
- The `Acceptance Criteria` section must contain verifiable completion criteria tailored to engineering delivery.
- Include `## Agent Context` and `## Agent Prompt`.
- If there is no meaningful content yet for either of those sections, set them to `N/A`.
