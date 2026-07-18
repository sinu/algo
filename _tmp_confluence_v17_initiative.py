"""
Confluence validation: V17 reversal signals + Initiative Drive continuation.

Checks:
1. Temporal overlap (same day, same direction, within N bars)
2. Whether V17 signals that coincide with Initiative Drive setups have higher WR
3. Whether Initiative Drive features can filter V17 signals
4. Whether V17 features improve Initiative Drive patterns
"""
import json, sys, os, random
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reversal_algo_v17 import detect_signals, compute_session_features, _compute_atr, TARGET_R

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v17_candle_data_merged")
all_files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith('.json')])

sep = "=" * 90
random.seed(42)
TRIALS = 50000


# =============================================================================
# INITIATIVE DRIVE DETECTION (from _tmp_initiative_final.py validated logic)
# =============================================================================

def detect_initiative_long(candles):
    """Detect Initiative Drive LONG setups (explosive green + DR pocket + pullback)."""
    trades = []
    for i in range(3, len(candles) - 5):
        c = candles[i]
        br = c['high'] - c['low']
        if br <= 0 or c['close'] <= c['open']:
            continue
        bp = (c['close'] - c['open']) / br
        atr = _compute_atr(candles, i)
        if atr <= 0:
            continue
        if bp < 0.70 or c['delta'] <= 0:
            continue

        # DR pocket presence (any count >= 0 for baseline, filter later)
        dr_above = c.get('dr_above_mid', 0)

        # Zone: 50-75% of bar range
        pl = c['low'] + br * 0.50
        ph = c['low'] + br * 0.75
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
            target = entry + risk * 1.5

            # Pullback bar quality
            pb_range = pbc['high'] - pbc['low']
            pb_close_pos = (pbc['close'] - pbc['low']) / pb_range if pb_range > 0 else 0.5
            pb_is_green = pbc['close'] > pbc['open']

            # Evaluate outcome (from NEXT bar to avoid look-ahead bias)
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
                'signal_bar': i,
                'entry_bar': j,
                'time': c['time'],
                'entry_time': pbc['time'],
                'side': 'LONG',
                'win': win,
                'body_pct': bp,
                'dr_above': dr_above,
                'pb_close_pos': pb_close_pos,
                'pb_is_green': pb_is_green,
                'delta': c['delta'],
                'atr': atr,
            })
            break
    return trades


def detect_initiative_short(candles):
    """Detect Initiative Drive SHORT setups (explosive red + DG pocket + pullback)."""
    trades = []
    for i in range(3, len(candles) - 5):
        c = candles[i]
        br = c['high'] - c['low']
        if br <= 0 or c['close'] >= c['open']:
            continue
        bp = (c['open'] - c['close']) / br
        atr = _compute_atr(candles, i)
        if atr <= 0:
            continue
        if bp < 0.70 or c['delta'] >= 0:
            continue

        dg_below = c.get('dg_below_mid', 0)

        # Zone: 35-60% of bar range
        pl = c['low'] + br * 0.35
        ph = c['low'] + br * 0.60
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
            target = entry - risk * 1.5

            pb_range = pbc['high'] - pbc['low']
            pb_close_pos = (pbc['close'] - pbc['low']) / pb_range if pb_range > 0 else 0.5
            pb_is_red = pbc['close'] < pbc['open']

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
                'signal_bar': i,
                'entry_bar': j,
                'time': c['time'],
                'entry_time': pbc['time'],
                'side': 'SHORT',
                'win': win,
                'body_pct': bp,
                'dg_below': dg_below,
                'pb_close_pos': pb_close_pos,
                'pb_is_red': pb_is_red,
                'delta': c['delta'],
                'atr': atr,
            })
            break
    return trades


# =============================================================================
# V17 SIGNAL OUTCOME EVALUATION
# =============================================================================

