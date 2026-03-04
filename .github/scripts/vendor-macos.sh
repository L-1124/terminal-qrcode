#!/usr/bin/env bash
set -euo pipefail

# 安装编译依赖（头文件 + 链接库）
# delocate 会自动将运行时依赖打包进 wheel
# setup.py 中的 _brew_paths() 负责检测 brew 安装路径

brew update
brew install jpeg-turbo libpng webp
echo "Installed development libraries for C extension build."
