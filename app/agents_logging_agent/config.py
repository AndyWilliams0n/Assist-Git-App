from app.agents_shared.types import AgentConfig


CONFIG = AgentConfig(
    name="Logging Agent",
    provider="openai",
    settings_key="logging_agent",
    system_prompt=(
        "You log workflow outcomes with concise, audit-friendly entries. "
        "Capture key agent actions, success/failure state, and notable errors."
    ),
)
