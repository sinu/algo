"""Offline batch backtest: run V17 on pre-downloaded footprint JSON files.

Reads candle data from v17_candle_data/*.json (produced by batch_download.py)
and runs V17 signal detection + trade evaluation without any API calls.
Much faster than live-polling for repeated backtests.

Usage:
    python batch_backtest_offline.py                          # All available data
    python batch_backtest_offline.py 2025-07-01 2026-07-14   # Custom range
    python batch_backtest_offline.py --parallel 4             # Multi-process
"""
import sys
import os
import json
import re
from datetime import datetime, timedelta, date
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "v17_candle_data")
RESULTS_FILE = os.path.join(SCRIPT_DIR, "batch_backtest_results.json")

sys.path.insert(0, SCRIPT_DIR)
from reversal_algo_v17 import compute_session_features, detect_signals, evaluate_trade


def run_day_offline(date_str):
    """Run V17 on a single day's saved candle data."""
    json_path = os.path.join(DATA_DIR, f"{date_str}.json")
    if not os.path.exists(json_path):
        return {"date": date_str, "error": "no_data", "trades": [], "signals": []}

    with open(json_path, 'r', encoding='utf-8') as f:
        candles = json.load(f)

    if not candles or len(candles) < 7:
        return {"date": date_str, "error": None, "trades": [], "signals": []}

    # Convert levels back to tuples if stored as lists
    for c in candles:
        if "levels" in c and isinstance(c["levels"], list):
            c["levels"] = [tuple(lv) if isinstance(lv, list) else lv for lv in c["levels"]]

    feats = compute_session_features(candles)
    signals = detect_signals(candles, feats, live_mode=False)

    # Evaluate each signal
    trades = []
    reported_indices = set()
    last_signal_idx = -3

    for sig in signals:
        idx = sig["candle_idx"]
        if idx in reported_indices:
            continue
        if idx - last_signal_idx < 2:
            continue

        reported_indices.add(idx)
        last_signal_idx = idx

        outcome_str, r_result, exit_idx = evaluate_trade(sig, candles)
        if outcome_str == "SKIPPED":
            continue

        # Map outcome to standard names
        outcome_map = {"WIN": "TARGET", "LOSS": "STOPPED", "TIMEOUT": "TIMEOUT"}
        outcome_name = outcome_map.get(outcome_str, outcome_str)

        grade = sig.get("grade", "B")
        score = sig.get("total_score", sig.get("score", 7))
        sig_type_map = {
            "double_push": "DP", "ceiling_rejection": "CR",
            "floor_bounce": "FB", "dom_sweep_breakout": "DS",
            "vwap_rejection": "VR", "vwap_pullback": "VP",
            "trap_rejection": "TR", "cascade": "C",
        }
        sig_type = sig_type_map.get(sig.get("signal_type", ""), "??")

        trades.append({
            "date": date_str,
            "time": sig.get("time", candles[idx]["time"]),
            "side": sig["side"],
            "grade": grade,
            "score": score,
            "sig_type": sig_type,
            "entry": sig["entry"],
            "stop": sig["stop"],
            "target": sig["target"],
            "outcome": outcome_name,
            "r_result": r_result,
        })

    return {"date": date_str, "error": None, "trades": trades, "signals": signals}


def get_available_days(start_date=None, end_date=None):
    """Get list of dates with downloaded data."""
    if not os.path.exists(DATA_DIR):
        return []

    days = []
    for f in sorted(os.listdir(DATA_DIR)):
        if not f.endswith('.json'):
            continue
        date_str = f.replace('.json', '')
        try:
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            continue
        if start_date and d < start_date:
            continue
        if end_date and d > end_date:
            continue
        # Skip empty files (holidays)
        fpath = os.path.join(DATA_DIR, f)
        if os.path.getsize(fpath) < 10:
            continue
        days.append(date_str)
    return days


def time_bucket(time_str):
    h = int(time_str.split(":")[0])
    m = int(time_str.split(":")[1])
    if h < 10:
        return "09:15-10:00"
    elif h == 10 and m < 30:
        return "10:00-10:30"
    elif h == 10:
        return "10:30-11:00"
    elif h == 11:
        return "11:00-12:00"
    elif h == 12:
        return "12:00-13:00"
    elif h == 13:
        return "13:00-14:00"
    else:
        return "14:00-15:30"


