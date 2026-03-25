from app.agents_shared.types import AgentConfig


CONFIG = AgentConfig(
    name="SDD Spec Agent",
    provider="openai",
    settings_key="sdd_spec",
    system_prompt=(
        "You are a specialized Spec-Driven Development agent. "
        "Research the local codebase first, then write comprehensive requirements.md, design.md, and tasks.md. "
        "Use concrete file references and produce actionable implementation checklists."
    ),
)
