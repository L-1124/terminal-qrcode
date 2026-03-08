"""Wheel smoke validator for C extension availability."""

import argparse
import glob
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
import venv
from pathlib import Path


def _wheel_platform_tags(path: Path) -> set[str]:
    """从 wheel 文件名提取平台 tag 列表."""
    stem = path.stem
    try:
        _dist_and_ver, _py_tag, _abi_tag, platform_tags = stem.rsplit("-", 3)
    except ValueError:
        return set()
    return {tag.lower() for tag in platform_tags.split(".")}


def _is_host_compatible_wheel(path: Path) -> bool:
    """判断 wheel 是否与当前宿主平台兼容."""
    wheel_tags = _wheel_platform_tags(path)
    if not wheel_tags:
        return False

    platform_tag = sysconfig.get_platform().replace("-", "_").replace(".", "_").lower()

    if os.name == "nt":
        if platform_tag.endswith("amd64"):
            return "win_amd64" in wheel_tags
        if platform_tag.endswith("arm64"):
            return "win_arm64" in wheel_tags
        return "win32" in wheel_tags

    if sys.platform == "linux":
        if platform_tag.endswith("x86_64"):
            arch = "x86_64"
        elif platform_tag.endswith("aarch64"):
            arch = "aarch64"
        elif platform_tag.endswith("i686") or platform_tag.endswith("i386"):
            arch = "i686"
        else:
            return False
        return any(
            (wheel_tag.startswith("manylinux") or wheel_tag.startswith("linux_")) and wheel_tag.endswith(f"_{arch}")
            for wheel_tag in wheel_tags
        )

    if sys.platform == "darwin":
        if platform_tag.endswith("arm64"):
            return any(
                wheel_tag.startswith("macosx_") and wheel_tag.endswith(("arm64", "universal2"))
                for wheel_tag in wheel_tags
            )
        return any(
            wheel_tag.startswith("macosx_") and wheel_tag.endswith(("x86_64", "universal2")) for wheel_tag in wheel_tags
        )

    return False


def _supported_wheels(wheel_glob: str) -> list[str]:
    wheels = sorted(glob.glob(wheel_glob))
    if not wheels:
        raise SystemExit("No wheel file found in wheelhouse/")
    interp_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    return [
        wheel
        for wheel in wheels
        if re.search(rf"-{interp_tag}-{interp_tag}-", Path(wheel).name) and _is_host_compatible_wheel(Path(wheel))
    ]


def _smoke_code() -> str:
    return "\n".join(
        [
            "from terminal_qrcode.simple_image import SimpleImage",
            "from terminal_qrcode import codecs",
            "",
            "png = SimpleImage.new('RGB', (1, 1), (1, 2, 3)).to_png_bytes()",
            "mode, width, height, data = codecs.decode_png_with_libpng(png)",
            "if mode != 'RGB' or width != 1 or height != 1 or len(data) != 3:",
            "    raise SystemExit('PNG C backend smoke test failed')",
            "",
            "for name in ['decode_jpeg_rgb', 'decode_webp_rgba']:",
            "    if not hasattr(codecs, name):",
            "        raise SystemExit(f'missing API: {name}')",
            "",
            "print('C extension smoke test passed.')",
        ]
    )


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def main() -> int:
    """Run wheel smoke validation for current interpreter tag."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-glob", default="wheelhouse/*.whl")
    args = parser.parse_args()

    supported = _supported_wheels(args.wheel_glob)
    interp_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    if not supported:
        host_platform = sysconfig.get_platform()
        print(
            f"No wheel matching interpreter tag {interp_tag} and host platform {host_platform}; skip smoke validation."
        )  # noqa: T201
        return 0

    code = _smoke_code()
    for wheel_path in supported:
        venv_dir = Path(tempfile.mkdtemp(prefix="tq-check-"))
        venv.create(venv_dir, with_pip=True, clear=True)
        py = _venv_python(venv_dir)

        subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([str(py), "-m", "pip", "install", wheel_path], check=True)
        subprocess.run([str(py), "-c", code], check=True)
        print(f"C extension smoke test passed for {wheel_path}")  # noqa: T201

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
