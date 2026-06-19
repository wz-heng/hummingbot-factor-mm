#!/usr/bin/env bash
# Idempotent VPS bootstrap. Re-run safely; existing state is detected.
#
# Pre-req: Ubuntu 22.04 LTS, run as root or with sudo, VPS in Tokyo region.
# Post-state: hummingbot source-installed under botuser, systemd units enabled
#             but NOT started (operator runs `systemctl start ...` after API
#             keys are configured).

set -euo pipefail

REPO_URL="${REPO_URL:?REPO_URL must be set; e.g. REPO_URL=git@github.com:you/factor-mm.git}"

# 0. Base tools + clock + auto-updates
apt update
apt install -y git ufw chrony unattended-upgrades curl wget
systemctl enable --now chrony
timedatectl set-ntp true

# 1. Firewall: deny incoming except SSH (Tailscale manages its own)
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

# 2. Tailscale (operator runs `tailscale up` interactively after script)
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

# 3. Bot user + Hummingbot
id -u botuser >/dev/null 2>&1 || useradd -m -s /bin/bash botuser

sudo -u botuser bash <<'EOSU'
set -euo pipefail
cd ~

# 3a. Miniconda
if [ ! -d miniconda3 ]; then
  wget -qO /tmp/miniconda.sh \
    https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  bash /tmp/miniconda.sh -b -p ~/miniconda3
  rm /tmp/miniconda.sh
fi

# 3b. Hummingbot source
if [ ! -d hummingbot ]; then
  git clone https://github.com/hummingbot/hummingbot.git
  cd hummingbot
  ./install
  source ~/miniconda3/etc/profile.d/conda.sh
  conda activate hummingbot
  ./compile
fi
EOSU

# 4. Our project repo + symlinks
sudo -u botuser bash <<EOSU
set -euo pipefail
cd ~
if [ ! -d factor-mm ]; then
  git clone "${REPO_URL}" factor-mm
fi
ln -sf ~/factor-mm/controllers/market_making/factor_mm_btc_perp.py \
       ~/hummingbot/controllers/market_making/factor_mm_btc_perp.py
ln -sf ~/factor-mm/controllers/market_making/factor_math.py \
       ~/hummingbot/controllers/market_making/factor_math.py
ln -sf ~/factor-mm/controllers/market_making/health.py \
       ~/hummingbot/controllers/market_making/health.py
ln -sf ~/factor-mm/controllers/market_making/metrics_sink.py \
       ~/hummingbot/controllers/market_making/metrics_sink.py
ln -sf ~/factor-mm/controllers/market_making/processed_data.py \
       ~/hummingbot/controllers/market_making/processed_data.py
EOSU

# 5. systemd units
cp deploy/hummingbot.service /etc/systemd/system/
cp deploy/factor-dashboard.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable hummingbot factor-dashboard

echo
echo "Bootstrap complete. Next steps:"
echo "  1. tailscale up   (interactive login)"
echo "  2. ssh as botuser; run ~/hummingbot/bin/hummingbot_quickstart.py"
echo "     to configure binance_perpetual_testnet API keys"
echo "  3. cp ~/factor-mm/conf/controllers/factor_mm_btc.yml.example \\"
echo "        ~/factor-mm/conf/controllers/factor_mm_btc.yml"
echo "  4. systemctl start hummingbot factor-dashboard"
echo "  5. journalctl -u hummingbot -f"
