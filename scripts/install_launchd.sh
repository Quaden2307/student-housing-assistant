#!/bin/sh
# Render the launchd template with this repo's path and load it for the current user.
# Re-run after editing the template. Check it is armed with:
#   launchctl print gui/$(id -u)/local.housing.sweep | grep -E "state|last exit|runs ="
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="local.housing.sweep"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$REPO/logs" "$HOME/Library/LaunchAgents"
sed "s|__REPO__|$REPO|g" "$REPO/scripts/launchd/$LABEL.plist.template" > "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
echo "installed $PLIST (runs daily at 06:30; logs in $REPO/logs/)"
