# AGENTS.md

qrcode-terminal 是一个终端二维码渲染工具，支持 Kitty/iTerm2 图形协议探测与半块字符降级。纯 Python 实现，策略模式架构。

## Project overview

* Python 3.10+，`src/` 布局，单包 `terminal_qrcode`。
* 架构：`TerminalProbe` 探测能力 → `RendererFactory` 创建策略 → `Renderer` 渲染输出。

## Dev environment

* 依赖管理：`uv`（构建后端 `setuptools`）。
* 代码质量：`ruff`（lint + format）、`pyrefly`（类型检查）。

### Setup commands

* 安装依赖：`uv sync`
* 运行测试：`uv run pytest`
* Lint 检查：`uv run ruff check .`
* 格式化：`uv run ruff format .`
* 类型检查：`uv run pyrefly check`

## Testing instructions

* 仅使用 `pytest` 函数式测试（`def test_...`），禁止类式测试。
* 测试文件平铺于 `tests/`，无 `__init__.py`（pytest 自动发现）。
* `probe.py` 测试必须 mock `select.select` 和 `sys.stdin`，阻断真实 TTY I/O。
* 渲染器测试验证转义序列特征（如 `\x1b_G` for Kitty、`\x1b]1337` for iTerm2），不验证完整输出。
* 需要单行 Docstring 描述测试行为

## Code quality

* `ruff` 行宽 88，目标 `py310`。
* Lint 规则：`E F I N UP B A C4 T20 RET`。
* **T20 规则**：源码禁止 `print()`。仅 `__main__.py` 允许 `# noqa: T201` 豁免。
* `pyrefly` 检查范围：`src/`。

## Conventions

* Docstrings 使用中文（英文符号），Google Style，只需要必要的注释，不需要过多注释。
* `probe.py` 中 `termios`/`tty` 为 POSIX 专属，通过 `try/except ImportError` 处理 Windows 兼容。对应变量使用 `Any` 类型标注绕过类型检查——此为有意设计，勿"修复"。
* 图像输入默认支持 PNG；`.jpg/.jpeg` 优先 `ctypes` 加载 `turbojpeg` 动态库，失败时回退系统 `djpeg`（libjpeg-turbo）。
* 渲染器必须处理 Tmux 穿透：检测 `TMUX` 环境变量，对转义序列做双重转义并包裹 `\x1bPtmux;...\x1b\\`。
* 无 `[project.scripts]` 入口，仅通过 `python -m terminal_qrcode` 运行。

## Anti-patterns

* 禁止在测试中直接操作 TTY（必须 mock）。
* 禁止 `as Any`、`@type: ignore` 等类型抑制（`probe.py` 中的 `Any` 变量除外）。
* 禁止使用 `__future__`

## Commit messages

* 使用 Conventional Commits：`<type>(<scope>): <subject>`。
* 仅在明确要求时才 `git commit` 或 `git push`。
