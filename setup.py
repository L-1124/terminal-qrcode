"""setuptools 构建入口."""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import Extension, setup


def _set_default_build_env() -> None:
    """为构建过程补齐默认环境变量路径."""
    repo_root = Path(__file__).resolve().parent
    if sys.platform == "win32":
        default_vcpkg_root = (repo_root / ".cache" / "bootstrap" / "vcpkg").resolve()
        os.environ.setdefault("QRT_VCPKG_ROOT", str(default_vcpkg_root))


def _split_paths(value: str) -> list[Path]:
    """拆分环境变量中的路径列表."""
    sep = ";" if sys.platform == "win32" else ":"
    return [Path(p.strip()) for p in value.split(sep) if p.strip()]


def _env_paths() -> tuple[list[Path], list[Path]]:
    """从环境变量获取 include/library 路径."""
    inc = os.environ.get("CIMAGE_INCLUDE_DIRS", "")
    lib = os.environ.get("CIMAGE_LIBRARY_DIRS", "")
    return _split_paths(inc), _split_paths(lib)


def _brew_paths() -> tuple[list[Path], list[Path]]:
    """检测 macOS brew 路径（含 keg-only 公式）."""
    include_dirs: list[Path] = []
    library_dirs: list[Path] = []

    def _brew_prefix(cmd: list[str]) -> Path | None:
        try:
            out = subprocess.check_output(cmd, text=True, timeout=5).strip()
            return Path(out) if out else None
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    if sys.platform == "darwin":
        prefix = _brew_prefix(["brew", "--prefix"])
        if prefix:
            include_dirs.append(prefix / "include")
            library_dirs.append(prefix / "lib")

        for formula in ("jpeg-turbo",):
            fprefix = _brew_prefix(["brew", "--prefix", formula])
            if fprefix:
                include_dirs.append(fprefix / "include")
                library_dirs.append(fprefix / "lib")

    return include_dirs, library_dirs


def _vcpkg_paths() -> tuple[list[Path], list[Path]]:
    """检测 Windows 本地 `.cache` 中的 vcpkg 路径."""
    include_dirs: list[Path] = []
    library_dirs: list[Path] = []

    if sys.platform == "win32":
        arch = platform.machine().lower()
        default_arch = "x86" if arch == "x86" else ("arm64" if arch == "arm64" else "x64")
        # 强制使用动态 CRT 的静态库三元组，规避 LNK2038 冲突
        default_triplet = f"{default_arch}-windows-static-md"

        triplet = os.environ.get("QRT_VCPKG_TRIPLET", default_triplet)
        root = Path(os.environ["QRT_VCPKG_ROOT"])
        installed = root / "installed" / triplet
        include_dirs = [installed / "include"]
        library_dirs = [installed / "lib"]

    return include_dirs, library_dirs


def _pkgconfig_paths() -> tuple[list[Path], list[Path]]:
    """通过 pkg-config 获取 Linux 系统路径."""
    includes: list[Path] = []
    libs: list[Path] = []

    if sys.platform == "linux" and shutil.which("pkg-config"):
        packages = ["libturbojpeg", "libpng", "libwebp", "zlib"]
        for pkg in packages:
            try:
                cflags = subprocess.check_output(
                    ["pkg-config", "--cflags-only-I", pkg], text=True, stderr=subprocess.DEVNULL
                ).strip()
                for flag in cflags.split():
                    if flag.startswith("-I"):
                        includes.append(Path(flag[2:]))

                libdir = subprocess.check_output(
                    ["pkg-config", "--variable=libdir", pkg], text=True, stderr=subprocess.DEVNULL
                ).strip()
                if libdir:
                    libs.append(Path(libdir))
            except subprocess.CalledProcessError:
                continue

    return includes, libs


def _linux_paths() -> tuple[list[Path], list[Path]]:
    """检测 Linux 系统硬编码路径（pkg-config 补充）."""
    includes: list[Path] = []
    libs: list[Path] = []

    if sys.platform == "linux":
        include_candidates = [
            "/usr/include",
            "/usr/local/include",
            "/usr/include/libjpeg-turbo",
            "/usr/local/include/libjpeg-turbo",
        ]
        library_candidates = [
            "/usr/lib64",
            "/usr/lib",
            "/usr/local/lib64",
            "/usr/local/lib",
        ]

        includes = [Path(p) for p in include_candidates if Path(p).is_dir()]
        libs = [Path(p) for p in library_candidates if Path(p).is_dir()]

    return includes, libs


