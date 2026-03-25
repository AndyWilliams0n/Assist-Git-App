from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

_SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"
_SETTINGS_EXAMPLE_PATH = Path(__file__).resolve().parent / "settings.json.example"
_LOCK = threading.Lock()

_DEFAULT_AGENT_SETTINGS: dict[str, dict[str, Any]] = {
    "orchestrator": {"model": "gpt-5.4-mini"},
    "planner": {"model": "gpt-5.4-mini"},
    "research": {"model": "gpt-5.4-mini"},
    "jira_api": {"bypass": False},
    "jira_content": {"model": "gpt-5.4-mini"},
    "git_content": {"model": "gpt-5.4-mini"},
    "sdd_spec": {"model": "gpt-5.3-codex", "bypass": False},
    "code_builder_codex": {"model": "gpt-5.3-codex", "bypass": False},
    "code_review": {"model": "gpt-5.3-codex", "bypass": False},
    "cli_agent": {"model": "gpt-5.4-mini"},
    "logging_agent": {"model": "gpt-5.4-mini"},
}

_LEGACY_AGENT_KEY_MAP = {
    "orchestrator_codex": "orchestrator",
    "planner_codex": "planner",
    "research_codex": "research",
    "code_builder_codex": "code_builder_codex",
    "code_review_codex": "code_review",
    "cli_agent_codex": "cli_agent",
    "logging_agent_codex": "logging_agent",
}

_DEFAULT_LLM_PROVIDER_SETTINGS: dict[str, dict[str, Any]] = {
    "openai": {"model": "gpt-4.1-mini"},
    "anthropic": {
        "model": "claude-3-5-sonnet-latest",
        "max_tokens": 4000,
    },
}

_DEFAULT_LLM_FUNCTION_SETTINGS: dict[str, dict[str, Any]] = {
    "jira_content_generation": {
        "openai_model": "gpt-5.4-mini",
        "anthropic_model": "claude-3-5-sonnet-latest",
    },
    "jira_description_generation": {
        "openai_model": "gpt-5.4-mini",
        "anthropic_model": "claude-3-5-sonnet-latest",
    },
    "git_content_generation": {
        "openai_model": "gpt-5.4-mini",
        "anthropic_model": "claude-3-5-sonnet-latest",
    },
}

_GIT_WORKFLOW_KEYS = ("chat", "pipeline", "pipeline_spec")
_SHARED_GIT_PAT_ENV_KEYS = ("GIT_SHARED_PAT", "ASSIST_GIT_PAT")


def _git_default_action() -> dict[str, Any]:
    return {
        "type": "none",
        "enabled": False,
        "branchNamePattern": "feature/{description}",
        "reuseExistingBranch": True,
        "commitMessagePattern": "feat: {description}",
        "targetBranch": "",
        "prTitlePattern": "feat: {description}",
        "prBodyTemplate": "## Summary\n\n{description}\n\n## Changes\n\n- ",
        "draft": False,
        "pushBeforePr": True,
        "customCommand": "",
    }


