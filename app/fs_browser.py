from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class FsEntry:
    name: str
    path: str
    type: str
    size: int | None
    modified_at: str | None


@dataclass
class FsColumn:
    path: str
    name: str
    parent: str | None
    entries: list[FsEntry]


def _format_time(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _entry_from_path(child: Path) -> FsEntry:
    stat = child.stat()
    return FsEntry(
        name=child.name,
        path=str(child.resolve()),
        type="dir" if child.is_dir() else "file",
        size=stat.st_size if child.is_file() else None,
        modified_at=_format_time(stat.st_mtime),
    )


def _should_include(child: Path, include_files: bool, show_hidden: bool) -> bool:
    if not show_hidden and child.name.startswith("."):
        return False
    if not include_files and not child.is_dir():
        return False
    return True


def _list_entries(base: Path, include_files: bool = True, show_hidden: bool = False) -> list[FsEntry]:
    entries: list[FsEntry] = []
    for child in base.iterdir():
        try:
            if not _should_include(child, include_files=include_files, show_hidden=show_hidden):
                continue
            entries.append(_entry_from_path(child))
        except PermissionError:
            continue

    entries.sort(key=lambda item: (item.type != "dir", item.name.lower()))
    return entries


def resolve_path(path: str | None) -> Path:
    if not path:
        return Path.home().resolve()
    return Path(path).expanduser().resolve()


def list_directory(path: str | None) -> dict[str, object]:
    base = resolve_path(path)
    if not base.exists():
        raise FileNotFoundError(f"Path not found: {base}")
    if not base.is_dir():
        raise NotADirectoryError(f"Not a directory: {base}")

    entries = _list_entries(base)

    parent = None if base.parent == base else str(base.parent)
    return {
        "path": str(base),
        "parent": parent,
        "home": str(Path.home().resolve()),
        "entries": [entry.__dict__ for entry in entries],
    }


def _path_chain(start: Path, target: Path) -> list[Path]:
    chain: list[Path] = []
    current = target

    while True:
        chain.append(current)
        if current == start:
            break
        if current.parent == current:
            break
        current = current.parent

    chain.reverse()
    return chain


def _column_label(path: Path, home: Path) -> str:
    if path == home:
        return "Home"
    if path.name:
        return path.name
    return path.anchor or str(path)


def list_tree_columns(
    path: str | None,
    include_files: bool = True,
    show_hidden: bool = False,
) -> dict[str, object]:
    selected = resolve_path(path)
    if not selected.exists():
        raise FileNotFoundError(f"Path not found: {selected}")
    if not selected.is_dir():
        raise NotADirectoryError(f"Not a directory: {selected}")

    home = Path.home().resolve()
    start = home if selected == home or home in selected.parents else Path(selected.anchor or "/").resolve()
    chain = _path_chain(start, selected)

    columns: list[FsColumn] = []
    for directory in chain:
        parent = None if directory.parent == directory else str(directory.parent)
        entries = _list_entries(directory, include_files=include_files, show_hidden=show_hidden)
        columns.append(
            FsColumn(
                path=str(directory),
                name=_column_label(directory, home),
                parent=parent,
                entries=entries,
            )
        )

    return {
        "home": str(home),
        "selected_path": str(selected),
        "columns": [
            {
                "path": column.path,
                "name": column.name,
                "parent": column.parent,
                "entries": [entry.__dict__ for entry in column.entries],
            }
            for column in columns
        ],
    }


def search_tree_entries(
    path: str | None,
    query: str = "",
    *,
    limit: int = 25,
    include_files: bool = True,
    show_hidden: bool = False,
) -> dict[str, object]:
    base = resolve_path(path)
    if not base.exists():
        raise FileNotFoundError(f"Path not found: {base}")
    if not base.is_dir():
        raise NotADirectoryError(f"Not a directory: {base}")

    normalized_query = query.strip().lower()
    max_results = max(1, min(limit, 200))
    queue: deque[Path] = deque([base])
    entries: list[FsEntry] = []

    while queue and len(entries) < max_results:
        directory = queue.popleft()
        try:
            children = sorted(
                directory.iterdir(),
                key=lambda child: (not child.is_dir(), child.name.lower()),
            )
        except PermissionError:
            continue

        for child in children:
            if not _should_include(child, include_files=include_files, show_hidden=show_hidden):
                continue

            child_name_lower = child.name.lower()
            if normalized_query in child_name_lower:
                try:
                    entries.append(_entry_from_path(child))
                except PermissionError:
                    continue
                if len(entries) >= max_results:
                    break

            if child.is_dir():
                queue.append(child)

    return {
        "path": str(base),
        "query": query,
        "entries": [entry.__dict__ for entry in entries],
    }


def _sanitize_folder_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Folder name is required")
    if cleaned in {".", ".."}:
        raise ValueError("Invalid folder name")
    if Path(cleaned).name != cleaned:
        raise ValueError("Folder name must not contain path separators")
    return cleaned


def _sanitize_entry_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Name is required")
    if cleaned in {".", ".."}:
        raise ValueError("Invalid name")
    if Path(cleaned).name != cleaned:
        raise ValueError("Name must not contain path separators")
    return cleaned


def create_directory(path: str, name: str) -> dict[str, object]:
    base = resolve_path(path)
    if not base.exists():
        raise FileNotFoundError(f"Path not found: {base}")
    if not base.is_dir():
        raise NotADirectoryError(f"Not a directory: {base}")

    folder_name = _sanitize_folder_name(name)
    target = (base / folder_name).resolve()
    target.mkdir(parents=False, exist_ok=False)
    return {
        "path": str(target),
        "name": target.name,
    }


def rename_entry(path: str, name: str) -> dict[str, object]:
    source = resolve_path(path)
    if not source.exists():
        raise FileNotFoundError(f"Path not found: {source}")

    entry_name = _sanitize_entry_name(name)
    target = (source.parent / entry_name).resolve()
    if target == source:
        return {
            "path": str(source),
            "name": source.name,
            "type": "dir" if source.is_dir() else "file",
        }
    if target.exists():
        raise FileExistsError(f"Path already exists: {target}")

    source.rename(target)
    return {
        "path": str(target),
        "name": target.name,
        "type": "dir" if target.is_dir() else "file",
    }


def delete_empty_directory(path: str) -> dict[str, object]:
    target = resolve_path(path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"Not a directory: {target}")

    try:
        next(target.iterdir())
    except StopIteration:
        pass
    else:
        raise ValueError("Directory is not empty")

    target.rmdir()
    return {
        "path": str(target),
        "name": target.name,
        "deleted": True,
    }
