from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx


class StitchServiceError(RuntimeError):
    pass


def _normalize_workspace_path(workspace_root: str) -> Path:
    value = str(workspace_root or '').strip()

    if not value:
        raise StitchServiceError('workspace_root is required')

    path = Path(value).expanduser().resolve()

    if not path.exists() or not path.is_dir():
        raise StitchServiceError('workspace_root must be an existing directory')

    return path


def _run_git(workspace_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ['git', '-C', str(workspace_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise StitchServiceError('Workspace is not a git repository') from exc

    return (completed.stdout or '').strip()


def ensure_git_workspace(workspace_root: str) -> tuple[Path, str]:
    path = _normalize_workspace_path(workspace_root)

    _run_git(path, 'rev-parse', '--is-inside-work-tree')

    top_level = _run_git(path, 'rev-parse', '--show-toplevel')

    repo_name = Path(top_level).name.strip()

    if not repo_name:
        raise StitchServiceError('Could not resolve repository name for workspace')

    return path, repo_name


def stitch_base_dir(workspace_root: Path) -> Path:
    return workspace_root / '.assist' / 'stitch'


def stitch_images_dir(workspace_root: Path) -> Path:
    return stitch_base_dir(workspace_root) / 'images'


def stitch_code_dir(workspace_root: Path) -> Path:
    return stitch_base_dir(workspace_root) / 'code'


def stitch_link_path(workspace_root: Path) -> Path:
    return stitch_base_dir(workspace_root) / 'link.json'


def stitch_design_md_path(workspace_root: Path) -> Path:
    return stitch_base_dir(workspace_root) / 'design-system.md'


def stitch_design_json_path(workspace_root: Path) -> Path:
    return stitch_base_dir(workspace_root) / 'design-system.json'


def assist_design_md_path(workspace_root: Path) -> Path:
    return workspace_root / '.assist' / 'design-system.md'


def assist_design_json_path(workspace_root: Path) -> Path:
    return workspace_root / '.assist' / 'design-system.json'


def _read_link_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None

    if not isinstance(raw, dict):
        return None

    project_id = str(raw.get('project_id') or '').strip()

    if not project_id:
        return None

    return raw


def read_workspace_link(workspace_root: str) -> dict[str, Any] | None:
    workspace_path = _normalize_workspace_path(workspace_root)
    return _read_link_file(stitch_link_path(workspace_path))


def _write_link_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{json.dumps(payload, indent=2)}\n', encoding='utf-8')


def _write_text_file(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{json.dumps(payload, indent=2)}\n', encoding='utf-8')


def _read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    return payload


def _node_bridge_path() -> Path:
    return (Path(__file__).resolve().parents[1] / 'mcp' / 'scripts' / 'stitch-bridge.mjs').resolve()


def _stitch_env() -> dict[str, str]:
    env = os.environ.copy()

    if not env.get('STITCH_API_KEY') and env.get('GEMINI_API_KEY'):
        env['STITCH_API_KEY'] = env['GEMINI_API_KEY']

    return env


def _call_bridge(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    script_path = _node_bridge_path()

    if not script_path.exists():
        raise StitchServiceError('Stitch bridge script is missing')

    try:
        completed = subprocess.run(
            ['node', str(script_path), action, json.dumps(payload)],
            capture_output=True,
            text=True,
            check=False,
            env=_stitch_env(),
        )
    except FileNotFoundError as exc:
        raise StitchServiceError('Node.js is required for Stitch SDK operations') from exc

    stdout = (completed.stdout or '').strip()

    if not stdout:
        stderr = (completed.stderr or '').strip()
        raise StitchServiceError(stderr or f'Stitch bridge failed with exit code {completed.returncode}')

    last_line = stdout.splitlines()[-1]

    try:
        payload_json = json.loads(last_line)
    except Exception as exc:
        raise StitchServiceError(f'Invalid Stitch bridge response: {last_line}') from exc

    if completed.returncode != 0 or not payload_json.get('ok'):
        error = str(payload_json.get('error') or '').strip() or 'Unknown Stitch bridge error'
        raise StitchServiceError(error)

    result = payload_json.get('result')

    if not isinstance(result, dict):
        raise StitchServiceError('Stitch bridge returned an invalid payload')

    return result


def _normalize_project_id(project: dict[str, Any]) -> str:
    value = str(project.get('name') or '').strip()

    if value.startswith('projects/'):
        return value.split('/', 1)[1]

    return value


def _find_owned_project_by_title(projects: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    target = title.strip().lower()

    if not target:
        return None

    for project in projects:
        value = str(project.get('title') or '').strip().lower()

        if value == target:
            return project

    return None


def link_workspace_project(
    workspace_root: str,
    project_id: str | None = None,
    create_if_missing: bool = True,
) -> dict[str, Any]:
    workspace_path, repo_name = ensure_git_workspace(workspace_root)

    link_file = stitch_link_path(workspace_path)
    linked = _read_link_file(link_file)

    resolved_project_id = str(project_id or '').strip() or str((linked or {}).get('project_id') or '').strip()

    project: dict[str, Any]

    if resolved_project_id:
        project = _call_bridge('get_project', {'projectId': resolved_project_id})
    else:
        list_result = _call_bridge('list_projects', {})
        projects = list_result.get('projects') if isinstance(list_result.get('projects'), list) else []
        matched = _find_owned_project_by_title(projects, repo_name)

        if matched:
            project = matched
            resolved_project_id = _normalize_project_id(project)
        elif create_if_missing:
            project = _call_bridge('create_project', {'title': repo_name})
            resolved_project_id = _normalize_project_id(project)
        else:
            raise StitchServiceError('No Stitch project found for this repository')

    if not resolved_project_id:
        resolved_project_id = _normalize_project_id(project)

    if not resolved_project_id:
        raise StitchServiceError('Could not resolve Stitch project id')

    saved = {
        'repo_name': repo_name,
        'project_id': resolved_project_id,
        'project_name': str(project.get('name') or f'projects/{resolved_project_id}'),
        'project_title': str(project.get('title') or repo_name),
    }

    _write_link_file(link_file, saved)

    return {
        **saved,
        'workspace_root': str(workspace_path),
    }


def _normalize_screen_id(screen: dict[str, Any]) -> str:
    name = str(screen.get('name') or '').strip()

    if '/screens/' in name:
        return name.split('/screens/', 1)[1]

    return name


def _extract_hex_colors(markdown: str) -> list[str]:
    seen: set[str] = set()
    colors: list[str] = []

    for match in re.finditer(r'#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?', markdown):
        normalized = match.group(0).upper()

        if normalized in seen:
            continue

        seen.add(normalized)
        colors.append(normalized)

    return colors


def _extract_named_color_pairs(markdown: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'(?im)\b(primary|secondary|tertiary|neutral|accent|success|warning|error)\b[^#\n\r]{0,50}(#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?)'
    )

    for match in pattern.finditer(markdown):
        name = str(match.group(1) or '').strip().lower().capitalize()
        hex_code = str(match.group(2) or '').strip().upper()
        dedupe_key = f'{name}:{hex_code}'

        if not name or not hex_code or dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        candidates.append({'name': name, 'hex': hex_code})

    return candidates


def _normalize_hex_color(value: str, fallback: str) -> str:
    text = str(value or '').strip()

    if not text:
        return fallback

    if re.match(r'^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$', text):
        return text.upper()

    return fallback


def _named_color_map(design_theme: dict[str, Any]) -> dict[str, str]:
    named_colors = design_theme.get('namedColors') if isinstance(design_theme.get('namedColors'), list) else []
    mapping: dict[str, str] = {}

    for item in named_colors:
        if not isinstance(item, dict):
            continue

        key = str(item.get('name') or item.get('id') or '').strip().lower()
        value = str(item.get('hex') or item.get('value') or item.get('color') or '').strip()

        if not key:
            continue

        if not re.match(r'^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$', value):
            continue

        mapping[key] = value.upper()

    return mapping


def _build_direct_design_system_json(
    design_theme: dict[str, Any],
    design_md: str,
    source_hash: str,
    project_id: str,
    project_title: str,
) -> dict[str, Any]:
    named_colors = _named_color_map(design_theme)
    primary = _normalize_hex_color(
        str(design_theme.get('overridePrimaryColor') or named_colors.get('primary') or ''),
        '#0066FF',
    )
    secondary = _normalize_hex_color(
        str(design_theme.get('overrideSecondaryColor') or named_colors.get('secondary') or ''),
        '#77767A',
    )
    tertiary = _normalize_hex_color(
        str(design_theme.get('overrideTertiaryColor') or named_colors.get('tertiary') or ''),
        '#9700FF',
    )
    neutral = _normalize_hex_color(
        str(design_theme.get('overrideNeutralColor') or named_colors.get('neutral') or ''),
        '#787677',
    )

    return {
        'meta': {
            'projectId': project_id,
            'projectTitle': project_title,
            'sourceHash': source_hash,
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'parser': 'stitch_theme_direct',
        },
        'colors': [
            {'name': 'Primary', 'hex': primary},
            {'name': 'Secondary', 'hex': secondary},
            {'name': 'Tertiary', 'hex': tertiary},
            {'name': 'Neutral', 'hex': neutral},
        ],
        'typography': {
            'headline': str(design_theme.get('headlineFont') or '').strip(),
            'body': str(design_theme.get('bodyFont') or '').strip(),
            'label': str(design_theme.get('labelFont') or '').strip(),
        },
        'styleGuidelines': str(design_theme.get('description') or '').strip(),
        'components': [],
        'rawMarkdown': design_md,
    }


def list_workspace_screens(workspace_root: str) -> dict[str, Any]:
    workspace_path, repo_name = ensure_git_workspace(workspace_root)
    linked = link_workspace_project(str(workspace_path), create_if_missing=False)
    project_id = linked['project_id']

    list_result = _call_bridge('list_screens', {'projectId': project_id})
    screens = list_result.get('screens') if isinstance(list_result.get('screens'), list) else []

    normalized: list[dict[str, Any]] = []

    for screen in screens:
        if not isinstance(screen, dict):
            continue

        screen_id = _normalize_screen_id(screen)

        if not screen_id:
            continue

        details = _call_bridge('get_screen', {'projectId': project_id, 'screenId': screen_id})

        normalized.append(
            {
                'screen_id': screen_id,
                'name': str(details.get('name') or screen.get('name') or ''),
                'title': str(details.get('title') or screen.get('title') or screen_id),
                'device_type': str(details.get('deviceType') or screen.get('deviceType') or ''),
                'width': details.get('width'),
                'height': details.get('height'),
                'screenshot_url': str(((details.get('screenshot') or {}) if isinstance(details.get('screenshot'), dict) else {}).get('downloadUrl') or ''),
                'html_url': str(((details.get('htmlCode') or {}) if isinstance(details.get('htmlCode'), dict) else {}).get('downloadUrl') or ''),
            }
        )

    return {
        'workspace_root': str(workspace_path),
        'repo_name': repo_name,
        'project_id': project_id,
        'project_title': linked['project_title'],
        'screens': normalized,
    }


def generate_workspace_screens(
    workspace_root: str,
    prompt: str,
    device_type: str = 'DESKTOP',
) -> dict[str, Any]:
    workspace_path, repo_name = ensure_git_workspace(workspace_root)
    linked = link_workspace_project(str(workspace_path), create_if_missing=False)
    project_id = linked['project_id']

    normalized_prompt = str(prompt or '').strip()

    if not normalized_prompt:
        raise StitchServiceError('prompt is required')

    generation = _call_bridge(
        'generate_screen',
        {
            'projectId': project_id,
            'prompt': normalized_prompt,
            'deviceType': str(device_type or 'DESKTOP').strip() or 'DESKTOP',
        },
    )

    output_components = generation.get('outputComponents') if isinstance(generation.get('outputComponents'), list) else []

    generated_ids: list[str] = []

    for component in output_components:
        if not isinstance(component, dict):
            continue

        design = component.get('design') if isinstance(component.get('design'), dict) else {}
        screens = design.get('screens') if isinstance(design.get('screens'), list) else []

        for screen in screens:
            if not isinstance(screen, dict):
                continue

            screen_id = _normalize_screen_id(screen)

            if screen_id and screen_id not in generated_ids:
                generated_ids.append(screen_id)

    details: list[dict[str, Any]] = []

    for screen_id in generated_ids:
        screen = _call_bridge('get_screen', {'projectId': project_id, 'screenId': screen_id})
        details.append(
            {
                'screen_id': screen_id,
                'name': str(screen.get('name') or ''),
                'title': str(screen.get('title') or screen_id),
                'screenshot_url': str(((screen.get('screenshot') or {}) if isinstance(screen.get('screenshot'), dict) else {}).get('downloadUrl') or ''),
                'html_url': str(((screen.get('htmlCode') or {}) if isinstance(screen.get('htmlCode'), dict) else {}).get('downloadUrl') or ''),
            }
        )

    return {
        'workspace_root': str(workspace_path),
        'repo_name': repo_name,
        'project_id': project_id,
        'project_title': linked['project_title'],
        'session_id': str(generation.get('sessionId') or ''),
        'screens': details,
    }


def _safe_file_slug(value: str, fallback: str) -> str:
    normalized = re.sub(r'[^a-zA-Z0-9._-]+', '-', str(value or '').strip()).strip('-').lower()

    if normalized:
        return normalized

    return fallback


async def _download_to_path(url: str, destination: Path) -> None:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)


async def download_workspace_screen_assets(
    workspace_root: str,
    screen_id: str,
    title: str | None = None,
) -> dict[str, Any]:
    workspace_path, _ = ensure_git_workspace(workspace_root)
    linked = link_workspace_project(str(workspace_path), create_if_missing=False)
    project_id = linked['project_id']

    resolved_screen_id = str(screen_id or '').strip()

    if not resolved_screen_id:
        raise StitchServiceError('screen_id is required')

    screen = _call_bridge('get_screen', {'projectId': project_id, 'screenId': resolved_screen_id})

    screenshot_url = str(((screen.get('screenshot') or {}) if isinstance(screen.get('screenshot'), dict) else {}).get('downloadUrl') or '')
    html_url = str(((screen.get('htmlCode') or {}) if isinstance(screen.get('htmlCode'), dict) else {}).get('downloadUrl') or '')

    if not screenshot_url and not html_url:
        raise StitchServiceError('No downloadable screenshot or html was found for this screen')

    base_name = _safe_file_slug(str(title or screen.get('title') or resolved_screen_id), resolved_screen_id)

    image_file_path = stitch_images_dir(workspace_path) / f'{base_name}.png'
    code_file_path = stitch_code_dir(workspace_path) / f'{base_name}.html'

    if screenshot_url:
        await _download_to_path(screenshot_url, image_file_path)

    if html_url:
        await _download_to_path(html_url, code_file_path)

    return {
        'workspace_root': str(workspace_path),
        'project_id': project_id,
        'screen_id': resolved_screen_id,
        'image_path': str(image_file_path) if screenshot_url else None,
        'code_path': str(code_file_path) if html_url else None,
        'image_url': screenshot_url,
        'html_url': html_url,
    }


def stitch_workspace_status(workspace_root: str) -> dict[str, Any]:
    try:
        workspace_path, repo_name = ensure_git_workspace(workspace_root)
    except StitchServiceError:
        return {
            'workspace_root': str(workspace_root or ''),
            'is_git_repo': False,
            'repo_name': '',
            'linked': False,
            'project_id': '',
            'project_title': '',
        }

    linked = _read_link_file(stitch_link_path(workspace_path))

    project_id = str((linked or {}).get('project_id') or '').strip()
    project_title = str((linked or {}).get('project_title') or '').strip()

    return {
        'workspace_root': str(workspace_path),
        'is_git_repo': True,
        'repo_name': repo_name,
        'linked': bool(project_id),
        'project_id': project_id,
        'project_title': project_title,
    }


async def load_workspace_design_system(
    workspace_root: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    workspace_path, repo_name = ensure_git_workspace(workspace_root)
    linked = link_workspace_project(str(workspace_path), create_if_missing=False)
    project_id = str(linked.get('project_id') or '').strip()
    project_title = str(linked.get('project_title') or '').strip() or repo_name

    if not project_id:
        raise StitchServiceError('No Stitch project is linked for this workspace')

    project = _call_bridge('get_project', {'projectId': project_id})
    design_theme = project.get('designTheme') if isinstance(project.get('designTheme'), dict) else {}
    design_md = str(design_theme.get('designMd') or '').strip()

    stitch_md_file = stitch_design_md_path(workspace_path)
    stitch_json_file = stitch_design_json_path(workspace_path)
    assist_md_file = assist_design_md_path(workspace_path)
    assist_json_file = assist_design_json_path(workspace_path)

    if design_md:
        markdown_with_newline = f'{design_md.rstrip()}\n'
        _write_text_file(stitch_md_file, markdown_with_newline)
        _write_text_file(assist_md_file, markdown_with_newline)

    design_json_payload: dict[str, Any] | None = None
    parser = ''
    source_hash = sha256(design_md.encode('utf-8')).hexdigest() if design_md else ''

    if design_md:
        design_json_payload = _build_direct_design_system_json(
            design_theme=design_theme,
            design_md=design_md,
            source_hash=source_hash,
            project_id=project_id,
            project_title=project_title,
        )
        parser = str(((design_json_payload.get('meta') or {}) if isinstance(design_json_payload.get('meta'), dict) else {}).get('parser') or 'stitch_theme_direct').strip() or 'stitch_theme_direct'
        _write_json_file(stitch_json_file, design_json_payload)
        _write_json_file(assist_json_file, design_json_payload)

    return {
        'workspace_root': str(workspace_path),
        'repo_name': repo_name,
        'project_id': project_id,
        'project_title': project_title,
        'available': bool(design_md),
        'design_md': design_md,
        'design_md_path': str(stitch_md_file) if stitch_md_file.exists() else '',
        'assist_design_md_path': str(assist_md_file) if assist_md_file.exists() else '',
        'design_json': design_json_payload,
        'design_json_path': str(stitch_json_file) if stitch_json_file.exists() and design_json_payload else '',
        'assist_design_json_path': str(assist_json_file) if assist_json_file.exists() and design_json_payload else '',
        'parser': parser,
    }
