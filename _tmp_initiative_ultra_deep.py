"""
Initiative Drive — Ultra-deep analysis.
Explore EVERY possible filter to maximize win rate.

Dimensions to test:
1. Body % threshold (70/75/80/85/90)
2. Range vs ATR (bar size relative to volatility)
3. Delta strength (absolute and relative)
4. DR/DG count and position
5. Rvol (volume relative to average)
6. POC position
7. Pullback bar quality (delta, DG/DR, close position, wick)
8. Number of bars to pullback (1-6)
9. Time of day (morning vs midday vs afternoon)
10. Trend context (prior 3-5 bars direction)
11. Entry technique (limit at pocket mid, limit at pocket low, market)
12. Zone width (tight vs wide)
13. Prior bar relationship (gap up/down, inside bar)
14. Multi-pocket vs single pocket
15. Has_dr_l_dr pattern
"""
import json, sys, os, random, statistics
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reversal_algo_v17 import _compute_atr, TARGET_R

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v17_candle_data_merged")
all_files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith('.json')])

sep = "=" * 90
RR = 1.5

# =============================================================================
# Build FULL feature-rich trade pool (both LONG and SHORT)
# Use limit entry (the PDF approach) with bias-free logic
# =============================================================================

def build_pool_long():
    """Build LONG trade pool with all possible features."""
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
            if bp < 0.60 or c['delta'] <= 0:
                continue

            # Zone: 50-75% of bar (upper body area)
            pl = c['low'] + br * 0.50
            ph = c['low'] + br * 0.75
            pm = (pl + ph) / 2

            # Look for limit fill
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
                target = entry + risk * RR

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

                # Compute ALL features
                hour = int(c['time'].split(':')[0])
                pb_br = pbc['high'] - pbc['low']
                pb_close_pos = (pbc['close'] - pbc['low']) / pb_br if pb_br > 0 else 0.5
                pb_low_wick = (min(pbc['open'], pbc['close']) - pbc['low']) / pb_br if pb_br > 0 else 0

                # Trend context: direction of prior 3 bars
                prior_up = sum(1 for k in range(max(0, i-3), i) if candles[k]['close'] > candles[k]['open'])
                prior_delta_sum = sum(candles[k]['delta'] for k in range(max(0, i-3), i))

                # Is this bar a breakout? (close > prior 3 bars high)
                prior_high = max(candles[k]['high'] for k in range(max(0, i-3), i))
                is_breakout = c['close'] > prior_high

                # Gap from previous bar
                prev = candles[i-1]
                gap_up = c['open'] > prev['high']

                trades.append({
                    'date': date_str, 'time': pbc['time'], 'win': win,
                    'exp_time': c['time'], 'pb_bars': j - i,
                    'hour': hour,
                    # Explosive bar features
                    'body_pct': bp,
                    'delta': c['delta'],
                    'rvol': c.get('rvol', 1.0),
                    'range_atr': br / atr,
                    'dr_above': c.get('dr_above_mid', 0),
                    'dr_below': c.get('dr_below_mid', 0),
                    'dg_above': c.get('dg_above_mid', 0),
                    'dg_below': c.get('dg_below_mid', 0),
                    'local_dr': c.get('local_dr', 0),
                    'local_dg': c.get('local_dg', 0),
                    'has_dr_l_dr': c.get('has_dr_l_dr', False),
                    'poc_pos': c.get('poc_position', 0.5),
                    'bid_dom': c.get('bid_dom_levels', 0),
                    'ask_dom': c.get('ask_dom_levels', 0),
                    'book_ratio': c.get('book_pressure_ratio', 1.0),
                    'is_churn': c.get('is_churn', False),
                    # Pullback bar features
                    'pb_delta': pbc['delta'],
                    'pb_dg': pbc.get('local_dg', 0),
                    'pb_dr': pbc.get('local_dr', 0),
                    'pb_close_pos': pb_close_pos,
                    'pb_low_wick': pb_low_wick,
                    'pb_is_green': pbc['close'] >= pbc['open'],
                    'pb_floor_abs': pbc.get('floor_abs', 0),
                    'pb_rvol': pbc.get('rvol', 1.0),
                    'pb_range_atr': pb_br / atr if atr > 0 else 0,
                    # Context features
                    'prior_up': prior_up,
                    'prior_delta_sum': prior_delta_sum,
                    'is_breakout': is_breakout,
                    'gap_up': gap_up,
                    'risk_atr': risk / atr,
                })
                break
    return trades