def evaluate_v17_signal(sig, candles):
    """Evaluate V17 signal outcome using TARGET_R."""
    idx = sig['candle_idx']
    entry = sig['entry']
    stop = sig['stop']
    target = sig['target']

    for fut in range(idx + 1, min(idx + 20, len(candles))):
        fc = candles[fut]
        if sig['side'] == 'LONG':
            if fc['low'] <= stop:
                return False
            if fc['high'] >= target:
                return True
        else:
            if fc['high'] >= stop:
                return False
            if fc['low'] <= target:
                return True
    return None  # timeout


# =============================================================================
# MAIN ANALYSIS
# =============================================================================

print(sep)
print("  CONFLUENCE ANALYSIS: V17 REVERSAL × INITIATIVE DRIVE")
print(sep)

# Collect all signals per day
v17_all = []
init_all = []

for fname in all_files:
    date_str = fname.replace('.json', '')
    with open(os.path.join(DATA_DIR, fname)) as f:
        candles = json.load(f)
    if len(candles) < 14:
        continue

    # V17 signals
    feats = compute_session_features(candles)
    signals = detect_signals(candles, feats, min_score=7, live_mode=False)
    for sig in signals:
        outcome = evaluate_v17_signal(sig, candles)
        if outcome is None:
            continue
        v17_all.append({
            'date': date_str,
            'side': sig['side'],
            'candle_idx': sig['candle_idx'],
            'time': sig['time'],
            'win': outcome,
            'score': sig['score'],
            'grade': sig['grade'],
            'signal_type': sig.get('signal_type', 'unknown'),
            'entry': sig['entry'],
            'stop': sig['stop'],
            'target': sig['target'],
        })

    # Initiative Drive signals
    init_longs = detect_initiative_long(candles)
    init_shorts = detect_initiative_short(candles)
    for t in init_longs + init_shorts:
        t['date'] = date_str
        init_all.append(t)

print(f"\n  V17 signals total: {len(v17_all)} (WR={sum(1 for t in v17_all if t['win'])/len(v17_all)*100:.1f}%)")
print(f"  Initiative signals total: {len(init_all)} (WR={sum(1 for t in init_all if t['win'])/len(init_all)*100:.1f}%)")

# =============================================================================
# OVERLAP DETECTION
# Various proximity windows: same bar, ±1 bar, ±2 bars, ±3 bars
# =============================================================================
print(f"\n{sep}")
print("  SECTION 1: TEMPORAL OVERLAP (same day + same direction + within N bars)")
print(sep)

for max_gap in [0, 1, 2, 3, 5]:
    v17_with_init = []
    v17_without_init = []
    init_with_v17 = []
    init_without_v17 = []

    for v in v17_all:
        has_overlap = False
        for ini in init_all:
            if ini['date'] != v['date']:
                continue
            if ini['side'] != v['side']:
                continue
            # Check if initiative signal bar is within max_gap of V17 signal bar
            if abs(ini['signal_bar'] - v['candle_idx']) <= max_gap:
                has_overlap = True
                break
        if has_overlap:
            v17_with_init.append(v)
        else:
            v17_without_init.append(v)

    for ini in init_all:
        has_overlap = False
        for v in v17_all:
            if v['date'] != ini['date']:
                continue
            if v['side'] != ini['side']:
                continue
            if abs(ini['signal_bar'] - v['candle_idx']) <= max_gap:
                has_overlap = True
                break
        if has_overlap:
            init_with_v17.append(ini)
        else:
            init_without_v17.append(ini)

    print(f"\n  Gap <= {max_gap} bars:")
    if v17_with_init:
        wr = sum(1 for t in v17_with_init if t['win']) / len(v17_with_init) * 100
        print(f"    V17 WITH Initiative overlap: n={len(v17_with_init)} WR={wr:.1f}%")
    else:
        print(f"    V17 WITH Initiative overlap: n=0")
    if v17_without_init:
        wr = sum(1 for t in v17_without_init if t['win']) / len(v17_without_init) * 100
        print(f"    V17 WITHOUT Initiative overlap: n={len(v17_without_init)} WR={wr:.1f}%")
    if init_with_v17:
        wr = sum(1 for t in init_with_v17 if t['win']) / len(init_with_v17) * 100
        print(f"    Initiative WITH V17 overlap: n={len(init_with_v17)} WR={wr:.1f}%")
    else:
        print(f"    Initiative WITH V17 overlap: n=0")
    if init_without_v17:
        wr = sum(1 for t in init_without_v17 if t['win']) / len(init_without_v17) * 100
        print(f"    Initiative WITHOUT V17 overlap: n={len(init_without_v17)} WR={wr:.1f}%")

