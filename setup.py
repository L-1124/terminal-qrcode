"""setuptools 构建入口，包含可选 C 扩展."""

from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext


class OptionalBuildExt(build_ext):
    """在编译失败时忽略 C 扩展，保持纯 Python 可安装."""

    def run(self) -> None:
        """执行 build_ext，并在失败时降级为纯 Python 包."""
        try:
            super().run()
        except Exception as exc:  # noqa: BLE001
            self.announce(f"Optional C extension build skipped: {exc}", level=2)

    def build_extension(self, ext: Extension) -> None:
        """编译单个扩展；失败时记录并继续构建流程."""
        try:
            super().build_extension(ext)
        except Exception as exc:  # noqa: BLE001
            self.announce(
                f"Optional extension '{ext.name}' failed: {exc}; falling back to pure Python.",
                level=2,
            )


setup(
    ext_modules=[
        Extension(
            "terminal_qrcode._cimage",
            ["src/terminal_qrcode/_cimage.c"],
        ),
    ],
    cmdclass={"build_ext": OptionalBuildExt},
)
