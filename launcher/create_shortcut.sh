#!/usr/bin/env bash
# Creates the "IELTS Prep" launcher in the app menu and on the Desktop (Ubuntu/GNOME and most desktops).
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
cat > "$APPS/ielts-prep.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=IELTS Prep
Comment=Local IELTS practice app
Exec="$ROOT/.venv/bin/python" "$ROOT/launcher/launch.pyw"
Path=$ROOT
Icon=$ROOT/launcher/ielts.png
Terminal=false
Categories=Education;
EOF
chmod +x "$APPS/ielts-prep.desktop"
echo "Created $APPS/ielts-prep.desktop"

DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP" ]; then
  cp "$APPS/ielts-prep.desktop" "$DESKTOP/"
  chmod +x "$DESKTOP/ielts-prep.desktop"
  # GNOME: mark as trusted so it launches on double-click
  gio set "$DESKTOP/ielts-prep.desktop" metadata::trusted true 2>/dev/null || true
  echo "Created $DESKTOP/ielts-prep.desktop"
fi
