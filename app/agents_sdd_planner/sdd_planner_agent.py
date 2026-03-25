from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agent_registry import make_agent_id, mark_agent_end, mark_agent_start
from app.agents_code_builder.runtime import run_codex_exec
from app.agents_sdd_spec.runtime import run_sdd_spec_agent
from app.settings_store import get_agent_model

_SAFE_SPEC_NAME_RE = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")
_SPEC_MANIFEST_FILENAME = ".spec.json"
_PLANNER_AGENT_ID = make_agent_id("agents", "Planner Agent")
_FENCED_CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)")
_INLINE_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_PLAIN_RELATIVE_PATH_RE = re.compile(r"(?<![A-Za-z0-9_/-])((?:\./)?[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)(?![A-Za-z0-9_/-])")


def _slugify(value: str, *, lowercase: bool = True) -> str:
    cleaned = str(value or "").strip()
    if lowercase:
        cleaned = cleaned.lower()
        cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    else:
        cleaned = re.sub(r"[^A-Za-z0-9]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned


def _derive_spec_name(prompt: str) -> str:
    candidate = _slugify(prompt, lowercase=True)[:64].strip("-")
    if candidate:
        return candidate
    return f"spec-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def normalize_spec_name(spec_name: str | None, prompt: str = "") -> str:
    candidate = _slugify(spec_name or "", lowercase=False)
    if not candidate:
        candidate = _derive_spec_name(prompt)
    if not _SAFE_SPEC_NAME_RE.fullmatch(candidate):
        raise ValueError("Invalid spec name. Use letters, numbers, and hyphens only.")
    return candidate


def _extract_json_payload(value: str) -> dict[str, object]:
    raw = str(value or "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw, re.IGNORECASE)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    generic = re.search(r"\{[\s\S]*\}", raw)
    if generic:
        try:
            parsed = json.loads(generic.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {}


def _fallback_manifest_name(prompt: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", str(prompt or "").strip())
    if not tokens:
        return "Untitled Specification"
    selected = tokens[:6]
    return " ".join(token.capitalize() for token in selected)


def _fallback_manifest_summary(prompt: str) -> str:
    collapsed = re.sub(r"\s+", " ", str(prompt or "").strip())
    if not collapsed:
        return "Specification request generated from user prompt."
    if len(collapsed) <= 220:
        return collapsed
    return collapsed[:217].rstrip() + "..."


def _normalize_manifest_text(value: str, fallback: str, max_length: int) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip())
    if not normalized:
        normalized = fallback
    if len(normalized) > max_length:
        normalized = normalized[: max(1, max_length - 3)].rstrip() + "..."
    return normalized


async def _generate_manifest_metadata(prompt: str, workspace_root: Path, model: str) -> tuple[str, str]:
    trimmed_prompt = str(prompt or "").strip()
    fallback_name = _fallback_manifest_name(trimmed_prompt)
    fallback_summary = _fallback_manifest_summary(trimmed_prompt)
    if not trimmed_prompt:
        return fallback_name, fallback_summary

    metadata_prompt = (
        "Generate metadata for a software specification request.\n"
        "Return JSON only with this shape:\n"
        '{"name":"Human readable title","summary":"Short summary"}\n'
        "Rules:\n"
        "- name must be concise and readable.\n"
        "- summary must be one sentence.\n"
        "- do not include markdown or code fences.\n\n"
        f"Request:\n{trimmed_prompt}\n"
    )

    try:
        result = await asyncio.to_thread(
            run_codex_exec,
            metadata_prompt,
            workspace_root,
            model,
            120,
            12000,
        )
        payload = _extract_json_payload(result.last_message)
        generated_name = _normalize_manifest_text(str(payload.get("name") or ""), fallback_name, 120)
        generated_summary = _normalize_manifest_text(str(payload.get("summary") or ""), fallback_summary, 260)
        return generated_name, generated_summary
    except Exception:
        return fallback_name, fallback_summary


def _next_manifest_version(manifest_path: Path) -> int:
    if not manifest_path.exists() or not manifest_path.is_file():
        return 1
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return 1
    if not isinstance(payload, dict):
        return 1
    current_version = payload.get("version")
    if isinstance(current_version, int) and current_version >= 1:
        return current_version + 1
    if isinstance(current_version, str) and current_version.strip().isdigit():
        parsed = int(current_version.strip())
        if parsed >= 1:
            return parsed + 1
    return 1


def _truncate_for_prompt(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    normalized = str(value or "")
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "\n... (truncated)"


def _resolve_secondary_absolute_path(
    token: str,
    *,
    primary_root: Path,
    secondary_root: Path,
) -> str | None:
    candidate = str(token or "").strip()
    if not candidate or "://" in candidate or candidate.startswith("~"):
        return None
    if "/" not in candidate:
        return None
    if Path(candidate).is_absolute():
        return None

    normalized_relative = candidate
    while normalized_relative.startswith("./"):
        normalized_relative = normalized_relative[2:]

    if not normalized_relative or normalized_relative.startswith("../"):
        return None

    secondary_candidate = (secondary_root / normalized_relative).resolve()
    try:
        secondary_candidate.relative_to(secondary_root)
    except ValueError:
        return None
    if not secondary_candidate.exists():
        return None

    primary_candidate = (primary_root / normalized_relative).resolve()
    try:
        primary_candidate.relative_to(primary_root)
    except ValueError:
        primary_exists = False
    else:
        primary_exists = primary_candidate.exists()

    if primary_exists:
        return None

    return str(secondary_candidate)


def _rewrite_secondary_paths_to_absolute(
    content: str,
    *,
    primary_root: Path,
    secondary_root: Path,
) -> str:
    source = str(content or "")
    if not source:
        return source

    def _replace_inline(match: re.Match[str]) -> str:
        token = str(match.group(1) or "").strip()
        absolute = _resolve_secondary_absolute_path(
            token,
            primary_root=primary_root,
            secondary_root=secondary_root,
        )
        if not absolute:
            return match.group(0)
        return f"`{absolute}`"

    def _replace_plain(match: re.Match[str]) -> str:
        raw_token = str(match.group(1) or "").strip()
        token = raw_token.rstrip(".,;:!?)]}")
        suffix = raw_token[len(token) :]
        absolute = _resolve_secondary_absolute_path(
            token,
            primary_root=primary_root,
            secondary_root=secondary_root,
        )
        if not absolute:
            return match.group(0)
        return f"{absolute}{suffix}"

    segments = _FENCED_CODE_BLOCK_RE.split(source)
    rewritten_segments: list[str] = []
    for segment in segments:
        if segment.startswith("```"):
            rewritten_segments.append(segment)
            continue
        rewritten = _INLINE_CODE_SPAN_RE.sub(_replace_inline, segment)
        rewritten = _PLAIN_RELATIVE_PATH_RE.sub(_replace_plain, rewritten)
        rewritten_segments.append(rewritten)
    return "".join(rewritten_segments)


def _normalize_manifest_context(prompt_context: list[dict[str, object]] | None) -> list[dict[str, object]]:
    if not prompt_context:
        return []

    normalized: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in prompt_context:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "").strip()
        raw_type = str(item.get("type") or "").strip().lower()
        if not raw_name:
            continue
        if raw_type not in {"file", "folder", "snippet", "image"}:
            continue

        if raw_type in {"file", "folder"}:
            raw_path = str(item.get("path") or "").strip()
            raw_absolute_path = str(item.get("absolute_path") or "").strip()
            if not raw_path:
                continue
            workspace_role = (
                "secondary"
                if str(item.get("workspace_role") or "").strip().lower() == "secondary"
                else "primary"
            )
            key = (raw_type, raw_path, workspace_role)
            if key in seen:
                continue
            seen.add(key)
            payload: dict[str, object] = {
                "name": raw_name,
                "type": raw_type,
                "path": raw_path,
                "workspace_role": workspace_role,
            }
            if raw_absolute_path:
                payload["absolute_path"] = raw_absolute_path
            normalized.append(payload)
            continue

        if raw_type == "snippet":
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            key = ("snippet", raw_name, content[:300])
            if key in seen:
                continue
            seen.add(key)
            payload: dict[str, object] = {
                "name": raw_name,
                "type": "snippet",
                "line_start": item.get("line_start"),
                "line_end": item.get("line_end"),
                "content_preview": _truncate_for_prompt(content, 400),
            }
            normalized.append(payload)
            continue

        mime_type = str(item.get("mime_type") or "image/png").strip() or "image/png"
        key = ("image", raw_name, mime_type)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "name": raw_name,
                "type": "image",
                "mime_type": mime_type,
            }
        )
    return normalized


def _history_entry(index: int, message: str, entry_type: str = "system") -> dict[str, str]:
    return {
        "id": f"sdd-history-{index}-{uuid4().hex[:8]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": message,
        "type": entry_type,
    }


def _render_prompt_context(
    prompt_context: list[dict[str, object]] | None,
    image_summaries: list[str] | None = None,
) -> str:
    lines: list[str] = []
    for item in prompt_context or []:
        if not isinstance(item, dict):
            continue
        context_type = str(item.get("type") or "").strip().lower()
        name = str(item.get("name") or "").strip()
        if context_type in {"file", "folder"}:
            path = str(item.get("path") or "").strip()
            absolute_path = str(item.get("absolute_path") or "").strip()
            workspace_role = (
                "secondary"
                if str(item.get("workspace_role") or "").strip().lower() == "secondary"
                else "primary"
            )
            if name and path:
                absolute_suffix = f" [abs: {absolute_path}]" if absolute_path else ""
                lines.append(f"- {context_type} [{workspace_role}]: {name} ({path}){absolute_suffix}")
            continue

        if context_type == "snippet":
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            line_start = item.get("line_start")
            line_end = item.get("line_end")
            if isinstance(line_start, int) and isinstance(line_end, int):
                lines.append(f"- snippet: {name} (lines {line_start}-{line_end})")
            else:
                lines.append(f"- snippet: {name}")
            lines.append(_truncate_for_prompt(content, 2400))
            continue

        if context_type == "image":
            mime_type = str(item.get("mime_type") or "image/png")
            lines.append(f"- image: {name or 'image'} (mime={mime_type})")

    if image_summaries:
        lines.append("- image-analysis:")
        for summary in image_summaries:
            if str(summary).strip():
                lines.append(f"  - {summary.strip()}")

    if not lines:
        return "(none)"
    return "\n".join(lines)


async def _run_sdd_edit_agent(
    *,
    task_prompt: str,
    workspace_root: Path,
    output_dir: Path,
    model: str | None = None,
) -> dict[str, str]:
    requirements_path = output_dir / "requirements.md"
    design_path = output_dir / "design.md"
    tasks_path = output_dir / "tasks.md"

    requirements_existing = _truncate_for_prompt(requirements_path.read_text(encoding="utf-8"), 50000)
    design_existing = _truncate_for_prompt(design_path.read_text(encoding="utf-8"), 50000)
    tasks_existing = _truncate_for_prompt(tasks_path.read_text(encoding="utf-8"), 50000)

    edit_prompt = (
        "You are the SDD Spec Agent in EDIT mode.\n"
        "You are updating an existing 3-file SDD bundle.\n\n"
        "Hard requirements:\n"
        "- Treat requirements.md, design.md, and tasks.md as one bundle.\n"
        "- Keep current structure, headings, and checklist ordering unless the request explicitly requires changes.\n"
        "- Apply focused edits only in impacted areas.\n"
        "- Keep unaffected sections stable.\n"
        "- Maintain parity across all three docs when one change impacts another.\n\n"
        "Output contract:\n"
        f"- Write requirements to: {requirements_path}\n"
        f"- Write design to: {design_path}\n"
        f"- Write tasks to: {tasks_path}\n"
        "- Return JSON only with this shape:\n"
        '{"requirements_path":"...","design_path":"...","tasks_path":"...","status":"success|failed","error":"..."}\n\n'
        f"Edit request:\n{task_prompt.strip()}\n\n"
        "Current bundle:\n"
        f"[requirements.md]\n{requirements_existing}\n\n"
        f"[design.md]\n{design_existing}\n\n"
        f"[tasks.md]\n{tasks_existing}\n"
    )

    result = await asyncio.to_thread(
        run_codex_exec,
        edit_prompt,
        workspace_root,
        model,
    )

    missing_paths: list[str] = []
    for path in (requirements_path, design_path, tasks_path):
        if not path.exists() or not path.is_file():
            missing_paths.append(str(path))
    if missing_paths:
        return {
            "requirements_path": str(requirements_path),
            "design_path": str(design_path),
            "tasks_path": str(tasks_path),
            "status": "failed",
            "error": "SDD Edit Agent did not produce required files: " + ", ".join(missing_paths),
        }

    payload: dict[str, Any] = {}
    raw = str(result.last_message or "").strip()
    if raw:
        payload = _extract_json_payload(raw)

    status = str(payload.get("status") or "success").strip().lower()
    error = str(payload.get("error") or "").strip()
    if status != "success" and not error:
        error = (result.stderr or "SDD Edit Agent reported failure.").strip()[:4000]

    return {
        "requirements_path": str(requirements_path),
        "design_path": str(design_path),
        "tasks_path": str(tasks_path),
        "status": "success" if status == "success" else "failed",
        "error": error,
    }


class SDDPlannerAgent:
    """API planner wrapper for generating SDD bundles in .assist/specs."""

    def __init__(self, model: str | None = None) -> None:
        configured = str(model or get_agent_model("planner") or "gpt-5-mini").strip()
        self.model = configured or "gpt-5-mini"

    async def process_prompt(
        self,
        *,
        prompt: str,
        workspace_path: str,
        file_tree: dict[str, Any],
        secondary_workspace_path: str | None = None,
        secondary_file_tree: dict[str, Any] | None = None,
        spec_name: str | None = None,
        raw_prompt: str | None = None,
        prompt_context: list[dict[str, object]] | None = None,
        mode: str = "create",
        current_bundle: dict[str, object] | None = None,
        image_summaries: list[str] | None = None,
    ) -> dict[str, object]:
        planner_error: str | None = None
        mark_agent_start(_PLANNER_AGENT_ID)

        try:
            workspace_root = Path(workspace_path).expanduser().resolve()
            if not workspace_root.exists() or not workspace_root.is_dir():
                raise ValueError(f"Workspace path is not a directory: {workspace_root}")
            secondary_workspace_root: Path | None = None
            if secondary_workspace_path and str(secondary_workspace_path).strip():
                candidate_secondary = Path(str(secondary_workspace_path).strip()).expanduser().resolve()
                if not candidate_secondary.exists() or not candidate_secondary.is_dir():
                    raise ValueError(f"Secondary workspace path is not a directory: {candidate_secondary}")
                if candidate_secondary != workspace_root:
                    secondary_workspace_root = candidate_secondary

            normalized_mode = str(mode or "create").strip().lower()
            if normalized_mode not in {"create", "edit"}:
                raise ValueError(f"Unsupported SDD planning mode: {mode}")

            resolved_spec_name = normalize_spec_name(spec_name, prompt)
            output_dir = workspace_root / ".assist" / "specs" / resolved_spec_name
            output_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = output_dir / _SPEC_MANIFEST_FILENAME
            user_prompt = str(raw_prompt or prompt).strip()
            normalized_context = _normalize_manifest_context(prompt_context)
            context_for_prompt = _render_prompt_context(prompt_context, image_summaries=image_summaries)
            spec_model = get_agent_model("sdd_spec")
            display_name, summary = await _generate_manifest_metadata(user_prompt, workspace_root, spec_model)
            next_version = _next_manifest_version(manifest_path)
            manifest_payload = {
                "name": display_name,
                "summary": summary,
                "prompt": user_prompt,
                "version": next_version,
                "mode": normalized_mode,
                "workspace_root": str(workspace_root),
                "secondary_workspace_root": str(secondary_workspace_root) if secondary_workspace_root else "",
                "context": normalized_context,
                "image_summaries": [str(item).strip() for item in (image_summaries or []) if str(item).strip()],
            }
            manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            history: list[dict[str, str]] = []
            history.append(_history_entry(len(history) + 1, f"Planning with {self.model}"))
            history.append(_history_entry(len(history) + 1, f"Saving to file: {_SPEC_MANIFEST_FILENAME}"))

            tree_json = json.dumps(file_tree or {}, ensure_ascii=False)
            if len(tree_json) > 50000:
                tree_json = tree_json[:50000] + "\n... (truncated)"
            secondary_tree_json = json.dumps(secondary_file_tree or {}, ensure_ascii=False)
            if len(secondary_tree_json) > 50000:
                secondary_tree_json = secondary_tree_json[:50000] + "\n... (truncated)"
            secondary_context_text = (
                f"- Secondary workspace root (read-only): {secondary_workspace_root}\n"
                f"- Secondary workspace tree snapshot (JSON):\n{secondary_tree_json}\n"
                if secondary_workspace_root is not None
                else "- Secondary workspace root (read-only): (none)\n"
            )

            if normalized_mode == "edit":
                if not isinstance(current_bundle, dict):
                    raise ValueError("Edit mode requires current_bundle.")

                history.append(_history_entry(len(history) + 1, "Editing existing SDD Bundle"))

                requirements_path = output_dir / "requirements.md"
                design_path = output_dir / "design.md"
                tasks_path = output_dir / "tasks.md"
                requirements_path.write_text(str(current_bundle.get("requirements") or ""), encoding="utf-8")
                design_path.write_text(str(current_bundle.get("design") or ""), encoding="utf-8")
                tasks_path.write_text(str(current_bundle.get("tasks") or ""), encoding="utf-8")

                planner_prompt = (
                    f"{prompt.strip()}\n\n"
                    "Planner context:\n"
                    f"- Planner model: {self.model}\n"
                    f"- Primary workspace root: {workspace_root}\n"
                    "- Mode: edit existing SDD bundle.\n"
                    "- Keep structure and tasks stable unless the user explicitly asks for structural changes.\n"
                    "- Apply focused edits and preserve unaffected sections.\n"
                    "- Use the secondary workspace only as read-only reference context.\n"
                    "- When using secondary workspace references, preserve the absolute path exactly as provided in Prompt references.\n"
                    "- Do not emit secondary references as relative paths such as `registry/...`; use full absolute paths.\n"
                    "- Prompt references:\n"
                    f"{context_for_prompt}\n"
                    f"- Primary workspace tree snapshot (JSON):\n{tree_json}\n"
                    f"{secondary_context_text}"
                )

                spec_result = await _run_sdd_edit_agent(
                    task_prompt=planner_prompt,
                    workspace_root=workspace_root,
                    output_dir=output_dir,
                    model=spec_model,
                )
            else:
                history.append(_history_entry(len(history) + 1, "Generating a SDD Bundle"))

                planner_prompt = (
                    f"{prompt.strip()}\n\n"
                    "Planner context:\n"
                    f"- Planner model: {self.model}\n"
                    f"- Primary workspace root: {workspace_root}\n"
                    "- Use the workspace file tree context to tailor requirements/design/tasks.\n"
                    "- Use the secondary workspace only as read-only reference context.\n"
                    "- When using secondary workspace references, preserve the absolute path exactly as provided in Prompt references.\n"
                    "- Do not emit secondary references as relative paths such as `registry/...`; use full absolute paths.\n"
                    "- Prompt references:\n"
                    f"{context_for_prompt}\n"
                    f"- Primary workspace tree snapshot (JSON):\n{tree_json}\n"
                    f"{secondary_context_text}"
                )

                spec_result = await run_sdd_spec_agent(
                    task_prompt=planner_prompt,
                    ticket_context=None,
                    workspace_path=str(workspace_root),
                    output_dir=str(output_dir),
                    model=spec_model,
                    memory_text="",
                )

            status = str(spec_result.get("status") or "").strip().lower()
            if status != "success":
                fallback_error = "Failed to update SDD spec files." if normalized_mode == "edit" else "Failed to generate SDD spec files."
                error_text = str(spec_result.get("error") or fallback_error).strip()
                history.append(_history_entry(len(history) + 1, f"Spec generation failed: {error_text}"))
                raise RuntimeError(error_text)

            requirements_path = Path(str(spec_result.get("requirements_path") or output_dir / "requirements.md"))
            design_path = Path(str(spec_result.get("design_path") or output_dir / "design.md"))
            tasks_path = Path(str(spec_result.get("tasks_path") or output_dir / "tasks.md"))

            requirements = requirements_path.read_text(encoding="utf-8")
            design = design_path.read_text(encoding="utf-8")
            tasks = tasks_path.read_text(encoding="utf-8")

            if secondary_workspace_root is not None:
                requirements = _rewrite_secondary_paths_to_absolute(
                    requirements,
                    primary_root=workspace_root,
                    secondary_root=secondary_workspace_root,
                )
                design = _rewrite_secondary_paths_to_absolute(
                    design,
                    primary_root=workspace_root,
                    secondary_root=secondary_workspace_root,
                )
                tasks = _rewrite_secondary_paths_to_absolute(
                    tasks,
                    primary_root=workspace_root,
                    secondary_root=secondary_workspace_root,
                )
                requirements_path.write_text(requirements, encoding="utf-8")
                design_path.write_text(design, encoding="utf-8")
                tasks_path.write_text(tasks, encoding="utf-8")

            history.append(_history_entry(len(history) + 1, "Saving to file: requirements.md"))
            history.append(_history_entry(len(history) + 1, "Saving to file: design.md"))
            history.append(_history_entry(len(history) + 1, "Saving to file: tasks.md"))

            return {
                "spec_name": resolved_spec_name,
                "requirements": requirements,
                "design": design,
                "tasks": tasks,
                "history": history,
            }
        except Exception as exc:
            planner_error = str(exc).strip() or type(exc).__name__
            raise
        finally:
            mark_agent_end(_PLANNER_AGENT_ID, planner_error or None)


__all__ = ["SDDPlannerAgent", "normalize_spec_name"]
