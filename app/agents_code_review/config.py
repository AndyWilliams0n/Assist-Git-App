from app.agents_shared.types import AgentConfig


CONFIG = AgentConfig(
    name="Code Review Agent",
    provider="openai",
    settings_key="code_review",
    system_prompt=(
        "Review workflow output and return JSON only as "
        "{\"passed\":true|false,\"notes\":\"...\",\"fix_instructions\":\"...\"}. "
        "Evaluate correctness against the user request, command exit status, and workspace diff evidence. "
        "If passed=true, fix_instructions must be empty. "
        "If passed=false, provide specific, actionable fix instructions."
    ),
)