def _git_default_phase_defs(workflow_key: str) -> list[dict[str, Any]]:
    if workflow_key == "chat":
        return [
            {
                "id": "initial",
                "label": "Pre-Intent / Chat Start",
                "description": "Runs before the Orchestrator Agent starts a chat-to-code run.",
                "agentName": "Orchestrator Agent",
                "icon": "play",
                "gitAction": _git_default_action(),
                "secondaryGitAction": _git_default_action(),
                "subtaskGitAction": _git_default_action(),
                "subtaskSecondaryGitAction": _git_default_action(),
            },
            {
                "id": "planning",
                "label": "Pre-Code Builder",
                "description": "Runs after planning/SDD generation and before Code Builder Codex.",
                "agentName": ["Planner Agent", "Orchestrator Agent"],
                "icon": "clipboard",
                "gitAction": {**_git_default_action(), "type": "create_branch", "enabled": False},
                "secondaryGitAction": _git_default_action(),
                "subtaskGitAction": _git_default_action(),
                "subtaskSecondaryGitAction": _git_default_action(),
            },
            {
                "id": "build",
                "label": "Pre-Code Review",
                "description": "Runs after Code Builder output and before Code Review Agent.",
                "agentName": "Code Builder Codex",
                "icon": "code",
                "gitAction": {**_git_default_action(), "type": "commit", "enabled": False},
                "secondaryGitAction": _git_default_action(),
                "subtaskGitAction": _git_default_action(),
                "subtaskSecondaryGitAction": _git_default_action(),
            },
            {
                "id": "review",
                "label": "Pre-Complete Result",
                "description": "Runs after Code Review and before the final Orchestrator response.",
                "agentName": "Code Review Agent",
                "icon": "search",
                "gitAction": {**_git_default_action(), "type": "create_pr", "enabled": False},
                "secondaryGitAction": _git_default_action(),
                "subtaskGitAction": _git_default_action(),
                "subtaskSecondaryGitAction": _git_default_action(),
            },
            {
                "id": "complete",
                "label": "Complete",
                "description": "Final terminal state for chat execution.",
                "agentName": "Orchestrator Agent",
                "icon": "check",
                "gitAction": _git_default_action(),
                "secondaryGitAction": _git_default_action(),
                "subtaskGitAction": _git_default_action(),
                "subtaskSecondaryGitAction": _git_default_action(),
            },
        ]

    if workflow_key == "pipeline_spec":
        start_label = "Pre-Intent / Pipeline SPEC Start"
        start_description = "Runs before Pipeline Agent starts a SPEC task run."
        planning_description = "Runs before Code Builder Codex for SPEC task execution."
        complete_description = "Final terminal state for SPEC pipeline workflow."
    else:
        start_label = "Pre-Intent / Pipeline Start"
        start_description = "Runs before Chat Intent Router or before Pipeline Agent starts a task run."
        planning_description = "Runs after planning/SDD generation and before Code Builder Codex."
        complete_description = "Final terminal state for chat or pipeline workflow."

    return [
        {
            "id": "initial",
            "label": start_label,
            "description": start_description,
            "agentName": ["Orchestrator Agent", "Pipeline Agent"],
            "icon": "play",
            "gitAction": _git_default_action(),
            "secondaryGitAction": _git_default_action(),
            "subtaskGitAction": _git_default_action(),
            "subtaskSecondaryGitAction": _git_default_action(),
        },
        {
            "id": "planning",
            "label": "Pre-Code Builder",
            "description": planning_description,
            "agentName": ["Planner Agent", "Pipeline Agent"],
            "icon": "clipboard",
            "gitAction": {**_git_default_action(), "type": "create_branch", "enabled": False},
            "secondaryGitAction": _git_default_action(),
            "subtaskGitAction": _git_default_action(),
            "subtaskSecondaryGitAction": _git_default_action(),
        },
        {
            "id": "build",
            "label": "Pre-Code Review",
            "description": "Runs after Code Builder output and before Code Review Agent (or review-equivalent checkpoint).",
            "agentName": "Code Builder Codex",
            "icon": "code",
            "gitAction": {**_git_default_action(), "type": "commit", "enabled": False},
            "secondaryGitAction": _git_default_action(),
            "subtaskGitAction": _git_default_action(),
            "subtaskSecondaryGitAction": _git_default_action(),
        },
        {
            "id": "review",
            "label": "Pre-Complete Result",
            "description": "Runs after Code Review and before final Orchestrator/Pipeline completion handoff.",
            "agentName": "Code Review Agent",
            "icon": "search",
            "gitAction": {**_git_default_action(), "type": "create_pr", "enabled": False},
            "secondaryGitAction": _git_default_action(),
            "subtaskGitAction": _git_default_action(),
            "subtaskSecondaryGitAction": _git_default_action(),
        },
        {
            "id": "complete",
            "label": "Complete",
            "description": complete_description,
            "agentName": ["Orchestrator Agent", "Pipeline Agent"],
            "icon": "check",
            "gitAction": _git_default_action(),
            "secondaryGitAction": _git_default_action(),
            "subtaskGitAction": _git_default_action(),
            "subtaskSecondaryGitAction": _git_default_action(),
        },
    ]


def _git_default_workflow_settings() -> dict[str, Any]:
    return {
        "defaultBranch": "main",
        "branchNamePattern": "feature/{description}",
        "commitMessagePattern": "feat: {description}",
        "prTitlePattern": "feat: {description}",
        "prBodyTemplate": "## Summary\n\n{description}\n\n## Changes\n\n- \n\n## Test Plan\n\n- ",
        "platform": "auto",
        "autoDetect": True,
        "autoPushOnCommit": False,
    }


