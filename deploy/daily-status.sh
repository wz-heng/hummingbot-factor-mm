#!/usr/bin/env bash
# Daily M6 status check. Run from VPS as any user.
# Usage:  bash /home/botuser/factor-mm/deploy/daily-status.sh
#         OR from your laptop:
#         ssh root@149.28.27.60 'bash /home/botuser/factor-mm/deploy/daily-status.sh'
#
# What it shows:
#   - uptime + service health
#   - cumulative PnL (TradeFill-based, ground truth)
#   - today's PnL + fill count
#   - inventory state distribution (% time within soft cap)
#   - health-check budget consumed (kill triggers, ob-age violations)
#   - last 5 fills

set -u

PY=/home/botuser/miniconda3/envs/hummingbot/bin/python
TRADES_DB=/home/botuser/hummingbot/data/factor_mm.sqlite
METRICS_DB=/home/botuser/hummingbot/data/factor_metrics.sqlite

echo "================================================================="
echo "  Factor MM · M6 Daily Status  ·  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "================================================================="

echo
echo "--- Service health ---"
systemctl is-active hummingbot factor-dashboard 2>/dev/null
echo "uptime: $(systemctl show hummingbot -p ActiveEnterTimestamp --value)"
echo "restarts since boot: $(systemctl show hummingbot -p NRestarts --value)"

echo
echo "--- PnL summary (from TradeFill — ground truth) ---"
sudo -u botuser "$PY" - "$TRADES_DB" <<'PY'
import sqlite3, sys, datetime
db = sys.argv[1]
c = sqlite3.connect(db)
today_ms = int(datetime.datetime.combine(datetime.date.today(), datetime.time()).timestamp() * 1000)
def q(where, params=()):
    return c.execute(f"""
        SELECT count(*),
               coalesce(sum(CASE WHEN trade_type='SELL' THEN amount*price/1e12
                                                       ELSE -amount*price/1e12 END), 0)
               - coalesce(sum(trade_fee_in_quote/1e6), 0),
               coalesce(sum(trade_fee_in_quote/1e6), 0),
               coalesce(sum(amount*price/1e12), 0)
        FROM TradeFill WHERE {where}
    """, params).fetchone()
all_n, all_pnl, all_fees, all_notional = q("1=1")
tod_n, tod_pnl, tod_fees, tod_notional = q("timestamp >= ?", (today_ms,))
print(f"  Cumulative:  {all_n:6d} fills  ·  PnL {all_pnl:+8.2f} USDT  ·  fees {all_fees:7.2f}  ·  notional {all_notional:10.1f}")
print(f"  Today:       {tod_n:6d} fills  ·  PnL {tod_pnl:+8.2f} USDT  ·  fees {tod_fees:7.2f}  ·  notional {tod_notional:10.1f}")
PY

echo
echo "--- Inventory + health distribution (from factor_metrics, last 24h) ---"
sudo -u botuser "$PY" - "$METRICS_DB" <<'PY'
import sqlite3, sys, time
db = sys.argv[1]
c = sqlite3.connect(db)
cutoff_ms = int((time.time() - 86400) * 1000)
n = c.execute("SELECT count(*) FROM metrics WHERE ts >= ?", (cutoff_ms,)).fetchone()[0]
if n == 0:
    print("  (no metrics in last 24h)")
else:
    soft_cap = 0.01
    in_soft = c.execute(
        "SELECT count(*) FROM metrics WHERE ts >= ? AND abs(net_base) < ?",
        (cutoff_ms, soft_cap)
    ).fetchone()[0]
    in_soft_pct = 100.0 * in_soft / n
    pass_target = "✅" if in_soft_pct >= 90 else "❌"
    print(f"  Rows in last 24h:           {n}")
    print(f"  Time within soft_cap:       {in_soft_pct:.1f}%  (M8 target: ≥ 90%)  {pass_target}")

    ob_violations = c.execute(
        "SELECT count(*) FROM metrics WHERE ts >= ? AND ob_age_sec > 2.0",
        (cutoff_ms,)
    ).fetchone()[0]
    drift_violations = c.execute(
        "SELECT count(*) FROM metrics WHERE ts >= ? AND clock_drift_sec > 0.5",
        (cutoff_ms,)
    ).fetchone()[0]
    kills = c.execute(
        "SELECT count(*) FROM metrics WHERE ts >= ? AND kill_engaged = 1",
        (cutoff_ms,)
    ).fetchone()[0]
    print(f"  OB age > 2.0s:              {ob_violations} ticks")
    print(f"  Clock drift > 0.5s:         {drift_violations} ticks")
    print(f"  Kill engaged:               {kills} ticks")

    f = c.execute(
        "SELECT avg(factor_bp), min(factor_bp), max(factor_bp) FROM metrics WHERE ts >= ?",
        (cutoff_ms,)
    ).fetchone()
    print(f"  Factor (bp) avg/min/max:    {f[0]:+.2f} / {f[1]:+.2f} / {f[2]:+.2f}")
    print(f"  (M8 target: typical ±5 bp, not single-sided)")
PY

echo
echo "--- Last 5 fills ---"
sudo -u botuser "$PY" - "$TRADES_DB" <<'PY'
import sqlite3, sys, datetime
db = sys.argv[1]
c = sqlite3.connect(db)
for r in c.execute("""
    SELECT timestamp, trade_type, order_type, position, price, amount
    FROM TradeFill ORDER BY timestamp DESC LIMIT 5
""").fetchall():
    t = datetime.datetime.fromtimestamp(r[0]/1000).strftime('%m-%d %H:%M:%S')
    print(f"  {t}  {r[1]:5s} {r[2]:7s} {r[3]:5s}  px {r[4]/1e6:9.2f}  qty {r[5]/1e6:7.5f}")
PY

echo
echo "--- Errors in last 24h (filtered) ---"
journalctl -u hummingbot --since "24 hours ago" --no-pager 2>/dev/null \
  | grep -iE "error|exception|traceback|fatal|kill switch|halt" \
  | grep -v "MQTT" \
  | tail -10 \
  || echo "  (none — clean)"

echo
echo "================================================================="
