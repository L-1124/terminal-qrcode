"""终端能力探测测试."""

import contextlib
import os
from unittest.mock import patch

import pytest

from terminal_qrcode import draw
from terminal_qrcode.contracts import TerminalCapability, TerminalColorLevel
from terminal_qrcode.probe import TerminalProbe


@pytest.fixture(autouse=True)
def _mock_terminal_size(monkeypatch):
    from terminal_qrcode import layout

    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((80, 24)))


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """每个测试前清理 probe 缓存，避免跨用例污染."""
    TerminalProbe._cache = None
    TerminalProbe._color_cache = None
    TerminalProbe._capabilities_cache = None


@patch.dict("os.environ", {"NO_COLOR": "1"}, clear=True)
@patch("sys.stdout")
def test_probe_color_respects_no_color(mock_stdout):
    """验证 NO_COLOR 会强制关闭文本颜色输出."""
    mock_stdout.isatty.return_value = True
    probe = TerminalProbe()
    assert probe.probe_color() == TerminalColorLevel.NONE


@patch.dict("os.environ", {"FORCE_COLOR": "3"}, clear=True)
@patch("sys.stdout")
def test_probe_color_force_truecolor(mock_stdout):
    """验证 FORCE_COLOR=3 会强制 truecolor 等级."""
    mock_stdout.isatty.return_value = True
    probe = TerminalProbe()
    assert probe.probe_color() == TerminalColorLevel.TRUECOLOR


@patch.dict("os.environ", {"COLORTERM": "truecolor"}, clear=True)
@patch("sys.stdout")
def test_probe_color_colorterm_truecolor(mock_stdout):
    """验证 COLORTERM=truecolor 会判定为 truecolor."""
    mock_stdout.isatty.return_value = True
    probe = TerminalProbe()
    assert probe.probe_color() == TerminalColorLevel.TRUECOLOR


@patch.dict("os.environ", {"TERM": "xterm-256color"}, clear=True)
@patch("sys.stdout")
def test_probe_color_term_256(mock_stdout):
    """验证 TERM 含 256color 时判定为 ansi256."""
    mock_stdout.isatty.return_value = True
    probe = TerminalProbe()
    assert probe.probe_color() == TerminalColorLevel.ANSI256


@patch.dict("os.environ", {"TERM": "screen"}, clear=True)
@patch("sys.stdout")
def test_probe_color_term_prefix_ansi256(mock_stdout):
    """验证常见 TERM 前缀默认升级为 ansi256 以避免 16 色不稳定."""
    mock_stdout.isatty.return_value = True
    probe = TerminalProbe()
    assert probe.probe_color() == TerminalColorLevel.ANSI256


@patch.dict("os.environ", {"TERM": "dumb"}, clear=True)
@patch("sys.stdout")
def test_probe_color_term_dumb(mock_stdout):
    """验证 TERM=dumb 会回退为无颜色等级."""
    mock_stdout.isatty.return_value = True
    probe = TerminalProbe()
    assert probe.probe_color() == TerminalColorLevel.NONE


@patch("sys.stdout")
def test_probe_color_requires_stdout_tty(mock_stdout):
    """验证非 TTY 输出时文本颜色探测回退为 NONE."""
    mock_stdout.isatty.return_value = False
    probe = TerminalProbe()
    assert probe.probe_color() == TerminalColorLevel.NONE


@patch.dict("os.environ", {"TERM": "xterm-256color"}, clear=True)
@patch("sys.stdout")
def test_probe_color_cached_after_first_call(mock_stdout):
    """验证颜色探测会命中缓存避免重复判定."""
    mock_stdout.isatty.return_value = True
    probe = TerminalProbe()
    assert probe.probe_color() == TerminalColorLevel.ANSI256
    assert probe.probe_color() == TerminalColorLevel.ANSI256


