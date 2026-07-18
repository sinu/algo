"""
Initiative Drive V2 — Fix limit order fill logic.

CRITICAL FIX:
  Previous version had entry = zone_midpoint regardless of whether
  price actually reached that level. A limit order at price X only
  fills if bar's low <= X (for LONG) or bar's high >= X (for SHORT).

Also: compare properly—
  1. Simple market entry (close of pullback bar) vs limit entry
  2. With/without DR/DG requirement
  3. Proper validation of whether the pattern edge is real
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
# LONG: Correct limit order logic
# =============================================================================

def run_long(body_min, delta_min, dr_min, max_pockets, zone_pcts, rr,
             entry_mode='limit', max_pb_bars=6, max_hold=12):
    """
    entry_mode:
      'limit' = limit order at zone midpoint (only fills if low <= midpoint)
      'market' = market entry at close of pullback bar (if close >= zone_low)
      'limit_low' = limit at zone_low (discount level - most conservative)
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

                # Price must pull back to the zone
                if pbc['low'] > pocket_high:
                    continue  # Hasn't reached zone

                # Price must not break well below zone
                if pbc['low'] < pocket_low - atr * 0.10:
                    break  # Pattern broken

                # Entry logic depends on mode
                if entry_mode == 'limit':
                    # Limit order at midpoint: fills only if low <= midpoint
                    if pbc['low'] > pocket_mid:
                        continue  # Limit not filled
                    entry = pocket_mid
                elif entry_mode == 'limit_low':
                    # Limit at zone low (discount): fills if low <= pocket_low
                    if pbc['low'] > pocket_low:
                        continue
                    entry = pocket_low
                else:  # market
                    # Market entry: close of pullback bar, if it held above zone_low
                    if pbc['close'] < pocket_low:
                        continue
                    entry = pbc['close']

                stop = pocket_low - atr * 0.10
                risk = entry - stop
                if risk <= 0 or risk > atr * 1.5:
                    continue
                target = entry + risk * rr

                # Check if stop hit on entry bar (only for limit orders)
                if entry_mode in ('limit', 'limit_low'):
                    if pbc['low'] <= stop:
                        # Stop was hit on same bar (limit filled then immediately stopped)
                        trades.append({
                            'date': date_str, 'time': pbc['time'], 'win': False,
                            'exp_time': c['time'], 'pb_bars': j - i,
                            'hour': int(c['time'].split(':')[0]),
                            'body_pct': body_pct, 'dr_above': dr_above,
                            'delta': c['delta'], 'rvol': c.get('rvol', 1.0),
                        })
                        break

                # Check if target hit on entry bar (for limit orders)
                if entry_mode in ('limit', 'limit_low'):
                    if pbc['high'] >= target:
                        trades.append({
                            'date': date_str, 'time': pbc['time'], 'win': True,
                            'exp_time': c['time'], 'pb_bars': j - i,
                            'hour': int(c['time'].split(':')[0]),
                            'body_pct': body_pct, 'dr_above': dr_above,
                            'delta': c['delta'], 'rvol': c.get('rvol', 1.0),
                        })
                        break

                # Evaluate future bars
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
                })
                break

    return trades


def run_short(body_min, delta_max, dg_min, max_pockets, zone_pcts, rr,
              entry_mode='limit', max_pb_bars=6, max_hold=12):
    """Mirror for SHORT."""
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

            # SHORT zone: upper area of bearish bar (pullback up)
            pocket_low = c['low'] + bar_range * zone_low_pct
            pocket_high = c['low'] + bar_range * zone_high_pct
            pocket_mid = (pocket_low + pocket_high) / 2

            for j in range(i + 1, min(i + max_pb_bars + 1, len(candles) - 3)):
                pbc = candles[j]

                # Pullback UP: HIGH must reach zone
                if pbc['high'] < pocket_low:
                    continue
                if pbc['high'] > pocket_high + atr * 0.10:
                    break  # Broke above zone

                if entry_mode == 'limit':
                    # Limit order at midpoint: fills if high >= midpoint
                    if pbc['high'] < pocket_mid:
                        continue
                    entry = pocket_mid
                elif entry_mode == 'limit_high':
                    if pbc['high'] < pocket_high:
                        continue
                    entry = pocket_high
                else:  # market
                    if pbc['close'] > pocket_high:
                        continue
                    entry = pbc['close']

                stop = pocket_high + atr * 0.10
                risk = stop - entry
                if risk <= 0 or risk > atr * 1.5:
                    continue
                target = entry - risk * rr

                # Stop on entry bar
                if entry_mode in ('limit', 'limit_high'):
                    if pbc['high'] >= stop:
                        trades.append({
                            'date': date_str, 'time': pbc['time'], 'win': False,
                            'exp_time': c['time'], 'pb_bars': j - i,
                            'hour': int(c['time'].split(':')[0]),
                            'body_pct': body_pct, 'dg_below': dg_below,
                            'delta': c['delta'], 'rvol': c.get('rvol', 1.0),
                        })
                        break

                # Target on entry bar
                if entry_mode in ('limit', 'limit_high'):
                    if pbc['low'] <= target:
                        trades.append({
                            'date': date_str, 'time': pbc['time'], 'win': True,
                            'exp_time': c['time'], 'pb_bars': j - i,
                            'hour': int(c['time'].split(':')[0]),
                            'body_pct': body_pct, 'dg_below': dg_below,
                            'delta': c['delta'], 'rvol': c.get('rvol', 1.0),
                        })
                        break

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
                })
                break

    return trades