def build_pool_short():
    """Build SHORT trade pool."""
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
            if bp < 0.60 or c['delta'] >= 0:
                continue

            # Zone: 25-50% of bar (lower body area for SHORT pocket)
            pl = c['low'] + br * 0.25
            ph = c['low'] + br * 0.50
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
                target = entry - risk * RR

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

                hour = int(c['time'].split(':')[0])
                pb_br = pbc['high'] - pbc['low']
                pb_close_pos = (pbc['close'] - pbc['low']) / pb_br if pb_br > 0 else 0.5
                pb_high_wick = (pbc['high'] - max(pbc['open'], pbc['close'])) / pb_br if pb_br > 0 else 0

                prior_dn = sum(1 for k in range(max(0, i-3), i) if candles[k]['close'] < candles[k]['open'])
                prior_delta_sum = sum(candles[k]['delta'] for k in range(max(0, i-3), i))
                prior_low = min(candles[k]['low'] for k in range(max(0, i-3), i))
                is_breakdown = c['close'] < prior_low
                prev = candles[i-1]
                gap_dn = c['open'] < prev['low']

                trades.append({
                    'date': date_str, 'time': pbc['time'], 'win': win,
                    'exp_time': c['time'], 'pb_bars': j - i,
                    'hour': hour,
                    'body_pct': bp,
                    'delta': c['delta'],
                    'rvol': c.get('rvol', 1.0),
                    'range_atr': br / atr,
                    'dg_below': c.get('dg_below_mid', 0),
                    'dg_above': c.get('dg_above_mid', 0),
                    'dr_above': c.get('dr_above_mid', 0),
                    'dr_below': c.get('dr_below_mid', 0),
                    'local_dr': c.get('local_dr', 0),
                    'local_dg': c.get('local_dg', 0),
                    'has_dg_l_dg': c.get('has_dg_l_dg', False),
                    'poc_pos': c.get('poc_position', 0.5),
                    'bid_dom': c.get('bid_dom_levels', 0),
                    'ask_dom': c.get('ask_dom_levels', 0),
                    'book_ratio': c.get('book_pressure_ratio', 1.0),
                    'is_churn': c.get('is_churn', False),
                    'pb_delta': pbc['delta'],
                    'pb_dr': pbc.get('local_dr', 0),
                    'pb_dg': pbc.get('local_dg', 0),
                    'pb_close_pos': pb_close_pos,
                    'pb_high_wick': pb_high_wick,
                    'pb_is_red': pbc['close'] < pbc['open'],
                    'pb_ceil_abs': pbc.get('ceil_abs', 0),
                    'pb_rvol': pbc.get('rvol', 1.0),
                    'pb_range_atr': pb_br / atr if atr > 0 else 0,
                    'prior_dn': prior_dn,
                    'prior_delta_sum': prior_delta_sum,
                    'is_breakdown': is_breakdown,
                    'gap_dn': gap_dn,
                    'risk_atr': risk / atr,
                })
                break
    return trades


print("Building trade pools...")
long_pool = build_pool_long()
short_pool = build_pool_short()
print(f"LONG pool: {len(long_pool)} trades, WR={sum(1 for t in long_pool if t['win'])/len(long_pool)*100:.1f}%")
print(f"SHORT pool: {len(short_pool)} trades, WR={sum(1 for t in short_pool if t['win'])/len(short_pool)*100:.1f}%")
print()

# =============================================================================
# EXHAUSTIVE SINGLE-FILTER SCAN
# =============================================================================

