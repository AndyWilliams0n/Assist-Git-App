from app.agents_shared.types import AgentConfig


CONFIG = AgentConfig(
    name="CLI Agent",
    provider="openai",
    settings_key="cli_agent",
    system_prompt=(
        "You produce safe local CLI command plans for explicit run-command requests. "
        "Return JSON only as {\"commands\":[\"...\"]}. "
        "Commands must be non-interactive, deterministic, and limited to the local workspace."
    ),
)
