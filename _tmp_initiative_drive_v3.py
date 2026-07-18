"""
Initiative Drive V3 — FIXED look-ahead bias.

The problem in V2: When a limit order fills on bar J (because bar J's low
reaches the limit price), we CANNOT know whether the bar's high came BEFORE
or AFTER the low. So we can't count wins on the fill bar.

CORRECT LOGIC:
- Limit fills when pb_bar.low <= limit_price (for LONG)
- On fill bar: check ONLY if stop was hit (low < stop → loss)
  because if low went below stop, the order might have filled then
  immediately stopped out (or not filled at all if stop < limit)
- On fill bar: DO NOT count wins (high >= target is NOT reliable)
- Evaluate outcome starting from bar J+1

Also need to be careful: if the fill bar's low is below the stop,
the limit may not have filled at all (price went through). In that case
it's "pattern broken" not a loss.
"""
import json, sys, os, random, statistics
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reversal_algo_v17 import _compute_atr, TARGET_R

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v17_candle_data_merged")
all_files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith('.json')])

sep = "=" * 90
random.seed(42)
TRIALS = 50000

# =============================================================================
# LONG — Fixed limit logic
# =============================================================================

def run_long_fixed(body_min, delta_min, dr_min, max_pockets, zone_pcts, rr,
                   entry_mode='limit', max_pb_bars=6, max_hold=12):
    """
    FIXED: On limit fill bar, only check stop. Wins counted from next bar.
    """
    trades = []
    zone_low_pct, zone_high_pct = zone_pcts

    for fname in all_files:
        date_str = fname.replace('.json', '')
        with open(os.path.join(DATA_DIR, fname)) as f:
            candles = json.load(f)
        if len(candles) < 14:
            continue

        for i in range(3, len(candles) - 5):
            c = candles[i]
            bar_range = c['high'] - c['low']
            if bar_range <= 0 or c['close'] <= c['open']:
                continue
            body_pct = (c['close'] - c['open']) / bar_range
            atr = _compute_atr(candles, i)
            if atr <= 0:
                continue

            if body_pct < body_min:
                continue
            if c['delta'] < delta_min:
                continue

            dr_above = c.get('dr_above_mid', 0)
            if dr_above < dr_min:
                continue
            if max_pockets > 0 and dr_above > max_pockets:
                continue

            pocket_low = c['low'] + bar_range * zone_low_pct
            pocket_high = c['low'] + bar_range * zone_high_pct
            pocket_mid = (pocket_low + pocket_high) / 2

            for j in range(i + 1, min(i + max_pb_bars + 1, len(candles) - 3)):
                pbc = candles[j]

                if entry_mode == 'limit':
                    # Limit at zone midpoint
                    limit_price = pocket_mid
                elif entry_mode == 'limit_low':
                    limit_price = pocket_low
                else:
                    # Market: use close of pb bar
                    limit_price = None

                if limit_price is not None:
                    # LIMIT ORDER LOGIC
                    # Bar must reach limit (low <= limit_price for LONG buy)
                    if pbc['low'] > limit_price:
                        continue  # Limit not reached

                    # If bar blew through stop, pattern is broken
                    stop = pocket_low - atr * 0.10
                    if pbc['low'] < stop:
                        break  # Price went through zone, broken

                    entry = limit_price
                    risk = entry - stop
                    if risk <= 0 or risk > atr * 1.5:
                        continue
                    target = entry + risk * rr

                    # On fill bar: we CANNOT determine if target hit first
                    # Only from NEXT bar can we reliably evaluate
                    win = loss = False
                    for fut in range(j + 1, min(j + max_hold + 1, len(candles))):
                        fc = candles[fut]
                        if fc['low'] <= stop:
                            loss = True
                            break
                        if fc['high'] >= target:
                            win = True
                            break
                    if not win and not loss:
                        continue

                else:
                    # MARKET ENTRY LOGIC
                    if pbc['low'] > pocket_high:
                        continue
                    if pbc['low'] < pocket_low - atr * 0.05:
                        break
                    if pbc['close'] < pocket_low:
                        continue

                    entry = pbc['close']
                    stop = pocket_low - atr * 0.10
                    risk = entry - stop
                    if risk <= 0 or risk > atr * 1.5:
                        continue
                    target = entry + risk * rr

                    win = loss = False
                    for fut in range(j + 1, min(j + max_hold + 1, len(candles))):
                        fc = candles[fut]
                        if fc['low'] <= stop:
                            loss = True
                            break
                        if fc['high'] >= target:
                            win = True
                            break
                    if not win and not loss:
                        continue

                trades.append({
                    'date': date_str, 'time': pbc['time'], 'win': win,
                    'exp_time': c['time'], 'pb_bars': j - i,
                    'hour': int(c['time'].split(':')[0]),
                    'body_pct': body_pct, 'dr_above': dr_above,
                    'delta': c['delta'], 'rvol': c.get('rvol', 1.0),
                    'range_atr': bar_range / atr,
                    'pb_delta': pbc['delta'],
                })
                break

    return trades


