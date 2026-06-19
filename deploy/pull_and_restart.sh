#!/usr/bin/env bash
# Pull latest factor-mm code and restart both services.
# Run on VPS as botuser (services need sudo for systemctl).

set -euo pipefail

cd ~/factor-mm
git fetch --prune
git pull --ff-only

sudo systemctl restart hummingbot factor-dashboard

echo "Restarted. Tailing hummingbot journal (Ctrl-C to detach):"
sudo journalctl -u hummingbot -f
