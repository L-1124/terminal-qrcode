"""Windows 平台依赖自举实现."""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

REQUIRED_PORTS = [
    "libjpeg-turbo:x64-windows",
    "libpng:x64-windows",
    "libwebp:x64-windows",
]


def _run_command(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _copy_required(source: Path, target: Path, name: str) -> None:
    if not source.exists():
        raise RuntimeError(f"Required dynamic library not found: {name}")
    shutil.copy2(source, target / name)


def bootstrap_windows(
    *,
    repo_root: Path,
    run_command: Callable[[list[str], Path | None], None] = _run_command,
) -> list[str]:
    """在 Windows 本地自举依赖并复制 DLL 到 _vendor 目录."""
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

    bin_dir = vcpkg_root / "installed" / "x64-windows" / "bin"
    if not bin_dir.exists():
        raise RuntimeError(f"vcpkg bin directory not found: {bin_dir}")

    _copy_required(bin_dir / "turbojpeg.dll", vendor_dir, "turbojpeg.dll")
    _copy_required(bin_dir / "jpeg62.dll", vendor_dir, "jpeg62.dll")
    _copy_required(bin_dir / "libwebp.dll", vendor_dir, "libwebp.dll")
    _copy_required(bin_dir / "libsharpyuv.dll", vendor_dir, "libsharpyuv.dll")
    _copy_required(bin_dir / "zlib1.dll", vendor_dir, "zlib1.dll")

    libpng_candidates = sorted(bin_dir.glob("libpng*.dll"))
    if not libpng_candidates:
        raise RuntimeError("Required dynamic library not found: libpng*.dll")
    libpng_primary = libpng_candidates[0]
    shutil.copy2(libpng_primary, vendor_dir / libpng_primary.name)
    if not (vendor_dir / "libpng16-16.dll").exists():
        shutil.copy2(libpng_primary, vendor_dir / "libpng16-16.dll")
    if not (vendor_dir / "libpng16.dll").exists():
        shutil.copy2(libpng_primary, vendor_dir / "libpng16.dll")

    return sorted(path.name for path in vendor_dir.glob("*.dll"))