def print_report(all_results):
    """Print comprehensive analysis report."""
    all_trades = []
    error_days = []
    no_signal_days = []

    for res in all_results:
        if res["error"]:
            error_days.append(res["date"])
            continue
        if not res["trades"]:
            no_signal_days.append(res["date"])
        all_trades.extend(res["trades"])

    if not all_trades:
        print("No trades found!")
        return

    total_days = len(all_results) - len(error_days)
    days_with_trades = total_days - len(no_signal_days)

    wins = [t for t in all_trades if t["r_result"] > 0]
    losses = [t for t in all_trades if t["r_result"] <= 0]
    total_r = sum(t["r_result"] for t in all_trades)
    gross_wins = sum(t["r_result"] for t in wins)
    gross_losses = abs(sum(t["r_result"] for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    print("=" * 70)
    print("  V17 OFFLINE BATCH BACKTEST REPORT")
    print("=" * 70)
    print(f"  Period: {all_results[0]['date']} to {all_results[-1]['date']}")
    print(f"  Days analysed: {total_days} | With trades: {days_with_trades} | No data: {len(error_days)}")
    print(f"  Total trades: {len(all_trades)} | Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"  Win rate: {len(wins)/len(all_trades)*100:.1f}%")
    print(f"  Total R: {total_r:+.1f}R")
    print(f"  Profit factor: {profit_factor:.2f}")
    print(f"  Avg R/trade: {total_r/len(all_trades):+.3f}R")
    if days_with_trades > 0:
        print(f"  Avg R/day: {total_r/days_with_trades:+.2f}R")
        print(f"  Avg trades/day: {len(all_trades)/days_with_trades:.1f}")
    print()

    # By outcome type
    targets = [t for t in all_trades if t["outcome"] == "TARGET"]
    stops = [t for t in all_trades if t["outcome"] == "STOPPED"]
    timeouts = [t for t in all_trades if t["outcome"] == "TIMEOUT"]
    print(f"  Outcomes: TARGET={len(targets)} | STOPPED={len(stops)} | TIMEOUT={len(timeouts)}")
    if timeouts:
        avg_to = sum(t["r_result"] for t in timeouts) / len(timeouts)
        print(f"  Avg timeout R: {avg_to:+.2f}R")
    print()

    # By signal type
    print("-" * 70)
    print("  BY SIGNAL TYPE")
    print("-" * 70)
    print(f"  {'Type':<6} {'Trades':>6} {'Wins':>5} {'WR%':>6} {'TotalR':>8} {'AvgR':>7} {'PF':>6}")
    print(f"  {'-'*6} {'-'*6} {'-'*5} {'-'*6} {'-'*8} {'-'*7} {'-'*6}")

    by_type = defaultdict(list)
    for t in all_trades:
        by_type[t.get("sig_type", "??")].append(t)

    for sig_type in sorted(by_type.keys()):
        trades_list = by_type[sig_type]
        n = len(trades_list)
        w = sum(1 for t in trades_list if t["r_result"] > 0)
        tr = sum(t["r_result"] for t in trades_list)
        gw = sum(t["r_result"] for t in trades_list if t["r_result"] > 0)
        gl = abs(sum(t["r_result"] for t in trades_list if t["r_result"] <= 0))
        pf = gw / gl if gl > 0 else float('inf')
        print(f"  {sig_type:<6} {n:>6} {w:>5} {w/n*100:>5.1f}% {tr:>+7.1f}R {tr/n:>+6.3f} {pf:>6.2f}")

    # By grade
    print()
    print("-" * 70)
    print("  BY GRADE")
    print("-" * 70)
    print(f"  {'Grade':<6} {'Trades':>6} {'Wins':>5} {'WR%':>6} {'TotalR':>8} {'AvgR':>7}")
    print(f"  {'-'*6} {'-'*6} {'-'*5} {'-'*6} {'-'*8} {'-'*7}")

    by_grade = defaultdict(list)
    for t in all_trades:
        by_grade[t.get("grade", "??")].append(t)

    for grade in ["A+", "A", "B+", "B"]:
        if grade not in by_grade:
            continue
        trades_list = by_grade[grade]
        n = len(trades_list)
        w = sum(1 for t in trades_list if t["r_result"] > 0)
        tr = sum(t["r_result"] for t in trades_list)
        print(f"  {grade:<6} {n:>6} {w:>5} {w/n*100:>5.1f}% {tr:>+7.1f}R {tr/n:>+6.3f}")

    # By time bucket
    print()
    print("-" * 70)
    print("  BY TIME OF DAY")
    print("-" * 70)
    print(f"  {'Bucket':<15} {'Trades':>6} {'Wins':>5} {'WR%':>6} {'TotalR':>8}")
    print(f"  {'-'*15} {'-'*6} {'-'*5} {'-'*6} {'-'*8}")

    by_time = defaultdict(list)
    for t in all_trades:
        by_time[time_bucket(t["time"])].append(t)

    for bucket in ["09:15-10:00", "10:00-10:30", "10:30-11:00", "11:00-12:00",
                   "12:00-13:00", "13:00-14:00", "14:00-15:30"]:
        if bucket not in by_time:
            continue
        trades_list = by_time[bucket]
        n = len(trades_list)
        w = sum(1 for t in trades_list if t["r_result"] > 0)
        tr = sum(t["r_result"] for t in trades_list)
        print(f"  {bucket:<15} {n:>6} {w:>5} {w/n*100:>5.1f}% {tr:>+7.1f}R")

    # By side
    print()
    print("-" * 70)
    print("  BY SIDE")
    print("-" * 70)
    for side in ["LONG", "SHORT"]:
        subset = [t for t in all_trades if t["side"] == side]
        if subset:
            w = sum(1 for t in subset if t["r_result"] > 0)
            tr = sum(t["r_result"] for t in subset)
            print(f"  {side:<6} n={len(subset):>4}  WR={w/len(subset)*100:.1f}%  R={tr:+.1f}")

    # Best/worst days
    print()
    print("-" * 70)
    print("  BEST/WORST DAYS")
    print("-" * 70)

    day_r = defaultdict(float)
    day_n = defaultdict(int)
    for t in all_trades:
        day_r[t["date"]] += t["r_result"]
        day_n[t["date"]] += 1

    sorted_days = sorted(day_r.items(), key=lambda x: x[1])
    print("  Worst 5:")
    for d, r in sorted_days[:5]:
        print(f"    {d}  {r:+.2f}R  ({day_n[d]} trades)")
    print("  Best 5:")
    for d, r in sorted_days[-5:]:
        print(f"    {d}  {r:+.2f}R  ({day_n[d]} trades)")

    # Monthly breakdown
    print()
    print("-" * 70)
    print("  MONTHLY BREAKDOWN")
    print("-" * 70)
    print(f"  {'Month':<10} {'Trades':>6} {'WR%':>6} {'TotalR':>8} {'Days':>5}")
    print(f"  {'-'*10} {'-'*6} {'-'*6} {'-'*8} {'-'*5}")

    by_month = defaultdict(list)
    for t in all_trades:
        month_key = t["date"][:7]
        by_month[month_key].append(t)

    for month in sorted(by_month.keys()):
        trades_list = by_month[month]
        n = len(trades_list)
        w = sum(1 for t in trades_list if t["r_result"] > 0)
        tr = sum(t["r_result"] for t in trades_list)
        days_ct = len(set(t["date"] for t in trades_list))
        print(f"  {month:<10} {n:>6} {w/n*100:>5.1f}% {tr:>+7.1f}R {days_ct:>5}")

    # Drawdown analysis
    print()
    print("-" * 70)
    print("  DRAWDOWN ANALYSIS")
    print("-" * 70)

    equity = [0.0]
    for t in all_trades:
        equity.append(equity[-1] + t["r_result"])

    peak = 0.0
    max_dd = 0.0
    dd_start = 0
    max_dd_start = 0
    max_dd_end = 0
    for i, eq in enumerate(equity):
        if eq > peak:
            peak = eq
            dd_start = i
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
            max_dd_start = dd_start
            max_dd_end = i

    print(f"  Max drawdown: {max_dd:.1f}R")
    print(f"  Final equity: {equity[-1]:+.1f}R")
    if max_dd_end < len(all_trades):
        print(f"  DD period: trade #{max_dd_start} to #{max_dd_end}")

    # Save results
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_trades, f, indent=1)
    print(f"\n  Results saved to: {RESULTS_FILE}")


def main():
    start_date = None
    end_date = None
    parallel = 1

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--parallel":
            parallel = int(args[i + 1])
            i += 2
        elif not start_date:
            start_date = datetime.strptime(args[i], '%Y-%m-%d').date()
            i += 1
        else:
            end_date = datetime.strptime(args[i], '%Y-%m-%d').date()
            i += 1

    available = get_available_days(start_date, end_date)

    if not available:
        print(f"No data files found in {DATA_DIR}")
        print(f"Run batch_download.py first to download footprint data.")
        return

    print(f"V17 Offline Batch Backtest")
    print(f"Data dir: {DATA_DIR}")
    print(f"Days available: {len(available)} ({available[0]} to {available[-1]})")
    print(f"Parallel workers: {parallel}")
    print("=" * 70)

    if parallel > 1:
        results = []
        with ProcessPoolExecutor(max_workers=parallel) as executor:
            futures = {executor.submit(run_day_offline, d): d for d in available}
            done = 0
            for future in as_completed(futures):
                done += 1
                res = future.result()
                results.append(res)
                n_trades = len(res["trades"])
                if done % 20 == 0:
                    print(f"  Progress: {done}/{len(available)} days...")
        results.sort(key=lambda r: r["date"])
    else:
        results = []
        for i, date_str in enumerate(available):
            res = run_day_offline(date_str)
            results.append(res)
            if (i + 1) % 20 == 0:
                print(f"  Progress: {i+1}/{len(available)} days...")

    print()
    print_report(results)


if __name__ == "__main__":
    main()
