#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
  PYINSTALLER="$ROOT/.venv/bin/pyinstaller"
else
  PYTHON="${PYTHON:-python3}"
  PYINSTALLER="${PYINSTALLER:-pyinstaller}"
fi

VERSION="$("$PYTHON" -c 'from maclean import __version__; print(__version__)')"
ARCH="$(uname -m)"
ARCHIVE="dist/maClean-${VERSION}-macos-${ARCH}.zip"
CHECKSUM="${ARCHIVE}.sha256"

"$PYINSTALLER" maclean.spec --noconfirm --clean
codesign --force --deep --sign - dist/maClean.app
codesign --verify --deep --strict --verbose=1 dist/maClean.app

rm -f "$ARCHIVE" "$CHECKSUM"
(
  cd dist
  COPYFILE_DISABLE=1 zip -qry "$(basename "$ARCHIVE")" maClean.app
)

if zipinfo -1 "$ARCHIVE" | grep -Eq '(^|/)\._'; then
  echo "HATA: ZIP içinde AppleDouble (._*) girdisi bulundu." >&2
  exit 1
fi

VERIFY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/maclean-release.XXXXXX")"
trap 'rm -rf "$VERIFY_DIR"' EXIT
unzip -q "$ARCHIVE" -d "$VERIFY_DIR"

if ! find "$VERIFY_DIR/maClean.app/Contents/Resources" -maxdepth 1 -type l | grep -q .; then
  echo "HATA: Uygulama sembolik linkleri ZIP içinde korunmadı." >&2
  exit 1
fi

codesign --verify --deep --strict --verbose=1 "$VERIFY_DIR/maClean.app"
"$VERIFY_DIR/maClean.app/Contents/MacOS/maClean" --smoke-test
shasum -a 256 "$ARCHIVE" > "$CHECKSUM"

echo "Release hazır:"
echo "  $ARCHIVE"
echo "  $CHECKSUM"