# =============================================================================
# SECTION 2: DIRECTIONAL CONFLUENCE (same day, same direction, wider window)
# Initiative as "context" for V17 - explosive move confirms V17 reversal direction
# =============================================================================
print(f"\n{sep}")
print("  SECTION 2: INITIATIVE AS CONTEXT (explosive bar on same day, same direction)")
print(sep)

# For each V17 signal, check if there was an Initiative Drive setup EARLIER that day
# in the same direction (the Initiative bar could be the momentum that V17 is reversing FROM,
# or could be confirming the direction V17 wants to trade)

v17_after_init_same_dir = []
v17_after_init_opp_dir = []
v17_no_init_context = []

for v in v17_all:
    same_dir_init = [ini for ini in init_all
                     if ini['date'] == v['date']
                     and ini['side'] == v['side']
                     and ini['signal_bar'] < v['candle_idx']]
    opp_dir_init = [ini for ini in init_all
                    if ini['date'] == v['date']
                    and ini['side'] != v['side']
                    and ini['signal_bar'] < v['candle_idx']]

    if same_dir_init:
        v17_after_init_same_dir.append(v)
    elif opp_dir_init:
        v17_after_init_opp_dir.append(v)
    else:
        v17_no_init_context.append(v)

print(f"\n  V17 after same-dir Initiative (momentum alignment):")
if v17_after_init_same_dir:
    wr = sum(1 for t in v17_after_init_same_dir if t['win']) / len(v17_after_init_same_dir) * 100
    print(f"    n={len(v17_after_init_same_dir)} WR={wr:.1f}%")
    for st in set(t['signal_type'] for t in v17_after_init_same_dir):
        sub = [t for t in v17_after_init_same_dir if t['signal_type'] == st]
        if len(sub) >= 3:
            swr = sum(1 for t in sub if t['win']) / len(sub) * 100
            print(f"      {st}: n={len(sub)} WR={swr:.1f}%")
else:
    print(f"    n=0")

print(f"\n  V17 after opposite-dir Initiative (counter-momentum):")
if v17_after_init_opp_dir:
    wr = sum(1 for t in v17_after_init_opp_dir if t['win']) / len(v17_after_init_opp_dir) * 100
    print(f"    n={len(v17_after_init_opp_dir)} WR={wr:.1f}%")
else:
    print(f"    n=0")

print(f"\n  V17 no Initiative context:")
if v17_no_init_context:
    wr = sum(1 for t in v17_no_init_context if t['win']) / len(v17_no_init_context) * 100
    print(f"    n={len(v17_no_init_context)} WR={wr:.1f}%")

# =============================================================================
# SECTION 3: INITIATIVE DRIVE FEATURES AS V17 FILTERS
# Check if V17 signals on days/bars with DR/DG pockets, high body%, etc. do better
# =============================================================================
print(f"\n{sep}")
print("  SECTION 3: INITIATIVE FEATURES AS V17 QUALITY FILTERS")
print(sep)

