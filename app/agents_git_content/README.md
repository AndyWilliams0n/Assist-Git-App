# Git Content Agent

This agent generates branch/PR description content for GitHub/GitLab push flows.

Editable templates live in:

- `app/agents_git_content/templates/shared_principles.md`
- `app/agents_git_content/templates/branch_description_layout.md`
- `app/agents_git_content/templates/generate_branch_description_prompt.md`

The git workflow runtime delegates to this agent during the `review` hook when an enabled action is about to push or create a PR/MR.