def scan_filters(pool, filters, label):
    """Test all single filters, rank by WR and net R."""
    results = []
    base_wr = sum(1 for t in pool if t['win']) / len(pool) * 100
    print(f"\n  --- {label} (baseline WR={base_wr:.1f}%, n={len(pool)}) ---")
    for name, fn in filters:
        match = [t for t in pool if fn(t)]
        if len(match) < 8:
            continue
        w = sum(1 for t in match if t['win'])
        wr = w / len(match) * 100
        net = w * RR - (len(match) - w)
        lift = wr - base_wr
        results.append((name, len(match), wr, net, lift))

    # Sort by WR descending
    results.sort(key=lambda x: -x[2])
    for name, n, wr, net, lift in results[:30]:
        print(f"    {name:<50} n={n:>3} WR={wr:.1f}% net={net:+.1f}R lift={lift:+.1f}pp")
    return results


# LONG filters
long_filters = [
    # Body
    ("body>=70%", lambda t: t['body_pct'] >= 0.70),
    ("body>=75%", lambda t: t['body_pct'] >= 0.75),
    ("body>=80%", lambda t: t['body_pct'] >= 0.80),
    ("body>=85%", lambda t: t['body_pct'] >= 0.85),
    ("body>=90%", lambda t: t['body_pct'] >= 0.90),
    # Range/ATR
    ("range>=0.6ATR", lambda t: t['range_atr'] >= 0.6),
    ("range>=0.8ATR", lambda t: t['range_atr'] >= 0.8),
    ("range>=1.0ATR", lambda t: t['range_atr'] >= 1.0),
    ("range>=1.2ATR", lambda t: t['range_atr'] >= 1.2),
    ("range<0.8ATR", lambda t: t['range_atr'] < 0.8),
    # Delta
    ("delta>3000", lambda t: t['delta'] > 3000),
    ("delta>5000", lambda t: t['delta'] > 5000),
    ("delta>8000", lambda t: t['delta'] > 8000),
    ("delta>10000", lambda t: t['delta'] > 10000),
    ("delta>15000", lambda t: t['delta'] > 15000),
    # Rvol
    ("rvol>=0.8", lambda t: t['rvol'] >= 0.8),
    ("rvol>=1.0", lambda t: t['rvol'] >= 1.0),
    ("rvol>=1.2", lambda t: t['rvol'] >= 1.2),
    ("rvol>=1.5", lambda t: t['rvol'] >= 1.5),
    # DR/DG
    ("dr_above>=1", lambda t: t['dr_above'] >= 1),
    ("dr_above>=2", lambda t: t['dr_above'] >= 2),
    ("dr_above==0", lambda t: t['dr_above'] == 0),
    ("local_dr>=1", lambda t: t['local_dr'] >= 1),
    ("local_dr>=2", lambda t: t['local_dr'] >= 2),
    ("local_dr>=3", lambda t: t['local_dr'] >= 3),
    ("has_dr_l_dr", lambda t: t['has_dr_l_dr']),
    ("dg_below>=1", lambda t: t['dg_below'] >= 1),
    # POC
    ("poc<0.3", lambda t: t['poc_pos'] < 0.3),
    ("poc<0.4", lambda t: t['poc_pos'] < 0.4),
    ("poc<0.5", lambda t: t['poc_pos'] < 0.5),
    ("poc>=0.5", lambda t: t['poc_pos'] >= 0.5),
    ("poc>=0.6", lambda t: t['poc_pos'] >= 0.6),
    # DOM
    ("bid_dom>=3", lambda t: t['bid_dom'] >= 3),
    ("bid_dom>=5", lambda t: t['bid_dom'] >= 5),
    ("book_ratio>1.5", lambda t: t['book_ratio'] > 1.5),
    ("book_ratio>2.0", lambda t: t['book_ratio'] > 2.0),
    # Pullback
    ("pb_delta>0", lambda t: t['pb_delta'] > 0),
    ("pb_delta<0", lambda t: t['pb_delta'] < 0),
    ("pb_dg>=1", lambda t: t['pb_dg'] >= 1),
    ("pb_dg>=2", lambda t: t['pb_dg'] >= 2),
    ("pb_floor_abs>=1", lambda t: t['pb_floor_abs'] >= 1),
    ("pb_close_pos>0.5", lambda t: t['pb_close_pos'] > 0.5),
    ("pb_close_pos>0.6", lambda t: t['pb_close_pos'] > 0.6),
    ("pb_close_pos>0.7", lambda t: t['pb_close_pos'] > 0.7),
    ("pb_is_green", lambda t: t['pb_is_green']),
    ("pb_low_wick>0.2", lambda t: t['pb_low_wick'] > 0.2),
    ("pb_low_wick>0.3", lambda t: t['pb_low_wick'] > 0.3),
    ("pb_bars==1", lambda t: t['pb_bars'] == 1),
    ("pb_bars<=2", lambda t: t['pb_bars'] <= 2),
    ("pb_bars<=3", lambda t: t['pb_bars'] <= 3),
    ("pb_bars>=2", lambda t: t['pb_bars'] >= 2),
    ("pb_rvol<1.0", lambda t: t['pb_rvol'] < 1.0),
    ("pb_range<0.5ATR", lambda t: t['pb_range_atr'] < 0.5),
    ("pb_range<0.7ATR", lambda t: t['pb_range_atr'] < 0.7),
    # Time
    ("hour<=10", lambda t: t['hour'] <= 10),
    ("hour<=11", lambda t: t['hour'] <= 11),
    ("hour>=11", lambda t: t['hour'] >= 11),
    ("hour>=12", lambda t: t['hour'] >= 12),
    ("hour>=13", lambda t: t['hour'] >= 13),
    ("9-11am", lambda t: 9 <= t['hour'] <= 11),
    ("11am-1pm", lambda t: 11 <= t['hour'] <= 13),
    ("1pm-3pm", lambda t: 13 <= t['hour'] <= 15),
    # Context
    ("prior_up>=2", lambda t: t['prior_up'] >= 2),
    ("prior_up==3", lambda t: t['prior_up'] == 3),
    ("prior_up<=1", lambda t: t['prior_up'] <= 1),
    ("prior_delta>0", lambda t: t['prior_delta_sum'] > 0),
    ("prior_delta>5000", lambda t: t['prior_delta_sum'] > 5000),
    ("is_breakout", lambda t: t['is_breakout']),
    ("not_breakout", lambda t: not t['is_breakout']),
    ("gap_up", lambda t: t['gap_up']),
    # Risk
    ("risk<0.3ATR", lambda t: t['risk_atr'] < 0.3),
    ("risk<0.4ATR", lambda t: t['risk_atr'] < 0.4),
    ("risk<0.5ATR", lambda t: t['risk_atr'] < 0.5),
    # NOT churn
    ("not_churn", lambda t: not t['is_churn']),
]

