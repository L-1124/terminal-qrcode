# terminal-qrcode

[![Python 3.10+](https://img.shields.io/badge/Python-3.10|3.11|3.12|3.13|3.14-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

[English](./README.en.md) | 简体中文

终端二维码图片渲染工具，支持图形协议、字符降级渲染和终端能力探测。

## 📦 安装

基础安装：

```bash
uv add terminal-qrcode
```

## ✨ API

```python
from terminal_qrcode import draw, generate

# 1. 渲染已有图片
out = draw("test.png", renderer="halfblock")
out.print()

# 2. 直接根据文本生成二维码
qr = generate("https://github.com", renderer="auto")
qr.print()
```

配合 Rich 使用时，`console.print(draw(...))` 或 `console.print(generate(...))` 会强制走 `halfblock` 文本渲染

```python
from rich.console import Console
from terminal_qrcode import generate

console = Console()
console.print(generate("https://github.com"))
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
- QR 布尔方阵：`list[list[bool]]`

## 💻 支持的终端渲染器

- `kitty`（Kitty Graphics Protocol）
- `iterm2`（Inline Image Protocol）
- `wezterm`（iTerm2 兼容协议）
- `sixel`（DEC Sixel）
- `halfblock`（Unicode 半块字符降级）

## 🔧 CLI

```bash
# 1. 直接根据文本生成二维码 (默认行为)
$ terminal_qrcode "https://github.com"

# 2. 渲染已有图片
$ terminal_qrcode -i qrcode.png
```

## 🛠️ 本地开发

```bash
# 安装开发依赖
$ uv sync

# 运行 Windows 开发安装脚本
$ uv run --no-project python scripts/install-dev.py
uv sync
```

## 📄 License

MIT
