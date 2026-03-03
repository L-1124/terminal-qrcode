#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${ROOT_DIR}/src/terminal_qrcode/_vendor/macos"

rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}"

brew update
brew install jpeg-turbo libpng webp

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

BREW_PREFIX="$(brew --prefix)"

copy_with_alias "${BREW_PREFIX}/opt/jpeg-turbo/lib/libturbojpeg.dylib" "libturbojpeg.dylib"

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

libpng_path="$(resolve_first_match "${BREW_PREFIX}/opt/libpng/lib/libpng16"*.dylib)" || {
  echo "libpng shared library not found on macOS runner." >&2
  exit 1
}
copy_with_alias "${libpng_path}" "libpng16.dylib"

libwebp_path="$(resolve_first_match "${BREW_PREFIX}/opt/webp/lib/libwebp"*.dylib)" || {
  echo "libwebp shared library not found on macOS runner." >&2
  exit 1
}
copy_with_alias "${libwebp_path}" "libwebp.dylib"

echo "Bundled macOS libraries:"
ls -al "${OUT_DIR}"
