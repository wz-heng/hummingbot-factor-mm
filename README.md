# factor-mm

Factor-driven market-making controller for `BTC-USDT` USDT-M perpetual on Hummingbot v2.

Design: `docs/superpowers/specs/2026-06-19-factor-mm-binance-perp-design.md`
Plan:   `docs/superpowers/plans/2026-06-19-factor-mm-binance-perp.md`

## What it does

- Computes a Micro-price + OBI factor each tick from L1 book state
- Adds an inventory-penalty skew that pulls net position back to target
- Sets Hummingbot's `reference_price` so the base class quotes around it
- Engages a kill switch on daily-loss / stale-book / clock-drift / empty-book
- Writes 1 Hz metrics to a separate sqlite for a Streamlit dashboard

This is a **learning project**, not a money printer. M9 (mainnet) is optional and always small.

## Local dev

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Expected: ~29 tests pass.

## Deployment (VPS, first run)

This is the end-to-end runbook. Plan ~60 minutes the first time.

### 1. Provision

- Provider: Vultr High Frequency Tokyo (or AWS Lightsail Tokyo). 2 vCPU / 4 GB / 30 GB SSD. Ubuntu 22.04.
- Record the public IPv4 in `~/.ssh/config` as `Host factor-vps`.

### 2. SSH baseline (your own dev machine)

```bash
ssh root@<vps-ip>
# Change SSH port, disable password auth, install ssh key. Skipped here for brevity.
```

### 3. Bootstrap the VPS

Copy and run the script:

```bash
scp deploy/bootstrap_vps.sh root@<vps-ip>:/root/
ssh root@<vps-ip>
REPO_URL=git@github.com:<you>/factor-mm.git bash /root/bootstrap_vps.sh
```

### 4. Bring Tailscale up

```bash
tailscale up    # interactive login
tailscale ip -4  # note the 100.x.x.x address
```

### 5. Configure Binance API key

In the Binance Futures Testnet console (https://testnet.binancefuture.com/):

- Generate API key
- Set **IP whitelist = VPS public IP** (the one you provisioned)
- Permissions: enable **Reading** and **Futures**; ensure **Withdrawal is DISABLED**

Then on the VPS:

```bash
sudo -iu botuser
cd ~/hummingbot
./bin/hummingbot_quickstart.py
# At the prompt:
> connect binance_perpetual_testnet
# Paste API key and secret when prompted. They are written to
# ~/hummingbot/conf/connectors/binance_perpetual_testnet.yml
> exit
```

Lock the file:

```bash
chmod 600 ~/hummingbot/conf/connectors/*.yml
```

### 6. Place the controller config

```bash
cp ~/factor-mm/conf/controllers/factor_mm_btc.yml.example \
   ~/factor-mm/conf/controllers/factor_mm_btc.yml
ln -sf ~/factor-mm/conf/controllers/factor_mm_btc.yml \
       ~/hummingbot/conf/controllers/factor_mm_btc.yml
```

Edit defaults only if you have a reason. Spec §6.6 is the source of truth.

### 7. Start the services

```bash
exit    # back to root
systemctl start hummingbot factor-dashboard
journalctl -u hummingbot -f
```

Expected within ~30 seconds:

- Log shows `connect binance_perpetual_testnet` succeeded
- Log shows `factor_mm_btc_perp` controller started
- Within a few minutes you see `CreateExecutorAction` / `StopExecutorAction` events as the bot quotes

### 8. Open the dashboard

From your dev machine (Tailscale connected):

```
http://<tailscale-100.x.x.x>:8501
```

You should see:

- Kill banner OFF
- Big numbers populated (Mid, Net Base, Reservation, Factor, Actions/60s, OB age)
- 3 time-series charts filling in over a couple of minutes
- "Recent fills" table populating after first fill

### 9. Day-to-day operations

**Pull and restart after code changes:**

```bash
ssh botuser@<vps-ip>
~/factor-mm/deploy/pull_and_restart.sh
```

**Stop everything:**

```bash
sudo systemctl stop hummingbot factor-dashboard
```

**Reset kill switch:** the kill is sticky in-process. Restart hummingbot to clear:

```bash
sudo systemctl restart hummingbot
```

**Check logs:**

```bash
sudo journalctl -u hummingbot -n 200 --no-pager
sudo journalctl -u factor-dashboard -n 50 --no-pager
```

## Milestones beyond first run

See spec §10 for M6 (7-day smoke), M7 (7-day tuning), M8 (Go/No-go review), M9 (optional mainnet small-amount).

## Memory

This is a learning project. M9 is optional and always small. If the factor stops working on mainnet, the right move is to go back to testnet to find a new factor, not add leverage.
