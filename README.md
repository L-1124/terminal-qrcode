# terminal-qrcode

[![Python 3.10+](https://img.shields.io/badge/Python-3.10|3.11|3.12|3.13|3.14-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

终端二维码图片渲染工具，支持图形协议、字符降级渲染和终端能力探测。

## 📦 安装

基础安装：

```bash
uv add terminal-qrcode
```

开发环境（含测试与集成依赖）：

```bash
uv sync
```

## ✨ Python API

```python
from terminal_qrcode import draw

a = draw("test.png", renderer="halfblock")
print(a)

raw = draw("test.png")
print(str(raw))
```

## 🖼️ 支持图片格式

- PNG
- JPEG
- WEBP

解码后端：

- PNG: `libpng`
- JPEG: `libjpeg-turbo`
- WEBP: `libwebp`

## 🧩 API 支持输入

- 本地图片路径：`str` / `pathlib.Path`
- 图像字节流：`bytes` / `bytearray`
- 兼容 PIL 的图像对象
- `qrcode.image.BaseImage` 包装对象
- 布尔矩阵：`list[list[bool]]`

## 💻 支持的终端渲染器

- `kitty`（Kitty Graphics Protocol）
- `iterm2`（Inline Image Protocol）
- `wezterm`（iTerm2 兼容协议）
- `sixel`（DEC Sixel）
- `halfblock`（Unicode 半块字符降级）

## 🔧 CLI

```bash
uv run python scripts/cli.py <image_path> [options]
```

仅探测当前终端能力：

```bash
uv run python scripts/cli.py --detect
```

常见渲染选项：

```bash
uv run python scripts/cli.py qrcode.png --renderer halfblock
uv run python scripts/cli.py qrcode.png --renderer auto
```

## 🛠️ 本地开发

```bash
uv sync
```

Windows

```bash
uv run --no-project python scripts/install-dev.py
uv sync
```

## 📄 License

MIT
