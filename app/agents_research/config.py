from app.agents_shared.types import AgentConfig


CONFIG = AgentConfig(
    name="Research Agent",
    provider="openai",
    settings_key="research",
    system_prompt=(
        "You are the research specialist for the autonomous workflow. "
        "Generate focused web research queries, synthesize fetched evidence, and return concise outputs with sources. "
        "When JSON is requested, return strict JSON only with exactly the requested schema."
    ),
)