# For each V17 signal, check characteristics of that candle through Initiative lens
v17_enhanced = []
for fname in all_files:
    date_str = fname.replace('.json', '')
    with open(os.path.join(DATA_DIR, fname)) as f:
        candles = json.load(f)
    if len(candles) < 14:
        continue

    feats = compute_session_features(candles)
    signals = detect_signals(candles, feats, min_score=7, live_mode=False)

    for sig in signals:
        outcome = evaluate_v17_signal(sig, candles)
        if outcome is None:
            continue
        idx = sig['candle_idx']
        c = candles[idx]
        br = c['high'] - c['low']
        if br <= 0:
            continue
        body_pct = abs(c['close'] - c['open']) / br
        is_bullish = c['close'] > c['open']

        v17_enhanced.append({
            'date': date_str,
            'side': sig['side'],
            'win': outcome,
            'score': sig['score'],
            'signal_type': sig.get('signal_type', 'unknown'),
            'body_pct': body_pct,
            'is_bullish': is_bullish,
            'dr_above': c.get('dr_above_mid', 0),
            'dr_below': c.get('dr_below_mid', 0),
            'dg_above': c.get('dg_above_mid', 0),
            'dg_below': c.get('dg_below_mid', 0),
            'delta': c['delta'],
            'has_dg': c.get('local_dg', 0) >= 3,
            'has_dr': c.get('local_dr', 0) >= 3,
        })

print(f"\n  V17 signals with enhanced features: {len(v17_enhanced)}")

# Filter: V17 LONG + DR pocket (Initiative-style momentum evidence)
v17_long = [t for t in v17_enhanced if t['side'] == 'LONG']
v17_short = [t for t in v17_enhanced if t['side'] == 'SHORT']

print(f"\n  === LONG V17 ({len(v17_long)} total, WR={sum(1 for t in v17_long if t['win'])/len(v17_long)*100:.1f}%) ===")

filters = [
    ("body>=70%", lambda t: t['body_pct'] >= 0.70),
    ("body>=80%", lambda t: t['body_pct'] >= 0.80),
    ("dr_above>=1", lambda t: t['dr_above'] >= 1),
    ("dr_above>=1 + body>=70%", lambda t: t['dr_above'] >= 1 and t['body_pct'] >= 0.70),
    ("delta>10000", lambda t: t['delta'] > 10000),
    ("delta>20000", lambda t: t['delta'] > 20000),
    ("has_dg (DG>=3)", lambda t: t['has_dg']),
    ("has_dg + body>=70%", lambda t: t['has_dg'] and t['body_pct'] >= 0.70),
    ("bullish candle", lambda t: t['is_bullish']),
    ("bullish + body>=70%", lambda t: t['is_bullish'] and t['body_pct'] >= 0.70),
    ("score>=9", lambda t: t['score'] >= 9),
    ("score>=9 + body>=70%", lambda t: t['score'] >= 9 and t['body_pct'] >= 0.70),
    ("score>=9 + dr_above>=1", lambda t: t['score'] >= 9 and t['dr_above'] >= 1),
]

for name, filt in filters:
    sub = [t for t in v17_long if filt(t)]
    if len(sub) >= 5:
        wr = sum(1 for t in sub if t['win']) / len(sub) * 100
        print(f"    {name}: n={len(sub)} WR={wr:.1f}%")

print(f"\n  === SHORT V17 ({len(v17_short)} total, WR={sum(1 for t in v17_short if t['win'])/len(v17_short)*100:.1f}%) ===")

filters_s = [
    ("body>=70%", lambda t: t['body_pct'] >= 0.70),
    ("body>=80%", lambda t: t['body_pct'] >= 0.80),
    ("dg_below>=1", lambda t: t['dg_below'] >= 1),
    ("dg_below>=1 + body>=70%", lambda t: t['dg_below'] >= 1 and t['body_pct'] >= 0.70),
    ("delta<-10000", lambda t: t['delta'] < -10000),
    ("delta<-20000", lambda t: t['delta'] < -20000),
    ("has_dr (DR>=3)", lambda t: t['has_dr']),
    ("has_dr + body>=70%", lambda t: t['has_dr'] and t['body_pct'] >= 0.70),
    ("bearish candle", lambda t: not t['is_bullish']),
    ("bearish + body>=70%", lambda t: not t['is_bullish'] and t['body_pct'] >= 0.70),
    ("score>=9", lambda t: t['score'] >= 9),
    ("score>=9 + body>=70%", lambda t: t['score'] >= 9 and t['body_pct'] >= 0.70),
    ("score>=9 + dg_below>=1", lambda t: t['score'] >= 9 and t['dg_below'] >= 1),
]

