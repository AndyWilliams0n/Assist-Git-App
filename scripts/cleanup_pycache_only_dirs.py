#!/usr/bin/env python3
"""Remove directories whose subtree contains only Python cache artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CACHE_EXTENSIONS = {".pyc", ".pyo"}


@dataclass(frozen=True)
class DirectorySummary:
    total_files: int
    cache_files: int
    non_cache_files: int


def _is_cache_file(path: Path) -> bool:
    return path.suffix in CACHE_EXTENSIONS or "__pycache__" in path.parts


def _summarize_root(root: Path) -> tuple[dict[Path, DirectorySummary], list[Path], list[Path]]:
    summaries: dict[Path, DirectorySummary] = {}
    candidates: list[Path] = []
    retained_disqualified: list[Path] = []

    for current_str, dirnames, filenames in __import__("os").walk(root, topdown=False):
        current = Path(current_str)

        total_files = 0
        cache_files = 0
        non_cache_files = 0

        for filename in filenames:
            total_files += 1
            if _is_cache_file(current / filename):
                cache_files += 1
            else:
                non_cache_files += 1

        for dirname in dirnames:
            child = current / dirname
            child_summary = summaries.get(child)
            if child_summary is None:
                continue
            total_files += child_summary.total_files
            cache_files += child_summary.cache_files
            non_cache_files += child_summary.non_cache_files

        summary = DirectorySummary(
            total_files=total_files,
            cache_files=cache_files,
            non_cache_files=non_cache_files,
        )
        summaries[current] = summary

        if summary.total_files == 0:
            continue

        if summary.non_cache_files == 0 and current.name != "__pycache__" and current != root:
            candidates.append(current)
            continue

        if summary.cache_files > 0 and summary.non_cache_files > 0:
            retained_disqualified.append(current)

    return summaries, candidates, retained_disqualified


def find_pycache_only_directories(roots: Iterable[Path]) -> tuple[list[Path], list[Path]]:
    candidates: list[Path] = []
    retained_disqualified: list[Path] = []

    for root in roots:
        _, root_candidates, root_disqualified = _summarize_root(root)
        candidates.extend(root_candidates)
        retained_disqualified.extend(root_disqualified)

    candidates = sorted(set(candidates), key=lambda p: (len(p.parts), str(p)), reverse=True)
    retained_disqualified = sorted(set(retained_disqualified), key=lambda p: (len(p.parts), str(p)))
    return candidates, retained_disqualified


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True, help="Root directory to scan (repeatable).")
    parser.add_argument("--dry-run", action="store_true", help="Report candidates without deleting.")
    parser.add_argument("--delete", action="store_true", help="Delete candidate directories.")
    parser.add_argument(
        "--fail-on-found",
        action="store_true",
        help="Return non-zero when pycache-only candidates are found.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.dry_run and args.delete:
        parser.error("Use either --dry-run or --delete, not both.")

    mode_delete = args.delete
    roots = [Path(root).resolve() for root in args.root]
    missing_roots = [str(root) for root in roots if not root.exists()]

    result = {
        "roots_scanned": [str(root) for root in roots],
        "candidates": [],
        "deleted": [],
        "retained_disqualified": [],
        "skipped_roots": [str(root) for root in roots],
        "errors": [],
    }

    if missing_roots:
        for missing in missing_roots:
            result["errors"].append({"path": missing, "error": "root does not exist"})
        print(json.dumps(result, indent=2))
        return 1

    candidates, retained_disqualified = find_pycache_only_directories(roots)
    result["candidates"] = [str(path) for path in candidates]
    result["retained_disqualified"] = [str(path) for path in retained_disqualified]

    if mode_delete:
        for candidate in candidates:
            try:
                shutil.rmtree(candidate)
                result["deleted"].append(str(candidate))
            except OSError as exc:
                result["errors"].append({"path": str(candidate), "error": str(exc)})
                break

    print(json.dumps(result, indent=2))

    if result["errors"]:
        return 1

    if args.fail_on_found and result["candidates"]:
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
