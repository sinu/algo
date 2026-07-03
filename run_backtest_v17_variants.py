"""Backtest all V17 DOM variants on 2026 data."""
import sys
import os
import glob
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from validate_v5_full import parse_day

RAW_DIR = "backtest_results_core/raw_logs"


def run_variant(module_name, files):
    mod = importlib.import_module(module_name)
    total_trades = 0
    wins = 0
    losses = 0
    total_r = 0.0
    long_trades = 0
    long_wins = 0
    long_r = 0.0
    short_trades = 0
    short_wins = 0
    short_r = 0.0
    cum_r = 0.0
    peak_r = 0.0
    max_dd = 0.0

    for fpath in files:
        candles = parse_day(fpath)
        if len(candles) < 15:
            continue
        feats = mod.compute_session_features(candles)
        signals = mod.detect_signals(candles, feats)
        for sig in signals:
            result, r_pnl = mod.evaluate_trade(sig, candles)
            if result == "SKIPPED":
                continue
            total_trades += 1
            total_r += r_pnl
            cum_r += r_pnl
            if cum_r > peak_r:
                peak_r = cum_r
            dd = peak_r - cum_r
            if dd > max_dd:
                max_dd = dd

            is_win = result == "WIN" or (result == "TIMEOUT" and r_pnl > 0)
            if sig["side"] == "LONG":
                long_trades += 1
                long_r += r_pnl
                if is_win:
                    long_wins += 1
            else:
                short_trades += 1
                short_r += r_pnl
                if is_win:
                    short_wins += 1
            if is_win:
                wins += 1
            elif result == "LOSS":
                losses += 1

    wr = wins / total_trades * 100 if total_trades > 0 else 0
    exp = total_r / total_trades if total_trades > 0 else 0
    pf = (wins * 1.2) / (losses * 1.0) if losses > 0 else 999
    lwr = long_wins / long_trades * 100 if long_trades > 0 else 0
    swr = short_wins / short_trades * 100 if short_trades > 0 else 0

    return {
        "trades": total_trades, "wins": wins, "losses": losses,
        "wr": wr, "total_r": total_r, "exp": exp, "pf": pf, "max_dd": max_dd,
        "long_trades": long_trades, "long_wins": long_wins, "long_r": long_r, "lwr": lwr,
        "short_trades": short_trades, "short_wins": short_wins, "short_r": short_r, "swr": swr,
    }


def main():
    files = sorted(glob.glob(os.path.join(RAW_DIR, "2026-*.txt")))
    print(f"V17 DOM VARIANT COMPARISON - {len(files)} days (Jan-Jun 2026)")
    print("=" * 90)

    variants = [
        ("reversal_algo_v16", "V16 (No DOM filter)"),
        ("reversal_algo_v17", "V17 Base (Cumulative DOM net)"),
        ("reversal_algo_v17a_pressure", "V17A (Weighted Book Pressure)"),
        ("reversal_algo_v17b_gradient", "V17B (Book Gradient)"),
        ("reversal_algo_v17c_largeorder", "V17C (Large Order Detection)"),
    ]

    results = []
    for mod_name, label in variants:
        print(f"  Running {label}...", end=" ", flush=True)
        r = run_variant(mod_name, files)
        r["label"] = label
        results.append(r)
        print(f"done ({r['trades']} trades)")

    # Print comparison table
    print()
    print("=" * 90)
    print(f"  {'Variant':<35} {'Trades':>7} {'WR':>6} {'TotalR':>8} {'Exp':>7} {'PF':>5} {'MaxDD':>6} {'LongR':>7} {'ShortR':>8}")
    print(f"  {'-'*35} {'-'*7} {'-'*6} {'-'*8} {'-'*7} {'-'*5} {'-'*6} {'-'*7} {'-'*8}")

    for r in results:
        print(f"  {r['label']:<35} {r['trades']:>7} {r['wr']:>5.1f}% {r['total_r']:>+7.1f} {r['exp']:>+6.3f} {r['pf']:>5.2f} {r['max_dd']:>5.1f}R {r['long_r']:>+6.1f} {r['short_r']:>+7.1f}")

    # Detailed breakdown
    print()
    print("=" * 90)
    print("  LONG SIDE:")
    print(f"  {'Variant':<35} {'Trades':>7} {'WR':>6} {'R':>8}")
    print(f"  {'-'*35} {'-'*7} {'-'*6} {'-'*8}")
    for r in results:
        print(f"  {r['label']:<35} {r['long_trades']:>7} {r['lwr']:>5.1f}% {r['long_r']:>+7.1f}")

    print()
    print("  SHORT SIDE:")
    print(f"  {'Variant':<35} {'Trades':>7} {'WR':>6} {'R':>8}")
    print(f"  {'-'*35} {'-'*7} {'-'*6} {'-'*8}")
    for r in results:
        print(f"  {r['label']:<35} {r['short_trades']:>7} {r['swr']:>5.1f}% {r['short_r']:>+7.1f}")

    # vs V16 delta
    v16 = results[0]
    print()
    print("=" * 90)
    print("  IMPROVEMENT vs V16:")
    print(f"  {'Variant':<35} {'dTrades':>8} {'dWR':>7} {'dR':>8} {'dExp':>8} {'dPF':>6}")
    print(f"  {'-'*35} {'-'*8} {'-'*7} {'-'*8} {'-'*8} {'-'*6}")
    for r in results[1:]:
        dt = r["trades"] - v16["trades"]
        dwr = r["wr"] - v16["wr"]
        dr = r["total_r"] - v16["total_r"]
        dexp = r["exp"] - v16["exp"]
        dpf = r["pf"] - v16["pf"]
        print(f"  {r['label']:<35} {dt:>+8} {dwr:>+6.1f}% {dr:>+7.1f} {dexp:>+7.3f} {dpf:>+5.2f}")

    print()
    print("=" * 90)


if __name__ == "__main__":
    main()
