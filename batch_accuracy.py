"""Run V17 algo on downloaded candle data and report accuracy.

Reads JSON candle files from v17_candle_data/ and produces:
- Per-day signal list with outcomes
- Overall win rate, P&L, breakdown by signal type
- Day-by-day summary

Usage:
    python batch_accuracy.py                    # All available days
    python batch_accuracy.py 2026-01-05        # Single day (detailed)
    python batch_accuracy.py 2026-01-05 2026-01-10  # Date range
"""
import sys
import os
import json
from datetime import datetime, date, timedelta

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reversal_algo_v17 import compute_session_features, detect_signals, evaluate_trade

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v17_candle_data")


def load_day(date_str):
    """Load candle data for a day from JSON."""
    fpath = os.path.join(DATA_DIR, f"{date_str}.json")
    if not os.path.exists(fpath):
        return None
    with open(fpath, 'r', encoding='utf-8') as f:
        candles = json.load(f)
    return candles if candles else None


def run_day(date_str, verbose=False):
    """Run V17 on a single day. Returns list of trade results."""
    candles = load_day(date_str)
    if not candles or len(candles) < 10:
        return None

    feats = compute_session_features(candles)
    signals = detect_signals(candles, feats)
    results = []

    for sig in signals:
        outcome, r_pnl = evaluate_trade(sig, candles)
        result = {
            "date": date_str,
            "time": sig.get("time", candles[sig["candle_idx"]].get("time", "")),
            "side": sig["side"],
            "signal_type": sig.get("signal_type", "double_push"),
            "grade": sig.get("grade", "?"),
            "score": sig.get("score", 0),
            "entry": sig["entry"],
            "stop": sig["stop"],
            "target": sig["target"],
            "R": sig["R"],
            "outcome": outcome,
            "r_pnl": r_pnl,
        }
        results.append(result)

        if verbose:
            color = "\033[92m" if outcome == "WIN" else "\033[91m" if outcome == "LOSS" else "\033[93m"
            reset = "\033[0m"
            print(f"  {result['time'][:5]} {result['side']:5s} {result['signal_type']:20s} "
                  f"Grade={result['grade']} Score={result['score']:2d} "
                  f"R={result['R']:.1f}pts -> {color}{outcome} {r_pnl:+.2f}R{reset}")

    return results


