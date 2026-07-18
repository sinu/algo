"""Final summary of Initiative Drive patterns."""
import json, sys, os, random
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reversal_algo_v17 import _compute_atr, TARGET_R

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v17_candle_data_merged")
all_files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith('.json')])

sep = "=" * 90
random.seed(42)
TRIALS = 50000


def run_long_limit(body_min, dr_min, zone_pcts, rr):
    trades = []
    for fname in all_files:
        date_str = fname.replace('.json', '')
        with open(os.path.join(DATA_DIR, fname)) as f:
            candles = json.load(f)
        if len(candles) < 14:
            continue
        for i in range(3, len(candles) - 5):
            c = candles[i]
            br = c['high'] - c['low']
            if br <= 0 or c['close'] <= c['open']:
                continue
            bp = (c['close'] - c['open']) / br
            atr = _compute_atr(candles, i)
            if atr <= 0:
                continue
            if bp < body_min or c['delta'] <= 0:
                continue
            if c.get('dr_above_mid', 0) < dr_min:
                continue

            pl = c['low'] + br * zone_pcts[0]
            ph = c['low'] + br * zone_pcts[1]
            pm = (pl + ph) / 2

            for j in range(i + 1, min(i + 7, len(candles) - 3)):
                pbc = candles[j]
                if pbc['low'] > pm:
                    continue
                stop = pl - atr * 0.10
                if pbc['low'] < stop:
                    break

                entry = pm
                risk = entry - stop
                if risk <= 0 or risk > atr * 1.5:
                    continue
                target = entry + risk * rr

                win = loss = False
                for fut in range(j + 1, min(j + 13, len(candles))):
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
                })
                break
    return trades


def run_short_limit(body_min, dg_min, zone_pcts, rr):
    trades = []
    for fname in all_files:
        date_str = fname.replace('.json', '')
        with open(os.path.join(DATA_DIR, fname)) as f:
            candles = json.load(f)
        if len(candles) < 14:
            continue
        for i in range(3, len(candles) - 5):
            c = candles[i]
            br = c['high'] - c['low']
            if br <= 0 or c['close'] >= c['open']:
                continue
            bp = (c['open'] - c['close']) / br
            atr = _compute_atr(candles, i)
            if atr <= 0:
                continue
            if bp < body_min or c['delta'] >= 0:
                continue
            if c.get('dg_below_mid', 0) < dg_min:
                continue

            pl = c['low'] + br * zone_pcts[0]
            ph = c['low'] + br * zone_pcts[1]
            pm = (pl + ph) / 2

            for j in range(i + 1, min(i + 7, len(candles) - 3)):
                pbc = candles[j]
                if pbc['high'] < pm:
                    continue
                stop = ph + atr * 0.10
                if pbc['high'] > stop:
                    break

                entry = pm
                risk = stop - entry
                if risk <= 0 or risk > atr * 1.5:
                    continue
                target = entry - risk * rr

                win = loss = False
                for fut in range(j + 1, min(j + 13, len(candles))):
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
                })
                break
    return trades


def run_short_market(body_min, dg_min, zone_pcts, rr):
    trades = []
    for fname in all_files:
        date_str = fname.replace('.json', '')
        with open(os.path.join(DATA_DIR, fname)) as f:
            candles = json.load(f)
        if len(candles) < 14:
            continue
        for i in range(3, len(candles) - 5):
            c = candles[i]
            br = c['high'] - c['low']
            if br <= 0 or c['close'] >= c['open']:
                continue
            bp = (c['open'] - c['close']) / br
            atr = _compute_atr(candles, i)
            if atr <= 0:
                continue
            if bp < body_min or c['delta'] >= 0:
                continue
            if c.get('dg_below_mid', 0) < dg_min:
                continue

            pl = c['low'] + br * zone_pcts[0]
            ph = c['low'] + br * zone_pcts[1]

            for j in range(i + 1, min(i + 7, len(candles) - 3)):
                pbc = candles[j]
                if pbc['high'] < pl:
                    continue
                if pbc['high'] > ph + atr * 0.05:
                    break
                if pbc['close'] > ph:
                    continue

                entry = pbc['close']
                stop = ph + atr * 0.10
                risk = stop - entry
                if risk <= 0 or risk > atr * 1.5:
                    continue
                target = entry - risk * rr

                win = loss = False
                for fut in range(j + 1, min(j + 13, len(candles))):
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
                })
                break
    return trades


def show_detail(name, trades, rr):
    n = len(trades)
    w = sum(1 for t in trades if t['win'])
    net = w * rr - (n - w)
    print(f"\n  {name}")
    print(f"  n={n} WR={w/n*100:.1f}% net={net:+.1f}R exp={net/n:+.3f}R")
    print()

    monthly = defaultdict(list)
    for t in trades:
        monthly[t['date'][:7]].append(t)
    pos = 0
    for m in sorted(monthly):
        sub = monthly[m]
        mw = sum(1 for t in sub if t['win'])
        mn = mw * rr - (len(sub) - mw)
        if mn > 0:
            pos += 1
        print(f"    {m}: n={len(sub)} WR={mw/len(sub)*100:.0f}% net={mn:+.1f}R")
    print(f"  Profitable months: {pos}/{len(monthly)}")

    # Equity stats
    sorted_t = sorted(trades, key=lambda x: (x['date'], x['time']))
    eq = [0]
    for t in sorted_t:
        eq.append(eq[-1] + (rr if t['win'] else -1))
    peak = max_dd = 0
    max_cl = cl = 0
    for e in eq:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd
    for t in sorted_t:
        if not t['win']:
            cl += 1
            max_cl = max(max_cl, cl)
        else:
            cl = 0
    print(f"  Max DD: {max_dd:.1f}R | Max consec loss: {max_cl} | Recovery: {net/max_dd:.1f}x" if max_dd > 0 else "")

    # OOS split
    half = len(sorted_t) // 2
    f1 = sorted_t[:half]
    f2 = sorted_t[half:]
    fw = sum(1 for t in f1 if t['win'])
    sw = sum(1 for t in f2 if t['win'])
    print(f"  OOS: first n={len(f1)} WR={fw/len(f1)*100:.0f}% | second n={len(f2)} WR={sw/len(f2)*100:.0f}%")

    # All trades
    print(f"\n  All trades:")
    for t in sorted_t:
        print(f"    {t['date']} exp@{t['exp_time']} entry@{t['time']} pb={t['pb_bars']} {'WIN' if t['win'] else 'LOSS'}")