for name, filt in filters_s:
    sub = [t for t in v17_short if filt(t)]
    if len(sub) >= 5:
        wr = sum(1 for t in sub if t['win']) / len(sub) * 100
        print(f"    {name}: n={len(sub)} WR={wr:.1f}%")

# =============================================================================
# SECTION 4: V17 SCORE AS INITIATIVE DRIVE FILTER
# Do Initiative Drive patterns with a concurrent/recent V17 signal do better?
# =============================================================================
print(f"\n{sep}")
print("  SECTION 4: V17 CONFIRMATION OF INITIATIVE DRIVE")
print(sep)

# Check if init trades that also have a V17 signal nearby (within 5 bars, same dir) do better
init_with_v17_confirm = []
init_without_v17_confirm = []

for ini in init_all:
    has_v17 = False
    for v in v17_all:
        if v['date'] != ini['date']:
            continue
        if v['side'] != ini['side']:
            continue
        # V17 signal within 5 bars of Initiative entry
        if abs(v['candle_idx'] - ini['entry_bar']) <= 5:
            has_v17 = True
            break
    if has_v17:
        init_with_v17_confirm.append(ini)
    else:
        init_without_v17_confirm.append(ini)

print(f"\n  Initiative WITH V17 confirmation (±5 bars):")
if init_with_v17_confirm:
    wr = sum(1 for t in init_with_v17_confirm if t['win']) / len(init_with_v17_confirm) * 100
    print(f"    n={len(init_with_v17_confirm)} WR={wr:.1f}%")
else:
    print(f"    n=0")

print(f"\n  Initiative WITHOUT V17 confirmation:")
if init_without_v17_confirm:
    wr = sum(1 for t in init_without_v17_confirm if t['win']) / len(init_without_v17_confirm) * 100
    print(f"    n={len(init_without_v17_confirm)} WR={wr:.1f}%")

# =============================================================================
# SECTION 5: PULLBACK QUALITY (from ultra_deep) APPLIED TO V17
# The breakthrough finding: pullback bar close position is the key discriminator
# =============================================================================
print(f"\n{sep}")
print("  SECTION 5: PULLBACK BAR QUALITY ON V17 SIGNALS")
print(sep)

# For V17, the "pullback" concept = the bar AFTER the signal candle
# Check if the bar after V17 signal has Initiative-style quality markers

v17_pb_analysis = []
for fname in all_files:
    date_str = fname.replace('.json', '')
    with open(os.path.join(DATA_DIR, fname)) as f:
        candles = json.load(f)
    if len(candles) < 14:
        continue

    feats = compute_session_features(candles)
    signals = detect_signals(candles, feats, min_score=7, live_mode=False)

    for sig in signals:
        idx = sig['candle_idx']
        if idx + 1 >= len(candles) - 3:
            continue
        outcome = evaluate_v17_signal(sig, candles)
        if outcome is None:
            continue

        # Next bar after signal = "confirmation bar"
        nb = candles[idx + 1]
        nb_range = nb['high'] - nb['low']
        if nb_range <= 0:
            continue
        nb_close_pos = (nb['close'] - nb['low']) / nb_range

        v17_pb_analysis.append({
            'side': sig['side'],
            'win': outcome,
            'nb_close_pos': nb_close_pos,
            'nb_is_green': nb['close'] > nb['open'],
            'nb_delta': nb['delta'],
            'signal_type': sig.get('signal_type', 'unknown'),
            'score': sig['score'],
        })

print(f"\n  V17 signals with next-bar data: {len(v17_pb_analysis)}")

# LONG: next bar close > 0.7 (strong close, like Initiative pb_close>0.7)
long_pb = [t for t in v17_pb_analysis if t['side'] == 'LONG']
short_pb = [t for t in v17_pb_analysis if t['side'] == 'SHORT']

