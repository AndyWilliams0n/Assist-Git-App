from __future__ import annotations

import re
import shlex
from datetime import datetime, timezone
from typing import Any, Literal

from app.agents_git import GitAgent
from app.agents_git_content import GitContentAgent
from app.settings_store import get_git_workflow_settings

GIT_HOOK_STAGES = ("initial", "planning", "build", "review", "complete")
ACTIVE_WORKSPACE_BRANCH_VALUE = "__active_workspace_branch__"


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._/-]+", "-", str(value or "").strip().lower())
    text = re.sub(r"-{2,}", "-", text).strip("-/")
    return text or "update"


def _render_template(template: str, values: dict[str, str], *, slug_description: bool = False) -> str:
    description = values.get("description", "")
    replacements = {
        **values,
        "description": _slugify(description) if slug_description else description,
    }
    text = str(template or "")
    for key, value in replacements.items():
        text = text.replace(f"{{{key}}}", str(value or ""))
    return " ".join(text.split()) if not slug_description else re.sub(r"/{2,}", "/", text).strip()


def _create_branch_fallback_result(
    *,
    current_branch: str,
    default_branch: str,
) -> dict[str, Any] | None:
    normalized_current = str(current_branch or "").strip()
    normalized_default = str(default_branch or "").strip()
    if not normalized_current:
        return None
    if normalized_default and normalized_current == normalized_default:
        return None
    return {
        "success": True,
        "branch": normalized_current,
        "created": False,
        "checked_out": True,
        "already_exists": True,
        "output": f"Reusing current branch '{normalized_current}'",
        "error": None,
    }


def _resolve_default_branch(setting_value: str, current_branch: str) -> str:
    normalized_setting = str(setting_value or "").strip()
    normalized_current = str(current_branch or "").strip()
    if normalized_setting == ACTIVE_WORKSPACE_BRANCH_VALUE:
        return normalized_current or "main"
    return normalized_setting or "main"


def _phase_config(
    stage_id: str,
    workflow_key: Literal["chat", "pipeline", "pipeline_spec"],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]] | None:
    config = get_git_workflow_settings()
    workflows = config.get("workflows") if isinstance(config.get("workflows"), dict) else {}
    workflow_config = workflows.get(workflow_key) if isinstance(workflows.get(workflow_key), dict) else {}
    settings = workflow_config.get("settings") if isinstance(workflow_config.get("settings"), dict) else {}
    phases = workflow_config.get("phases") if isinstance(workflow_config.get("phases"), list) else []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        if str(phase.get("id") or "") == stage_id:
            primary_action = phase.get("gitAction") if isinstance(phase.get("gitAction"), dict) else {}
            secondary_action = (
                phase.get("secondaryGitAction")
                if isinstance(phase.get("secondaryGitAction"), dict)
                else {}
            )
            subtask_primary_action = (
                phase.get("subtaskGitAction")
                if isinstance(phase.get("subtaskGitAction"), dict)
                else {}
            )
            subtask_secondary_action = (
                phase.get("subtaskSecondaryGitAction")
                if isinstance(phase.get("subtaskSecondaryGitAction"), dict)
                else {}
            )
            grouped_actions = phase.get("gitActions")
            if isinstance(grouped_actions, dict):
                grouped_primary = grouped_actions.get("primary")
                if isinstance(grouped_primary, dict):
                    primary_action = grouped_primary
                grouped_secondary = grouped_actions.get("secondary")
                if isinstance(grouped_secondary, dict):
                    secondary_action = grouped_secondary
                grouped_subtask_primary = grouped_actions.get("subtask-primary")
                if isinstance(grouped_subtask_primary, dict):
                    subtask_primary_action = grouped_subtask_primary
                grouped_subtask_secondary = grouped_actions.get("subtask-secondary")
                if isinstance(grouped_subtask_secondary, dict):
                    subtask_secondary_action = grouped_subtask_secondary
            return {
                "primary": primary_action,
                "secondary": secondary_action,
                "subtask-primary": subtask_primary_action,
                "subtask-secondary": subtask_secondary_action,
            }, settings if isinstance(settings, dict) else {}
    return None


def _enabled_action(action: dict[str, Any]) -> tuple[bool, str]:
    action_type = str(action.get("type") or "none").strip()
    enabled = bool(action.get("enabled")) and action_type != "none"
    return enabled, action_type


