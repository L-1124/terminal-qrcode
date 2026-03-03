#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${ROOT_DIR}/src/terminal_qrcode/_vendor/linux"

rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

install_deps() {
  if command -v dnf >/dev/null 2>&1; then
    dnf -y install libjpeg-turbo libjpeg-turbo-devel libpng libpng-devel libwebp libwebp-devel
    return
  fi
  if command -v yum >/dev/null 2>&1; then
    yum -y install libjpeg-turbo libjpeg-turbo-devel libpng libpng-devel libwebp libwebp-devel
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y \
      libturbojpeg0 \
      libturbojpeg0-dev \
      libpng16-16 \
      libpng-dev \
      libwebp7 \
      libwebp-dev
    return
  fi
  echo "Unsupported package manager on Linux runner." >&2
  exit 1
}

resolve_first_match() {
  local pattern
  for pattern in "$@"; do
    if compgen -G "${pattern}" >/dev/null; then
      compgen -G "${pattern}" | head -n 1
      return 0
    fi
  done
  return 1
}

copy_with_alias() {
  local src="$1"
  local alias_name="$2"
  local base_name
  base_name="$(basename "${src}")"
  cp -L "${src}" "${OUT_DIR}/${base_name}"
  if [[ "${base_name}" != "${alias_name}" ]]; then
    cp -L "${src}" "${OUT_DIR}/${alias_name}"
  fi
}

install_deps

turbojpeg_path="$(resolve_first_match \
  /usr/lib64/libturbojpeg.so* \
  /usr/lib/aarch64-linux-gnu/libturbojpeg.so* \
  /usr/lib/x86_64-linux-gnu/libturbojpeg.so* \
  /usr/lib/libturbojpeg.so*)" || {
  echo "libturbojpeg shared library not found on Linux runner." >&2
  exit 1
}
libpng_path="$(resolve_first_match \
  /usr/lib64/libpng16.so* \
  /usr/lib/aarch64-linux-gnu/libpng16.so* \
  /usr/lib/x86_64-linux-gnu/libpng16.so* \
  /usr/lib/libpng16.so*)" || {
  echo "libpng shared library not found on Linux runner." >&2
  exit 1
}
libwebp_path="$(resolve_first_match \
  /usr/lib64/libwebp.so* \
  /usr/lib/aarch64-linux-gnu/libwebp.so* \
  /usr/lib/x86_64-linux-gnu/libwebp.so* \
  /usr/lib/libwebp.so*)" || {
  echo "libwebp shared library not found on Linux runner." >&2
  exit 1
}
copy_with_alias "${turbojpeg_path}" "libturbojpeg.so"
copy_with_alias "${libpng_path}" "libpng16.so"
copy_with_alias "${libwebp_path}" "libwebp.so"

echo "Bundled Linux libraries:"
ls -al "${OUT_DIR}"
