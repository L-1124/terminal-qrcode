"""setuptools 构建入口，强制构建 C 扩展."""

import os
import sys
from pathlib import Path

from setuptools import Extension, setup


def _split_paths(value: str) -> list[str]:
    """拆分环境变量中的路径列表."""
    sep = ";" if sys.platform == "win32" else ":"
    return [p.strip() for p in value.split(sep) if p.strip()]


def _env_paths() -> tuple[list[str], list[str]]:
    """从环境变量获取 include/library 路径（CI 使用）."""
    include_dirs: list[str] = []
    library_dirs: list[str] = []
    inc = os.environ.get("CIMAGE_INCLUDE_DIRS", "")
    lib = os.environ.get("CIMAGE_LIBRARY_DIRS", "")
    if inc:
        include_dirs.extend(_split_paths(inc))
    if lib:
        library_dirs.extend(_split_paths(lib))
    return include_dirs, library_dirs


def _brew_paths() -> tuple[list[str], list[str]]:
    """MacOS brew 路径检测（含 keg-only 公式."""
    include_dirs: list[str] = []
    library_dirs: list[str] = []
    if sys.platform == "darwin":
        import subprocess

        def _brew_prefix(cmd: list[str]) -> str:
            try:
                return subprocess.check_output(cmd, text=True).strip()
            except (FileNotFoundError, subprocess.CalledProcessError):
                return ""

        prefix = _brew_prefix(["brew", "--prefix"])
        if not prefix:
            return ([], [])
        include_dirs.append(os.path.join(prefix, "include"))
        library_dirs.append(os.path.join(prefix, "lib"))
        # jpeg-turbo 是 keg-only，需要显式添加路径
        for formula in ("jpeg-turbo",):
            fprefix = _brew_prefix(["brew", "--prefix", formula])
            if not fprefix:
                continue
            inc = os.path.join(fprefix, "include")
            lib = os.path.join(fprefix, "lib")
            if os.path.isdir(inc):
                include_dirs.append(inc)
            if os.path.isdir(lib):
                library_dirs.append(lib)
    return include_dirs, library_dirs


def _vcpkg_paths() -> tuple[list[str], list[str]]:
    """Windows 本地开发 vcpkg 路径检测."""
    if sys.platform != "win32":
        return ([], [])
    triplet = os.environ.get("QRT_VCPKG_TRIPLET", "x64-windows-static")
    root = Path(os.environ.get("QRT_VCPKG_ROOT", ".cache/bootstrap/vcpkg"))
    installed = root / "installed" / triplet
    include_dir = installed / "include"
    lib_dir = installed / "lib"
    include_dirs: list[str] = []
    library_dirs: list[str] = []
    if include_dir.exists():
        include_dirs.append(str(include_dir))
    if lib_dir.exists():
        library_dirs.append(str(lib_dir))
    return include_dirs, library_dirs


def _linux_paths() -> tuple[list[str], list[str]]:
    """Linux 系统路径检测（manylinux 下常见子目录）."""
    if sys.platform != "linux":
        return ([], [])
    include_candidates = [
        "/usr/include",
        "/usr/local/include",
        "/usr/include/libjpeg-turbo",
        "/usr/local/include/libjpeg-turbo",
        "/usr/include/libpng15",
        "/usr/include/libpng16",
    ]
    library_candidates = [
        "/usr/lib64",
        "/usr/lib",
        "/usr/local/lib64",
        "/usr/local/lib",
    ]
    include_dirs = [path for path in include_candidates if os.path.isdir(path)]
    library_dirs = [path for path in library_candidates if os.path.isdir(path)]
    return include_dirs, library_dirs


def _platform_libraries() -> list[str]:
    """返回平台对应的链接库名列表."""
    if sys.platform == "win32":
        return ["turbojpeg", "libpng16", "libwebp", "zlib"]
    return ["turbojpeg", "png", "webp"]


def _windows_static_libraries() -> list[str]:
    """返回 Windows 静态链接库名列表."""
    return ["turbojpeg", "libpng16", "libwebp", "zlib"]


def _resolve_paths() -> tuple[list[str], list[str]]:
    """按优先级解析 include/library 路径."""
    # 1. 环境变量（最高优先级，CI 使用）
    inc, lib = _env_paths()
    if inc or lib:
        return inc, lib
    # 2. brew 检测（macOS）
    inc, lib = _brew_paths()
    if inc or lib:
        return inc, lib
    # 3. vcpkg 检测（Windows 本地开发）
    inc, lib = _vcpkg_paths()
    if inc or lib:
        return inc, lib
    # 4. Linux 系统路径检测（manylinux）
    return _linux_paths()


_include_dirs, _library_dirs = _resolve_paths()

setup(
    ext_modules=[
        Extension(
            "terminal_qrcode._cimage",
            ["src/terminal_qrcode/_cimage.c"],
            libraries=(_windows_static_libraries() if sys.platform == "win32" else _platform_libraries()),
            include_dirs=_include_dirs,
            library_dirs=_library_dirs,
            extra_link_args=[],
        ),
    ],
)
