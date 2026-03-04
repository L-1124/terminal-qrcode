#!/usr/bin/env bash
set -euo pipefail

# 安装编译依赖（头文件 + 链接库）
# 动态链接后由 auditwheel repair 自动将运行时依赖打包进 wheel

install_turbojpeg_dev_yum() {
  # 部分仓库使用 libturbojpeg-devel，部分使用 libjpeg-turbo-devel。
  yum -y install libturbojpeg-devel && return
  yum -y install libjpeg-turbo-devel
}

install_turbojpeg_dev_dnf() {
  dnf -y install libturbojpeg-devel && return
  dnf -y install libjpeg-turbo-devel
}

has_turbojpeg_header() {
  [ -f /usr/include/turbojpeg.h ] || [ -f /usr/local/include/turbojpeg.h ]
}

build_turbojpeg_from_source() {
  local workdir cmake_bin
  workdir="$(mktemp -d)"
  cmake_bin="$(command -v cmake3 || command -v cmake)"

  curl -fsSL -o "$workdir/libjpeg-turbo.tar.gz" \
    "https://github.com/libjpeg-turbo/libjpeg-turbo/archive/refs/tags/3.1.3.tar.gz"
  tar -xzf "$workdir/libjpeg-turbo.tar.gz" -C "$workdir"

  "$cmake_bin" \
    -S "$workdir/libjpeg-turbo-3.1.3" \
    -B "$workdir/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DENABLE_SHARED=1 \
    -DENABLE_STATIC=1
  "$cmake_bin" --build "$workdir/build" -j"$(nproc)"
  "$cmake_bin" --install "$workdir/build"
  ldconfig || true
  rm -rf "$workdir"
}

ensure_turbojpeg_header() {
  if has_turbojpeg_header; then
    return
  fi
  echo "turbojpeg.h not found in system packages, building libjpeg-turbo from source..."

  if command -v dnf >/dev/null 2>&1; then
    dnf -y install gcc gcc-c++ make nasm cmake || dnf -y install gcc gcc-c++ make nasm cmake3
  elif command -v yum >/dev/null 2>&1; then
    yum -y install gcc gcc-c++ make nasm cmake || yum -y install gcc gcc-c++ make nasm cmake3
  else
    echo "No supported package manager for building libjpeg-turbo from source." >&2
    exit 1
  fi

  build_turbojpeg_from_source
  if has_turbojpeg_header; then
    return
  fi
  if [ -f /usr/include/turbojpeg.h ] || [ -f /usr/local/include/turbojpeg.h ]; then
    return
  fi
  echo "turbojpeg.h not found after dependency installation." >&2
  exit 1
}

install_deps() {
  if command -v dnf >/dev/null 2>&1; then
    install_turbojpeg_dev_dnf
    dnf -y install libpng-devel libwebp-devel zlib-devel
    ensure_turbojpeg_header
    return
  fi
  if command -v yum >/dev/null 2>&1; then
    install_turbojpeg_dev_yum
    yum -y install libpng-devel libwebp-devel zlib-devel
    ensure_turbojpeg_header
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y libturbojpeg0-dev libpng-dev libwebp-dev zlib1g-dev
    return
  fi
  echo "Unsupported package manager on Linux runner." >&2
  exit 1
}

install_deps
echo "Installed development libraries for C extension build."