def _get_target_lib_candidates() -> list[tuple[str, ...]]:
    """返回平台对应的依赖库候补名列表."""
    if sys.platform == "win32":
        return [
            ("turbojpeg", "jpeg"),
            ("libpng16", "libpng"),
            ("libwebp", "webp"),
            ("zlib", "z"),
        ]
    return [
        ("turbojpeg", "jpeg"),
        ("png16", "png"),
        ("webp",),
        ("z",),
    ]


def _resolve_directories() -> tuple[list[Path], list[Path]]:
    """合并各策略获取的目录并去重验证."""
    inc_env, lib_env = _env_paths()

    if sys.platform == "darwin":
        inc_pkg, lib_pkg = _brew_paths()
    elif sys.platform == "win32":
        inc_pkg, lib_pkg = _vcpkg_paths()
    else:
        inc_pc, lib_pc = _pkgconfig_paths()
        inc_os, lib_os = _linux_paths()
        inc_pkg = inc_pc + inc_os
        lib_pkg = lib_pc + lib_os

    all_includes = inc_env + inc_pkg
    all_libs = lib_env + lib_pkg

    valid_includes = list(dict.fromkeys(p for p in all_includes if p.is_dir()))
    valid_libs = list(dict.fromkeys(p for p in all_libs if p.is_dir()))

    return valid_includes, valid_libs


def _find_static_objects(library_dirs: list[Path], lib_candidates: list[tuple[str, ...]]) -> list[str]:
    """Windows 平台检索静态库，非 Windows 平台返回空."""
    is_win = sys.platform == "win32"

    # 非 Windows 平台使用动态链接，不返回静态库
    if not is_win:
        return []

    static_objects: list[str] = []

    for candidates in lib_candidates:
        found_path: Path | None = None

        for name in candidates:
            filename = f"{name}.lib"
            for lib_dir in library_dirs:
                candidate_path = lib_dir / filename
                if candidate_path.is_file():
                    found_path = candidate_path
                    break
            if found_path:
                break

        if not found_path:
            raise FileNotFoundError(
                f"Static library for {candidates} not found in directories: {[str(p) for p in library_dirs]}"
            )
        static_objects.append(str(found_path))

    return static_objects


def _get_library_names(lib_candidates: list[tuple[str, ...]]) -> list[str]:
    """为非 Windows 平台生成动态链接库名列表."""
    if sys.platform == "win32":
        return []

    # 使用第一个候补名作为链接目标
    return [candidates[0] for candidates in lib_candidates]


def _get_compiler_configs() -> tuple[list[tuple[str, str | None]], list[str]]:
    """获取平台相关的编译宏与编译参数."""
    macros: list[tuple[str, str | None]] = [("NDEBUG", None)]
    compile_args: list[str] = []

    if sys.platform == "win32":
        macros.extend(
            [
                ("WIN32_LEAN_AND_MEAN", None),
                ("_CRT_SECURE_NO_WARNINGS", None),
            ]
        )
        compile_args.extend(["/O2", "/W3", "/MD"])
    else:
        compile_args.extend(["-O3", "-Wall", "-Wextra"])

    return macros, compile_args


_set_default_build_env()
_include_dirs_path, _library_dirs_path = _resolve_directories()
_include_dirs = [str(p) for p in _include_dirs_path]
_library_dirs = [str(p) for p in _library_dirs_path]
_lib_candidates = _get_target_lib_candidates()
_extra_objects = _find_static_objects(_library_dirs_path, _lib_candidates)  # Windows 静态库
_libraries = _get_library_names(_lib_candidates)  # Linux/macOS 动态链接库名
_macros, _compile_args = _get_compiler_configs()

setup(
    ext_modules=[
        Extension(
            "terminal_qrcode._cimage",
            ["src/terminal_qrcode/_cimage.c"],
            include_dirs=_include_dirs,
            library_dirs=_library_dirs,
            extra_objects=_extra_objects,
            libraries=_libraries,
            define_macros=_macros,
            extra_compile_args=_compile_args,
            extra_link_args=[],
        ),
    ],
)
