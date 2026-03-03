"""终端能力探测模块, 用于检测当前终端是否支持特定的图形协议."""

import contextlib
import logging
import os
import re
import select
import sys
import time
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from terminal_qrcode.core import TerminalCapability

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    termios: Any | None = None
    tty: Any | None = None
    msvcrt: Any | None
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
else:
    import termios
    import tty

    msvcrt: Any | None = None

_PROBE_TOTAL_BUDGET_MS = 80
_TMUX_PROBE_BUDGET_MS = 20
_STEP_TIMEOUT_KITTY_MS = 25
_STEP_TIMEOUT_CAP_MS = 25
_STEP_TIMEOUT_DA1_MS = 20
_RETRY_TIMEOUT_MS = 10


@dataclass(frozen=True)
class _ProbeCache:
    key: tuple[object, ...]
    capability: TerminalCapability
    probe_source: str
    elapsed_ms: float


class TerminalProbe:
    """终端能力探测器."""

    _cache: _ProbeCache | None = None

    @staticmethod
    def _parse_term_features(features: str) -> tuple[bool, bool]:
        """解析 feature string，提取 inline-file(F) 与 sixel(Sx) 能力位."""
        tokens = [t for t in re.split(r"[,\s;]+", features) if t]
        has_file = "F" in tokens
        has_sixel = "Sx" in tokens
        return has_file, has_sixel

    @staticmethod
    def _capability_from_feature_flags(has_file: bool, has_sixel: bool) -> TerminalCapability | None:
        """将 Feature Reporting 能力位映射为终端能力枚举."""
        if has_file:
            program = os.environ.get("TERM_PROGRAM", "").lower()
            if "wezterm" in program:
                return TerminalCapability.WEZTERM
            return TerminalCapability.ITERM2
        if has_sixel:
            return TerminalCapability.SIXEL
        return None

    def _probe_term_features_env(self) -> TerminalCapability | None:
        """优先读取 TERM_FEATURES 环境变量进行强判定."""
        feature_string = os.environ.get("TERM_FEATURES", "").strip()
        if not feature_string:
            return None
        has_file, has_sixel = self._parse_term_features(feature_string)
        cap = self._capability_from_feature_flags(has_file, has_sixel)
        logger.debug(
            "Feature probe (env): has_F=%s has_Sx=%s source=term_features_env",
            has_file,
            has_sixel,
        )
        return cap

    def _query_capabilities(self, timeout: float, *, remaining_budget: float | None = None) -> str:
        """发送 iTerm2 Feature Reporting Capabilities 查询."""
        return self._query_terminal_retry("\x1b]1337;Capabilities\x07", timeout, remaining_budget=remaining_budget)

    def _probe_term_features_query(
        self, timeout: float, *, remaining_budget: float | None = None
    ) -> TerminalCapability | None:
        """通过 Capabilities 响应进行强判定."""
        response = self._query_capabilities(timeout, remaining_budget=remaining_budget)
        if not response:
            return None
        match = re.search(r"Capabilities=([^\x07\x1b\\]+)", response)
        if not match:
            return None
        has_file, has_sixel = self._parse_term_features(match.group(1))
        cap = self._capability_from_feature_flags(has_file, has_sixel)
        logger.debug(
            "Feature probe (query): has_F=%s has_Sx=%s source=capabilities_query",
            has_file,
            has_sixel,
        )
        return cap

    @contextlib.contextmanager
    def _raw_mode(self) -> Generator[None, None, None]:
        """进入 TTY 原始模式的上下文管理器."""
        if not sys.stdin.isatty():
            yield
            return

        if sys.platform == "win32":
            yield
            return

        if termios is not None and tty is not None:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                yield
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return
        yield

    def _query_terminal(self, query: str, timeout: float) -> str:
        """向终端发送查询序列并读取响应, 受全局严格超时控制."""
        if not sys.stdin.isatty():
            return ""

        # 清除输入缓冲区
        if sys.platform != "win32":
            try:
                if termios is not None:
                    termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except Exception:  # noqa: BLE001
                pass
        else:
            try:
                if msvcrt is not None:
                    while msvcrt.kbhit():
                        msvcrt.getch()
            except Exception:  # noqa: BLE001
                pass

        sys.stdout.write(query)
        sys.stdout.flush()

        start_time = time.monotonic()
        stdin = sys.stdin

        if sys.platform == "win32" and msvcrt is not None:
            res_bytes = bytearray()
            started = False
            while time.monotonic() - start_time < timeout:
                if msvcrt.kbhit():
                    char = msvcrt.getch()
                    if not started:
                        if char == b"\x1b":
                            started = True
                            res_bytes.clear()
                            res_bytes.extend(char)
                    else:
                        res_bytes.extend(char)
                    # 常见结束符: c (DA), \ (ST), BEL (\x07)
                    if started and char in (b"c", b"\\", b"\x07"):
                        break
                else:
                    # 极短暂休眠防止 CPU 占用率飙升到 100%
                    time.sleep(0.005)
            return res_bytes.decode("ascii", errors="ignore")

        response = ""
        started = False
        while True:
            # 计算绝对剩余时间, 阻断慢速响应的累加效应
            elapsed = time.monotonic() - start_time
            remaining = timeout - elapsed

            if remaining <= 0:
                break

            # select 此时使用动态收缩的剩余时间
            rlist, _, _ = select.select([stdin], [], [], remaining)
            if not rlist:
                break

            char = stdin.read(1)
            if not started:
                if char == "\x1b":
                    started = True
                    response = char
            else:
                response += char
            # 常见结束符: c (DA), \ (ST), BEL (\x07)
            if started and char in ("c", "\\", "\x07"):
                break
        return response

    def _query_terminal_retry(self, query: str, timeout: float, *, remaining_budget: float | None = None) -> str:
        """发送查询并重试一次以降低脏数据和慢链路导致的偶发误判."""
        first = self._query_terminal(query, timeout)
        if first.startswith("\x1b"):
            return first

        if first == "":
            return ""

        if first:
            logger.debug(f"Probe got non-control response, retrying once: {repr(first)}")

        retry_timeout = _RETRY_TIMEOUT_MS / 1000.0
        if remaining_budget is not None:
            retry_timeout = min(retry_timeout, max(0.0, remaining_budget))
        if retry_timeout <= 0:
            return ""
        return self._query_terminal(query, retry_timeout)

    @staticmethod
    def _is_sixel_da1(response: str) -> bool:
        """判断响应是否为包含 Sixel 能力位(4)的 DA1 报文."""
        match = re.match(r"^\x1b\[\??([0-9;]+)c$", response)
        if not match:
            return False
        return "4" in match.group(1).split(";")

    @staticmethod
    def _supports_interactive_probe() -> bool:
        """交互探测要求 stdin/stdout 都是 TTY."""
        return sys.stdin.isatty() and sys.stdout.isatty()

    @staticmethod
    def _budget_seconds() -> float:
        """计算本次探测预算（tmux 下更保守）."""
        budget_ms = _TMUX_PROBE_BUDGET_MS if "TMUX" in os.environ else _PROBE_TOTAL_BUDGET_MS
        return budget_ms / 1000.0

    @staticmethod
    def _is_wezterm_env() -> bool:
        """判断当前环境是否具备 WezTerm 特征."""
        term_program = os.environ.get("TERM_PROGRAM", "").lower()
        if "wezterm" in term_program:
            return True
        return "WEZTERM_EXECUTABLE" in os.environ or "WEZTERM_PANE" in os.environ

    def _can_use_wezterm_heuristic(self) -> bool:
        """判断是否可启用 WezTerm 乐观启发式."""
        return self._is_wezterm_env() and sys.stdout.isatty() and "TMUX" not in os.environ

    @staticmethod
    def _cache_key() -> tuple[object, ...]:
        """构建进程内缓存 key."""
        return (
            os.environ.get("TERM_FEATURES", ""),
            os.environ.get("KITTY_WINDOW_ID", ""),
            os.environ.get("TERM_PROGRAM", ""),
            os.environ.get("WEZTERM_EXECUTABLE", ""),
            os.environ.get("WEZTERM_PANE", ""),
            os.environ.get("TMUX", ""),
            sys.stdin.isatty(),
            sys.stdout.isatty(),
            sys.platform,
        )

    def probe(self, timeout: float = 0.1) -> TerminalCapability:
        """
        执行终端状态探测.

        Args:
            timeout: I/O 阻塞超时时间(秒).

        Returns:
            TerminalCapability: 探测到的终端能力.

        """
        key = self._cache_key()
        cache = self._cache
        if cache is not None and cache.key == key:
            logger.debug(
                "Selected capability via probe_source=cache cached_source=%s cached_elapsed_ms=%.2f",
                cache.probe_source,
                cache.elapsed_ms,
            )
            return cache.capability

        start = time.monotonic()

        cap_from_env = self._probe_term_features_env()
        if cap_from_env is not None:
            logger.debug("Selected capability via probe_source=term_features_env")
            elapsed_ms = (time.monotonic() - start) * 1000.0
            self._cache = _ProbeCache(key, cap_from_env, "term_features_env", elapsed_ms)
            return cap_from_env

        if "KITTY_WINDOW_ID" in os.environ:
            logger.debug("Selected capability via probe_source=kitty_env")
            elapsed_ms = (time.monotonic() - start) * 1000.0
            self._cache = _ProbeCache(key, TerminalCapability.KITTY, "kitty_env", elapsed_ms)
            return TerminalCapability.KITTY

        if self._can_use_wezterm_heuristic():
            term_program = os.environ.get("TERM_PROGRAM", "")
            logger.debug(
                "Selected capability via probe_source=wezterm_heuristic stdout_tty=%s tmux=%s term_program=%r",
                sys.stdout.isatty(),
                "TMUX" in os.environ,
                term_program,
            )
            elapsed_ms = (time.monotonic() - start) * 1000.0
            self._cache = _ProbeCache(
                key,
                TerminalCapability.ITERM2,
                "wezterm_heuristic",
                elapsed_ms,
            )
            return TerminalCapability.ITERM2

        if not self._supports_interactive_probe():
            logger.debug("No interactive TTY, using FALLBACK (probe_source=fallback)")
            elapsed_ms = (time.monotonic() - start) * 1000.0
            self._cache = _ProbeCache(key, TerminalCapability.FALLBACK, "fallback", elapsed_ms)
            return TerminalCapability.FALLBACK

        budget = min(timeout, self._budget_seconds())
        logger.debug("Entering TTY interactive probe (budget=%.3fs)", budget)
        with self._raw_mode():

            def _remaining() -> float:
                return max(0.0, budget - (time.monotonic() - start))

            # Level 1: single-shot priority query (Kitty)
            remain = _remaining()
            if remain > 0:
                kitty_timeout = min(remain, _STEP_TIMEOUT_KITTY_MS / 1000.0)
                kitty_query = "\x1b_Gi=31,a=q,s=1,v=1,t=d,f=24;AAAA\x1b\\"
                res = self._query_terminal_retry(kitty_query, kitty_timeout, remaining_budget=_remaining())
                logger.debug("Kitty query response: %r", res)
                if "i=31;OK" in res:
                    logger.debug("Selected capability via probe_source=kitty_query")
                    elapsed_ms = (time.monotonic() - start) * 1000.0
                    self._cache = _ProbeCache(key, TerminalCapability.KITTY, "kitty_query", elapsed_ms)
                    return TerminalCapability.KITTY

            # Level 1.5: upgrade with remaining budget
            remain = _remaining()
            if remain > 0:
                cap_timeout = min(remain, _STEP_TIMEOUT_CAP_MS / 1000.0)
                cap_from_query = self._probe_term_features_query(cap_timeout, remaining_budget=_remaining())
                if cap_from_query is not None:
                    logger.debug("Selected capability via probe_source=capabilities_query")
                    elapsed_ms = (time.monotonic() - start) * 1000.0
                    self._cache = _ProbeCache(key, cap_from_query, "capabilities_query", elapsed_ms)
                    return cap_from_query

            remain = _remaining()
            if remain > 0:
                da1_timeout = min(remain, _STEP_TIMEOUT_DA1_MS / 1000.0)
                da1_query = "\x1b[c"
                res_da1 = self._query_terminal_retry(da1_query, da1_timeout, remaining_budget=_remaining())
                logger.debug("DA1 query response: %r", res_da1)
                if self._is_sixel_da1(res_da1):
                    logger.debug("Selected capability via probe_source=da1")
                    elapsed_ms = (time.monotonic() - start) * 1000.0
                    self._cache = _ProbeCache(key, TerminalCapability.SIXEL, "da1", elapsed_ms)
                    return TerminalCapability.SIXEL

        source = "tmux_conservative_fallback" if "TMUX" in os.environ else "fallback"
        logger.debug("No capability matched, using FALLBACK (probe_source=%s)", source)
        elapsed_ms = (time.monotonic() - start) * 1000.0
        self._cache = _ProbeCache(key, TerminalCapability.FALLBACK, source, elapsed_ms)
        return TerminalCapability.FALLBACK