def report(name, trades, rr):
    total = len(trades)
    if total < 5:
        print(f"  {name:<60} n={total} (too few)")
        return None
    wins = sum(1 for t in trades if t['win'])
    losses = total - wins
    wr = wins / total * 100
    net = wins * rr - losses
    exp = net / total
    print(f"  {name:<60} n={total:>3} WR={wr:.1f}% net={net:+.1f}R exp={exp:+.3f}")
    return {'n': total, 'w': wins, 'net': net}


# =============================================================================
# LONG: Correct limit vs market entry comparison
# =============================================================================
print(sep)
print("  LONG: LIMIT vs MARKET entry (correct fill logic)")
print(sep)
print()

print("  --- Entry mode comparison (body>=75%, delta>0, dr_above>=1, zone=50-75%) ---")
for mode in ['limit', 'market']:
    for rr in [1.2, 1.5, 2.0]:
        trades = run_long(
            body_min=0.75, delta_min=0, dr_min=1, max_pockets=2,
            zone_pcts=(0.50, 0.75), rr=rr, entry_mode=mode
        )
        report(f"{mode} RR={rr}", trades, rr)
    print()

print("  --- Without DR requirement (is the pocket zone enough?) ---")
for mode in ['limit', 'market']:
    for rr in [1.2, 1.5, 2.0]:
        trades = run_long(
            body_min=0.75, delta_min=0, dr_min=0, max_pockets=0,
            zone_pcts=(0.50, 0.75), rr=rr, entry_mode=mode
        )
        report(f"{mode} NO_DR RR={rr}", trades, rr)
    print()

# =============================================================================
# LONG: Body threshold with fixed correct limit
# =============================================================================
print("  --- Body threshold sensitivity (limit entry, zone=50-75%, RR=1.5) ---")
for body in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
    for dr in [0, 1]:
        trades = run_long(
            body_min=body, delta_min=0, dr_min=dr, max_pockets=2,
            zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit'
        )
        label = f"dr>={dr}" if dr > 0 else "no_dr"
        report(f"body>={body:.0%} {label}", trades, 1.5)

print()
print("  --- Zone sensitivity (body>=75% dr>=1 limit RR=1.5) ---")
zones = [
    ("40-65%", (0.40, 0.65)),
    ("45-70%", (0.45, 0.70)),
    ("50-75%", (0.50, 0.75)),
    ("55-80%", (0.55, 0.80)),
    ("50-70%", (0.50, 0.70)),
    ("45-75%", (0.45, 0.75)),
]
for zn, zp in zones:
    trades = run_long(
        body_min=0.75, delta_min=0, dr_min=1, max_pockets=2,
        zone_pcts=zp, rr=1.5, entry_mode='limit'
    )
    report(f"zone={zn}", trades, 1.5)

# =============================================================================
# SHORT: Same analysis
# =============================================================================
print()
print(sep)
print("  SHORT: LIMIT vs MARKET entry (correct fill logic)")
print(sep)
print()

print("  --- Entry mode comparison (body>=75%, delta<0, dg_below>=1, zone=30-55%) ---")
for mode in ['limit', 'market']:
    for rr in [1.2, 1.5, 2.0]:
        trades = run_short(
            body_min=0.75, delta_max=0, dg_min=1, max_pockets=2,
            zone_pcts=(0.30, 0.55), rr=rr, entry_mode=mode
        )
        report(f"{mode} RR={rr}", trades, rr)
    print()