print(f"\n  LONG V17 ({len(long_pb)} total, WR={sum(1 for t in long_pb if t['win'])/len(long_pb)*100:.1f}%):")
pb_filters_l = [
    ("next_bar close>0.7", lambda t: t['nb_close_pos'] > 0.7),
    ("next_bar close>0.6", lambda t: t['nb_close_pos'] > 0.6),
    ("next_bar is green", lambda t: t['nb_is_green']),
    ("next_bar green + close>0.6", lambda t: t['nb_is_green'] and t['nb_close_pos'] > 0.6),
    ("next_bar delta>0", lambda t: t['nb_delta'] > 0),
    ("next_bar delta>0 + close>0.6", lambda t: t['nb_delta'] > 0 and t['nb_close_pos'] > 0.6),
    ("next_bar close<0.4 (BAD)", lambda t: t['nb_close_pos'] < 0.4),
]

for name, filt in pb_filters_l:
    sub = [t for t in long_pb if filt(t)]
    if len(sub) >= 5:
        wr = sum(1 for t in sub if t['win']) / len(sub) * 100
        print(f"    {name}: n={len(sub)} WR={wr:.1f}%")

print(f"\n  SHORT V17 ({len(short_pb)} total, WR={sum(1 for t in short_pb if t['win'])/len(short_pb)*100:.1f}%):")
pb_filters_s = [
    ("next_bar close<0.3", lambda t: t['nb_close_pos'] < 0.3),
    ("next_bar close<0.4", lambda t: t['nb_close_pos'] < 0.4),
    ("next_bar is red", lambda t: not t['nb_is_green']),
    ("next_bar red + close<0.4", lambda t: not t['nb_is_green'] and t['nb_close_pos'] < 0.4),
    ("next_bar delta<0", lambda t: t['nb_delta'] < 0),
    ("next_bar delta<0 + close<0.4", lambda t: t['nb_delta'] < 0 and t['nb_close_pos'] < 0.4),
    ("next_bar close>0.7 (BAD)", lambda t: t['nb_close_pos'] > 0.7),
]

for name, filt in pb_filters_s:
    sub = [t for t in short_pb if filt(t)]
    if len(sub) >= 5:
        wr = sum(1 for t in sub if t['win']) / len(sub) * 100
        print(f"    {name}: n={len(sub)} WR={wr:.1f}%")

# =============================================================================
# SECTION 6: MONTE CARLO VALIDATION OF BEST CONFLUENCE FINDINGS
# =============================================================================
print(f"\n{sep}")
print("  SECTION 6: MONTE CARLO VALIDATION")
print(sep)

# Test significance of best overlap filters
# MC test: does the filtered WR significantly exceed baseline?

def mc_test(baseline, filtered_n, filtered_wins, trials=50000):
    """Permutation test: how often does random sample of same size achieve same wins?"""
    if filtered_n == 0 or filtered_n > len(baseline):
        return 1.0
    better = 0
    for _ in range(trials):
        s = random.sample(baseline, filtered_n)
        sw = sum(1 for t in s if t['win'])
        if sw >= filtered_wins:
            better += 1
    return better / trials

# Test: V17 LONG + next bar close > 0.7
long_filtered = [t for t in long_pb if t['nb_close_pos'] > 0.7]
if long_filtered:
    n_f = len(long_filtered)
    w_f = sum(1 for t in long_filtered if t['win'])
    wr_f = w_f / n_f * 100
    p = mc_test(long_pb, n_f, w_f)
    print(f"\n  V17 LONG + next_bar close>0.7: n={n_f} WR={wr_f:.1f}% p={p:.5f}")

# Test: V17 SHORT + next bar close < 0.3
short_filtered = [t for t in short_pb if t['nb_close_pos'] < 0.3]
if short_filtered:
    n_f = len(short_filtered)
    w_f = sum(1 for t in short_filtered if t['win'])
    wr_f = w_f / n_f * 100
    p = mc_test(short_pb, n_f, w_f)
    print(f"  V17 SHORT + next_bar close<0.3: n={n_f} WR={wr_f:.1f}% p={p:.5f}")