print(sep)
print("  LONG — SINGLE FILTER SCAN (sorted by WR)")
print(sep)
long_results = scan_filters(long_pool, long_filters, "LONG")

# SHORT filters
short_filters = [
    ("body>=70%", lambda t: t['body_pct'] >= 0.70),
    ("body>=75%", lambda t: t['body_pct'] >= 0.75),
    ("body>=80%", lambda t: t['body_pct'] >= 0.80),
    ("body>=85%", lambda t: t['body_pct'] >= 0.85),
    ("range>=0.6ATR", lambda t: t['range_atr'] >= 0.6),
    ("range>=0.8ATR", lambda t: t['range_atr'] >= 0.8),
    ("range>=1.0ATR", lambda t: t['range_atr'] >= 1.0),
    ("range<0.8ATR", lambda t: t['range_atr'] < 0.8),
    ("delta<-3000", lambda t: t['delta'] < -3000),
    ("delta<-5000", lambda t: t['delta'] < -5000),
    ("delta<-8000", lambda t: t['delta'] < -8000),
    ("delta<-10000", lambda t: t['delta'] < -10000),
    ("rvol>=0.8", lambda t: t['rvol'] >= 0.8),
    ("rvol>=1.0", lambda t: t['rvol'] >= 1.0),
    ("rvol>=1.2", lambda t: t['rvol'] >= 1.2),
    ("rvol>=1.5", lambda t: t['rvol'] >= 1.5),
    ("dg_below>=1", lambda t: t['dg_below'] >= 1),
    ("dg_below>=2", lambda t: t['dg_below'] >= 2),
    ("dg_below==0", lambda t: t['dg_below'] == 0),
    ("local_dg>=1", lambda t: t['local_dg'] >= 1),
    ("local_dg>=2", lambda t: t['local_dg'] >= 2),
    ("local_dg>=3", lambda t: t['local_dg'] >= 3),
    ("has_dg_l_dg", lambda t: t['has_dg_l_dg']),
    ("dr_above>=1", lambda t: t['dr_above'] >= 1),
    ("poc>0.5", lambda t: t['poc_pos'] > 0.5),
    ("poc>0.6", lambda t: t['poc_pos'] > 0.6),
    ("poc>0.7", lambda t: t['poc_pos'] > 0.7),
    ("poc<0.5", lambda t: t['poc_pos'] < 0.5),
    ("ask_dom>=3", lambda t: t['ask_dom'] >= 3),
    ("ask_dom>=5", lambda t: t['ask_dom'] >= 5),
    ("book_ratio<0.7", lambda t: t['book_ratio'] < 0.7),
    ("book_ratio<0.5", lambda t: t['book_ratio'] < 0.5),
    ("pb_delta<0", lambda t: t['pb_delta'] < 0),
    ("pb_delta>0", lambda t: t['pb_delta'] > 0),
    ("pb_dr>=1", lambda t: t['pb_dr'] >= 1),
    ("pb_dr>=2", lambda t: t['pb_dr'] >= 2),
    ("pb_ceil_abs>=1", lambda t: t['pb_ceil_abs'] >= 1),
    ("pb_close_pos<0.5", lambda t: t['pb_close_pos'] < 0.5),
    ("pb_close_pos<0.4", lambda t: t['pb_close_pos'] < 0.4),
    ("pb_is_red", lambda t: t['pb_is_red']),
    ("pb_high_wick>0.2", lambda t: t.get('pb_high_wick', 0) > 0.2),
    ("pb_high_wick>0.3", lambda t: t.get('pb_high_wick', 0) > 0.3),
    ("pb_bars==1", lambda t: t['pb_bars'] == 1),
    ("pb_bars<=2", lambda t: t['pb_bars'] <= 2),
    ("pb_bars<=3", lambda t: t['pb_bars'] <= 3),
    ("pb_bars>=2", lambda t: t['pb_bars'] >= 2),
    ("pb_rvol<1.0", lambda t: t['pb_rvol'] < 1.0),
    ("pb_range<0.5ATR", lambda t: t['pb_range_atr'] < 0.5),
    ("hour<=10", lambda t: t['hour'] <= 10),
    ("hour<=11", lambda t: t['hour'] <= 11),
    ("hour>=11", lambda t: t['hour'] >= 11),
    ("hour>=12", lambda t: t['hour'] >= 12),
    ("hour>=13", lambda t: t['hour'] >= 13),
    ("9-11am", lambda t: 9 <= t['hour'] <= 11),
    ("11am-1pm", lambda t: 11 <= t['hour'] <= 13),
    ("1pm-3pm", lambda t: 13 <= t['hour'] <= 15),
    ("prior_dn>=2", lambda t: t['prior_dn'] >= 2),
    ("prior_dn==3", lambda t: t['prior_dn'] == 3),
    ("prior_delta<0", lambda t: t['prior_delta_sum'] < 0),
    ("prior_delta<-5000", lambda t: t['prior_delta_sum'] < -5000),
    ("is_breakdown", lambda t: t['is_breakdown']),
    ("not_breakdown", lambda t: not t['is_breakdown']),
    ("gap_dn", lambda t: t['gap_dn']),
    ("risk<0.3ATR", lambda t: t['risk_atr'] < 0.3),
    ("risk<0.4ATR", lambda t: t['risk_atr'] < 0.4),
    ("not_churn", lambda t: not t['is_churn']),
]