def run_short_fixed(body_min, delta_max, dg_min, max_pockets, zone_pcts, rr,
                    entry_mode='limit', max_pb_bars=6, max_hold=12):
    """FIXED: Same fix for SHORT."""
    trades = []
    zone_low_pct, zone_high_pct = zone_pcts

    for fname in all_files:
        date_str = fname.replace('.json', '')
        with open(os.path.join(DATA_DIR, fname)) as f:
            candles = json.load(f)
        if len(candles) < 14:
            continue

        for i in range(3, len(candles) - 5):
            c = candles[i]
            bar_range = c['high'] - c['low']
            if bar_range <= 0 or c['close'] >= c['open']:
                continue
            body_pct = (c['open'] - c['close']) / bar_range
            atr = _compute_atr(candles, i)
            if atr <= 0:
                continue

            if body_pct < body_min:
                continue
            if c['delta'] > delta_max:
                continue

            dg_below = c.get('dg_below_mid', 0)
            if dg_below < dg_min:
                continue
            if max_pockets > 0 and dg_below > max_pockets:
                continue

            # SHORT: pocket is in lower area of bearish bar
            # Pullback UP means we SHORT when price reaches pocket
            pocket_low = c['low'] + bar_range * zone_low_pct
            pocket_high = c['low'] + bar_range * zone_high_pct
            pocket_mid = (pocket_low + pocket_high) / 2

            for j in range(i + 1, min(i + max_pb_bars + 1, len(candles) - 3)):
                pbc = candles[j]

                if entry_mode == 'limit':
                    limit_price = pocket_mid
                elif entry_mode == 'limit_high':
                    limit_price = pocket_high
                else:
                    limit_price = None

                if limit_price is not None:
                    # Limit for SHORT: fills when high >= limit_price
                    if pbc['high'] < limit_price:
                        continue

                    stop = pocket_high + atr * 0.10
                    if pbc['high'] > stop:
                        break  # Blew through

                    entry = limit_price
                    risk = stop - entry
                    if risk <= 0 or risk > atr * 1.5:
                        continue
                    target = entry - risk * rr

                    # Evaluate from NEXT bar only
                    win = loss = False
                    for fut in range(j + 1, min(j + max_hold + 1, len(candles))):
                        fc = candles[fut]
                        if fc['high'] >= stop:
                            loss = True
                            break
                        if fc['low'] <= target:
                            win = True
                            break
                    if not win and not loss:
                        continue

                else:
                    # Market entry
                    if pbc['high'] < pocket_low:
                        continue
                    if pbc['high'] > pocket_high + atr * 0.05:
                        break
                    if pbc['close'] > pocket_high:
                        continue

                    entry = pbc['close']
                    stop = pocket_high + atr * 0.10
                    risk = stop - entry
                    if risk <= 0 or risk > atr * 1.5:
                        continue
                    target = entry - risk * rr

                    win = loss = False
                    for fut in range(j + 1, min(j + max_hold + 1, len(candles))):
                        fc = candles[fut]
                        if fc['high'] >= stop:
                            loss = True
                            break
                        if fc['low'] <= target:
                            win = True
                            break
                    if not win and not loss:
                        continue

                trades.append({
                    'date': date_str, 'time': pbc['time'], 'win': win,
                    'exp_time': c['time'], 'pb_bars': j - i,
                    'hour': int(c['time'].split(':')[0]),
                    'body_pct': body_pct, 'dg_below': dg_below,
                    'delta': c['delta'], 'rvol': c.get('rvol', 1.0),
                    'range_atr': bar_range / atr,
                    'pb_delta': pbc['delta'],
                })
                break

    return trades


