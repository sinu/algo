"""
Initiative Drive — Proper implementation from PDF rules.

KEY RULES FROM PDF:
1. Must be EXPLOSIVE: 80-90% body, high volume, high delta
2. Two types of pocket:
   - Type A (DR pocket on bullish bar): place limit order AT the DR level
   - Type B (DG pocket on bullish bar): wait for test, enter on retest
3. Must have <=2 pocket positions (too many = don't trade)
4. If multiple pockets, select the LOWEST one (discount)
5. Outside value area = better probability
6. Wick pocket: wait for break, then trade retest

WHAT THIS MEANS FOR DATA:
- The "pocket" is the actual PRICE LEVEL where DR/DG occurred
- We don't have exact price levels of DR, but we have dr_above_mid / dr_below_mid
- For bullish bar: DR above midpoint = DR in body (Type A signal)
                   DG below midpoint = DG in lower area (Type B signal — pocket in body)
- The key difference: entry is at the POCKET PRICE LEVEL, not just "within zone"

Since we don't have exact DR level prices, we'll approximate:
- DR in upper half of bullish bar → pocket ~= 60-75% of bar range (midpoint to top area)
- DG in lower body → pocket ~= 25-40% of bar range
- "Select lowest pocket" → we use the lower estimate

For BEARISH (mirror):
- DG below midpoint on bearish bar = buyers tried at bottom, failed
- DR above midpoint on bearish bar = absorption at top (Type B bearish)
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
# BULLISH Initiative Drive (LONG)
# =============================================================================
print(sep)
print("  INITIATIVE DRIVE — BULLISH (LONG)")
print("  Rules: body>=80%, high delta, DR pocket above mid")
print("  Entry: limit order at pocket level (price returns to DR zone)")
print(sep)
print()

def find_bullish_initiative(candles, i):
    """Check if candle[i] qualifies as bullish initiative drive."""
    c = candles[i]
    bar_range = c['high'] - c['low']
    if bar_range <= 0:
        return None
    if c['close'] <= c['open']:
        return None

    body = c['close'] - c['open']
    body_pct = body / bar_range

    atr = _compute_atr(candles, i)
    if atr <= 0:
        return None

    # Must be explosive: body >= X% (test multiple thresholds)
    # PDF says 80-90% but let's validate what works in data
    # Also need high delta
    dr_above = c.get('dr_above_mid', 0)
    dr_below = c.get('dr_below_mid', 0)
    dg_above = c.get('dg_above_mid', 0)
    dg_below = c.get('dg_below_mid', 0)
    total_dr = c.get('local_dr', 0)

    # Pocket count (DR levels in the body/upper area = pockets)
    pocket_count = dr_above  # For bullish, DR above mid = pocket positions

    return {
        'body_pct': body_pct,
        'delta': c['delta'],
        'rvol': c.get('rvol', 1.0),
        'atr': atr,
        'bar_range': bar_range,
        'dr_above': dr_above,
        'dr_below': dr_below,
        'dg_below': dg_below,
        'total_dr': total_dr,
        'pocket_count': pocket_count,
        'poc_pos': c.get('poc_position', 0.5),
        'high': c['high'],
        'low': c['low'],
        'open': c['open'],
        'close': c['close'],
    }


def run_initiative_long(body_min, delta_min, dr_min, max_pockets, zone_pcts, rr,
                         pb_filter=None, max_pb_bars=6, max_hold=12):
    """
    Run bullish initiative drive backtest.
    zone_pcts: (low_pct, high_pct) of bar range for pocket location
    """
    trades = []

    for fname in all_files:
        date_str = fname.replace('.json', '')
        with open(os.path.join(DATA_DIR, fname)) as f:
            candles = json.load(f)
        if len(candles) < 14:
            continue

        for i in range(3, len(candles) - 5):
            info = find_bullish_initiative(candles, i)
            if info is None:
                continue

            # Filters
            if info['body_pct'] < body_min:
                continue
            if info['delta'] < delta_min:
                continue
            if info['dr_above'] < dr_min:
                continue
            if max_pockets > 0 and info['dr_above'] > max_pockets:
                continue  # Too many pockets = skip

            c = candles[i]
            atr = info['atr']
            bar_range = info['bar_range']

            # Pocket zone (where limit order would be placed)
            # "Select the lowest pocket" = use lower bound
            pocket_low = c['low'] + bar_range * zone_pcts[0]
            pocket_high = c['low'] + bar_range * zone_pcts[1]

            # Wait for price to come to pocket (limit order fill simulation)
            for j in range(i + 1, min(i + max_pb_bars + 1, len(candles) - 3)):
                pbc = candles[j]

                # Limit order: price must touch pocket level
                # For bullish, the LOW of pullback bar must reach the pocket
                if pbc['low'] > pocket_high:
                    continue  # Price hasn't reached pocket yet

                # Price must not blow through pocket (stop would be hit)
                if pbc['low'] < pocket_low - atr * 0.10:
                    break  # Broke the pocket, pattern failed

                # Apply pullback filter
                if pb_filter and not pb_filter(pbc):
                    continue

                # Limit order entry at pocket midpoint (simulating limit fill)
                entry = (pocket_low + pocket_high) / 2
                # If bar opened below entry, entry = open (can't get better)
                if pbc['open'] < entry:
                    entry = pbc['close']  # Market entry on close instead
                    if entry < pocket_low:
                        continue

                stop = pocket_low - atr * 0.10
                risk = entry - stop
                if risk <= 0 or risk > atr * 1.5:
                    continue
                target = entry + risk * rr

                # Check if stop was hit on the ENTRY bar itself
                if pbc['low'] <= stop:
                    trades.append({
                        'date': date_str, 'time': pbc['time'], 'win': False,
                        'exp_time': c['time'], 'pb_bars': j - i,
                        'hour': int(c['time'].split(':')[0]),
                        'body_pct': info['body_pct'],
                        'delta': info['delta'],
                        'dr_above': info['dr_above'],
                        'poc_pos': info['poc_pos'],
                        'rvol': info['rvol'],
                        'range_atr': bar_range / atr,
                    })
                    break

                # Evaluate outcome from next bars
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
                    'body_pct': info['body_pct'],
                    'delta': info['delta'],
                    'dr_above': info['dr_above'],
                    'poc_pos': info['poc_pos'],
                    'rvol': info['rvol'],
                    'range_atr': bar_range / atr,
                })
                break

    return trades


def report(name, trades, rr):
    total = len(trades)
    if total < 5:
        print(f"  {name:<55} n={total} (too few)")
        return None
    wins = sum(1 for t in trades if t['win'])
    losses = total - wins
    wr = wins / total * 100
    net = wins * rr - losses
    exp = net / total
    print(f"  {name:<55} n={total:>3} WR={wr:.1f}% net={net:+.1f}R exp={exp:+.3f}")
    return {'n': total, 'w': wins, 'net': net}


# =============================================================================
# Test body% thresholds (PDF says 80-90%)
# =============================================================================
print("  --- Body % sensitivity (with dr_above>=1, delta>0) ---")
for body in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
    trades = run_initiative_long(
        body_min=body, delta_min=0, dr_min=1, max_pockets=0,
        zone_pcts=(0.45, 0.70), rr=1.5
    )
    report(f"body>={body:.0%} dr>=1 delta>0", trades, 1.5)

# =============================================================================
# Test with stricter body + delta (as PDF suggests high delta)
# =============================================================================
print("\n  --- Body>=75% + delta thresholds ---")
for delta in [0, 3000, 5000, 8000, 10000]:
    trades = run_initiative_long(
        body_min=0.75, delta_min=delta, dr_min=1, max_pockets=0,
        zone_pcts=(0.45, 0.70), rr=1.5
    )
    report(f"body>=75% dr>=1 delta>{delta}", trades, 1.5)

print("\n  --- Body>=80% + delta thresholds ---")
for delta in [0, 3000, 5000, 8000]:
    trades = run_initiative_long(
        body_min=0.80, delta_min=delta, dr_min=1, max_pockets=0,
        zone_pcts=(0.45, 0.70), rr=1.5
    )
    report(f"body>=80% dr>=1 delta>{delta}", trades, 1.5)

# =============================================================================
# Test max_pockets rule (PDF: must have <=2 pockets)
# =============================================================================
print("\n  --- Max pockets (PDF: <=2, skip if more) ---")
for mp in [1, 2, 3, 99]:
    trades = run_initiative_long(
        body_min=0.75, delta_min=3000, dr_min=1, max_pockets=mp,
        zone_pcts=(0.45, 0.70), rr=1.5
    )
    label = f"max_pockets<={mp}" if mp < 99 else "no limit"
    report(f"body>=75% delta>3000 {label}", trades, 1.5)

# =============================================================================
# Test zone definitions
# =============================================================================
print("\n  --- Zone definitions (pocket level position) ---")
zones = [
    ("50-75%", (0.50, 0.75)),
    ("45-70%", (0.45, 0.70)),
    ("40-65%", (0.40, 0.65)),
    ("50-70%", (0.50, 0.70)),
    ("55-80%", (0.55, 0.80)),
    ("45-75%", (0.45, 0.75)),
    ("40-60%", (0.40, 0.60)),
]
for zn, zp in zones:
    trades = run_initiative_long(
        body_min=0.75, delta_min=3000, dr_min=1, max_pockets=2,
        zone_pcts=zp, rr=1.5
    )
    report(f"body>=75% delta>3000 pkt<=2 zone={zn}", trades, 1.5)

# =============================================================================
# Test R:R
# =============================================================================
print("\n  --- R:R sensitivity (best config so far) ---")
for rr in [1.0, 1.2, 1.5, 2.0, 2.5]:
    trades = run_initiative_long(
        body_min=0.75, delta_min=3000, dr_min=1, max_pockets=2,
        zone_pcts=(0.45, 0.70), rr=rr
    )
    report(f"RR={rr}", trades, rr)

# =============================================================================
# BEARISH Initiative Drive (SHORT)
# =============================================================================
print()
print(sep)
print("  INITIATIVE DRIVE — BEARISH (SHORT)")
print("  Rules: body>=X%, negative delta, DG pocket below mid")
print(sep)
print()

def run_initiative_short(body_min, delta_max, dg_min, max_pockets, zone_pcts, rr,
                          pb_filter=None, max_pb_bars=6, max_hold=12):
    """Run bearish initiative drive backtest."""
    trades = []

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
            body = c['open'] - c['close']
            body_pct = body / bar_range
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

            # Pocket zone for SHORT: the DG is in lower half of bearish bar
            # Mirror: pullback UP to the pocket level (30-55% from low)
            pocket_low = c['low'] + bar_range * zone_pcts[0]
            pocket_high = c['low'] + bar_range * zone_pcts[1]

            for j in range(i + 1, min(i + max_pb_bars + 1, len(candles) - 3)):
                pbc = candles[j]
                # Pullback UP: HIGH must reach pocket
                if pbc['high'] < pocket_low:
                    continue
                if pbc['high'] > pocket_high + atr * 0.10:
                    break  # Broke above pocket

                if pb_filter and not pb_filter(pbc):
                    continue

                # Limit order at pocket midpoint (short)
                entry = (pocket_low + pocket_high) / 2
                if pbc['open'] > entry:
                    entry = pbc['close']
                    if entry > pocket_high:
                        continue

                stop = pocket_high + atr * 0.10
                risk = stop - entry
                if risk <= 0 or risk > atr * 1.5:
                    continue
                target = entry - risk * rr

                # Check entry bar
                if pbc['high'] >= stop:
                    trades.append({
                        'date': date_str, 'time': pbc['time'], 'win': False,
                        'exp_time': c['time'], 'pb_bars': j - i,
                        'hour': int(c['time'].split(':')[0]),
                        'body_pct': body_pct,
                        'delta': c['delta'],
                        'dg_below': dg_below,
                        'rvol': c.get('rvol', 1.0),
                        'range_atr': bar_range / atr,
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
                    'body_pct': body_pct,
                    'delta': c['delta'],
                    'dg_below': dg_below,
                    'rvol': c.get('rvol', 1.0),
                    'range_atr': bar_range / atr,
                })
                break

    return trades


# Test body% for SHORT
print("  --- Body % sensitivity (with dg_below>=1, delta<0) ---")
for body in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
    trades = run_initiative_short(
        body_min=body, delta_max=0, dg_min=1, max_pockets=0,
        zone_pcts=(0.30, 0.55), rr=1.5
    )
    report(f"body>={body:.0%} dg>=1 delta<0", trades, 1.5)

print("\n  --- Body>=75% + delta thresholds (SHORT) ---")
for delta in [0, -3000, -5000, -8000]:
    trades = run_initiative_short(
        body_min=0.75, delta_max=delta, dg_min=1, max_pockets=0,
        zone_pcts=(0.30, 0.55), rr=1.5
    )
    report(f"body>=75% dg>=1 delta<{delta}", trades, 1.5)

print("\n  --- Max pockets SHORT ---")
for mp in [1, 2, 99]:
    trades = run_initiative_short(
        body_min=0.75, delta_max=0, dg_min=1, max_pockets=mp,
        zone_pcts=(0.30, 0.55), rr=1.5
    )
    label = f"max_pockets<={mp}" if mp < 99 else "no limit"
    report(f"body>=75% delta<0 {label}", trades, 1.5)

print("\n  --- Zone definitions (SHORT) ---")
zones_s = [
    ("25-50%", (0.25, 0.50)),
    ("30-55%", (0.30, 0.55)),
    ("30-60%", (0.30, 0.60)),
    ("35-55%", (0.35, 0.55)),
    ("25-55%", (0.25, 0.55)),
    ("35-60%", (0.35, 0.60)),
]
for zn, zp in zones_s:
    trades = run_initiative_short(
        body_min=0.75, delta_max=0, dg_min=1, max_pockets=2,
        zone_pcts=zp, rr=1.5
    )
    report(f"body>=75% delta<0 pkt<=2 zone={zn}", trades, 1.5)

print("\n  --- R:R sensitivity (SHORT best config) ---")
for rr in [1.0, 1.2, 1.5, 2.0, 2.5]:
    trades = run_initiative_short(
        body_min=0.75, delta_max=0, dg_min=1, max_pockets=2,
        zone_pcts=(0.30, 0.55), rr=rr
    )
    report(f"RR={rr}", trades, rr)

# =============================================================================
# MONTE CARLO on best configurations
# =============================================================================
print()
print(sep)
print("  MONTE CARLO VALIDATION")
print(sep)
print()

# LONG best
print("  LONG candidates:")
long_configs = [
    ("body>=75% delta>3000 dr>=1 pkt<=2", 0.75, 3000, 1, 2, (0.45, 0.70)),
    ("body>=75% delta>5000 dr>=1 pkt<=2", 0.75, 5000, 1, 2, (0.45, 0.70)),
    ("body>=80% delta>0 dr>=1 pkt<=2", 0.80, 0, 1, 2, (0.45, 0.70)),
    ("body>=80% delta>3000 dr>=1 pkt<=2", 0.80, 3000, 1, 2, (0.45, 0.70)),
    ("body>=70% delta>5000 dr>=1 pkt<=2", 0.70, 5000, 1, 2, (0.45, 0.70)),
]

# Broader LONG baseline (any bullish pullback to zone, no DR filter)
long_broad = run_initiative_long(
    body_min=0.55, delta_min=0, dr_min=0, max_pockets=0,
    zone_pcts=(0.45, 0.70), rr=1.5
)
print(f"  Broader baseline (body>=55% any pullback): n={len(long_broad)}")
bw = sum(1 for t in long_broad if t['win'])
print(f"  Baseline WR: {bw/len(long_broad)*100:.1f}%")
print()

for name, bm, dm, dr, mp, zp in long_configs:
    trades = run_initiative_long(
        body_min=bm, delta_min=dm, dr_min=dr, max_pockets=mp,
        zone_pcts=zp, rr=1.5
    )
    n = len(trades)
    if n < 5:
        print(f"  {name}: n={n} (too few)")
        continue
    w = sum(1 for t in trades if t['win'])
    net = w * 1.5 - (n - w)
    if net <= 0:
        print(f"  {name}: n={n} WR={w/n*100:.1f}% net={net:+.1f}R (negative)")
        continue

    # MC vs broader baseline
    better = 0
    for _ in range(TRIALS):
        sample = random.sample(long_broad, min(n, len(long_broad)))
        sw = sum(1 for t in sample if t['win'])
        if sw >= w:
            better += 1
    p = better / TRIALS
    sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else 'ns'
    print(f"  {name:<50} n={n:>3} WR={w/n*100:.1f}% net={net:+.1f}R p={p:.5f} [{sig}]")

    # Monthly if significant
    if p < 0.10:
        monthly = defaultdict(list)
        for t in trades:
            monthly[t['date'][:7]].append(t)
        pos = sum(1 for m, ts in monthly.items()
                  if sum(1 for t in ts if t['win'])*1.5 - sum(1 for t in ts if not t['win']) > 0)
        print(f"    Profitable months: {pos}/{len(monthly)}")

# SHORT best
print()
print("  SHORT candidates:")
short_broad = run_initiative_short(
    body_min=0.55, delta_max=0, dg_min=0, max_pockets=0,
    zone_pcts=(0.30, 0.55), rr=1.5
)
print(f"  Broader baseline (body>=55% delta<0 any pullback): n={len(short_broad)}")
sbw = sum(1 for t in short_broad if t['win'])
print(f"  Baseline WR: {sbw/len(short_broad)*100:.1f}%")
print()

short_configs = [
    ("body>=75% delta<0 dg>=1 pkt<=2", 0.75, 0, 1, 2, (0.30, 0.55)),
    ("body>=75% delta<-3000 dg>=1 pkt<=2", 0.75, -3000, 1, 2, (0.30, 0.55)),
    ("body>=75% delta<-5000 dg>=1 pkt<=2", 0.75, -5000, 1, 2, (0.30, 0.55)),
    ("body>=80% delta<0 dg>=1 pkt<=2", 0.80, 0, 1, 2, (0.30, 0.55)),
    ("body>=70% delta<0 dg>=1 pkt<=2", 0.70, 0, 1, 2, (0.30, 0.55)),
    ("body>=65% delta<0 dg>=1 pkt<=2", 0.65, 0, 1, 2, (0.30, 0.55)),
]

for name, bm, dm, dg, mp, zp in short_configs:
    trades = run_initiative_short(
        body_min=bm, delta_max=dm, dg_min=dg, max_pockets=mp,
        zone_pcts=zp, rr=1.5
    )
    n = len(trades)
    if n < 5:
        print(f"  {name}: n={n} (too few)")
        continue
    w = sum(1 for t in trades if t['win'])
    net = w * 1.5 - (n - w)
    if net <= 0:
        print(f"  {name}: n={n} WR={w/n*100:.1f}% net={net:+.1f}R (negative)")
        continue

    better = 0
    for _ in range(TRIALS):
        sample = random.sample(short_broad, min(n, len(short_broad)))
        sw = sum(1 for t in sample if t['win'])
        if sw >= w:
            better += 1
    p = better / TRIALS
    sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else 'ns'
    print(f"  {name:<50} n={n:>3} WR={w/n*100:.1f}% net={net:+.1f}R p={p:.5f} [{sig}]")

    if p < 0.10:
        monthly = defaultdict(list)
        for t in trades:
            monthly[t['date'][:7]].append(t)
        pos = sum(1 for m, ts in monthly.items()
                  if sum(1 for t in ts if t['win'])*1.5 - sum(1 for t in ts if not t['win']) > 0)
        print(f"    Profitable months: {pos}/{len(monthly)}")

        # OOS split
        sorted_t = sorted(trades, key=lambda t: t['date'])
        half = len(sorted_t) // 2
        f1w = sum(1 for t in sorted_t[:half] if t['win'])
        f2w = sum(1 for t in sorted_t[half:] if t['win'])
        print(f"    OOS: first={f1w}/{half} WR={f1w/half*100:.0f}% | second={f2w}/{len(sorted_t)-half} WR={f2w/(len(sorted_t)-half)*100:.0f}%")

print()
print(sep)
print("  SUMMARY")
print(sep)