print()
print(sep)
print("  SHORT — SINGLE FILTER SCAN (sorted by WR)")
print(sep)
short_results = scan_filters(short_pool, short_filters, "SHORT")

# =============================================================================
# TOP COMBO SEARCH (2-filter and 3-filter)
# =============================================================================

def combo_search(pool, filters, label, min_n=8):
    """Find best 2-filter and 3-filter combinations."""
    base_wr = sum(1 for t in pool if t['win']) / len(pool) * 100

    # Pre-compute filter masks for speed
    masks = {}
    for name, fn in filters:
        mask = [fn(t) for t in pool]
        n_match = sum(mask)
        if n_match >= min_n:
            masks[name] = mask

    print(f"\n  --- {label}: TOP 2-FILTER COMBOS (n>={min_n}) ---")
    combos_2 = []
    filter_names = list(masks.keys())
    for i in range(len(filter_names)):
        for j in range(i+1, len(filter_names)):
            n1, n2 = filter_names[i], filter_names[j]
            match_idx = [k for k in range(len(pool)) if masks[n1][k] and masks[n2][k]]
            n = len(match_idx)
            if n < min_n:
                continue
            w = sum(1 for k in match_idx if pool[k]['win'])
            wr = w / n * 100
            net = w * RR - (n - w)
            if wr > base_wr + 5:  # Only show significant lifts
                combos_2.append((f"{n1} + {n2}", n, wr, net))

    combos_2.sort(key=lambda x: -x[2])
    for name, n, wr, net in combos_2[:25]:
        print(f"    {name:<60} n={n:>3} WR={wr:.1f}% net={net:+.1f}R")

    # Top 3-filter combos from the best 2-filter base
    print(f"\n  --- {label}: TOP 3-FILTER COMBOS (n>={min_n}) ---")
    # Take top 10 2-filter combos and add a third filter
    combos_3 = []
    top_2 = combos_2[:15]
    for combo_name, _, _, _ in top_2:
        parts = combo_name.split(" + ")
        if len(parts) != 2:
            continue
        n1, n2 = parts
        if n1 not in masks or n2 not in masks:
            continue
        base_match = [k for k in range(len(pool)) if masks[n1][k] and masks[n2][k]]
        for n3 in filter_names:
            if n3 == n1 or n3 == n2:
                continue
            match_idx = [k for k in base_match if masks[n3][k]]
            n = len(match_idx)
            if n < min_n:
                continue
            w = sum(1 for k in match_idx if pool[k]['win'])
            wr = w / n * 100
            net = w * RR - (n - w)
            if wr > base_wr + 10:
                combos_3.append((f"{n1} + {n2} + {n3}", n, wr, net))

    combos_3.sort(key=lambda x: -x[2])
    # Deduplicate
    seen = set()
    unique_3 = []
    for item in combos_3:
        key = tuple(sorted(item[0].split(" + ")))
        if key not in seen:
            seen.add(key)
            unique_3.append(item)
    for name, n, wr, net in unique_3[:25]:
        print(f"    {name:<70} n={n:>3} WR={wr:.1f}% net={net:+.1f}R")

    return combos_2, unique_3