# Test: V17 LONG with Initiative overlap (gap<=3)
v17_long_all = [t for t in v17_all if t['side'] == 'LONG']
v17_long_with_init = []
for v in v17_long_all:
    for ini in init_all:
        if ini['date'] == v['date'] and ini['side'] == 'LONG' and abs(ini['signal_bar'] - v['candle_idx']) <= 3:
            v17_long_with_init.append(v)
            break
if v17_long_with_init:
    n_f = len(v17_long_with_init)
    w_f = sum(1 for t in v17_long_with_init if t['win'])
    wr_f = w_f / n_f * 100
    p = mc_test(v17_long_all, n_f, w_f)
    print(f"  V17 LONG with Init overlap (±3 bars): n={n_f} WR={wr_f:.1f}% p={p:.5f}")

# Test: V17 SHORT with Initiative overlap (gap<=3)
v17_short_all = [t for t in v17_all if t['side'] == 'SHORT']
v17_short_with_init = []
for v in v17_short_all:
    for ini in init_all:
        if ini['date'] == v['date'] and ini['side'] == 'SHORT' and abs(ini['signal_bar'] - v['candle_idx']) <= 3:
            v17_short_with_init.append(v)
            break
if v17_short_with_init:
    n_f = len(v17_short_with_init)
    w_f = sum(1 for t in v17_short_with_init if t['win'])
    wr_f = w_f / n_f * 100
    p = mc_test(v17_short_all, n_f, w_f)
    print(f"  V17 SHORT with Init overlap (±3 bars): n={n_f} WR={wr_f:.1f}% p={p:.5f}")

# Test: Initiative with V17 confirmation
if init_with_v17_confirm:
    n_f = len(init_with_v17_confirm)
    w_f = sum(1 for t in init_with_v17_confirm if t['win'])
    wr_f = w_f / n_f * 100
    p = mc_test(init_all, n_f, w_f)
    print(f"  Initiative with V17 confirm (±5 bars): n={n_f} WR={wr_f:.1f}% p={p:.5f}")

# =============================================================================
# SECTION 7: COMBINED PORTFOLIO (V17 + Non-overlapping Initiative)
# =============================================================================
print(f"\n{sep}")
print("  SECTION 7: COMBINED PORTFOLIO ANALYSIS")
print(sep)

# Combine: take all V17 signals + Initiative signals that DON'T overlap with V17
# This gives max coverage without double-counting

combined = []
for v in v17_all:
    combined.append({'date': v['date'], 'time': v['time'], 'side': v['side'], 'win': v['win'], 'source': 'V17'})

for ini in init_all:
    # Check if this Initiative signal overlaps with any V17 signal
    overlaps = False
    for v in v17_all:
        if v['date'] == ini['date'] and v['side'] == ini['side'] and abs(v['candle_idx'] - ini['signal_bar']) <= 3:
            overlaps = True
            break
    if not overlaps:
        combined.append({'date': ini['date'], 'time': ini['entry_time'], 'side': ini['side'], 'win': ini['win'], 'source': 'Initiative'})

n_comb = len(combined)
w_comb = sum(1 for t in combined if t['win'])
v17_only_n = sum(1 for t in combined if t['source'] == 'V17')
init_only_n = sum(1 for t in combined if t['source'] == 'Initiative')

print(f"\n  Combined portfolio: n={n_comb} (V17={v17_only_n}, Init_new={init_only_n})")
print(f"  Combined WR: {w_comb/n_comb*100:.1f}%")
print(f"  V17 WR: {sum(1 for t in combined if t['source']=='V17' and t['win'])/v17_only_n*100:.1f}%")
if init_only_n > 0:
    print(f"  Init (non-overlapping) WR: {sum(1 for t in combined if t['source']=='Initiative' and t['win'])/init_only_n*100:.1f}%")

