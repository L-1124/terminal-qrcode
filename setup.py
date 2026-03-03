"""setuptools 构建入口，强制构建 C 扩展."""

import os
import sys
from pathlib import Path

from setuptools import Extension, setup


def _platform_libraries() -> list[str]:
    if sys.platform == "win32":
        return ["turbojpeg", "libpng16", "libwebp"]
    if sys.platform == "darwin":
        return ["turbojpeg", "png16", "webp"]
    return ["turbojpeg", "png16", "webp"]


def _vcpkg_paths() -> tuple[list[str], list[str]]:
    if sys.platform != "win32":
        return ([], [])

    triplet = os.environ.get("QRT_VCPKG_TRIPLET", "x64-windows")
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


_include_dirs, _library_dirs = _vcpkg_paths()

setup(
    ext_modules=[
        Extension(
            "terminal_qrcode._cimage",
            ["src/terminal_qrcode/_cimage.c"],
            libraries=_platform_libraries(),
            include_dirs=_include_dirs,
            library_dirs=_library_dirs,
        ),
    ],
)
