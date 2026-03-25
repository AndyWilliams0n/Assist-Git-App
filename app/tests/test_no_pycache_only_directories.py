from pathlib import Path

import importlib.util
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SCOPED_ROOTS = [
    REPO_ROOT / ".assist/specs/GIT-1-2",
    REPO_ROOT / "app",
]
MODULE_PATH = REPO_ROOT / "scripts/cleanup_pycache_only_dirs.py"

spec = importlib.util.spec_from_file_location("cleanup_pycache_only_dirs", MODULE_PATH)
if spec is None or spec.loader is None:
    raise AssertionError(f"Unable to load cleanup script from {MODULE_PATH}")
cleanup_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cleanup_module
spec.loader.exec_module(cleanup_module)


def test_scoped_roots_have_no_pycache_only_directories() -> None:
    candidates, _ = cleanup_module.find_pycache_only_directories(SCOPED_ROOTS)
    assert candidates == [], "Found pycache-only directories:\n" + "\n".join(str(path) for path in candidates)