def main():
    single_day = None
    start_date = None
    end_date = None

    if len(sys.argv) == 2:
        single_day = sys.argv[1]
    elif len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]

    # Get available data files
    if not os.path.exists(DATA_DIR):
        print(f"No data directory found: {DATA_DIR}")
        print("Run batch_download.py first.")
        return

    available = sorted(f.replace('.json', '') for f in os.listdir(DATA_DIR) if f.endswith('.json'))
    if not available:
        print("No data files found. Run batch_download.py first.")
        return

    # Filter by date range if specified
    if single_day:
        if single_day in available:
            available = [single_day]
        else:
            print(f"No data for {single_day}")
            return
    elif start_date and end_date:
        available = [d for d in available if start_date <= d <= end_date]

    if not available:
        print("No matching dates found.")
        return

    # Single day mode: detailed output
    if single_day or len(available) == 1:
        date_str = available[0]
        print(f"\n{'='*60}")
        print(f"  V17 Accuracy Report: {date_str}")
        print(f"{'='*60}")
        results = run_day(date_str, verbose=True)
        if not results:
            print("  No signals / no data")
            return
        wins = sum(1 for r in results if r["outcome"] == "WIN")
        losses = sum(1 for r in results if r["outcome"] == "LOSS")
        total_r = sum(r["r_pnl"] for r in results)
        print(f"\n  Summary: {wins}W {losses}L | Net: {total_r:+.1f}R")
        print(f"{'='*60}")
        return

    # Batch mode: summary across all days
    print(f"\n{'='*70}")
    print(f"  V17 BATCH ACCURACY: {available[0]} to {available[-1]} ({len(available)} days)")
    print(f"{'='*70}\n")

    all_results = []
    day_summaries = []
    days_with_signals = 0

    for date_str in available:
        results = run_day(date_str)
        if results is None:
            continue

        days_with_signals += 1
        all_results.extend(results)

        wins = sum(1 for r in results if r["outcome"] == "WIN")
        losses = sum(1 for r in results if r["outcome"] == "LOSS")
        timeouts = sum(1 for r in results if r["outcome"] == "TIMEOUT")
        day_r = sum(r["r_pnl"] for r in results)
        day_summaries.append({
            "date": date_str, "signals": len(results),
            "wins": wins, "losses": losses, "timeouts": timeouts, "r_pnl": day_r
        })

    if not all_results:
        print("No trades found across all days.")
        return

    # Overall stats
    total_wins = sum(1 for r in all_results if r["outcome"] == "WIN")
    total_losses = sum(1 for r in all_results if r["outcome"] == "LOSS")
    total_timeouts = sum(1 for r in all_results if r["outcome"] == "TIMEOUT")
    total_r = sum(r["r_pnl"] for r in all_results)
    wr = total_wins / (total_wins + total_losses) * 100 if (total_wins + total_losses) > 0 else 0

    print(f"  OVERALL: {len(all_results)} trades across {days_with_signals} days")
    print(f"  Wins: {total_wins} | Losses: {total_losses} | Timeouts: {total_timeouts}")
    print(f"  Win Rate: {wr:.1f}%")
    print(f"  Net P&L: {total_r:+.1f}R")
    print(f"  Avg per day: {total_r/days_with_signals:+.2f}R")

    # Breakdown by signal type
    print(f"\n  {'─'*60}")
    print(f"  SIGNAL TYPE BREAKDOWN:")
    print(f"  {'─'*60}")
    types = {}
    for r in all_results:
        st = r["signal_type"]
        if st not in types:
            types[st] = {"wins": 0, "losses": 0, "timeouts": 0, "r_pnl": 0}
        if r["outcome"] == "WIN":
            types[st]["wins"] += 1
        elif r["outcome"] == "LOSS":
            types[st]["losses"] += 1
        else:
            types[st]["timeouts"] += 1
        types[st]["r_pnl"] += r["r_pnl"]

    print(f"  {'Type':<22} {'W':>4} {'L':>4} {'T':>4} {'WR%':>6} {'Net R':>8}")
    for st in sorted(types.keys(), key=lambda k: types[k]["r_pnl"], reverse=True):
        t = types[st]
        n = t["wins"] + t["losses"]
        wr_t = t["wins"] / n * 100 if n > 0 else 0
        print(f"  {st:<22} {t['wins']:>4} {t['losses']:>4} {t['timeouts']:>4} {wr_t:>5.1f}% {t['r_pnl']:>+7.1f}R")

    # Breakdown by side
    print(f"\n  {'─'*60}")
    print(f"  SIDE BREAKDOWN:")
    for side in ["LONG", "SHORT"]:
        side_r = [r for r in all_results if r["side"] == side]
        if not side_r:
            continue
        sw = sum(1 for r in side_r if r["outcome"] == "WIN")
        sl = sum(1 for r in side_r if r["outcome"] == "LOSS")
        swr = sw / (sw + sl) * 100 if (sw + sl) > 0 else 0
        sr = sum(r["r_pnl"] for r in side_r)
        print(f"  {side:5s}: {sw}W {sl}L ({swr:.1f}%) | Net: {sr:+.1f}R")

    # Day-by-day P&L
    print(f"\n  {'─'*60}")
    print(f"  DAY-BY-DAY (top 10 best / worst):")
    print(f"  {'─'*60}")
    sorted_days = sorted(day_summaries, key=lambda d: d["r_pnl"], reverse=True)

    print(f"  Best days:")
    for d in sorted_days[:10]:
        print(f"    {d['date']}: {d['wins']}W {d['losses']}L {d['r_pnl']:+.1f}R ({d['signals']} signals)")

    print(f"\n  Worst days:")
    for d in sorted_days[-10:]:
        print(f"    {d['date']}: {d['wins']}W {d['losses']}L {d['r_pnl']:+.1f}R ({d['signals']} signals)")

    # Equity curve (cumulative R)
    print(f"\n  {'─'*60}")
    print(f"  MONTHLY SUMMARY:")
    print(f"  {'─'*60}")
    months = {}
    for d in day_summaries:
        m = d["date"][:7]
        if m not in months:
            months[m] = {"r_pnl": 0, "wins": 0, "losses": 0, "days": 0}
        months[m]["r_pnl"] += d["r_pnl"]
        months[m]["wins"] += d["wins"]
        months[m]["losses"] += d["losses"]
        months[m]["days"] += 1

    print(f"  {'Month':<10} {'Days':>5} {'W':>5} {'L':>5} {'WR%':>6} {'Net R':>8}")
    for m in sorted(months.keys()):
        mm = months[m]
        n = mm["wins"] + mm["losses"]
        wr_m = mm["wins"] / n * 100 if n > 0 else 0
        print(f"  {m:<10} {mm['days']:>5} {mm['wins']:>5} {mm['losses']:>5} {wr_m:>5.1f}% {mm['r_pnl']:>+7.1f}R")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
