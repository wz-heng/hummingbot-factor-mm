#!/usr/bin/env bash
# Recovery script for Hummingbot install failure during initial VPS bootstrap.
# Idempotent. Logs everything to /root/hb-recovery.log.
# Touches /root/hb-recovery.done on success, /root/hb-recovery.failed on failure.

set -uo pipefail

LOGFILE=/root/hb-recovery.log
DONE=/root/hb-recovery.done
FAILED=/root/hb-recovery.failed

rm -f "$DONE" "$FAILED"
exec > "$LOGFILE" 2>&1

log() { echo "[$(date '+%H:%M:%S')] $*"; }
fail() { log "FAILED at line $1"; touch "$FAILED"; exit 1; }
trap 'fail $LINENO' ERR
set -e

log "==== Step 1: root apt deps ===="
apt update -qq
DEBIAN_FRONTEND=noninteractive apt install -y -qq build-essential tmux >/dev/null
log "apt deps OK"

log "==== Step 2: hummingbot install as botuser ===="
sudo -iu botuser bash <<'EOSU'
set -euo pipefail
log() { echo "[$(date '+%H:%M:%S')] [botuser] $*"; }

cd ~/hummingbot
source ~/miniconda3/etc/profile.d/conda.sh

if conda info --envs | grep -q '^hummingbot '; then
  log "conda env 'hummingbot' already exists"
else
  log "Creating conda env from setup/environment.yml..."
  conda env create -f setup/environment.yml
fi

conda activate hummingbot
log "active python: $(which python)"

if ! command -v conda-develop >/dev/null 2>&1 && ! conda develop --help >/dev/null 2>&1; then
  log "Installing conda-build (provides conda develop)..."
  conda install -y -q conda-build
fi

if ! command -v pre-commit >/dev/null 2>&1; then
  log "Installing pre-commit..."
  pip install -q pre-commit
fi

log "Running ./install (may take 5-10 minutes)..."
./install

log "Running ./compile (may take 8-12 minutes on 2GB RAM)..."
./compile

log "Sanity checks..."
python -c "import hummingbot; print('hummingbot import OK:', hummingbot.__file__)"
test -f bin/hummingbot_quickstart.py
log "==== botuser stage DONE ===="
EOSU

log "==== Step 3: re-run bootstrap to finish symlinks + systemd ===="
REPO_URL=https://github.com/wz-heng/hummingbot-factor-mm.git \
  bash /root/bootstrap_vps.sh

log "==== ALL DONE ===="
touch "$DONE"
