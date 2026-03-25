from __future__ import annotations

import os
import time
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

GITIGNORE_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "gitignore.txt"
ASSIST_TEST_RELATIVE_PATH = ".assist/test"
ASSIST_TEST_TMP_RELATIVE_PATH = ".assist/test/tmp"
ASSIST_IMAGES_RELATIVE_PATH = ".assist/images"
ASSIST_PIPELINE_RELATIVE_PATH = ".assist/pipeline"
CODE_BUILDER_WORKSPACE_RULES = (
    "Workspace guardrails:\n"
    "- If the workspace is a git repository and the root `.gitignore` is missing, create it from the standard template before other changes.\n"
    "- Store generated test artifacts in `.assist/test/`; use `$ASSIST_TEST_DIR` when a command needs an absolute path.\n"
    "- Keep screenshots, downloads, snapshots, fixtures, and temporary test data under `.assist/test/`.\n"
    "- Prefer unit tests; run browser or end-to-end suites only when they are required for the change.\n"
    "- Do not commit generated files under `.assist/test/`.\n"
)


@dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


@dataclass
class WorkspaceBootstrapResult:
    workspace_root: Path
    assist_images_dir: Path
    assist_pipeline_dir: Path
    assist_test_dir: Path
    assist_test_tmp_dir: Path
    gitignore_created: bool
    assist_test_dir_created: bool


def assist_test_dir(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / Path(ASSIST_TEST_RELATIVE_PATH)


def ensure_workspace_bootstrap(root: str | Path) -> WorkspaceBootstrapResult:
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Workspace path does not exist: {root_path}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"Workspace path is not a directory: {root_path}")

    images_dir = root_path / Path(ASSIST_IMAGES_RELATIVE_PATH)
    pipeline_dir = root_path / Path(ASSIST_PIPELINE_RELATIVE_PATH)
    test_dir = assist_test_dir(root_path)
    tmp_dir = root_path / Path(ASSIST_TEST_TMP_RELATIVE_PATH)
    test_dir_previously_present = test_dir.exists()
    images_dir.mkdir(parents=True, exist_ok=True)
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    gitignore_created = False
    gitignore_path = root_path / ".gitignore"
    if (root_path / ".git").exists() and not gitignore_path.exists() and GITIGNORE_TEMPLATE_PATH.exists():
        gitignore_path.write_text(GITIGNORE_TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        gitignore_created = True

    return WorkspaceBootstrapResult(
        workspace_root=root_path,
        assist_images_dir=images_dir,
        assist_pipeline_dir=pipeline_dir,
        assist_test_dir=test_dir,
        assist_test_tmp_dir=tmp_dir,
        gitignore_created=gitignore_created,
        assist_test_dir_created=not test_dir_previously_present,
    )


class WorkspaceManager:
    def __init__(
        self,
        root: str | Path | None = None,
        mode: Literal["read_write", "read_only"] = "read_write",
    ) -> None:
        root_path = Path(root) if root else Path(os.getenv("WORKSPACE_ROOT", Path.cwd()))
        self.root = root_path.resolve()
        normalized_mode = str(mode or "read_write").strip().lower()
        if normalized_mode not in {"read_write", "read_only"}:
            raise ValueError(f"Unsupported workspace mode: {mode}")
        self.mode = normalized_mode

    def _assert_writable(self, operation: str) -> None:
        if self.mode != "read_only":
            return
        raise PermissionError(f"Workspace is read-only. '{operation}' is not allowed.")

    def resolve_path(self, path: str) -> Path:
        candidate = (self.root / path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Path escapes workspace root") from exc
        return candidate

    def list_tree(self, path: str = ".", max_depth: int = 2, max_entries: int = 240) -> str:
        base = self.resolve_path(path)
        if not base.exists():
            return f"(missing) {path}"
        if base.is_file():
            return str(base.relative_to(self.root))

        entries: list[str] = []

        def walk(current: Path, depth: int, prefix: str) -> None:
            if len(entries) >= max_entries:
                return
            if depth > max_depth:
                return
            try:
                children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except Exception:
                return
            for child in children:
                if len(entries) >= max_entries:
                    return
                name = f"{child.name}/" if child.is_dir() else child.name
                rel = child.relative_to(self.root)
                entries.append(f"{prefix}{name}  ({rel})")
                if child.is_dir():
                    walk(child, depth + 1, prefix + "  ")

        walk(base, 0, "")
        if not entries:
            return f"(empty) {path}"
        if len(entries) >= max_entries:
            entries.append("... (truncated)")
        return "\n".join(entries)

    def read_text(self, path: str, max_bytes: int = 200_000) -> str:
        target = self.resolve_path(path)
        if not target.exists():
            raise FileNotFoundError(path)
        data = target.read_bytes()
        truncated = False
        if len(data) > max_bytes:
            data = data[:max_bytes]
            truncated = True
        text = data.decode("utf-8", errors="replace")
        if truncated:
            text += "\n\n... (truncated)"
        return text

    def write_text(self, path: str, content: str) -> None:
        self._assert_writable("write_text")
        target = self.resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def append_text(self, path: str, content: str) -> None:
        self._assert_writable("append_text")
        target = self.resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(content)

    def replace_text(self, path: str, old: str, new: str, count: int = 1) -> int:
        self._assert_writable("replace_text")
        target = self.resolve_path(path)
        text = target.read_text(encoding="utf-8")
        replaced = text.replace(old, new, count)
        if text == replaced:
            return 0
        target.write_text(replaced, encoding="utf-8")
        return 1

    def delete_path(self, path: str) -> None:
        self._assert_writable("delete_path")
        target = self.resolve_path(path)
        if target.is_dir():
            for child in target.iterdir():
                rel_child = str(child.relative_to(self.root))
                self.delete_path(rel_child)
            target.rmdir()
        else:
            target.unlink(missing_ok=True)

    def mkdir(self, path: str) -> None:
        self._assert_writable("mkdir")
        target = self.resolve_path(path)
        target.mkdir(parents=True, exist_ok=True)


def run_command(
    command: str,
    cwd: Path,
    timeout_seconds: int = 30,
    max_output: int = 16_000,
    env: dict[str, str] | None = None,
) -> CommandResult:
    start = time.time()
    try:
        run_env = os.environ.copy()
        if env:
            run_env.update({str(k): str(v) for k, v in env.items()})
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env=run_env,
            timeout=timeout_seconds,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if not stderr:
            stderr = f"Command timed out after {timeout_seconds} seconds."
        exit_code = 124
    end = time.time()
    duration_ms = int((end - start) * 1000)
    if len(stdout) > max_output:
        stdout = stdout[:max_output] + "\n... (truncated)"
    if len(stderr) > max_output:
        stderr = stderr[:max_output] + "\n... (truncated)"

    return CommandResult(
        command=command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
    )