def _normalize_git_workflow_entry(value: Any, workflow_key: str) -> dict[str, Any]:
    defaults_phases = _git_default_phase_defs(workflow_key)
    defaults_settings = _git_default_workflow_settings()
    if not isinstance(value, dict):
        value = {}

    raw_settings = value.get("settings")
    normalized_settings = dict(defaults_settings)
    if isinstance(raw_settings, dict):
        for key in normalized_settings:
            if key in raw_settings:
                normalized_settings[key] = raw_settings[key]

    raw_phases = value.get("phases")
    raw_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(raw_phases, list):
        for item in raw_phases:
            if not isinstance(item, dict):
                continue
            phase_id = str(item.get("id") or "").strip()
            if phase_id:
                raw_by_id[phase_id] = item

    normalized_phases: list[dict[str, Any]] = []
    for default_phase in defaults_phases:
        phase_id = str(default_phase.get("id") or "")
        current = raw_by_id.get(phase_id, {})
        phase = dict(default_phase)
        phase["label"] = str(current.get("label") or default_phase["label"])
        phase["description"] = str(current.get("description") or default_phase["description"])
        phase["agentName"] = current.get("agentName", default_phase["agentName"])
        phase["icon"] = str(current.get("icon") or default_phase["icon"])

        action = dict(_git_default_action())
        default_action = default_phase.get("gitAction")
        if isinstance(default_action, dict):
            action.update(default_action)
        secondary_action = dict(_git_default_action())
        default_secondary_action = default_phase.get("secondaryGitAction")
        if isinstance(default_secondary_action, dict):
            secondary_action.update(default_secondary_action)
        subtask_action = dict(_git_default_action())
        default_subtask_action = default_phase.get("subtaskGitAction")
        if isinstance(default_subtask_action, dict):
            subtask_action.update(default_subtask_action)
        subtask_secondary_action = dict(_git_default_action())
        default_subtask_secondary_action = default_phase.get("subtaskSecondaryGitAction")
        if isinstance(default_subtask_secondary_action, dict):
            subtask_secondary_action.update(default_subtask_secondary_action)

        current_action = current.get("gitAction")
        if isinstance(current_action, dict):
            action.update(current_action)
        current_secondary_action = current.get("secondaryGitAction")
        if isinstance(current_secondary_action, dict):
            secondary_action.update(current_secondary_action)
        current_subtask_action = current.get("subtaskGitAction")
        if isinstance(current_subtask_action, dict):
            subtask_action.update(current_subtask_action)
        current_subtask_secondary_action = current.get("subtaskSecondaryGitAction")
        if isinstance(current_subtask_secondary_action, dict):
            subtask_secondary_action.update(current_subtask_secondary_action)

        current_actions = current.get("gitActions")
        if isinstance(current_actions, dict):
            current_primary_from_group = current_actions.get("primary")
            if isinstance(current_primary_from_group, dict):
                action.update(current_primary_from_group)
            current_secondary_from_group = current_actions.get("secondary")
            if isinstance(current_secondary_from_group, dict):
                secondary_action.update(current_secondary_from_group)
            current_subtask_primary_from_group = current_actions.get("subtask-primary")
            if isinstance(current_subtask_primary_from_group, dict):
                subtask_action.update(current_subtask_primary_from_group)
            current_subtask_secondary_from_group = current_actions.get("subtask-secondary")
            if isinstance(current_subtask_secondary_from_group, dict):
                subtask_secondary_action.update(current_subtask_secondary_from_group)

        phase["gitAction"] = action
        phase["secondaryGitAction"] = secondary_action
        phase["subtaskGitAction"] = subtask_action
        phase["subtaskSecondaryGitAction"] = subtask_secondary_action
        normalized_phases.append(phase)

    return {"settings": normalized_settings, "phases": normalized_phases}


def _normalize_git_workflow_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}

    raw_workflows = value.get("workflows")
    legacy_source = value if isinstance(value, dict) else {}
    normalized_workflows: dict[str, dict[str, Any]] = {}
    if isinstance(raw_workflows, dict):
        for workflow_key in _GIT_WORKFLOW_KEYS:
            source = raw_workflows.get(workflow_key)
            if not isinstance(source, dict):
                source = legacy_source
            normalized_workflows[workflow_key] = _normalize_git_workflow_entry(source, workflow_key)
    else:
        for workflow_key in _GIT_WORKFLOW_KEYS:
            normalized_workflows[workflow_key] = _normalize_git_workflow_entry(legacy_source, workflow_key)

    return {
        "workflows": normalized_workflows,
    }


