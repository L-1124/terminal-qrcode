# AGENTS.md

**terminal-qrcode** — 终端二维码/图像渲染工具，支持 Kitty/iTerm2/Sixel/Halfblock 多协议。

## Project overview

- Python 3.10+，`src/terminal_qrcode` 单包，无依赖库
- 架构：`TerminalProbe` → `RendererRegistry` → `Renderer`（策略模式）
- C 扩展 `_cimage` 处理 PNG/JPEG/WEBP 解码，支持 Windows/POSIX
- CI 用 `cibuildwheel` 自动构建跨版本 wheels

## Setup commands

- 本地开发：`uv sync`
- 运行 CLI：`uv run terminal_qrcode --help`

## C extension

- `uv run` `uv sync` 会自动构建 `_cimage`，无需手动编译

## Testing instructions

- 仅用函数式测试 (`def test_...`)，禁止类式测试 (`class Test...`)
- 测试平铺在 `tests/` 下，无 `__init__.py`，pytest 自动发现 `test_*.py`
- 每个测试函数必须有单行 Docstring
- 运行测试：`uv run pytest`
- 详细输出：`uv run pytest -v`
- 特定测试：`uv run pytest -k "test_kitty" -v`
- 显示打印：`uv run pytest -s`
- 覆盖率：`uv run pytest --cov=src/terminal_qrcode`

### Test file mapping

- `test_probe_terminal.py` — 终端能力探测，**必须 mock** `select.select` 和 `sys.stdin`，禁止真实 TTY I/O
- `test_api_draw.py` — 渲染 API 功能
- `test_renderers_core.py` — 渲染器转义序列特征（Kitty: `\x1b_G`, iTerm2: `\x1b]1337;`, Sixel: `\x1b]..q`）
- `test_cli_main.py` — 命令行接口
- `test_image_simple.py` — 图像处理接口

## Code quality

- Lint 检查：`uv run ruff check .`
- 自动修复：`uv run ruff check . --fix`
- 代码格式：`uv run ruff format .`
- 类型检查：`uv run pyrefly check`（扫描 `src/`）

### Code style rules

- **Import**: 标准库 → 第三方 → 本地 (`from . import ...`)
- **Docstring**: Google Style，中文，记录 Args/Returns/Raises
- **Type hints**: 非必要需要完善的类型提示，禁止使用`future`导入，Python 3.10+ 原生支持

## Key conventions

- **POSIX 兼容**：`probe.py` 中 `termios`/`tty` 仅 UNIX 可用，Windows 通过 `try/except ImportError` 处理，用 `Any` 类型标注——此为有意设计
- **图像解码**：PNG/JPEG/WEBP 通过 `_cimage` 使用静态链接后端，发布 wheel 时会打包所需 lib，不依赖运行时外部 `djpeg`
- **Tmux 穿透**：渲染器必须检查 `TMUX` 环境变量，需双重转义 `\x1bPtmux;...\x1b\\`
- **配置架构**：`RenderConfig` 包含 `qr`/`layout`/`probe` 三层子配置，测试代码使用 `RenderConfig.from_flat()` 构造
- **Finder 优化**：`_cimage.c` 中 Finder 检测已优化（早期终止、消除 sqrt、比例预检），大尺寸图像性能提升 30-50%

## PR instructions

- 标题格式：`<type>(<scope>): <subject>`，如 `feat(renderers): 添加 WezTerm 渲染器支持`
- 提交前必须运行：`uv run ruff check . && uv run ruff format . && uv run pyrefly check && uv run pytest`
- 新代码必须补充或更新测试
- 提交消息使用 Conventional Commits（类型：`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`）例如:
  - `feat(renderers): 添加 WezTerm 渲染器支持`

## Common tasks

### Add new renderer

1. 在 `renderers.py` 实现 `Renderer` 子类
2. 在 `RendererRegistry.select_renderer()` 中注册
3. 在 `test_renderers_core.py` 添加转义序列特征测试
4. 更新 README.md


### Test with Tmux

```bash
TMUX="session" uv run pytest tests/test_renderers_core.py -v
```

## Anti-patterns

- ❌ 直接操作 TTY（未 mock）— 用 `unittest.mock` 或 `pytest-mock`
- ❌ `class Test...` 风格 — 改用 `def test_...`
- ❌ `from __future__ import ...` — 3.10 无需
- ❌ 测试文件嵌套 — 平铺在 `tests/` 下

## Must Follow

- 以"皇上启奏:" 为每个回复的开头