def rpt(name, trades, rr):
    n = len(trades)
    if n < 5:
        print(f"  {name:<60} n={n} (too few)")
        return None
    w = sum(1 for t in trades if t['win'])
    l = n - w
    wr = w / n * 100
    net = w * rr - l
    exp = net / n
    print(f"  {name:<60} n={n:>3} WR={wr:.1f}% net={net:+.1f}R exp={exp:+.3f}")
    return {'n': n, 'w': w, 'net': net, 'trades': trades}

# =============================================================================
# LONG TESTS
# =============================================================================
print(sep)
print("  LONG — FIXED (no look-ahead on fill bar)")
print(sep)
print()

print("  --- Entry mode comparison ---")
for mode in ['limit', 'market']:
    for rr in [1.2, 1.5, 2.0]:
        trades = run_long_fixed(
            body_min=0.75, delta_min=0, dr_min=1, max_pockets=2,
            zone_pcts=(0.50, 0.75), rr=rr, entry_mode=mode
        )
        rpt(f"LONG {mode} body>=75% dr>=1 zone=50-75% RR={rr}", trades, rr)
    print()

print("  --- Body thresholds (limit, dr>=1, zone=50-75%, RR=1.5) ---")
for body in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
    trades = run_long_fixed(
        body_min=body, delta_min=0, dr_min=1, max_pockets=2,
        zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit'
    )
    rpt(f"limit body>={body:.0%} dr>=1", trades, 1.5)

print()
print("  --- DR requirement (limit, body>=75%, zone=50-75%, RR=1.5) ---")
for dr in [0, 1, 2]:
    trades = run_long_fixed(
        body_min=0.75, delta_min=0, dr_min=dr, max_pockets=2 if dr > 0 else 0,
        zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit'
    )
    rpt(f"limit body>=75% dr>={dr}", trades, 1.5)

print()
print("  --- Delta thresholds (limit, body>=75%, dr>=1, zone=50-75%, RR=1.5) ---")
for delta in [0, 3000, 5000, 8000, 10000]:
    trades = run_long_fixed(
        body_min=0.75, delta_min=delta, dr_min=1, max_pockets=2,
        zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit'
    )
    rpt(f"limit body>=75% dr>=1 delta>{delta}", trades, 1.5)

print()
print("  --- Zone sensitivity (limit, body>=75%, dr>=1, RR=1.5) ---")
zones = [
    ("40-65%", (0.40, 0.65)),
    ("45-70%", (0.45, 0.70)),
    ("50-75%", (0.50, 0.75)),
    ("55-80%", (0.55, 0.80)),
    ("45-65%", (0.45, 0.65)),
    ("50-70%", (0.50, 0.70)),
]
for zn, zp in zones:
    trades = run_long_fixed(
        body_min=0.75, delta_min=0, dr_min=1, max_pockets=2,
        zone_pcts=zp, rr=1.5, entry_mode='limit'
    )
    rpt(f"zone={zn}", trades, 1.5)

# =============================================================================
# SHORT TESTS
# =============================================================================
print()
print(sep)
print("  SHORT — FIXED (no look-ahead on fill bar)")
print(sep)
print()

print("  --- Entry mode comparison ---")
for mode in ['limit', 'market']:
    for rr in [1.2, 1.5, 2.0]:
        trades = run_short_fixed(
            body_min=0.75, delta_max=0, dg_min=1, max_pockets=2,
            zone_pcts=(0.30, 0.55), rr=rr, entry_mode=mode
        )
        rpt(f"SHORT {mode} body>=75% dg>=1 zone=30-55% RR={rr}", trades, rr)
    print()