print()
print(sep)
print("  LONG — COMBO SEARCH")
print(sep)
long_c2, long_c3 = combo_search(long_pool, long_filters, "LONG")

print()
print(sep)
print("  SHORT — COMBO SEARCH")
print(sep)
short_c2, short_c3 = combo_search(short_pool, short_filters, "SHORT")

# =============================================================================
# MONTE CARLO on top combos
# =============================================================================
print()
print(sep)
print("  MONTE CARLO on TOP patterns (50K trials)")
print(sep)
print()

random.seed(42)

def mc_test(pool, filter_fn, name, trials=50000):
    match = [t for t in pool if filter_fn(t)]
    n = len(match)
    if n < 8:
        return None
    w = sum(1 for t in match if t['win'])
    wr = w / n * 100
    net = w * RR - (n - w)
    if net <= 0:
        return None
    better = 0
    for _ in range(trials):
        sample = random.sample(pool, n)
        sw = sum(1 for t in sample if t['win'])
        if sw >= w:
            better += 1
    p = better / trials
    sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else 'ns'
    print(f"  {name:<65} n={n:>3} WR={wr:.1f}% net={net:+.1f}R p={p:.5f} [{sig}]")
    return {'name': name, 'n': n, 'w': w, 'wr': wr, 'net': net, 'p': p}