@patch("sys.stdout")
@patch("sys.stdin")
@patch("select.select")
@patch("terminal_qrcode.probe.sys.platform", "linux")
def test_probe_timeout(mock_select, mock_stdin, mock_stdout):
    """验证终端探测在超时时能够正确回退到基础能力."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True
    mock_stdin.fileno.return_value = 0
    mock_select.return_value = ([], [], [])

    probe = TerminalProbe()
    cap = probe.probe(timeout=0.01)

    assert cap == TerminalCapability.FALLBACK
    assert mock_stdout.write.called


@patch("terminal_qrcode.probe.TerminalProbe.probe")
def test_draw_short_circuit(mock_probe):
    """验证强制指定渲染器时会绕过自动探测."""
    size = 21
    matrix = [[False for _ in range(size)] for _ in range(size)]

    def _add_finder(ox: int, oy: int) -> None:
        for y in range(7):
            for x in range(7):
                if x in (0, 6) or y in (0, 6):
                    matrix[oy + y][ox + x] = True
                elif x in (1, 5) or y in (1, 5):
                    matrix[oy + y][ox + x] = False
                else:
                    matrix[oy + y][ox + x] = True

    _add_finder(0, 0)
    _add_finder(size - 7, 0)
    _add_finder(0, size - 7)
    result = "".join(draw(matrix, renderer="halfblock"))
    assert not mock_probe.called
    assert any(c in result for c in ("▄", "▀", "█", " "))


@patch("terminal_qrcode.probe.sys.platform", "win32")
@patch("terminal_qrcode.probe.TerminalProbe._query_terminal")
def test_probe_win32_short_circuit(mock_query):
    """验证 Windows 平台不会调用交互式查询路径."""
    probe = TerminalProbe()
    cap = probe.probe(timeout=0.01)

    assert cap == TerminalCapability.FALLBACK
    assert not mock_query.called


@patch("sys.stdout")
@patch("sys.stdin")
@patch("select.select")
@patch("terminal_qrcode.probe.sys.platform", "linux")
def test_query_terminal_ignores_dirty_prefix(mock_select, mock_stdin, mock_stdout):
    """验证终端查询会忽略前导脏字节并锚定 ESC 开头响应."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True
    mock_stdin.fileno.return_value = 0
    mock_select.side_effect = [([mock_stdin], [], [])] * 20 + [([], [], [])]
    mock_stdin.read.side_effect = list("abc\x1b[?62;4;6c")

    probe = TerminalProbe()
    response = probe._query_terminal("\x1b[c", timeout=0.05)

    assert response == "\x1b[?62;4;6c"
    assert mock_stdout.write.called


@patch("terminal_qrcode.probe.TerminalProbe._query_terminal")
@patch("terminal_qrcode.probe.TerminalProbe._raw_mode")
@patch("sys.stdin")
def test_probe_da1_retry_recovers_from_dirty_read(mock_stdin, mock_raw_mode, mock_query_terminal):
    """验证 DA1 首次受脏数据干扰时会重试并识别 Sixel 能力."""
    mock_stdin.isatty.return_value = True
    with patch("sys.stdout") as mock_stdout:
        mock_stdout.isatty.return_value = True
        mock_raw_mode.return_value = contextlib.nullcontext()
        mock_query_terminal.side_effect = [
            "",
            "",
            "xx",
            "\x1b[?62;4;6c",
        ]

        probe = TerminalProbe()
        cap = probe.probe(timeout=0.5)

    assert cap == TerminalCapability.SIXEL


@patch("terminal_qrcode.probe.TerminalProbe._query_terminal")
def test_retry_skips_when_empty_response(mock_query):
    """验证空响应不会触发二次重试."""
    mock_query.return_value = ""
    probe = TerminalProbe()
    assert probe._query_terminal_retry("x", 0.1, remaining_budget=0.05) == ""
    assert mock_query.call_count == 1


@patch("terminal_qrcode.probe.TerminalProbe._query_terminal")
def test_retry_only_on_dirty_prefix(mock_query):
    """验证脏数据会触发一次短重试."""
    mock_query.side_effect = ["dirty", "\x1b[?62;4c"]
    probe = TerminalProbe()
    out = probe._query_terminal_retry("x", 0.1, remaining_budget=0.05)
    assert out == "\x1b[?62;4c"
    assert mock_query.call_count == 2


