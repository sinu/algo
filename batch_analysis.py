"""Batch analysis: run current V17 algo across all market days and produce stats.

Runs live_v17_direct.py for each day, parses session summaries, and outputs:
- Overall win rate, profit factor, total R
- Breakdown by signal type (DP, CR, DS, FB, VP, TR, C)
- Breakdown by grade (A+, A, B+, B)
- Breakdown by time-of-day bucket
- Worst/best days
- Loss cluster analysis

Usage:
    python batch_analysis.py                        # Full range Dec 3 2025 - Jul 4 2026
    python batch_analysis.py 2026-06-01 2026-06-30  # Custom range
    python batch_analysis.py --parallel 4           # Run 4 processes concurrently
"""
import sys
import os
import re
import subprocess
from datetime import datetime, timedelta, date
from collections import defaultdict
import json
import time

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_SCRIPT = os.path.join(SCRIPT_DIR, "live_v17_direct.py")

SIG_TYPE_MAP = {
    "C": "cascade", "DP": "double_push", "CR": "ceiling_rejection",
    "FB": "floor_bounce", "VP": "vwap_pullback", "IS": "iceberg_squeeze",
    "DS": "dom_sweep_breakout", "TR": "trap_rejection"
}


def get_market_days(start_date, end_date):
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def run_day(date_str):
    """Run live_v17_direct.py for a single day, return parsed results."""
    try:
        result = subprocess.run(
            [sys.executable, LIVE_SCRIPT, date_str],
            capture_output=True, timeout=90, cwd=SCRIPT_DIR,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        output = result.stdout.decode('utf-8', errors='replace')
        return parse_session(output, date_str)
    except subprocess.TimeoutExpired:
        return {"date": date_str, "error": "timeout", "trades": []}
    except Exception as e:
        return {"date": date_str, "error": str(e), "trades": []}


def parse_session(output, date_str):
    """Parse V17 session summary from output."""
    trades = []
    signals = []

    # Parse "All signals:" section
    sig_pattern = re.compile(
        r'(\d{2}:\d{2}:\d{2})\s+(LONG|SHORT)\s+(\w\+?)\s+Score=\s*(\d+)\s+'
        r'Entry=([\d.]+)\s+Stop=([\d.]+)\s+Tgt=([\d.]+)\s+\[(\w+)\]'
    )
    # Parse "Completed trades:" section
    trade_pattern = re.compile(
        r'(\d{2}:\d{2}:\d{2})\s+(LONG|SHORT)\s+->\s+(TARGET|STOPPED|TIMEOUT)\s+\(([-+\d.]+)R\)'
    )

    for m in sig_pattern.finditer(output):
        signals.append({
            "time": m.group(1),
            "side": m.group(2),
            "grade": m.group(3),
            "score": int(m.group(4)),
            "entry": float(m.group(5)),
            "stop": float(m.group(6)),
            "target": float(m.group(7)),
            "sig_type": m.group(8),
        })

    for m in trade_pattern.finditer(output):
        trades.append({
            "time": m.group(1),
            "side": m.group(2),
            "outcome": m.group(3),
            "r_result": float(m.group(4)),
        })

    # Match signals to trades by time+side
    for trade in trades:
        for sig in signals:
            if sig["time"] == trade["time"] and sig["side"] == trade["side"]:
                trade["grade"] = sig["grade"]
                trade["score"] = sig["score"]
                trade["sig_type"] = sig["sig_type"]
                trade["entry"] = sig["entry"]
                trade["stop"] = sig["stop"]
                trade["target"] = sig["target"]
                break
        trade["date"] = date_str

    return {"date": date_str, "trades": trades, "signals": signals, "error": None}


def time_bucket(time_str):
    """Group time into buckets."""
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
    print("  V17 BATCH ANALYSIS REPORT")
    print("=" * 70)
    print(f"  Period: {all_results[0]['date']} to {all_results[-1]['date']}")
    print(f"  Days analysed: {total_days} | With trades: {days_with_trades} | Errors: {len(error_days)}")
    print(f"  Total trades: {len(all_trades)} | Wins: {len(wins)} | Losses: {len(losses)}")
    print(f"  Win rate: {len(wins)/len(all_trades)*100:.1f}%")
    print(f"  Total R: {total_r:+.1f}R")
    print(f"  Profit factor: {profit_factor:.2f}")
    print(f"  Avg R/trade: {total_r/len(all_trades):+.3f}R")
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

    for st in sorted(by_type.keys(), key=lambda k: -sum(t["r_result"] for t in by_type[k])):
        trades = by_type[st]
        w = [t for t in trades if t["r_result"] > 0]
        l = [t for t in trades if t["r_result"] <= 0]
        tr = sum(t["r_result"] for t in trades)
        gw = sum(t["r_result"] for t in w)
        gl = abs(sum(t["r_result"] for t in l))
        pf = gw / gl if gl > 0 else float('inf')
        wr = len(w) / len(trades) * 100
        avg = tr / len(trades)
        print(f"  {st:<6} {len(trades):>6} {len(w):>5} {wr:>5.1f}% {tr:>+7.1f}R {avg:>+6.3f} {pf:>6.2f}")
    print()

    # By grade
    print("-" * 70)
    print("  BY GRADE")
    print("-" * 70)
    print(f"  {'Grade':<6} {'Trades':>6} {'Wins':>5} {'WR%':>6} {'TotalR':>8} {'AvgR':>7} {'PF':>6}")
    print(f"  {'-'*6} {'-'*6} {'-'*5} {'-'*6} {'-'*8} {'-'*7} {'-'*6}")

    by_grade = defaultdict(list)
    for t in all_trades:
        by_grade[t.get("grade", "??")].append(t)

    for g in ["A+", "A", "B+", "B", "??"]:
        if g not in by_grade:
            continue
        trades = by_grade[g]
        w = [t for t in trades if t["r_result"] > 0]
        l = [t for t in trades if t["r_result"] <= 0]
        tr = sum(t["r_result"] for t in trades)
        gw = sum(t["r_result"] for t in w)
        gl = abs(sum(t["r_result"] for t in l))
        pf = gw / gl if gl > 0 else float('inf')
        wr = len(w) / len(trades) * 100
        avg = tr / len(trades)
        print(f"  {g:<6} {len(trades):>6} {len(w):>5} {wr:>5.1f}% {tr:>+7.1f}R {avg:>+6.3f} {pf:>6.2f}")
    print()

    # By time bucket
    print("-" * 70)
    print("  BY TIME OF DAY")
    print("-" * 70)
    print(f"  {'Bucket':<14} {'Trades':>6} {'Wins':>5} {'WR%':>6} {'TotalR':>8} {'AvgR':>7}")
    print(f"  {'-'*14} {'-'*6} {'-'*5} {'-'*6} {'-'*8} {'-'*7}")

    by_time = defaultdict(list)
    for t in all_trades:
        by_time[time_bucket(t["time"])].append(t)

    for tb in sorted(by_time.keys()):
        trades = by_time[tb]
        w = [t for t in trades if t["r_result"] > 0]
        tr = sum(t["r_result"] for t in trades)
        wr = len(w) / len(trades) * 100
        avg = tr / len(trades)
        print(f"  {tb:<14} {len(trades):>6} {len(w):>5} {wr:>5.1f}% {tr:>+7.1f}R {avg:>+6.3f}")
    print()

    # By side
    print("-" * 70)
    print("  BY SIDE")
    print("-" * 70)
    longs = [t for t in all_trades if t["side"] == "LONG"]
    shorts = [t for t in all_trades if t["side"] == "SHORT"]
    for label, trades in [("LONG", longs), ("SHORT", shorts)]:
        w = [t for t in trades if t["r_result"] > 0]
        tr = sum(t["r_result"] for t in trades)
        wr = len(w) / len(trades) * 100 if trades else 0
        print(f"  {label:<6} Trades={len(trades)} Wins={len(w)} WR={wr:.1f}% TotalR={tr:+.1f}")
    print()

    # Best/Worst days
    print("-" * 70)
    print("  BEST DAYS (top 10)")
    print("-" * 70)
    day_r = defaultdict(float)
    day_trades = defaultdict(int)
    for t in all_trades:
        day_r[t["date"]] += t["r_result"]
        day_trades[t["date"]] += 1

    sorted_days = sorted(day_r.items(), key=lambda x: -x[1])
    for d, r in sorted_days[:10]:
        print(f"  {d}  {r:>+6.1f}R  ({day_trades[d]} trades)")
    print()

    print("-" * 70)
    print("  WORST DAYS (bottom 10)")
    print("-" * 70)
    for d, r in sorted_days[-10:]:
        print(f"  {d}  {r:>+6.1f}R  ({day_trades[d]} trades)")
    print()

    # Losing streaks
    print("-" * 70)
    print("  CONSECUTIVE LOSSES (max streak per day)")
    print("-" * 70)
    for res in all_results:
        if res["error"] or not res["trades"]:
            continue
        streak = 0
        max_streak = 0
        for t in res["trades"]:
            if t["r_result"] <= 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        if max_streak >= 3:
            day_total = sum(t["r_result"] for t in res["trades"])
            print(f"  {res['date']}  streak={max_streak}  day_total={day_total:+.1f}R")
    print()

    # Loss analysis: which signal types lose most
    print("-" * 70)
    print("  ALL LOSSES (sorted by R)")
    print("-" * 70)
    losses_sorted = sorted(losses, key=lambda t: t["r_result"])
    for t in losses_sorted[:30]:
        sig = t.get("sig_type", "??")
        grade = t.get("grade", "?")
        print(f"  {t['date']} {t['time']} {t['side']:<5} {sig:<3} {grade:<3} {t['r_result']:+.2f}R")

    print()
    print("=" * 70)
    print(f"  SUMMARY: {len(all_trades)} trades | WR={len(wins)/len(all_trades)*100:.1f}% | "
          f"Total={total_r:+.1f}R | PF={profit_factor:.2f}")
    print("=" * 70)

    # Save raw data for further analysis
    out_path = os.path.join(SCRIPT_DIR, "batch_analysis_results.json")
    with open(out_path, 'w') as f:
        json.dump(all_trades, f, indent=2)
    print(f"\n  Raw trade data saved to: {out_path}")


def main():
    parallel = 1
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    for i, a in enumerate(sys.argv[1:]):
        if a == '--parallel' and i + 2 < len(sys.argv):
            parallel = int(sys.argv[i + 2])

    if len(args) >= 2:
        start_date = datetime.strptime(args[0], '%Y-%m-%d').date()
        end_date = datetime.strptime(args[1], '%Y-%m-%d').date()
    else:
        start_date = date(2025, 12, 3)
        end_date = date(2026, 7, 4)

    market_days = get_market_days(start_date, end_date)
    print(f"V17 Batch Analysis: {start_date} to {end_date}")
    print(f"Market days: {len(market_days)} | Parallel: {parallel}")
    print("=" * 70)

    all_results = []
    t0 = time.time()

    if parallel > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=parallel) as executor:
            futures = {executor.submit(run_day, d.strftime('%Y-%m-%d')): d for d in market_days}
            done = 0
            for future in as_completed(futures):
                done += 1
                res = future.result()
                all_results.append(res)
                n_trades = len(res["trades"])
                day_r = sum(t["r_result"] for t in res["trades"]) if res["trades"] else 0
                status = f"{n_trades}t {day_r:+.1f}R" if not res["error"] else res["error"]
                if done % 10 == 0 or res["error"]:
                    elapsed = time.time() - t0
                    print(f"  [{done}/{len(market_days)}] {elapsed:.0f}s elapsed | last: {res['date']} {status}")
        all_results.sort(key=lambda x: x["date"])
    else:
        for i, day in enumerate(market_days):
            date_str = day.strftime('%Y-%m-%d')
            res = run_day(date_str)
            all_results.append(res)
            n_trades = len(res["trades"])
            day_r = sum(t["r_result"] for t in res["trades"]) if res["trades"] else 0
            status = f"{n_trades}t {day_r:+.1f}R" if not res["error"] else res["error"]
            if (i + 1) % 10 == 0:
                elapsed = time.time() - t0
                print(f"  [{i+1}/{len(market_days)}] {elapsed:.0f}s elapsed | {date_str} {status}")

    elapsed = time.time() - t0
    print(f"\n  Completed in {elapsed:.1f}s ({elapsed/len(market_days):.1f}s/day)")
    print()

    print_report(all_results)


if __name__ == "__main__":
    main()
