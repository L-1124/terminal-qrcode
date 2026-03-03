"""本地开发依赖自举入口."""

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_windows_bootstrap() -> Callable[..., list[str]]:
    module_path = Path(__file__).resolve().parent / "bootstrap" / "windows.py"
    spec = importlib.util.spec_from_file_location("bootstrap_windows", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load bootstrap module from: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.bootstrap_windows
    except AttributeError as exc:
        raise RuntimeError("bootstrap_windows entrypoint not found in windows.py") from exc


def main() -> int:
    """执行平台依赖自举流程."""
    if sys.platform != "win32":
        sys.stderr.write("Only Windows bootstrap is implemented for local development now.\n")
        sys.stderr.write("Use CI workflow for Linux/macOS wheel dependency bundling.\n")
        return 2

    outputs: list[str] = []
    try:
        bootstrap_windows = _load_windows_bootstrap()
        outputs = bootstrap_windows(repo_root=_repo_root())
    except Exception as exc:
        sys.stderr.write(f"bootstrap failed: {exc}\n")
        return 1

    sys.stdout.write("Bundled libraries (windows):\n")
    for name in outputs:
        sys.stdout.write(f"- {name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
