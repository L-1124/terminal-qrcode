"""本地开发依赖安装脚本."""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REQUIRED_PORTS = [
    "libjpeg-turbo:x64-windows-static",
    "libpng:x64-windows-static",
    "libwebp[core]:x64-windows-static",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_command(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def install_windows_dev(
    *,
    repo_root: Path,
    run_command: Callable[[list[str], Path | None], None] = _run_command,
) -> list[str]:
    """在 Windows 本地安装开发依赖."""
    cache_root = repo_root / ".cache" / "bootstrap"
    vcpkg_root = cache_root / "vcpkg"
    vcpkg_bin_cache = cache_root / "vcpkg-bincache"
    vendor_dir = repo_root / "src" / "terminal_qrcode" / "_vendor" / "windows"

    if vendor_dir.exists():
        shutil.rmtree(vendor_dir)
    vendor_dir.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    vcpkg_bin_cache.mkdir(parents=True, exist_ok=True)

    # 避免继承到无效缓存目录，导致 vcpkg install 直接失败。
    os.environ["VCPKG_DEFAULT_BINARY_CACHE"] = str(vcpkg_bin_cache)

    if not vcpkg_root.exists():
        run_command(["git", "clone", "https://github.com/microsoft/vcpkg.git", str(vcpkg_root)], repo_root)

    bootstrap_bat = vcpkg_root / "bootstrap-vcpkg.bat"
    if not bootstrap_bat.exists():
        raise RuntimeError(f"bootstrap script not found: {bootstrap_bat}")
    run_command(["cmd", "/c", str(bootstrap_bat)], vcpkg_root)

    vcpkg_exe = vcpkg_root / "vcpkg.exe"
    if not vcpkg_exe.exists():
        raise RuntimeError(f"vcpkg executable not found: {vcpkg_exe}")

    run_command([str(vcpkg_exe), "--disable-metrics", "install", *REQUIRED_PORTS], vcpkg_root)

    return []  # No DLLs bundled in static mode


def main() -> int:
    """执行本地开发依赖安装流程."""
    if sys.platform != "win32":
        print("Only Windows install is implemented for local development now.", file=sys.stderr)  # noqa: T201
        print("Use CI workflow for Linux/macOS wheel dependency bundling.", file=sys.stderr)  # noqa: T201
        return 2

    outputs: list[str] = []
    try:
        outputs = install_windows_dev(repo_root=_repo_root())
    except Exception as exc:
        print(f"install failed: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    print("Bundled libraries (windows):")  # noqa: T201
    for name in outputs:
        print(f"- {name}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