def _is_missing_remote_ref_error(error_text: str) -> bool:
    normalized_error = str(error_text or "").strip().lower()
    return "couldn't find remote ref" in normalized_error or "could not find remote ref" in normalized_error


def _action_pushes_remote(action: dict[str, Any], settings: dict[str, Any]) -> bool:
    action_type = str(action.get("type") or "none").strip()
    if action_type == "push":
        return True
    if action_type == "create_pr":
        return bool(action.get("pushBeforePr", True))
    if action_type == "commit":
        return bool(settings.get("autoPushOnCommit"))
    return False


def _extract_test_report_hints(summary_text: str) -> tuple[str, str]:
    text = str(summary_text or "").strip()
    if not text:
        return "Not available in this run", "Not available in this run"

    lowered = text.lower()
    coverage_hint = "Not available in this run"
    passed_hint = "Not available in this run"

    coverage_match = re.search(r"(coverage[^\n]{0,80})", text, flags=re.IGNORECASE)
    if coverage_match:
        coverage_hint = " ".join(str(coverage_match.group(1) or "").split())[:180]

    passed_match = re.search(r"(\d+)\s+(?:tests?\s+)?passed", lowered)
    if passed_match:
        passed_hint = str(passed_match.group(1))

    return coverage_hint, passed_hint


async def _collect_outgoing_paths_for_description(
    *,
    agent: GitAgent,
    workspace: str,
    remote_name: str,
    branch_name: str,
) -> list[str]:
    collector = getattr(agent, "_collect_outgoing_paths", None)
    if callable(collector):
        try:
            paths, error_text = await collector(workspace, remote_name, branch_name)
            if not error_text and isinstance(paths, list):
                return [
                    str(item).strip()
                    for item in paths
                    if str(item).strip()
                ]
        except Exception:
            pass

    code, out, _ = await agent._run(  # noqa: SLF001 - controlled git inspection command
        ["git", "diff", "--name-only", "HEAD~1..HEAD"],
        cwd=workspace,
    )
    if code != 0:
        return []
    return [
        str(line).strip()
        for line in out.splitlines()
        if str(line).strip()
    ]


async def _generate_review_branch_description(
    *,
    workspace: str,
    workflow_key: Literal["chat", "pipeline", "pipeline_spec"],
    status: dict[str, Any],
    settings: dict[str, Any],
    context: dict[str, str],
    enabled_slots: list[tuple[str, dict[str, Any], str]],
    git_agent: GitAgent,
) -> dict[str, Any] | None:
    if not enabled_slots:
        return None

    should_generate = any(_action_pushes_remote(action, settings) for _, action, _ in enabled_slots)
    if not should_generate:
        return None

    requested_platform = str(settings.get("platform") or "auto").strip() or "auto"
    resolved_platform = await git_agent._resolve_platform(workspace, requested_platform)  # noqa: SLF001 - runtime platform resolution
    if resolved_platform not in {"github", "gitlab"}:
        return None

    branch_name = str(status.get("branch") or "").strip()
    if not branch_name:
        return None

    remote_name = "origin"
    remotes = status.get("remotes")
    if isinstance(remotes, list):
        for item in remotes:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("name") or "").strip()
            if candidate:
                remote_name = candidate
                break

    changed_files = await _collect_outgoing_paths_for_description(
        agent=git_agent,
        workspace=workspace,
        remote_name=remote_name,
        branch_name=branch_name,
    )
    summary_text = str(context.get("summary") or "").strip()
    coverage_hint, passed_hint = _extract_test_report_hints(summary_text)

    original_request = str(context.get("description") or "").strip() or str(context.get("summary") or "").strip()
    ticket_key = str(context.get("ticket") or "").strip()
    workflow_type = str(context.get("type") or workflow_key).strip()

    git_content_agent = GitContentAgent(registry_mode="agents")
    generated = await git_content_agent.generate_branch_description(
        {
            "workflow_type": workflow_type,
            "ticket_key": ticket_key or "n/a",
            "branch_name": branch_name,
            "original_request": original_request or "Not provided.",
            "execution_summary": summary_text or "Not provided.",
            "changed_files": changed_files,
            "coverage_hint": coverage_hint,
            "passed_hint": passed_hint,
        }
    )
    if not generated.get("success"):
        return None

    description_text = str(generated.get("description") or "").strip()
    if not description_text:
        return None

    set_result = await git_agent.set_branch_description(
        workspace=workspace,
        description=description_text,
        branch=branch_name,
    )

    return {
        "description": description_text,
        "branch": branch_name,
        "set_branch_description": set_result,
        "used_fallback": bool(generated.get("used_fallback")),
        "platform": resolved_platform,
    }


