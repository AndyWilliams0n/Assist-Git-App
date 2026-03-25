Create a new Jira ticket response for software delivery.

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

Description rules:
- Use each heading exactly once as `## <Heading>`.
- Make the title concise, implementation-ready, and outcome-oriented.
- Keep the content specific to the requested work and any parent ticket context.
- Keep the overall ticket concise and implementation-ready.
- `## User Story`: 1 short paragraph.
- `## Requirements`: 3-6 short bullets only.
- `## Acceptance Criteria`: 3-5 short verifiable bullets only.
- Do not add Background, Scope, Technical Notes, Definition of Done, or any other sections.
- Include `## Agent Context` and `## Agent Prompt`.
- If there is no meaningful content yet for either of those sections, set them to `N/A`.