# =============================================================================
# 1. LONG LIMIT (the PDF-described pattern)
# =============================================================================
print(sep)
print("  INITIATIVE DRIVE — FINAL VALIDATED PATTERNS")
print(sep)

# Best LONG: body>=70%, dr_above>=1, limit at 50-75% zone midpoint
long_dr = run_long_limit(0.70, 1, (0.50, 0.75), 1.5)
show_detail("LONG LIMIT: body>=70% dr_above>=1 zone=50-75% RR=1.5", long_dr, 1.5)

# MC for LONG
long_base = run_long_limit(0.70, 0, (0.50, 0.75), 1.5)
n_b = len(long_base)
w_b = sum(1 for t in long_base if t['win'])
n_d = len(long_dr)
w_d = sum(1 for t in long_dr if t['win'])
print(f"\n  MC: Baseline (no DR) n={n_b} WR={w_b/n_b*100:.1f}%")
print(f"  MC: DR>=1 n={n_d} WR={w_d/n_d*100:.1f}%")
better = 0
for _ in range(TRIALS):
    s = random.sample(long_base, n_d)
    sw = sum(1 for t in s if t['win'])
    if sw >= w_d:
        better += 1
p = better / TRIALS
print(f"  MC p-value: {p:.5f}")

# =============================================================================
# 2. SHORT LIMIT
# =============================================================================
short_dg = run_short_limit(0.70, 1, (0.35, 0.60), 1.5)
show_detail("SHORT LIMIT: body>=70% dg_below>=1 zone=35-60% RR=1.5", short_dg, 1.5)

short_base = run_short_limit(0.70, 0, (0.35, 0.60), 1.5)
n_sb = len(short_base)
w_sb = sum(1 for t in short_base if t['win'])
n_sd = len(short_dg)
w_sd = sum(1 for t in short_dg if t['win'])
print(f"\n  MC: Baseline (no DG) n={n_sb} WR={w_sb/n_sb*100:.1f}%")
print(f"  MC: DG>=1 n={n_sd} WR={w_sd/n_sd*100:.1f}%")
better = 0
for _ in range(TRIALS):
    s = random.sample(short_base, min(n_sd, n_sb))
    sw = sum(1 for t in s if t['win'])
    if sw >= w_sd:
        better += 1
p = better / TRIALS
print(f"  MC p-value: {p:.5f}")

# =============================================================================
# 3. SHORT MARKET (for algo implementation)
# =============================================================================
short_mkt = run_short_market(0.70, 1, (0.30, 0.55), 1.5)
show_detail("SHORT MARKET: body>=70% dg_below>=1 zone=30-55% RR=1.5", short_mkt, 1.5)

short_mkt_base = run_short_market(0.70, 0, (0.30, 0.55), 1.5)
n_smb = len(short_mkt_base)
w_smb = sum(1 for t in short_mkt_base if t['win'])
n_smd = len(short_mkt)
w_smd = sum(1 for t in short_mkt if t['win'])
print(f"\n  MC: Baseline (no DG) n={n_smb} WR={w_smb/n_smb*100:.1f}%")
print(f"  MC: DG>=1 n={n_smd} WR={w_smd/n_smd*100:.1f}%")
better = 0
for _ in range(TRIALS):
    s = random.sample(short_mkt_base, min(n_smd, n_smb))
    sw = sum(1 for t in s if t['win'])
    if sw >= w_smd:
        better += 1
p = better / TRIALS
print(f"  MC p-value: {p:.5f}")

# =============================================================================
# COMBINED
# =============================================================================
print()
print(sep)
print("  COMBINED (LONG limit + SHORT limit)")
print(sep)
combined = long_dr + short_dg
cw = sum(1 for t in combined if t['win'])
cn = len(combined)
cnet = cw * 1.5 - (cn - cw)
print(f"  n={cn} WR={cw/cn*100:.1f}% net={cnet:+.1f}R exp={cnet/cn:+.3f}R")
print(f"  ~{cn/52:.1f} trades/week")

monthly = defaultdict(list)
for t in combined:
    monthly[t['date'][:7]].append(t)
pos = 0
for m in sorted(monthly):
    sub = monthly[m]
    mw = sum(1 for t in sub if t['win'])
    mn = mw * 1.5 - (len(sub) - mw)
    if mn > 0:
        pos += 1
    print(f"    {m}: n={len(sub)} WR={mw/len(sub)*100:.0f}% net={mn:+.1f}R")
print(f"  Profitable months: {pos}/{len(monthly)}")