@patch("terminal_qrcode.probe.TerminalProbe._query_terminal_retry")
@patch("terminal_qrcode.probe.TerminalProbe._raw_mode")
@patch("sys.stdout")
@patch("sys.stdin")
def test_probe_stops_when_budget_exhausted(mock_stdin, mock_stdout, mock_raw_mode, mock_retry):
    """验证预算耗尽时不进入后续探测步骤."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True
    mock_raw_mode.return_value = contextlib.nullcontext()
    mock_retry.return_value = ""

    probe = TerminalProbe()
    with patch.object(probe, "_budget_seconds", return_value=0.0):
        cap = probe.probe(timeout=0.01)
    assert cap == TerminalCapability.FALLBACK
    assert mock_retry.call_count == 0


@patch("sys.stdout")
@patch("sys.stdin")
def test_probe_requires_stdin_and_stdout_tty_for_interactive(mock_stdin, mock_stdout):
    """验证交互探测要求 stdin/stdout 同时为 TTY."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = False
    probe = TerminalProbe()
    cap = probe.probe(timeout=0.01)
    assert cap == TerminalCapability.FALLBACK


@patch.dict("os.environ", {"TERM_FEATURES": "F Sx"}, clear=False)
def test_probe_term_features_env_file_wins_inline():
    """验证 TERM_FEATURES 包含 F 时优先判定为 inline image 能力."""
    probe = TerminalProbe()
    assert probe.probe(timeout=0.01) == TerminalCapability.ITERM2


@patch.dict("os.environ", {"TERM_FEATURES": "Sx"}, clear=False)
def test_probe_term_features_env_sixel_only():
    """验证 TERM_FEATURES 仅含 Sx 时判定为 Sixel."""
    probe = TerminalProbe()
    assert probe.probe(timeout=0.01) == TerminalCapability.SIXEL


@patch("terminal_qrcode.probe.TerminalProbe._query_capabilities")
@patch("sys.stdin")
def test_probe_capabilities_query_parsing(mock_stdin, mock_query):
    """验证 Capabilities 查询结果可解析为 inline image 能力."""
    mock_stdin.isatty.return_value = True
    with patch("sys.stdout") as mock_stdout:
        mock_stdout.isatty.return_value = True
        mock_query.return_value = "\x1b]1337;Capabilities=F Sx\x07"
        probe = TerminalProbe()
        assert probe.probe(timeout=0.2) == TerminalCapability.ITERM2


@patch("terminal_qrcode.probe.TerminalProbe._query_terminal_retry")
@patch("terminal_qrcode.probe.TerminalProbe._raw_mode")
@patch("sys.stdout")
@patch("sys.stdin")
def test_probe_single_shot_then_optional_upgrade_with_remaining_budget(
    mock_stdin, mock_stdout, mock_raw_mode, mock_retry
):
    """验证会先做单次探测，并在有剩余预算时升级后续探测."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True
    mock_raw_mode.return_value = contextlib.nullcontext()
    mock_retry.side_effect = ["", "\x1b]1337;Capabilities=F\x07"]

    probe = TerminalProbe()
    cap = probe.probe(timeout=0.2)
    assert cap == TerminalCapability.ITERM2
    assert mock_retry.call_count >= 2


@patch.dict("os.environ", {}, clear=True)
@patch("sys.stdin")
def test_probe_conservative_fallback_without_strong_signal(mock_stdin):
    """验证缺少强证据时保守回退为 FALLBACK."""
    mock_stdin.isatty.return_value = False
    probe = TerminalProbe()
    assert probe.probe(timeout=0.01) == TerminalCapability.FALLBACK


@patch.dict("os.environ", {"TMUX": "1"}, clear=False)
@patch("sys.stdout")
@patch("sys.stdin")
def test_probe_tmux_uses_conservative_policy(mock_stdin, mock_stdout):
    """验证 tmux 环境下使用保守探测预算策略."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True
    probe = TerminalProbe()
    assert probe._budget_seconds() == 0.02


