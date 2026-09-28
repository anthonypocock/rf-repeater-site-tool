#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$ROOT_DIR/vendor/ntia-itm"
NTIA_REPO="https://github.com/NTIA/itm.git"
NTIA_COMMIT="183ad95bd813a8be11009df396e1c631356864b2"

if [[ -d "$VENDOR_DIR/.git" ]]; then
  current="$(git -C "$VENDOR_DIR" rev-parse HEAD)"
  if [[ "$current" == "$NTIA_COMMIT" ]]; then
    echo "NTIA ITM already present at $NTIA_COMMIT"
    exit 0
  fi
  rm -rf "$VENDOR_DIR"
fi

mkdir -p "$(dirname "$VENDOR_DIR")"
git clone --depth 1 "$NTIA_REPO" "$VENDOR_DIR"
git -C "$VENDOR_DIR" fetch --depth 1 origin "$NTIA_COMMIT"
git -C "$VENDOR_DIR" checkout --detach "$NTIA_COMMIT"

# NTIA source uses Windows-style relative include paths. Patch only the local
# vendor checkout so Linux CI can compile it without modifying upstream source.
python3 - "$VENDOR_DIR/src" <<'PATCH'
import pathlib, sys
for file in pathlib.Path(sys.argv[1]).glob("*.cpp"):
    file.write_text(file.read_text().replace("..\\include\\", "../include/"))
PATCH

echo "Fetched NTIA ITM at $NTIA_COMMIT"

