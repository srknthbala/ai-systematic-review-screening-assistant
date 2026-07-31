#!/usr/bin/env bash
# Build AI Systematic Review Screening Assistant.app and wrap it in a .dmg
# with the usual drag-to-Applications window.
#
#   ./packaging/macos/build.sh [version]
#
# Signing is optional and off by default. Set this to produce an app that
# opens without a Gatekeeper warning on other machines:
#   APP_CERT="Developer ID Application: Your Name (TEAMID)"
set -euo pipefail

VERSION="${1:-1.0.0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/dist"
NAME="AI Systematic Review Screening Assistant"
APP="$OUT/$NAME.app"
VOLNAME="AI Screening Assistant"
STAGE="$ROOT/build/dmg"
MOUNT="/Volumes/$VOLNAME"
DMG="$OUT/AI-Screening-Assistant-$VERSION.dmg"

cd "$ROOT"

echo "==> Generating icons"
python packaging/make_icons.py
python - <<'PY'
import sys
sys.path.insert(0, 'packaging')
from pathlib import Path
from make_icons import dmg_background
dmg_background().save(Path('packaging/icons/dmg-background.png'))
PY

echo "==> Freezing the app"
if ! rm -rf build dist 2>/dev/null; then
  echo "Could not clear ./dist. If it contains root-owned files from an" >&2
  echo "interrupted build, remove it first:  sudo rm -rf dist" >&2
  exit 1
fi
if [ -e dist ]; then
  echo "./dist still exists after cleanup, aborting." >&2
  exit 1
fi
python -m PyInstaller packaging/ai-screening.spec --noconfirm --log-level WARN
[ -d "$APP" ] || { echo "PyInstaller did not produce $APP" >&2; exit 1; }

if [ -n "${APP_CERT:-}" ]; then
  echo "==> Signing the app bundle"
  codesign --force --deep --options runtime --timestamp --sign "$APP_CERT" "$APP"
  codesign --verify --strict "$APP"
else
  echo "==> No APP_CERT set, leaving the bundle unsigned"
fi

echo "==> Staging the disk image"
rm -rf "$STAGE"; mkdir -p "$STAGE/.background"
cp -R "$APP" "$STAGE/"
# The alias the user drags onto. A symlink is all /Applications needs to be.
ln -s /Applications "$STAGE/Applications"
cp packaging/icons/dmg-background.png "$STAGE/.background/background.png"

echo "==> Creating a writable image"
rm -f "$DMG" "$OUT/rw.dmg"
hdiutil create -srcfolder "$STAGE" -volname "$VOLNAME" -fs HFS+ \
               -format UDRW -ov -quiet "$OUT/rw.dmg"

hdiutil detach "$MOUNT" -quiet 2>/dev/null || true
hdiutil attach "$OUT/rw.dmg" -readwrite -noverify -noautoopen -quiet
sleep 2

# Lay the window out. Finder scripting needs Apple Events permission, which a
# headless or restricted session will not have, so never let it fail the build:
# without it the DMG still opens and still works, it just is not pre-arranged.
echo "==> Arranging the window"
if osascript - "$VOLNAME" <<'APPLESCRIPT' >/dev/null 2>&1
on run argv
  set vol to item 1 of argv
  tell application "Finder"
    tell disk vol
      open
      set current view of container window to icon view
      set toolbar visible of container window to false
      set statusbar visible of container window to false
      set the bounds of container window to {200, 140, 840, 560}
      set opts to the icon view options of container window
      set arrangement of opts to not arranged
      set icon size of opts to 128
      set background picture of opts to file ".background:background.png"
      set position of item "AI Systematic Review Screening Assistant.app" of container window to {160, 190}
      set position of item "Applications" of container window to {480, 190}
      close
      open
      update without registering applications
      delay 1
    end tell
  end tell
end run
APPLESCRIPT
then
  echo "    window arranged"
else
  echo "    Finder scripting unavailable, shipping an unstyled (but working) window"
fi

# Volume icon last: Finder rewrites the volume root while arranging the
# window and discards it if it is written before that.
cp packaging/icons/icon.icns "$MOUNT/.VolumeIcon.icns"
SetFile -a C "$MOUNT" 2>/dev/null || true

sync
hdiutil detach "$MOUNT" -quiet 2>/dev/null || hdiutil detach "$MOUNT" -force -quiet 2>/dev/null || true

echo "==> Compressing"
hdiutil convert "$OUT/rw.dmg" -format UDZO -imagekey zlib-level=9 -o "$DMG" -quiet
rm -f "$OUT/rw.dmg"
rm -rf "$STAGE"

echo
echo "Built: $DMG"
if [ -z "${APP_CERT:-}" ]; then
  cat <<'NOTE'

The app inside is unsigned. On another Mac, Gatekeeper will block it on first
launch: right-click the app in /Applications and choose Open, then confirm.
To ship without that you need an Apple Developer ID (99 USD/year), then set
APP_CERT and notarise the disk image:

  xcrun notarytool submit dist/AI-Screening-Assistant-VERSION.dmg \
      --apple-id you@example.com --team-id TEAMID --password APP_PASSWORD --wait
  xcrun stapler staple dist/AI-Screening-Assistant-VERSION.dmg
NOTE
fi