def _read_settings_unlocked() -> dict[str, Any]:
    try:
        raw = _SETTINGS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

    try:
        data = json.loads(raw)
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}
    return data


def load_settings() -> dict[str, Any]:
    with _LOCK:
        return _read_settings_unlocked()


def ensure_settings_file_exists() -> None:
    with _LOCK:
        if _SETTINGS_PATH.exists():
            return

        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

        if _SETTINGS_EXAMPLE_PATH.exists():
            try:
                example_raw = _SETTINGS_EXAMPLE_PATH.read_text(encoding="utf-8")
                json.loads(example_raw)
                _SETTINGS_PATH.write_text(example_raw, encoding="utf-8")
                return
            except Exception:
                pass

        _SETTINGS_PATH.write_text("{}\n", encoding="utf-8")


def update_settings(mutator: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    with _LOCK:
        current = _read_settings_unlocked()
        updated = mutator(current)
        if not isinstance(updated, dict):
            updated = current
        if updated == current:
            return current
        _SETTINGS_PATH.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
        return updated


def _read_agents_settings(settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}

    agents = settings.get("agents") if isinstance(settings, dict) else {}
    if isinstance(agents, dict):
        for key, value in agents.items():
            if isinstance(value, dict):
                normalized[str(key)] = dict(value)

    legacy_agents = settings.get("agents_codex") if isinstance(settings, dict) else {}
    if isinstance(legacy_agents, dict):
        for legacy_key, value in legacy_agents.items():
            if not isinstance(value, dict):
                continue
            key = _LEGACY_AGENT_KEY_MAP.get(str(legacy_key), str(legacy_key))
            normalized.setdefault(key, dict(value))

    return normalized


def _ensure_agents_settings(current: dict[str, Any]) -> dict[str, dict[str, Any]]:
    agents = _read_agents_settings(current)
    current["agents"] = agents
    current.pop("agents_codex", None)
    return agents


def get_agent_settings(agent_key: str) -> dict[str, Any]:
    defaults = dict(_DEFAULT_AGENT_SETTINGS.get(agent_key, {}))
    settings = load_settings()
    entry = _read_agents_settings(settings).get(agent_key)
    if isinstance(entry, dict):
        defaults.update(entry)
    return defaults


def get_agent_model(agent_key: str) -> str | None:
    model = str(get_agent_settings(agent_key).get("model") or "").strip()
    return model or None


def get_llm_provider_settings(provider: str | None = None) -> dict[str, Any]:
    settings = load_settings()
    llm = settings.get("llm") if isinstance(settings, dict) else {}
    if not isinstance(llm, dict):
        llm = {}
    raw_providers = llm.get("providers")
    providers: dict[str, dict[str, Any]] = {}
    if isinstance(raw_providers, dict):
        for key, value in raw_providers.items():
            if isinstance(value, dict):
                providers[str(key)] = dict(value)

    if provider is None:
        merged: dict[str, Any] = {}
        for key, default_value in _DEFAULT_LLM_PROVIDER_SETTINGS.items():
            item = dict(default_value)
            current = providers.get(key)
            if isinstance(current, dict):
                item.update(current)
            merged[key] = item
        return merged

    item = dict(_DEFAULT_LLM_PROVIDER_SETTINGS.get(provider, {}))
    current = providers.get(provider)
    if isinstance(current, dict):
        item.update(current)
    return item


def get_llm_function_settings(function_key: str) -> dict[str, Any]:
    settings = load_settings()
    llm = settings.get("llm") if isinstance(settings, dict) else {}
    if not isinstance(llm, dict):
        llm = {}
    raw_functions = llm.get("functions")
    functions: dict[str, dict[str, Any]] = {}
    if isinstance(raw_functions, dict):
        for key, value in raw_functions.items():
            if isinstance(value, dict):
                functions[str(key)] = dict(value)

    item = dict(_DEFAULT_LLM_FUNCTION_SETTINGS.get(function_key, {}))
    current = functions.get(function_key)
    if isinstance(current, dict):
        item.update(current)
    return item


def get_agent_bypass_settings() -> dict[str, bool]:
    def _read_bypass(key: str) -> bool:
        return bool(get_agent_settings(key).get("bypass"))

    return {
        "jira_api": _read_bypass("jira_api"),
        "sdd_spec": _read_bypass("sdd_spec"),
        "code_builder": _read_bypass("code_builder_codex"),
        "code_review": _read_bypass("code_review"),
    }


def set_agent_bypass_settings(
    *,
    jira_api: bool | None = None,
    sdd_spec: bool | None = None,
    code_builder: bool | None = None,
    code_review: bool | None = None,
) -> dict[str, bool]:
    def _mutate(current: dict[str, Any]) -> dict[str, Any]:
        agents = _ensure_agents_settings(current)

        for key in ("jira_api", "sdd_spec", "code_builder_codex", "code_review"):
            if not isinstance(agents.get(key), dict):
                agents[key] = {}

        if jira_api is not None:
            agents["jira_api"]["bypass"] = bool(jira_api)

        if sdd_spec is not None:
            agents["sdd_spec"]["bypass"] = bool(sdd_spec)

        if code_builder is not None:
            agents["code_builder_codex"]["bypass"] = bool(code_builder)

        if code_review is not None:
            agents["code_review"]["bypass"] = bool(code_review)

        return current

    update_settings(_mutate)
    return get_agent_bypass_settings()


def get_vision_settings() -> dict[str, int | float | str]:
    settings = load_settings()
    vision = settings.get("vision") if isinstance(settings, dict) else {}
    if not isinstance(vision, dict):
        vision = {}

    model = str(vision.get("model") or "").strip() or "gpt-5.4-mini"

    def _read_int(key: str, default_value: int) -> int:
        value = vision.get(key)
        if isinstance(value, bool):
            return default_value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except Exception:
                return default_value
        return default_value

    def _read_float(key: str, default_value: float) -> float:
        value = vision.get(key)
        if isinstance(value, bool):
            return default_value
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except Exception:
                return default_value
        return default_value

    max_images_per_turn = max(0, _read_int("max_images_per_turn", 2))
    max_image_bytes = max(1, _read_int("max_image_bytes", 8 * 1024 * 1024))
    timeout_seconds = max(1.0, _read_float("timeout_seconds", 20.0))

    return {
        "model": model,
        "max_images_per_turn": max_images_per_turn,
        "max_image_bytes": max_image_bytes,
        "timeout_seconds": timeout_seconds,
    }


# ---------------------------------------------------------------------------
# GitHub / GitLab integration settings
# ---------------------------------------------------------------------------

def _mask_token(token: str) -> str:
    """Return token with all but last 4 chars masked."""
    if not token:
        return ""
    if len(token) <= 4:
        return "*" * len(token)
    return "*" * (len(token) - 4) + token[-4:]


def _get_shared_git_pat() -> str:
    for env_key in _SHARED_GIT_PAT_ENV_KEYS:
        token = str(os.getenv(env_key, "")).strip()
        if token:
            return token
    return ""


def get_github_settings() -> dict[str, Any]:
    settings = load_settings()
    gh = settings.get("github") if isinstance(settings, dict) else {}
    if not isinstance(gh, dict):
        gh = {}
    token = str(gh.get("token") or os.getenv("GITHUB_TOKEN", "") or _get_shared_git_pat()).strip()
    username = str(gh.get("username") or os.getenv("GITHUB_USERNAME", "")).strip()
    return {
        "has_token": bool(token),
        "token_masked": _mask_token(token),
        "username": username,
    }


def get_github_token() -> str:
    """Return raw token for API calls."""
    settings = load_settings()
    gh = settings.get("github") if isinstance(settings, dict) else {}
    if not isinstance(gh, dict):
        gh = {}
    return str(gh.get("token") or os.getenv("GITHUB_TOKEN", "") or _get_shared_git_pat()).strip()


def get_github_username() -> str:
    settings = load_settings()
    gh = settings.get("github") if isinstance(settings, dict) else {}
    if not isinstance(gh, dict):
        gh = {}
    return str(gh.get("username") or os.getenv("GITHUB_USERNAME", "")).strip()


def update_github_settings(token: str | None = None, username: str | None = None) -> dict[str, Any]:
    def _mutate(current: dict[str, Any]) -> dict[str, Any]:
        gh = current.get("github")
        if not isinstance(gh, dict):
            gh = {}
            current["github"] = gh
        if token is not None:
            gh["token"] = token.strip()
        if username is not None:
            gh["username"] = username.strip()
        return current

    update_settings(_mutate)
    return get_github_settings()


def get_gitlab_settings() -> dict[str, Any]:
    settings = load_settings()
    gl = settings.get("gitlab") if isinstance(settings, dict) else {}
    if not isinstance(gl, dict):
        gl = {}
    token = str(gl.get("token") or os.getenv("GITLAB_TOKEN", "") or _get_shared_git_pat()).strip()
    url = str(gl.get("url") or os.getenv("GITLAB_URL", "https://gitlab.com")).strip() or "https://gitlab.com"
    username = str(gl.get("username") or os.getenv("GITLAB_USERNAME", "")).strip()
    return {
        "has_token": bool(token),
        "token_masked": _mask_token(token),
        "url": url,
        "username": username,
    }


def get_gitlab_token() -> str:
    settings = load_settings()
    gl = settings.get("gitlab") if isinstance(settings, dict) else {}
    if not isinstance(gl, dict):
        gl = {}
    return str(gl.get("token") or os.getenv("GITLAB_TOKEN", "") or _get_shared_git_pat()).strip()


def get_gitlab_url() -> str:
    settings = load_settings()
    gl = settings.get("gitlab") if isinstance(settings, dict) else {}
    if not isinstance(gl, dict):
        gl = {}
    return str(gl.get("url") or os.getenv("GITLAB_URL", "https://gitlab.com")).strip() or "https://gitlab.com"


def get_gitlab_username() -> str:
    settings = load_settings()
    gl = settings.get("gitlab") if isinstance(settings, dict) else {}
    if not isinstance(gl, dict):
        gl = {}
    return str(gl.get("username") or os.getenv("GITLAB_USERNAME", "")).strip()


def update_gitlab_settings(token: str | None = None, url: str | None = None, username: str | None = None) -> dict[str, Any]:
    def _mutate(current: dict[str, Any]) -> dict[str, Any]:
        gl = current.get("gitlab")
        if not isinstance(gl, dict):
            gl = {}
            current["gitlab"] = gl
        if token is not None:
            gl["token"] = token.strip()
        if url is not None:
            gl["url"] = url.strip()
        if username is not None:
            gl["username"] = username.strip()
        return current

    update_settings(_mutate)
    return get_gitlab_settings()


def get_jira_settings() -> dict[str, str]:
    from app.db import get_jira_config
    return get_jira_config()


def update_jira_settings(
    project_key: str | None = None,
    board_id: str | None = None,
    assignee_filter: str | None = None,
    jira_users: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    from app.db import save_jira_config
    return save_jira_config(
        project_key=project_key,
        board_id=board_id,
        assignee_filter=assignee_filter,
        jira_users=jira_users,
    )


def get_git_workflow_settings() -> dict[str, Any]:
    settings = load_settings()
    raw = settings.get("git_workflow") if isinstance(settings, dict) else {}
    return _normalize_git_workflow_config(raw)


def update_git_workflow_settings(
    *,
    workflows: dict[str, dict[str, Any]] | None = None,
    workflow_key: str | None = None,
    phases: list[dict[str, Any]] | None = None,
    workflow_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def _mutate(current: dict[str, Any]) -> dict[str, Any]:
        existing = current.get("git_workflow") if isinstance(current.get("git_workflow"), dict) else {}
        normalized_existing = _normalize_git_workflow_config(existing)
        merged_workflows = dict(
            normalized_existing.get("workflows")
            if isinstance(normalized_existing.get("workflows"), dict)
            else {}
        )

        if isinstance(workflows, dict):
            for key, value in workflows.items():
                if key not in _GIT_WORKFLOW_KEYS or not isinstance(value, dict):
                    continue
                merged_workflows[key] = value

        target_keys: tuple[str, ...]
        normalized_workflow_key = str(workflow_key or "").strip()
        if normalized_workflow_key in _GIT_WORKFLOW_KEYS:
            target_keys = (normalized_workflow_key,)
        else:
            target_keys = _GIT_WORKFLOW_KEYS

        if phases is not None or workflow_settings is not None:
            for key in target_keys:
                current_workflow = (
                    dict(merged_workflows.get(key))
                    if isinstance(merged_workflows.get(key), dict)
                    else {}
                )
                if phases is not None:
                    current_workflow["phases"] = phases
                if workflow_settings is not None:
                    current_workflow["settings"] = workflow_settings
                merged_workflows[key] = current_workflow

        return {**current, "git_workflow": _normalize_git_workflow_config({"workflows": merged_workflows})}

    update_settings(_mutate)
    return get_git_workflow_settings()
