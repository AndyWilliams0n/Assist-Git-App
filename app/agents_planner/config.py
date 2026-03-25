from app.agents_shared.types import AgentConfig


CONFIG = AgentConfig(
    name="Planner Agent",
    provider="openai",
    settings_key="planner",
    system_prompt=(
        "You are the planner for the autonomous workflow. "
        "Classify intent conservatively and create concise, executable plans. "
        "When JSON is requested, return strict JSON only with exactly the requested schema. "
        "When markdown is requested, return a concrete checklist with implementation and verification steps."
    ),
)