print("  LONG candidates:")
# Test top patterns from combo search
long_mc_tests = [
    ("body>=80%", lambda t: t['body_pct'] >= 0.80),
    ("body>=85%", lambda t: t['body_pct'] >= 0.85),
    ("body>=80% + pb_close>0.6", lambda t: t['body_pct'] >= 0.80 and t['pb_close_pos'] > 0.6),
    ("body>=80% + pb_is_green", lambda t: t['body_pct'] >= 0.80 and t['pb_is_green']),
    ("body>=75% + prior_up>=2", lambda t: t['body_pct'] >= 0.75 and t['prior_up'] >= 2),
    ("body>=75% + is_breakout", lambda t: t['body_pct'] >= 0.75 and t['is_breakout']),
    ("body>=75% + pb_low_wick>0.2", lambda t: t['body_pct'] >= 0.75 and t['pb_low_wick'] > 0.2),
    ("body>=70% + range<0.8ATR", lambda t: t['body_pct'] >= 0.70 and t['range_atr'] < 0.8),
    ("body>=75% + range<0.8ATR", lambda t: t['body_pct'] >= 0.75 and t['range_atr'] < 0.8),
    ("body>=75% + delta>5000", lambda t: t['body_pct'] >= 0.75 and t['delta'] > 5000),
    ("body>=80% + delta>5000", lambda t: t['body_pct'] >= 0.80 and t['delta'] > 5000),
    ("body>=75% + dr_above>=1", lambda t: t['body_pct'] >= 0.75 and t['dr_above'] >= 1),
    ("body>=70% + dr_above>=1 + pb_is_green", lambda t: t['body_pct'] >= 0.70 and t['dr_above'] >= 1 and t['pb_is_green']),
    ("body>=75% + dr_above>=1 + pb_close>0.6", lambda t: t['body_pct'] >= 0.75 and t['dr_above'] >= 1 and t['pb_close_pos'] > 0.6),
    ("body>=75% + poc<0.4", lambda t: t['body_pct'] >= 0.75 and t['poc_pos'] < 0.4),
    ("body>=70% + pb_floor_abs>=1", lambda t: t['body_pct'] >= 0.70 and t['pb_floor_abs'] >= 1),
    ("body>=80% + prior_up>=2", lambda t: t['body_pct'] >= 0.80 and t['prior_up'] >= 2),
    ("body>=80% + pb_bars==1", lambda t: t['body_pct'] >= 0.80 and t['pb_bars'] == 1),
    ("body>=75% + bid_dom>=3", lambda t: t['body_pct'] >= 0.75 and t['bid_dom'] >= 3),
    ("range<0.8ATR + pb_close>0.6", lambda t: t['range_atr'] < 0.8 and t['pb_close_pos'] > 0.6),
    ("range<0.8ATR + pb_is_green", lambda t: t['range_atr'] < 0.8 and t['pb_is_green']),
    ("pb_floor_abs>=1", lambda t: t['pb_floor_abs'] >= 1),
    ("pb_close>0.7 + body>=75%", lambda t: t['pb_close_pos'] > 0.7 and t['body_pct'] >= 0.75),
    ("not_breakout + body>=75%", lambda t: not t['is_breakout'] and t['body_pct'] >= 0.75),
]

long_sig = []
for name, fn in long_mc_tests:
    result = mc_test(long_pool, fn, name)
    if result and result['p'] < 0.10:
        long_sig.append(result)

