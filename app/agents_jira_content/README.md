# Jira Content Agent

This agent generates Jira ticket titles, descriptions, and comments for the Jira REST workflow.

Editable templates live in:

- `app/agents_jira_content/templates/shared_principles.md`
- `app/agents_jira_content/templates/create_ticket_prompt.md`
- `app/agents_jira_content/templates/edit_ticket_prompt.md`
- `app/agents_jira_content/templates/comment_prompt.md`

The Jira REST API agent delegates ticket content generation here before creating or editing issues in Jira.
Create, edit, and comment generation are strict: the model must return the required format or the agent retries and then fails.
