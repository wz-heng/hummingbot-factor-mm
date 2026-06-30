#!/usr/bin/env bash
# Pull latest factor-mm code and restart both services.
# Run on VPS as botuser (services need sudo for systemctl).

set -euo pipefail

cd ~/factor-mm
git fetch --prune
git pull --ff-only

# Re-create symlinks for any newly added controller module
# (bootstrap_vps.sh only runs this loop on first install; doing it here
# means new files like exchange_health.py are picked up automatically).
for f in ~/factor-mm/controllers/market_making/*.py; do
  base=$(basename "$f")
  [ "$base" = "__init__.py" ] && continue
  ln -sf "$f" ~/hummingbot/controllers/market_making/"$base"
done

sudo systemctl restart hummingbot factor-dashboard

echo "Restarted. Tailing hummingbot journal (Ctrl-C to detach):"
sudo journalctl -u hummingbot -f
