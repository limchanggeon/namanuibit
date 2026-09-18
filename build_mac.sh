#!/bin/zsh
# Builds 나만의빛.app and packages it as dist/나만의빛-<version>.dmg.
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="나만의빛"
BINARY_NAME="Namanuibit"   # must match BINARY_NAME in lightloom.spec
VERSION="1.0.0"
DMG="dist/${APP_NAME}-${VERSION}.dmg"

if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12
fi
uv pip install -r requirements.lock.txt -r requirements.build.txt

.venv/bin/python assets/make_icons.py
rm -rf build "dist/${BINARY_NAME}" "dist/${APP_NAME}.app" "$DMG"
.venv/bin/python -m PyInstaller --noconfirm --clean lightloom.spec

# Ad-hoc signature: without it Gatekeeper reports an arm64 bundle as damaged.
# PyInstaller signs with --timestamp, which fails without network access and can
# leave a partial signature behind; clear that before signing again.
find "dist/${APP_NAME}.app" \( -name "*.cstemp" -o -name "_CodeSignature" \) -prune -exec rm -rf {} +
codesign --force --deep --sign - "dist/${APP_NAME}.app"
codesign --verify --deep --strict "dist/${APP_NAME}.app"

STAGE="$(mktemp -d)/${APP_NAME}"
mkdir -p "$STAGE"
cp -R "dist/${APP_NAME}.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$(dirname "$STAGE")"
# The .app already carries everything; drop PyInstaller's intermediate copy.
rm -rf "dist/${BINARY_NAME}"

echo
echo "완료: $DMG"
du -sh "dist/${APP_NAME}.app" "$DMG"
