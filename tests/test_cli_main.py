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


def test_main_accepts_fit_flags(monkeypatch, tmp_path):
    """验证 CLI 支持 --fit/--no-fit 选项并正确透传 draw."""
    path = tmp_path / "x.png"
    path.write_bytes(b"dummy")
    seen: dict[str, object] = {}

    def _fake_draw(*_args, **kwargs):
        seen.update(kwargs)
        return DrawOutput(["ok"])

    monkeypatch.setattr("sys.argv", ["terminal_qrcode", str(path), "--no-fit"])
    monkeypatch.setattr("terminal_qrcode.__main__.draw", _fake_draw)
    main()
    assert seen.get("fit") is False


def test_main_accepts_max_cols(monkeypatch, tmp_path):
    """验证 CLI 支持 --max-cols 并正确透传 draw."""
    path = tmp_path / "x.png"
    path.write_bytes(b"dummy")
    seen: dict[str, object] = {}

    def _fake_draw(*_args, **kwargs):
        seen.update(kwargs)
        return DrawOutput(["ok"])

    monkeypatch.setattr("sys.argv", ["terminal_qrcode", str(path), "--max-cols", "66"])
    monkeypatch.setattr("terminal_qrcode.__main__.draw", _fake_draw)
    main()
    assert seen.get("max_cols") == 66


def test_img_width_default_none(monkeypatch, tmp_path):
    """验证 CLI 未指定 --img-width 时会透传 None."""
    path = tmp_path / "x.png"
    path.write_bytes(b"dummy")
    seen: dict[str, object] = {}

    def _fake_draw(*_args, **kwargs):
        seen.update(kwargs)
        return DrawOutput(["ok"])

    monkeypatch.setattr("sys.argv", ["terminal_qrcode", str(path)])
    monkeypatch.setattr("terminal_qrcode.__main__.draw", _fake_draw)
    main()
    assert seen.get("img_width") is None


def test_fit_true_without_img_width_not_capped_by_40(monkeypatch, tmp_path):
    """验证 CLI fit=True 且未指定 --img-width 时不会注入 40."""
    path = tmp_path / "x.png"
    path.write_bytes(b"dummy")
    seen: dict[str, object] = {}

    def _fake_draw(*_args, **kwargs):
        seen.update(kwargs)
        return DrawOutput(["ok"])

    monkeypatch.setattr("sys.argv", ["terminal_qrcode", str(path), "--fit"])
    monkeypatch.setattr("terminal_qrcode.__main__.draw", _fake_draw)
    main()
    assert seen.get("fit") is True
    assert seen.get("img_width") is None


def test_fit_false_with_no_img_width_uses_40_default(monkeypatch, tmp_path):
    """验证 CLI fit=False 且未指定 --img-width 时由内核走默认 40 语义."""
    path = tmp_path / "x.png"
    path.write_bytes(b"dummy")
    seen: dict[str, object] = {}

    def _fake_draw(*_args, **kwargs):
        seen.update(kwargs)
        return DrawOutput(["ok"])

    monkeypatch.setattr("sys.argv", ["terminal_qrcode", str(path), "--no-fit"])
    monkeypatch.setattr("terminal_qrcode.__main__.draw", _fake_draw)
    main()
    assert seen.get("fit") is False
    assert seen.get("img_width") is None
