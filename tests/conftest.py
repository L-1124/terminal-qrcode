"""测试公共夹具."""

import pytest


def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """强制测试纪律：禁止在类中定义测试."""
    _ = session
    _ = config
    invalid_items: list[pytest.Item] = []
    for item in items:
        if isinstance(item.parent, pytest.Class):
            invalid_items.append(item)

    if invalid_items:
        paths = {item.nodeid for item in invalid_items}
        pytest.fail(
            f"Testing discipline violation: Tests must not be defined within classes. "
            f"Found {len(invalid_items)} violating tests in {paths}"
        )


@pytest.fixture(autouse=True)
def _intercept_unmocked_tty_ops(monkeypatch):
    """拦截未经 mock 的 tty 和控制台底层操作，防止测试泄漏和终端环境污染."""
    import shutil
    import sys
    import types

    original_get_terminal_size = shutil.get_terminal_size

    # 确保测试期间已正确 mock get_terminal_size，除非明确允许
    def _block_get_terminal_size(*args, **kwargs):
        # 允许 pytest 和 argparse 内部调用
        frame: types.FrameType | None = sys._getframe(1)
        # 向上查找调用栈中的 pytest 或 argparse 内部调用
        for _ in range(5):
            if frame is None:
                break
            filename = frame.f_code.co_filename
            funcname = frame.f_code.co_name
            if "_pytest" in filename or "pytest" in funcname or "argparse.py" in filename:
                return original_get_terminal_size(*args, **kwargs)
            frame = frame.f_back

        pytest.fail("检测到未被 mock 的 shutil.get_terminal_size 调用！测试可能泄漏环境变量或依赖物理中断.")

    monkeypatch.setattr(shutil, "get_terminal_size", _block_get_terminal_size)

    # 有些测试合理的需要 os.isatty 等类似方法，但我们目前拦截 shutil.get_terminal_size
    # 确保布局算法与绘制结果在测试集中百分之百确定。

    # 让 layout 模块直接继承拦截钩子，如果未在测试中局部 mock 则也直接报错
    from terminal_qrcode import _layout

    monkeypatch.setattr(_layout, "get_terminal_size", _block_get_terminal_size)