# Monthly breakdown
monthly = defaultdict(list)
for t in combined:
    monthly[t['date'][:7]].append(t)
print(f"\n  Monthly breakdown:")
pos_months = 0
for m in sorted(monthly):
    sub = monthly[m]
    mw = sum(1 for t in sub if t['win'])
    # V17 uses TARGET_R=1.2, Initiative uses 1.5; approximate with avg 1.3
    mn = mw * 1.3 - (len(sub) - mw)
    if mn > 0:
        pos_months += 1
    v17_sub = [t for t in sub if t['source'] == 'V17']
    init_sub = [t for t in sub if t['source'] == 'Initiative']
    print(f"    {m}: n={len(sub)} (V17={len(v17_sub)},Init={len(init_sub)}) WR={mw/len(sub)*100:.0f}% net~{mn:+.1f}R")
print(f"  Profitable months: {pos_months}/{len(monthly)}")

# =============================================================================
# SECTION 8: SHARED EXPLOSIVE BAR — the EXACT overlap
# V17 fires on bar i, and that SAME bar i is also an Initiative Drive explosive candle
# =============================================================================
print(f"\n{sep}")
print("  SECTION 8: EXACT OVERLAP — V17 signal bar IS the Initiative explosive bar")
print(sep)

exact_overlap = []
for fname in all_files:
    date_str = fname.replace('.json', '')
    with open(os.path.join(DATA_DIR, fname)) as f:
        candles = json.load(f)
    if len(candles) < 14:
        continue

    feats = compute_session_features(candles)
    signals = detect_signals(candles, feats, min_score=7, live_mode=False)

    for sig in signals:
        idx = sig['candle_idx']
        c = candles[idx]
        br = c['high'] - c['low']
        if br <= 0:
            continue
        body_pct = abs(c['close'] - c['open']) / br

        # Check if this V17 signal bar qualifies as Initiative explosive bar
        is_initiative = False
        if sig['side'] == 'LONG':
            if c['close'] > c['open'] and body_pct >= 0.70 and c['delta'] > 0:
                dr = c.get('dr_above_mid', 0)
                if dr >= 1:
                    is_initiative = True
        else:
            if c['close'] < c['open'] and body_pct >= 0.70 and c['delta'] < 0:
                dg = c.get('dg_below_mid', 0)
                if dg >= 1:
                    is_initiative = True

        outcome = evaluate_v17_signal(sig, candles)
        if outcome is None:
            continue

        exact_overlap.append({
            'date': date_str,
            'side': sig['side'],
            'win': outcome,
            'is_initiative': is_initiative,
            'body_pct': body_pct,
            'score': sig['score'],
            'signal_type': sig.get('signal_type', 'unknown'),
        })

init_yes = [t for t in exact_overlap if t['is_initiative']]
init_no = [t for t in exact_overlap if not t['is_initiative']]

print(f"\n  V17 signal bar IS Initiative explosive bar (body>=70% + DR/DG + dir match):")
if init_yes:
    wr = sum(1 for t in init_yes if t['win']) / len(init_yes) * 100
    print(f"    n={len(init_yes)} WR={wr:.1f}%")
    for side in ['LONG', 'SHORT']:
        sub = [t for t in init_yes if t['side'] == side]
        if sub:
            swr = sum(1 for t in sub if t['win']) / len(sub) * 100
            print(f"      {side}: n={len(sub)} WR={swr:.1f}%")
else:
    print(f"    n=0")

print(f"\n  V17 signal bar NOT Initiative bar:")
if init_no:
    wr = sum(1 for t in init_no if t['win']) / len(init_no) * 100
    print(f"    n={len(init_no)} WR={wr:.1f}%")

# MC test for exact overlap
if init_yes and init_no:
    n_f = len(init_yes)
    w_f = sum(1 for t in init_yes if t['win'])
    p = mc_test(exact_overlap, n_f, w_f)
    print(f"    MC p-value: {p:.5f}")

print(f"\n{sep}")
print("  ANALYSIS COMPLETE")
print(sep)