print()
print("  SHORT candidates:")
short_mc_tests = [
    ("body>=75%", lambda t: t['body_pct'] >= 0.75),
    ("body>=80%", lambda t: t['body_pct'] >= 0.80),
    ("body>=85%", lambda t: t['body_pct'] >= 0.85),
    ("dg_below>=1", lambda t: t['dg_below'] >= 1),
    ("dg_below>=1 + body>=70%", lambda t: t['dg_below'] >= 1 and t['body_pct'] >= 0.70),
    ("dg_below>=1 + body>=75%", lambda t: t['dg_below'] >= 1 and t['body_pct'] >= 0.75),
    ("dg_below>=1 + body>=80%", lambda t: t['dg_below'] >= 1 and t['body_pct'] >= 0.80),
    ("body>=75% + pb_delta<0", lambda t: t['body_pct'] >= 0.75 and t['pb_delta'] < 0),
    ("body>=75% + pb_is_red", lambda t: t['body_pct'] >= 0.75 and t['pb_is_red']),
    ("body>=75% + prior_dn>=2", lambda t: t['body_pct'] >= 0.75 and t['prior_dn'] >= 2),
    ("body>=75% + is_breakdown", lambda t: t['body_pct'] >= 0.75 and t['is_breakdown']),
    ("body>=80% + pb_delta<0", lambda t: t['body_pct'] >= 0.80 and t['pb_delta'] < 0),
    ("body>=80% + dg_below>=1", lambda t: t['body_pct'] >= 0.80 and t['dg_below'] >= 1),
    ("body>=75% + delta<-5000", lambda t: t['body_pct'] >= 0.75 and t['delta'] < -5000),
    ("body>=75% + pb_close<0.4", lambda t: t['body_pct'] >= 0.75 and t['pb_close_pos'] < 0.4),
    ("body>=75% + poc>0.6", lambda t: t['body_pct'] >= 0.75 and t['poc_pos'] > 0.6),
    ("body>=75% + range<0.8ATR", lambda t: t['body_pct'] >= 0.75 and t['range_atr'] < 0.8),
    ("dg_below>=1 + pb_delta<0", lambda t: t['dg_below'] >= 1 and t['pb_delta'] < 0),
    ("dg_below>=1 + pb_is_red", lambda t: t['dg_below'] >= 1 and t['pb_is_red']),
    ("dg_below>=1 + prior_dn>=2", lambda t: t['dg_below'] >= 1 and t['prior_dn'] >= 2),
    ("dg_below>=1 + poc>0.6", lambda t: t['dg_below'] >= 1 and t['poc_pos'] > 0.6),
    ("body>=80% + prior_dn>=2", lambda t: t['body_pct'] >= 0.80 and t['prior_dn'] >= 2),
    ("body>=80% + pb_is_red", lambda t: t['body_pct'] >= 0.80 and t['pb_is_red']),
    ("body>=75% + range<0.8ATR + pb_delta<0", lambda t: t['body_pct'] >= 0.75 and t['range_atr'] < 0.8 and t['pb_delta'] < 0),
    ("dg_below>=1 + body>=75% + pb_delta<0", lambda t: t['dg_below'] >= 1 and t['body_pct'] >= 0.75 and t['pb_delta'] < 0),
    ("body>=75% + pb_dr>=1", lambda t: t['body_pct'] >= 0.75 and t['pb_dr'] >= 1),
    ("body>=80% + pb_dr>=1", lambda t: t['body_pct'] >= 0.80 and t['pb_dr'] >= 1),
    ("pb_ceil_abs>=1", lambda t: t['pb_ceil_abs'] >= 1),
    ("body>=70% + pb_ceil_abs>=1", lambda t: t['body_pct'] >= 0.70 and t['pb_ceil_abs'] >= 1),
    ("body>=75% + ask_dom>=3", lambda t: t['body_pct'] >= 0.75 and t['ask_dom'] >= 3),
    ("dg_below>=1 + range>=0.8ATR", lambda t: t['dg_below'] >= 1 and t['range_atr'] >= 0.8),
    ("hour>=12 + body>=75%", lambda t: t['hour'] >= 12 and t['body_pct'] >= 0.75),
    ("hour>=13 + dg_below>=1", lambda t: t['hour'] >= 13 and t['dg_below'] >= 1),
]

short_sig = []
for name, fn in short_mc_tests:
    result = mc_test(short_pool, fn, name)
    if result and result['p'] < 0.10:
        short_sig.append(result)

# =============================================================================
# SUMMARY
# =============================================================================
print()
print(sep)
print("  SIGNIFICANT PATTERNS (p<0.10)")
print(sep)
if long_sig:
    print("\n  LONG:")
    for r in sorted(long_sig, key=lambda x: x['p']):
        print(f"    {r['name']:<60} n={r['n']:>3} WR={r['wr']:.1f}% net={r['net']:+.1f}R p={r['p']:.5f}")
if short_sig:
    print("\n  SHORT:")
    for r in sorted(short_sig, key=lambda x: x['p']):
        print(f"    {r['name']:<60} n={r['n']:>3} WR={r['wr']:.1f}% net={r['net']:+.1f}R p={r['p']:.5f}")