async def _local_branch_exists(agent: GitAgent, workspace: str, branch_name: str) -> bool:
    normalized_branch_name = str(branch_name or "").strip()
    if not normalized_branch_name:
        return False

    get_branches_fn = getattr(agent, "get_branches", None)
    if not callable(get_branches_fn):
        return False

    try:
        branches_payload = await get_branches_fn(workspace)
    except Exception:
        return False

    local_branches = branches_payload.get("local") if isinstance(branches_payload, dict) else []
    if not isinstance(local_branches, list):
        return False

    return normalized_branch_name in {
        str(branch or "").strip()
        for branch in local_branches
        if str(branch or "").strip()
    }


async def _run_single_git_action(
    *,
    stage_id: str,
    workspace: str,
    action: dict[str, Any],
    settings: dict[str, Any],
    ctx: dict[str, str],
    status: dict[str, Any],
    generated_branch_description: str | None,
    target_branch_override: str | None,
    agent: GitAgent,
) -> dict[str, Any]:
    action_type = str(action.get("type") or "none").strip()
    branch_pattern = str(action.get("branchNamePattern") or settings.get("branchNamePattern") or "feature/{description}")
    commit_pattern = str(action.get("commitMessagePattern") or settings.get("commitMessagePattern") or "feat: {description}")
    pr_title_pattern = str(action.get("prTitlePattern") or settings.get("prTitlePattern") or "feat: {description}")
    pr_body_template = str(action.get("prBodyTemplate") or settings.get("prBodyTemplate") or "{description}")
    override_target_branch = str(target_branch_override or "").strip()
    action_target_branch = str(action.get("targetBranch") or "").strip()
    global_default_branch_setting = str(settings.get("defaultBranch") or "main")
    global_default_branch = _resolve_default_branch(
        global_default_branch_setting,
        ctx.get("branch", ""),
    )
    target_branch = override_target_branch or action_target_branch or global_default_branch
    platform = str(settings.get("platform") or "auto")
    primary_remote = ""
    status_remotes = status.get("remotes")
    if isinstance(status_remotes, list):
        for remote_item in status_remotes:
            if not isinstance(remote_item, dict):
                continue
            candidate_remote = str(remote_item.get("name") or "").strip()
            if not candidate_remote:
                continue
            primary_remote = candidate_remote
            break
    remote_name = primary_remote or "origin"

    result: dict[str, Any]
    if action_type == "check_git":
        result = status
        ok = bool(result.get("is_git_repo"))
    elif action_type == "check_pr":
        result = await agent.list_prs(workspace, platform=platform)
        ok = bool(result.get("success"))
    elif action_type == "fetch":
        result = await agent.fetch(
            workspace,
            remote=remote_name,
            branch=target_branch or None,
        )
        ok = bool(result.get("success"))
        if (
            not ok
            and target_branch
            and _is_missing_remote_ref_error(str(result.get("error") or ""))
            and await _local_branch_exists(agent, workspace, target_branch)
        ):
            fallback_result = await agent.fetch(
                workspace,
                remote=remote_name,
                branch=None,
            )
            fallback_success = bool(fallback_result.get("success"))
            if fallback_success:
                warning_message = (
                    f"Remote ref '{target_branch}' was not found; continued with local branch and a full fetch."
                )
                result = {
                    **fallback_result,
                    "success": True,
                    "remote": remote_name,
                    "branch": target_branch,
                    "error": None,
                    "warning": warning_message,
                    "missing_remote_ref_error": str(result.get("error") or ""),
                    "fallback_fetch": fallback_result,
                }
                ok = True
    elif action_type == "pull":
        result = await agent.pull(
            workspace,
            remote=remote_name,
            branch=target_branch or None,
            ff_only=True,
            rebase=False,
        )
        ok = bool(result.get("success"))
    elif action_type == "rebase":
        result = await agent.rebase(
            workspace,
            base_branch=target_branch or "main",
            remote=remote_name,
            fetch_first=True,
        )
        ok = bool(result.get("success"))
    elif action_type == "create_branch":
        branch_name = _render_template(branch_pattern, ctx, slug_description=True)
        reuse_existing_branch = bool(action.get("reuseExistingBranch", True))
        if not branch_name:
            fallback_result = _create_branch_fallback_result(
                current_branch=ctx.get("branch", ""),
                default_branch=(
                    ""
                    if str(global_default_branch_setting).strip() == ACTIVE_WORKSPACE_BRANCH_VALUE
                    else global_default_branch
                ),
            )
            if fallback_result is not None:
                result = fallback_result
                ok = True
            else:
                available_context = ", ".join(sorted(key for key, value in ctx.items() if str(value or "").strip()))
                return {
                    "ok": False,
                    "stage": stage_id,
                    "action": action_type,
                    "error": (
                        "Create-branch pattern resolved to an empty branch name. "
                        f"pattern={branch_pattern!r}. "
                        "Use a pattern that resolves for this workflow, such as "
                        "'feature/{description}' or '{branch}', or start from a non-default working branch. "
                        f"Available context keys: {available_context or 'none'}."
                    ),
                }
        else:
            result = await agent.create_branch(
                workspace,
                branch_name,
                target_branch or None,
                reuse_existing=reuse_existing_branch,
            )
            ok = bool(result.get("success"))
    elif action_type == "commit":
        message = _render_template(commit_pattern, ctx)
        result = await agent.commit(workspace, message, add_all=True)
        ok = bool(result.get("success"))
        if ok and bool(settings.get("autoPushOnCommit")):
            push_result = await agent.push(workspace, remote=remote_name)
            result = {**result, "auto_push": push_result}
            ok = bool(push_result.get("success"))
    elif action_type == "create_pr":
        title = _render_template(pr_title_pattern, ctx)
        if generated_branch_description:
            body = generated_branch_description
        else:
            body = _render_template(pr_body_template, ctx)
        result = await agent.create_pr(
            workspace=workspace,
            title=title,
            body=body,
            target_branch=target_branch or "main",
            draft=bool(action.get("draft")),
            push_first=bool(action.get("pushBeforePr", True)),
            platform=platform,
            remote=remote_name,
        )
        ok = bool(result.get("success"))
    elif action_type == "push":
        result = await agent.push(workspace, remote=remote_name)
        ok = bool(result.get("success"))
    elif action_type == "custom":
        command = str(action.get("customCommand") or "").strip()
        if not command.startswith("git "):
            return {
                "ok": False,
                "stage": stage_id,
                "action": action_type,
                "error": "Custom command must start with 'git '",
            }
        try:
            cmd = shlex.split(command)
        except Exception as exc:
            return {"ok": False, "stage": stage_id, "action": action_type, "error": f"Invalid custom command: {exc}"}
        code, out, err = await agent._run(cmd, cwd=workspace)  # noqa: SLF001 - internal helper reused for controlled git commands
        result = {"success": code == 0, "output": out, "error": err if code != 0 else None}
        ok = code == 0
    else:
        return {"ok": False, "stage": stage_id, "action": action_type, "error": f"Unsupported action '{action_type}'"}

    message = f"Git hook {stage_id}: {action_type} {'ok' if ok else 'failed'}"
    if result.get("warning"):
        message += f" ({str(result.get('warning'))[:240]})"
    if result.get("error"):
        message += f" ({str(result.get('error'))[:240]})"
    return {
        "ok": ok,
        "stage": stage_id,
        "action": action_type,
        "message": message,
        "result": result,
    }