print("  --- Without DG requirement ---")
for mode in ['limit', 'market']:
    for rr in [1.2, 1.5, 2.0]:
        trades = run_short(
            body_min=0.75, delta_max=0, dg_min=0, max_pockets=0,
            zone_pcts=(0.30, 0.55), rr=rr, entry_mode=mode
        )
        report(f"{mode} NO_DG RR={rr}", trades, rr)
    print()

# =============================================================================
# MONTE CARLO: Test whether DR/DG adds value over baseline
# =============================================================================
print(sep)
print("  MONTE CARLO: Does DR/DG filter add edge over baseline?")
print(sep)
print()

# LONG: Compare dr>=1 vs no_dr (same everything else)
print("  LONG (limit, body>=75%, zone=50-75%, RR=1.5):")
long_base = run_long(body_min=0.75, delta_min=0, dr_min=0, max_pockets=0,
                     zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit')
long_dr = run_long(body_min=0.75, delta_min=0, dr_min=1, max_pockets=2,
                   zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit')

n_base = len(long_base)
w_base = sum(1 for t in long_base if t['win'])
n_dr = len(long_dr)
w_dr = sum(1 for t in long_dr if t['win'])
print(f"  Baseline (no DR): n={n_base} WR={w_base/n_base*100:.1f}%")
print(f"  DR>=1:            n={n_dr} WR={w_dr/n_dr*100:.1f}%")

# MC: is DR subset significantly BETTER than random N from baseline?
if n_dr <= n_base and n_dr >= 5:
    better = 0
    for _ in range(TRIALS):
        sample = random.sample(long_base, n_dr)
        sw = sum(1 for t in sample if t['win'])
        if sw >= w_dr:
            better += 1
    p = better / TRIALS
    print(f"  MC p-value (DR>=1 vs baseline): {p:.5f}")
    print(f"  Conclusion: DR filter {'ADDS' if p < 0.05 else 'does NOT add'} significant value for LONG")

# SHORT: Compare dg>=1 vs no_dg
print()
print("  SHORT (limit, body>=75%, zone=30-55%, RR=1.5):")
short_base = run_short(body_min=0.75, delta_max=0, dg_min=0, max_pockets=0,
                       zone_pcts=(0.30, 0.55), rr=1.5, entry_mode='limit')
short_dg = run_short(body_min=0.75, delta_max=0, dg_min=1, max_pockets=2,
                     zone_pcts=(0.30, 0.55), rr=1.5, entry_mode='limit')

n_sbase = len(short_base)
w_sbase = sum(1 for t in short_base if t['win'])
n_sdg = len(short_dg)
w_sdg = sum(1 for t in short_dg if t['win'])
print(f"  Baseline (no DG): n={n_sbase} WR={w_sbase/n_sbase*100:.1f}%")
print(f"  DG>=1:            n={n_sdg} WR={w_sdg/n_sdg*100:.1f}%")

if n_sdg <= n_sbase and n_sdg >= 5:
    better = 0
    for _ in range(TRIALS):
        sample = random.sample(short_base, n_sdg)
        sw = sum(1 for t in sample if t['win'])
        if sw >= w_sdg:
            better += 1
    p = better / TRIALS
    print(f"  MC p-value (DG>=1 vs baseline): {p:.5f}")
    print(f"  Conclusion: DG filter {'ADDS' if p < 0.05 else 'does NOT add'} significant value for SHORT")

# =============================================================================
# THEN: Is the BASELINE itself significant? (explosive + pullback to zone)
# =============================================================================
print()
print(sep)
print("  IS THE BASELINE SIGNIFICANT? (explosive body>=75% + pullback to zone)")
print(sep)
print()

# Compare against ALL pullbacks to same zone (without body requirement)
print("  LONG: Compare body>=75% vs body>=50% (any strong pullback)")
long_all = run_long(body_min=0.50, delta_min=0, dr_min=0, max_pockets=0,
                    zone_pcts=(0.50, 0.75), rr=1.5, entry_mode='limit')
n_all = len(long_all)
w_all = sum(1 for t in long_all if t['win'])
print(f"  body>=50% (all): n={n_all} WR={w_all/n_all*100:.1f}%")
print(f"  body>=75% (explosive): n={n_base} WR={w_base/n_base*100:.1f}%")

if n_base <= n_all and n_base >= 5:
    better = 0
    for _ in range(TRIALS):
        sample = random.sample(long_all, n_base)
        sw = sum(1 for t in sample if t['win'])
        if sw >= w_base:
            better += 1
    p = better / TRIALS
    print(f"  MC p-value (body>=75% vs all): {p:.5f}")
    print(f"  Conclusion: {'YES' if p < 0.05 else 'NO'} — explosive body significantly better")

print()
print("  SHORT: Compare body>=75% vs body>=50% (any strong pullback)")
short_all = run_short(body_min=0.50, delta_max=0, dg_min=0, max_pockets=0,
                      zone_pcts=(0.30, 0.55), rr=1.5, entry_mode='limit')
n_sall = len(short_all)
w_sall = sum(1 for t in short_all if t['win'])
print(f"  body>=50% (all): n={n_sall} WR={w_sall/n_sall*100:.1f}%")
print(f"  body>=75% (explosive): n={n_sbase} WR={w_sbase/n_sbase*100:.1f}%")

if n_sbase <= n_sall and n_sbase >= 5:
    better = 0
    for _ in range(TRIALS):
        sample = random.sample(short_all, n_sbase)
        sw = sum(1 for t in sample if t['win'])
        if sw >= w_sbase:
            better += 1
    p = better / TRIALS
    print(f"  MC p-value (body>=75% vs all): {p:.5f}")
    print(f"  Conclusion: {'YES' if p < 0.05 else 'NO'} — explosive body significantly better")

# =============================================================================
# MONTHLY + EQUITY for best configs
# =============================================================================
print()
print(sep)
print("  MONTHLY BREAKDOWN — BEST CONFIGS")
print(sep)
print()

def monthly_report(name, trades, rr):
    if not trades:
        return
    total = len(trades)
    wins = sum(1 for t in trades if t['win'])
    net = wins * rr - (total - wins)
    print(f"\n  {name}: n={total} WR={wins/total*100:.1f}% net={net:+.1f}R exp={net/total:+.3f}R")
    monthly = defaultdict(list)
    for t in trades:
        monthly[t['date'][:7]].append(t)
    pos = 0
    for m in sorted(monthly.keys()):
        sub = monthly[m]
        w = sum(1 for t in sub if t['win'])
        mn = w * rr - (len(sub) - w)
        if mn > 0: pos += 1
        print(f"    {m}: n={len(sub)} WR={w/len(sub)*100:.0f}% net={mn:+.1f}R {'[+]' if mn>0 else '[-]'}")
    print(f"  Profitable months: {pos}/{len(monthly)}")

    # Equity curve stats
    sorted_t = sorted(trades, key=lambda t: (t['date'], t['time']))
    equity = [0.0]
    for t in sorted_t:
        equity.append(equity[-1] + (rr if t['win'] else -1.0))
    peak = max_dd = 0
    max_consec_loss = consec = 0
    for e in equity:
        if e > peak: peak = e
        dd = peak - e
        if dd > max_dd: max_dd = dd
    for t in sorted_t:
        if not t['win']:
            consec += 1
            max_consec_loss = max(max_consec_loss, consec)
        else:
            consec = 0
    print(f"  Max DD: {max_dd:.1f}R | Max consec loss: {max_consec_loss} | Recovery factor: {net/max_dd:.1f}" if max_dd > 0 else "")

# LONG best
monthly_report("LONG limit body>=75% dr>=1 zone=50-75% RR=1.5", long_dr, 1.5)

# SHORT best
monthly_report("SHORT limit body>=75% dg>=1 zone=30-55% RR=1.5", short_dg, 1.5)

# LONG baseline (no DR)
monthly_report("LONG baseline (no DR requirement) body>=75% zone=50-75% RR=1.5", long_base, 1.5)

# SHORT baseline (no DG)
monthly_report("SHORT baseline (no DG requirement) body>=75% zone=30-55% RR=1.5", short_base, 1.5)

# Combined: LONG + SHORT best
all_combined = long_dr + short_dg
monthly_report("COMBINED (LONG dr>=1 + SHORT dg>=1)", all_combined, 1.5)

# Combined baseline
all_base = long_base + short_base
monthly_report("COMBINED BASELINE (no DR/DG filter)", all_base, 1.5)

print()
print(sep)
print("  CONCLUSION")
print(sep)