print("  --- Body thresholds (limit, dg>=1, zone=30-55%, RR=1.5) ---")
for body in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
    trades = run_short_fixed(
        body_min=body, delta_max=0, dg_min=1, max_pockets=2,
        zone_pcts=(0.30, 0.55), rr=1.5, entry_mode='limit'
    )
    rpt(f"limit body>={body:.0%} dg>=1", trades, 1.5)

print()
print("  --- DG requirement (limit, body>=75%, zone=30-55%, RR=1.5) ---")
for dg in [0, 1, 2]:
    trades = run_short_fixed(
        body_min=0.75, delta_max=0, dg_min=dg, max_pockets=2 if dg > 0 else 0,
        zone_pcts=(0.30, 0.55), rr=1.5, entry_mode='limit'
    )
    rpt(f"limit body>=75% dg>={dg}", trades, 1.5)

print()
print("  --- Zone sensitivity (limit, body>=75%, dg>=1, RR=1.5) ---")
zones_s = [
    ("25-50%", (0.25, 0.50)),
    ("30-55%", (0.30, 0.55)),
    ("35-60%", (0.35, 0.60)),
    ("25-55%", (0.25, 0.55)),
    ("30-50%", (0.30, 0.50)),
    ("35-55%", (0.35, 0.55)),
]
for zn, zp in zones_s:
    trades = run_short_fixed(
        body_min=0.75, delta_max=0, dg_min=1, max_pockets=2,
        zone_pcts=zp, rr=1.5, entry_mode='limit'
    )
    rpt(f"zone={zn}", trades, 1.5)

# =============================================================================
# MONTE CARLO — Test DR/DG value-add (fixed version)
# =============================================================================
print()
print(sep)
print("  MONTE CARLO — FIXED VERSION")
print(sep)
print()