async def run_configured_git_action(
    *,
    stage_id: str,
    workspace_path: str,
    workflow_key: Literal["chat", "pipeline", "pipeline_spec"] = "pipeline",
    context: dict[str, str] | None = None,
    target_branch_override: str | None = None,
    git_agent: GitAgent | None = None,
    is_subtask: bool = False,
) -> dict[str, Any]:
    if stage_id not in GIT_HOOK_STAGES:
        return {"ok": False, "skipped": True, "reason": f"unknown stage '{stage_id}'"}

    resolved = _phase_config(stage_id, workflow_key)
    if not resolved:
        return {"ok": False, "skipped": True, "reason": "git workflow config missing"}
    actions, settings = resolved

    workspace = str(workspace_path or "").strip()
    if not workspace:
        return {"ok": False, "skipped": True, "stage": stage_id, "action": "none", "reason": "workspace missing"}

    agent = git_agent or GitAgent()
    ctx = {
        "description": "",
        "ticket": "",
        "type": "",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "branch": "",
        "summary": "",
    }
    if context:
        for key in list(ctx.keys()):
            if key in context:
                ctx[key] = str(context.get(key) or "")

    status = await agent.get_status(workspace)
    if not status.get("is_git_repo"):
        return {
            "ok": False,
            "stage": stage_id,
            "action": "check_git",
            "error": str(status.get("error") or "Workspace is not a git repository"),
            "result": status,
        }
    ctx["branch"] = str(status.get("branch") or ctx["branch"])

    if is_subtask:
        action_slots = (
            ("subtask-primary", actions.get("subtask-primary") if isinstance(actions.get("subtask-primary"), dict) else {}),
            ("subtask-secondary", actions.get("subtask-secondary") if isinstance(actions.get("subtask-secondary"), dict) else {}),
        )
    else:
        action_slots = (
            ("primary", actions.get("primary") if isinstance(actions.get("primary"), dict) else {}),
            ("secondary", actions.get("secondary") if isinstance(actions.get("secondary"), dict) else {}),
        )
    enabled_slots: list[tuple[str, dict[str, Any], str]] = []
    for slot_name, slot_action in action_slots:
        enabled, action_type = _enabled_action(slot_action)
        if enabled:
            enabled_slots.append((slot_name, slot_action, action_type))

    if not enabled_slots:
        primary_slot = "subtask-primary" if is_subtask else "primary"
        secondary_slot = "subtask-secondary" if is_subtask else "secondary"
        primary_type = str((actions.get(primary_slot) or {}).get("type") or "none")
        secondary_type = str((actions.get(secondary_slot) or {}).get("type") or "none")
        action_label = f"{primary_slot}:{primary_type}, {secondary_slot}:{secondary_type}"
        return {
            "ok": True,
            "skipped": True,
            "stage": stage_id,
            "action": action_label,
            "reason": "disabled",
        }

    generated_description_result: dict[str, Any] | None = None
    if stage_id == "review":
        generated_description_result = await _generate_review_branch_description(
            workspace=workspace,
            workflow_key=workflow_key,
            status=status,
            settings=settings,
            context=ctx,
            enabled_slots=enabled_slots,
            git_agent=agent,
        )

    generated_branch_description = (
        str(generated_description_result.get("description") or "").strip()
        if isinstance(generated_description_result, dict)
        else ""
    )

    outcomes: list[dict[str, Any]] = []
    for slot_name, slot_action, _ in enabled_slots:
        outcome = await _run_single_git_action(
            stage_id=stage_id,
            workspace=workspace,
            action=slot_action,
            settings=settings,
            ctx=ctx,
            status=status,
            generated_branch_description=generated_branch_description or None,
            target_branch_override=target_branch_override,
            agent=agent,
        )
        slot_outcome = {
            "slot": slot_name,
            "ok": bool(outcome.get("ok")),
            "action": str(outcome.get("action") or ""),
            "message": str(outcome.get("message") or ""),
            "result": outcome.get("result") if isinstance(outcome.get("result"), dict) else {},
        }
        outcomes.append(slot_outcome)

        if not bool(outcome.get("ok")):
            failed_action = f"{slot_name}:{str(outcome.get('action') or 'unknown')}"
            if len(outcomes) == 1 and len(enabled_slots) == 1:
                return {
                    **outcome,
                    "slot": slot_name,
                    "generated_branch_description": generated_description_result,
                    "actions": outcomes,
                }
            return {
                "ok": False,
                "stage": stage_id,
                "action": failed_action,
                "message": str(outcome.get("message") or f"Git hook {stage_id}: {failed_action} failed"),
                "result": outcome.get("result") if isinstance(outcome.get("result"), dict) else {},
                "generated_branch_description": generated_description_result,
                "actions": outcomes,
            }

    if len(outcomes) == 1:
        only = outcomes[0]
        action_label = (
            only["action"]
            if str(only.get("slot") or "") == "primary"
            else f"{only['slot']}:{only['action']}"
        )
        return {
            "ok": True,
            "stage": stage_id,
            "action": action_label,
            "message": only["message"] or f"Git hook {stage_id}: {only['slot']} {only['action']} ok",
            "result": only["result"],
            "generated_branch_description": generated_description_result,
            "actions": outcomes,
        }

    action_label = ", ".join(f"{item['slot']}:{item['action']}" for item in outcomes)
    return {
        "ok": True,
        "stage": stage_id,
        "action": action_label,
        "message": f"Git hook {stage_id}: {action_label} ok",
        "result": {
            "primary": outcomes[0].get("result", {}),
            "secondary": outcomes[1].get("result", {}),
        },
        "generated_branch_description": generated_description_result,
        "actions": outcomes,
    }
