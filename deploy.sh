#!/usr/bin/env bash
# Copy this add-on to a Home Assistant machine on the local network and update it.
# Usage: ./deploy.sh [ssh-target]   (default root@homeassistant.local)
# Env:   HA_SSH_KEY=~/.ssh/homeassistant
# Bump `version` in config.yaml first, or HA won't rebuild the add-on.
set -euo pipefail
cd "$(dirname "$0")"
TARGET="${1:-root@homeassistant.local}"
KEY="${HA_SSH_KEY:-$HOME/.ssh/homeassistant}"
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes "$TARGET")

COPYFILE_DISABLE=1 tar --exclude='__pycache__' --exclude='.DS_Store' --exclude='options.json' -C invisible_display -cf - . |
  "${SSH[@]}" 'mkdir -p /local_apps/invisible_display && tar -xf - -C /local_apps/invisible_display \
    && rm -f /local_apps/invisible_display/._* \
    && ha store reload >/dev/null && sleep 3 \
    && (ha addons update local_invisible_display || ha addons rebuild local_invisible_display) 2>&1 | tail -2 \
    && ha addons info local_invisible_display | grep -E "^(version|state):"'