# LONG: dr>=1 vs no requirement
print("  LONG (limit, body>=75%, zone=50-75%, RR=1.5):")
long_base = run_long_fixed(body_min=0.75, delta_min=0, dr_min=0, max_pockets=0,
                           zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit')
long_dr = run_long_fixed(body_min=0.75, delta_min=0, dr_min=1, max_pockets=2,
                         zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit')
n_b = len(long_base)
w_b = sum(1 for t in long_base if t['win'])
n_d = len(long_dr)
w_d = sum(1 for t in long_dr if t['win'])
print(f"  Baseline: n={n_b} WR={w_b/n_b*100:.1f}%")
print(f"  DR>=1:    n={n_d} WR={w_d/n_d*100:.1f}%")
if n_d <= n_b and n_d >= 5:
    better = 0
    for _ in range(TRIALS):
        sample = random.sample(long_base, n_d)
        sw = sum(1 for t in sample if t['win'])
        if sw >= w_d:
            better += 1
    p = better / TRIALS
    sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else 'ns'
    print(f"  MC p-value: {p:.5f} [{sig}]")

# With delta filter
print()
long_delta = run_long_fixed(body_min=0.75, delta_min=5000, dr_min=1, max_pockets=2,
                            zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit')
n_dd = len(long_delta)
w_dd = sum(1 for t in long_delta if t['win'])
print(f"  DR>=1 + delta>5000: n={n_dd} WR={w_dd/n_dd*100:.1f}%" if n_dd >= 5 else f"  n={n_dd} too few")
if n_dd <= n_b and n_dd >= 5:
    better = 0
    for _ in range(TRIALS):
        sample = random.sample(long_base, n_dd)
        sw = sum(1 for t in sample if t['win'])
        if sw >= w_dd:
            better += 1
    p = better / TRIALS
    sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else 'ns'
    print(f"  MC p-value: {p:.5f} [{sig}]")

# SHORT
print()
print("  SHORT (limit, body>=75%, zone=30-55%, RR=1.5):")
short_base = run_short_fixed(body_min=0.75, delta_max=0, dg_min=0, max_pockets=0,
                             zone_pcts=(0.30, 0.55), rr=1.5, entry_mode='limit')
short_dg = run_short_fixed(body_min=0.75, delta_max=0, dg_min=1, max_pockets=2,
                           zone_pcts=(0.30, 0.55), rr=1.5, entry_mode='limit')
n_sb = len(short_base)
w_sb = sum(1 for t in short_base if t['win'])
n_sd = len(short_dg)
w_sd = sum(1 for t in short_dg if t['win'])
print(f"  Baseline: n={n_sb} WR={w_sb/n_sb*100:.1f}%")
print(f"  DG>=1:    n={n_sd} WR={w_sd/n_sd*100:.1f}%")
if n_sd <= n_sb and n_sd >= 5:
    better = 0
    for _ in range(TRIALS):
        sample = random.sample(short_base, n_sd)
        sw = sum(1 for t in sample if t['win'])
        if sw >= w_sd:
            better += 1
    p = better / TRIALS
    sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else 'ns'
    print(f"  MC p-value: {p:.5f} [{sig}]")

# =============================================================================
# MARKET ENTRY DEEP DIVE (this is the realistic one)
# =============================================================================
print()
print(sep)
print("  MARKET ENTRY — DEEP DIVE (realistic for algo)")
print(sep)
print()

# LONG market
print("  LONG MARKET (body>=75% dr>=1 zone=50-75%):")
for rr in [1.0, 1.2, 1.5, 2.0]:
    trades = run_long_fixed(
        body_min=0.75, delta_min=0, dr_min=1, max_pockets=2,
        zone_pcts=(0.50, 0.75), rr=rr, entry_mode='market'
    )
    rpt(f"RR={rr}", trades, rr)

print()
print("  LONG MARKET body>=75% + filters (zone=50-75%, RR=1.5):")
base_long_mkt = run_long_fixed(
    body_min=0.75, delta_min=0, dr_min=0, max_pockets=0,
    zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='market'
)
dr1_long_mkt = run_long_fixed(
    body_min=0.75, delta_min=0, dr_min=1, max_pockets=2,
    zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='market'
)
rpt("baseline (no DR)", base_long_mkt, 1.5)
rpt("dr>=1", dr1_long_mkt, 1.5)

# Additional filters on market trades
if dr1_long_mkt:
    print()
    print("  Filters on LONG market dr>=1 trades:")
    for fname, fn in [
        ("pb_delta>0", lambda t: t['pb_delta'] > 0),
        ("delta>5000", lambda t: t['delta'] > 5000),
        ("delta>5000 + pb_delta>0", lambda t: t['delta'] > 5000 and t['pb_delta'] > 0),
        ("rvol>=1.0", lambda t: t['rvol'] >= 1.0),
        ("range>=0.8ATR", lambda t: t['range_atr'] >= 0.8),
        ("body>=80%", lambda t: t['body_pct'] >= 0.80),
        ("body>=80% + delta>5000", lambda t: t['body_pct'] >= 0.80 and t['delta'] > 5000),
    ]:
        sub = [t for t in dr1_long_mkt if fn(t)]
        if len(sub) >= 5:
            w = sum(1 for t in sub if t['win'])
            net = w * 1.5 - (len(sub) - w)
            print(f"    {fname:<40} n={len(sub):>3} WR={w/len(sub)*100:.1f}% net={net:+.1f}R")

# SHORT market
print()
print("  SHORT MARKET (body>=75% dg>=1 zone=30-55%):")
for rr in [1.0, 1.2, 1.5, 2.0]:
    trades = run_short_fixed(
        body_min=0.75, delta_max=0, dg_min=1, max_pockets=2,
        zone_pcts=(0.30, 0.55), rr=rr, entry_mode='market'
    )
    rpt(f"RR={rr}", trades, rr)

print()
print("  SHORT MARKET body>=75% + filters (zone=30-55%, RR=1.5):")
base_short_mkt = run_short_fixed(
    body_min=0.75, delta_max=0, dg_min=0, max_pockets=0,
    zone_pcts=(0.30, 0.55), rr=1.5, entry_mode='market'
)
dg1_short_mkt = run_short_fixed(
    body_min=0.75, delta_max=0, dg_min=1, max_pockets=2,
    zone_pcts=(0.30, 0.55), rr=1.5, entry_mode='market'
)
rpt("baseline (no DG)", base_short_mkt, 1.5)
rpt("dg>=1", dg1_short_mkt, 1.5)

if dg1_short_mkt:
    print()
    print("  Filters on SHORT market dg>=1 trades:")
    for fname, fn in [
        ("pb_delta<0", lambda t: t['pb_delta'] < 0),
        ("delta<-5000", lambda t: t['delta'] < -5000),
        ("delta<-5000 + pb_delta<0", lambda t: t['delta'] < -5000 and t['pb_delta'] < 0),
        ("rvol>=1.0", lambda t: t['rvol'] >= 1.0),
        ("range>=0.8ATR", lambda t: t['range_atr'] >= 0.8),
        ("body>=80%", lambda t: t['body_pct'] >= 0.80),
        ("body>=80% + delta<-5000", lambda t: t['body_pct'] >= 0.80 and t['delta'] < -5000),
    ]:
        sub = [t for t in dg1_short_mkt if fn(t)]
        if len(sub) >= 5:
            w = sum(1 for t in sub if t['win'])
            net = w * 1.5 - (len(sub) - w)
            print(f"    {fname:<40} n={len(sub):>3} WR={w/len(sub)*100:.1f}% net={net:+.1f}R")

# =============================================================================
# MC on market entry patterns
# =============================================================================
print()
print(sep)
print("  MC ON MARKET ENTRY (realistic)")
print(sep)
print()

# LONG market: dr>=1 vs baseline
if dr1_long_mkt and base_long_mkt:
    n_lm = len(dr1_long_mkt)
    w_lm = sum(1 for t in dr1_long_mkt if t['win'])
    n_lb = len(base_long_mkt)
    w_lb = sum(1 for t in base_long_mkt if t['win'])
    print(f"  LONG market: baseline n={n_lb} WR={w_lb/n_lb*100:.1f}% | dr>=1 n={n_lm} WR={w_lm/n_lm*100:.1f}%")
    if n_lm <= n_lb and n_lm >= 5:
        better = 0
        for _ in range(TRIALS):
            sample = random.sample(base_long_mkt, n_lm)
            sw = sum(1 for t in sample if t['win'])
            if sw >= w_lm:
                better += 1
        p = better / TRIALS
        print(f"  MC p-value (dr>=1 vs base): {p:.5f}")

    # With delta>5000 + pb_delta>0
    long_best_mkt = [t for t in dr1_long_mkt if t['delta'] > 5000 and t['pb_delta'] > 0]
    if len(long_best_mkt) >= 5:
        n_lbm = len(long_best_mkt)
        w_lbm = sum(1 for t in long_best_mkt if t['win'])
        print(f"  dr>=1 + delta>5000 + pb_delta>0: n={n_lbm} WR={w_lbm/n_lbm*100:.1f}%")
        better = 0
        for _ in range(TRIALS):
            sample = random.sample(base_long_mkt, min(n_lbm, n_lb))
            sw = sum(1 for t in sample if t['win'])
            if sw >= w_lbm:
                better += 1
        p = better / TRIALS
        sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else 'ns'
        print(f"  MC p-value: {p:.5f} [{sig}]")

# SHORT market: dg>=1 vs baseline
print()
if dg1_short_mkt and base_short_mkt:
    n_sm = len(dg1_short_mkt)
    w_sm = sum(1 for t in dg1_short_mkt if t['win'])
    n_sb2 = len(base_short_mkt)
    w_sb2 = sum(1 for t in base_short_mkt if t['win'])
    print(f"  SHORT market: baseline n={n_sb2} WR={w_sb2/n_sb2*100:.1f}% | dg>=1 n={n_sm} WR={w_sm/n_sm*100:.1f}%")
    if n_sm <= n_sb2 and n_sm >= 5:
        better = 0
        for _ in range(TRIALS):
            sample = random.sample(base_short_mkt, n_sm)
            sw = sum(1 for t in sample if t['win'])
            if sw >= w_sm:
                better += 1
        p = better / TRIALS
        sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else 'ns'
        print(f"  MC p-value (dg>=1 vs base): {p:.5f} [{sig}]")

print()
print(sep)
print("  DONE")
print(sep)
