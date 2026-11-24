#!/usr/bin/env bash
# Start Orion in voice mode at login (Mac: launchd, Linux: autostart entry).
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR/data"
if [ "$(uname)" = "Darwin" ]; then
  P="$HOME/Library/LaunchAgents/com.orion.assistant.plist"
  cat > "$P" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.orion.assistant</string>
<key>ProgramArguments</key><array><string>$DIR/venv/bin/python</string><string>$DIR/main.py</string><string>--voice</string></array>
<key>WorkingDirectory</key><string>$DIR</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><false/>
<key>StandardOutPath</key><string>$DIR/data/orion.log</string>
<key>StandardErrorPath</key><string>$DIR/data/orion.log</string>
</dict></plist>
PLIST
  launchctl unload "$P" 2>/dev/null
  launchctl load "$P"
  echo "Autostart enabled (macOS). macOS will ask for microphone permission the first time."
  echo "Undo: launchctl unload \"$P\" && rm \"$P\""
else
  mkdir -p "$HOME/.config/autostart"
  cat > "$HOME/.config/autostart/orion.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Orion
Exec=$DIR/venv/bin/python $DIR/main.py --voice
Path=$DIR
Terminal=false
DESKTOP
  echo "Autostart enabled (Linux). Undo: rm ~/.config/autostart/orion.desktop"
fi
