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

- `test_probe.py` — 终端能力探测，**必须 mock** `select.select` 和 `sys.stdin`，禁止真实 TTY I/O
- `test_api.py` — `draw` 与 `generate` 核心 API 功能
- `test_render.py` — 渲染器转义序列特征、规范化输出及渲染器选择逻辑
- `test_integration.py` — Pillow 与 qrcode 库的集成兼容性
- `test_image.py` — 图像处理基础接口

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
- **配置架构**：`RenderConfig` 包含 `qr`/`layout`/`probe` 三层子配置
- **性能优化**：`_cimage.c` 包含深度优化逻辑：
  - **Finder 检测**：早期终止、消除 sqrt、比例预检。
  - **内存机制**：Sixel 编码使用单一连续缓冲区，避免 Python C-API 高频对象分配碎片化。
  - **分支预测**：阈值化处理采用位掩码（Branchless）技术，消除 Alpha 判断的流水线冲刷惩罚。
  - **计算冗余**：矩阵缩放采用 32 位整数赋值（RGBA）或循环展开（RGB）消除内层 memcpy。

## PR instructions

- 标题格式：`<type>(<scope>): <subject>`，如 `feat(renderers): 添加 WezTerm 渲染器支持`
- 提交前必须运行：`uv run ruff check . && uv run ruff format . && uv run pyrefly check && uv run pytest`
- 新代码必须补充或更新测试
- 提交消息使用 Conventional Commits（类型：`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`）使用中文message，例如:
  - `feat(renderers): 添加 WezTerm 渲染器支持`

## Common tasks

### Add new renderer

1. 在 `renderers.py` 实现 `Renderer` 子类
2. 在 `RendererRegistry.select_renderer()` 中注册
3. 在 `test_render.py` 添加转义序列特征测试
4. 更新 README.md

### Test with Tmux

```bash
TMUX="session" uv run pytest tests/test_render.py -v
```

## Anti-patterns

- ❌ 直接操作 TTY（未 mock）— 用 `unittest.mock` 或 `pytest-mock`
- ❌ `class Test...` 风格 — 改用 `def test_...`
- ❌ `from __future__ import ...` — 3.10 无需
- ❌ 测试文件嵌套 — 平铺在 `tests/` 下

## Must Follow

- 以"皇上启奏:" 为每个回复的开头
