"""CLI 入口参数解析测试."""

import pytest

from terminal_qrcode import DrawOutput
from terminal_qrcode.__main__ import main


def test_main_accepts_positional_image_path(monkeypatch, tmp_path, capsys):
    """验证 CLI 支持位置参数形式的图片路径."""
    path = tmp_path / "x.png"
    path.write_bytes(b"dummy")

    monkeypatch.setattr("sys.argv", ["terminal_qrcode", str(path), "-r", "halfblock"])
    monkeypatch.setattr("terminal_qrcode.__main__.draw", lambda *_args, **_kwargs: DrawOutput(["ok"]))

    main()
    out = capsys.readouterr().out
    assert "ok" in out


def test_main_rejects_when_no_image_arg(monkeypatch):
    """验证 CLI 在未提供任何图片参数时返回参数错误."""
    monkeypatch.setattr("sys.argv", ["terminal_qrcode"])
    with pytest.raises(SystemExit):
        main()


@pytest.mark.parametrize(
    ("extra_args", "expected_fit", "expected_max_cols"),
    [
        ([], True, None),
        (["--fit"], True, None),
        (["--no-fit"], False, None),
        (["--max-cols", "66"], True, 66),
    ],
)
def test_main_forwarding_core_flags(monkeypatch, tmp_path, extra_args, expected_fit, expected_max_cols):
    """验证 CLI 核心参数透传行为（fit/max-cols/img-width 默认值）."""
    path = tmp_path / "x.png"
    path.write_bytes(b"dummy")
    seen: dict[str, object] = {}

    def _fake_draw(*_args, **kwargs):
        seen.update(kwargs)
        return DrawOutput(["ok"])

    monkeypatch.setattr("sys.argv", ["terminal_qrcode", str(path), *extra_args])
    monkeypatch.setattr("terminal_qrcode.__main__.draw", _fake_draw)
    main()
    assert seen.get("fit") is expected_fit
    assert seen.get("max_cols") == expected_max_cols
    assert seen.get("img_width") is None


def test_main_accepts_data_option(monkeypatch, capsys):
    """验证 CLI 支持通过 --data 生成二维码."""
    seen: dict[str, object] = {}

    def _fake_generate(*args, **kwargs):
        seen["data"] = args[0]
        seen.update(kwargs)
        return DrawOutput(["ok-data"])

    monkeypatch.setattr("sys.argv", ["terminal_qrcode", "--data", "hello", "-r", "halfblock"])
    monkeypatch.setattr("terminal_qrcode.__main__.generate", _fake_generate)
    main()
    out = capsys.readouterr().out
    assert "ok-data" in out
    assert seen["data"] == "hello"
    assert seen["force_renderer"] == "halfblock"


def test_main_rejects_when_image_and_data_are_both_set(monkeypatch):
    """验证 CLI 同时传 image_path 和 --data 时返回参数错误."""
    monkeypatch.setattr("sys.argv", ["terminal_qrcode", "x.png", "--data", "hello"])
    with pytest.raises(SystemExit):
        main()