@patch("terminal_qrcode.probe.TerminalProbe._query_terminal_retry")
@patch("terminal_qrcode.probe.TerminalProbe._raw_mode")
@patch("sys.stdout")
@patch("sys.stdin")
def test_probe_cached_after_first_call(mock_stdin, mock_stdout, mock_raw_mode, mock_retry):
    """验证探测结果会被缓存，避免重复阻塞探测."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True
    mock_raw_mode.return_value = contextlib.nullcontext()
    mock_retry.side_effect = ["\x1b_Gi=31;OK\x1b\\"]

    probe = TerminalProbe()
    assert probe.probe(timeout=0.2) == TerminalCapability.KITTY
    assert probe.probe(timeout=0.2) == TerminalCapability.KITTY
    assert mock_retry.call_count == 1


@patch.dict("os.environ", {"TERM": "xterm-256color"}, clear=True)
@patch("terminal_qrcode.probe.TerminalProbe.probe_color")
@patch("terminal_qrcode.probe.TerminalProbe.probe")
def test_capabilities_cached_after_first_call(mock_probe, mock_probe_color):
    """验证终端能力快照会整体缓存，避免重复组合探测."""
    mock_probe.return_value = TerminalCapability.FALLBACK
    mock_probe_color.return_value = TerminalColorLevel.ANSI256

    probe = TerminalProbe()
    first = probe.capabilities(timeout=0.2)
    second = probe.capabilities(timeout=0.2)

    assert first == second
    assert first.capability == TerminalCapability.FALLBACK
    assert first.color_level == TerminalColorLevel.ANSI256
    assert mock_probe.call_count == 1
    assert mock_probe_color.call_count == 1


@patch.dict("os.environ", {"TERM_PROGRAM": "WezTerm"}, clear=False)
@patch("terminal_qrcode.probe.TerminalProbe._query_terminal_retry")
@patch("sys.stdout")
@patch("sys.stdin")
def test_probe_wezterm_heuristic_bypasses_interactive(mock_stdin, mock_stdout, mock_retry):
    """验证 WezTerm 启发式会直接命中 inline image 并跳过交互探测."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True
    probe = TerminalProbe()
    assert probe.probe(timeout=0.2) == TerminalCapability.WEZTERM
    assert mock_retry.call_count == 0


@patch.dict("os.environ", {"TERM_PROGRAM": "WezTerm"}, clear=False)
@patch("terminal_qrcode.probe.TerminalProbe._query_terminal_retry")
@patch("sys.stdout")
@patch("sys.stdin")
def test_probe_wezterm_heuristic_requires_stdout_tty(mock_stdin, mock_stdout, mock_retry):
    """验证 WezTerm 启发式要求 stdout 为 TTY."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = False
    probe = TerminalProbe()
    assert probe.probe(timeout=0.05) == TerminalCapability.FALLBACK
    assert mock_retry.call_count == 0


@patch.dict("os.environ", {"TERM_PROGRAM": "WezTerm", "TMUX": "1"}, clear=False)
@patch("terminal_qrcode.probe.TerminalProbe._query_terminal_retry")
@patch("sys.stdout")
@patch("sys.stdin")
def test_probe_wezterm_heuristic_disabled_in_tmux(mock_stdin, mock_stdout, mock_retry):
    """验证 tmux 环境会禁用 WezTerm 启发式快路径."""
    mock_stdin.isatty.return_value = True
    mock_stdout.isatty.return_value = True
    mock_retry.return_value = ""
    probe = TerminalProbe()
    assert probe.probe(timeout=0.05) == TerminalCapability.FALLBACK
    assert mock_retry.call_count >= 1


@patch("terminal_qrcode.probe.sys.platform", "linux")
@patch("terminal_qrcode.probe.tty")
@patch("terminal_qrcode.probe.termios")
@patch("sys.stdin")
def test_raw_mode_noop_when_tcgetattr_fails(mock_stdin, mock_termios, mock_tty):
    """验证 tcgetattr 抛错时 _raw_mode 会降级为 no-op."""
    mock_stdin.isatty.return_value = True
    mock_stdin.fileno.return_value = 0
    mock_termios.error = OSError
    mock_termios.tcgetattr.side_effect = OSError("ioctl failed")

    probe = TerminalProbe()
    with probe._raw_mode():
        pass

    mock_tty.setcbreak.assert_not_called()
    mock_termios.tcsetattr.assert_not_called()


@patch("terminal_qrcode.probe.sys.platform", "linux")
@patch("terminal_qrcode.probe.tty")
@patch("terminal_qrcode.probe.termios")
@patch("sys.stdin")
def test_raw_mode_noop_when_fileno_raises_type_error(mock_stdin, mock_termios, mock_tty):
    """验证 fileno 抛 TypeError 时 _raw_mode 会降级为 no-op."""
    mock_stdin.isatty.return_value = True
    mock_stdin.fileno.side_effect = TypeError("bad fileno")

    probe = TerminalProbe()
    with probe._raw_mode():
        pass

    mock_termios.tcgetattr.assert_not_called()
    mock_tty.setcbreak.assert_not_called()
