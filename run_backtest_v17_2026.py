"""Run V17 backtest on Jan-June 2026 data and compare with V16."""
import sys
import os
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from reversal_algo_v17 import compute_session_features, detect_signals, evaluate_trade
from validate_v5_full import parse_day

RAW_DIR = "backtest_results_core/raw_logs"


def run_backtest(algo_module, files, label):
    """Run backtest for a given algo module on files."""
    total_trades = 0
    wins = 0
    losses = 0
    timeouts = 0
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

    dp_trades = 0
    dp_wins = 0
    dp_r = 0.0
    cascade_trades = 0
    cascade_wins = 0
    cascade_r = 0.0
    fb_trades = 0
    fb_wins = 0
    fb_r = 0.0
    cr_trades = 0
    cr_wins = 0
    cr_r = 0.0
    fbr_trades = 0
    fbr_wins = 0
    fbr_r = 0.0

    fbr_wins, fbr_r = 0, 0.0
    all_trades = []

    monthly_stats = {}
    daily_r_list = []

    for fpath in files:
        date = os.path.basename(fpath)[:10]
        month = date[:7]
        candles = parse_day(fpath)
        if len(candles) < 15:
            continue

        feats = algo_module.compute_session_features(candles)
        signals = algo_module.detect_signals(candles, feats)

        day_r = 0.0
        for sig in signals:
            result, r_pnl, *_ = algo_module.evaluate_trade(sig, candles)
            if result == "SKIPPED":
                continue
            sig["pnl"] = r_pnl
            sig["result"] = result
            all_trades.append(sig)
            total_trades += 1
            total_r += r_pnl
            cum_r += r_pnl
            day_r += r_pnl

            if cum_r > peak_r:
                peak_r = cum_r
            dd = peak_r - cum_r
            if dd > max_dd:
                max_dd = dd

            if month not in monthly_stats:
                monthly_stats[month] = {"trades": 0, "wins": 0, "losses": 0, "r": 0.0}
            monthly_stats[month]["trades"] += 1
            monthly_stats[month]["r"] += r_pnl

            sig_type = sig.get("signal_type", "double_push")
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

            if sig_type == "cascade":
                cascade_trades += 1
                cascade_r += r_pnl
                if is_win:
                    cascade_wins += 1
            elif sig_type == "floor_bounce":
                fb_trades += 1
                fb_r += r_pnl
                if is_win:
                    fb_wins += 1
            elif sig_type == "ceiling_rejection":
                cr_trades += 1
                cr_r += r_pnl
                if is_win:
                    cr_wins += 1
            elif sig_type == "failed_breakout":
                fbr_trades += 1
                fbr_r += r_pnl
                if is_win:
                    fbr_wins += 1
            else:
                dp_trades += 1
                dp_r += r_pnl
                if is_win:
                    dp_wins += 1

            if is_win:
                wins += 1
                monthly_stats[month]["wins"] += 1
            elif result == "LOSS":
                losses += 1
                monthly_stats[month]["losses"] += 1
            else:
                timeouts += 1

        daily_r_list.append((date, day_r))

    return {
        "trades": all_trades,
        "label": label,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "total_r": total_r,
        "long_trades": long_trades,
        "long_wins": long_wins,
        "long_r": long_r,
        "short_trades": short_trades,
        "short_wins": short_wins,
        "short_r": short_r,
        "max_dd": max_dd,
        "dp_trades": dp_trades,
        "dp_wins": dp_wins,
        "dp_r": dp_r,
        "cascade_trades": cascade_trades,
        "cascade_wins": cascade_wins,
        "cascade_r": cascade_r,
        "fb_trades": fb_trades,
        "fb_wins": fb_wins,
        "fb_r": fb_r,
        "cr_trades": cr_trades,
        "cr_wins": cr_wins,
        "cr_r": cr_r,
        "fbr_trades": fbr_trades,
        "fbr_wins": fbr_wins,
        "fbr_r": fbr_r,
        "monthly_stats": monthly_stats,
        "daily_r_list": daily_r_list,
    }


def print_results(r):
    wr = r["wins"] / r["total_trades"] * 100 if r["total_trades"] > 0 else 0
    exp = r["total_r"] / r["total_trades"] if r["total_trades"] > 0 else 0
    lwr = r["long_wins"] / r["long_trades"] * 100 if r["long_trades"] > 0 else 0
    swr = r["short_wins"] / r["short_trades"] * 100 if r["short_trades"] > 0 else 0

    print(f"\n  {r['label']}")
    print(f"  {'='*60}")
    print(f"  Total trades: {r['total_trades']}")
    print(f"  Wins: {r['wins']} | Losses: {r['losses']} | Timeouts: {r['timeouts']}")
    print(f"  Win Rate: {wr:.1f}%")
    print(f"  Total R: {r['total_r']:+.2f}")
    print(f"  Expectancy: {exp:+.3f}R per trade")
    gross_win = r["wins"] * 1.2
    gross_loss = r["losses"] * 1.0
    pf = gross_win / gross_loss if gross_loss > 0 else 999
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Max Drawdown: {r['max_dd']:.1f}R")
    print(f"  LONG:  {r['long_trades']} trades, WR {lwr:.1f}%, R {r['long_r']:+.2f}")
    print(f"  SHORT: {r['short_trades']} trades, WR {swr:.1f}%, R {r['short_r']:+.2f}")

    # Signal type breakdown
    if r["dp_trades"] > 0:
        dp_wr = r["dp_wins"] / r["dp_trades"] * 100
        dp_exp = r["dp_r"] / r["dp_trades"]
        print(f"  Double-Push: {r['dp_trades']} trades | WR {dp_wr:.1f}% | R {r['dp_r']:+.2f} | Exp {dp_exp:+.3f}")
    if r["cascade_trades"] > 0:
        cas_wr = r["cascade_wins"] / r["cascade_trades"] * 100
        cas_exp = r["cascade_r"] / r["cascade_trades"]
        print(f"  Cascade:     {r['cascade_trades']} trades | WR {cas_wr:.1f}% | R {r['cascade_r']:+.2f} | Exp {cas_exp:+.3f}")
    if r["fb_trades"] > 0:
        fb_wr = r["fb_wins"] / r["fb_trades"] * 100
        fb_exp = r["fb_r"] / r["fb_trades"]
        print(f"  Floor Bounce: {r['fb_trades']} trades | WR {fb_wr:.1f}% | R {r['fb_r']:+.2f} | Exp {fb_exp:+.3f}")
    if r["cr_trades"] > 0:
        cr_wr = r["cr_wins"] / r["cr_trades"] * 100
        cr_exp = r["cr_r"] / r["cr_trades"]
        print(f"  Ceil Reject:  {r['cr_trades']} trades | WR {cr_wr:.1f}% | R {r['cr_r']:+.2f} | Exp {cr_exp:+.3f}")
    if r["fbr_trades"] > 0:
        fbr_wr = r["fbr_wins"] / r["fbr_trades"] * 100
        fbr_exp = r["fbr_r"] / r["fbr_trades"]
        print(f"  Fail Breakout: {r['fbr_trades']} trades | WR {fbr_wr:.1f}% | R {r['fbr_r']:+.2f} | Exp {fbr_exp:+.3f}")

    # Monthly
    print(f"\n  Monthly:")
    print(f"  {'Month':<10} {'Trades':>7} {'Wins':>5} {'Loss':>5} {'WR':>6} {'R':>8} {'Exp':>7}")
    for month in sorted(r["monthly_stats"].keys()):
        ms = r["monthly_stats"][month]
        mwr = ms["wins"] / ms["trades"] * 100 if ms["trades"] > 0 else 0
        mexp = ms["r"] / ms["trades"] if ms["trades"] > 0 else 0
        print(f"  {month:<10} {ms['trades']:>7} {ms['wins']:>5} {ms['losses']:>5} {mwr:>5.1f}% {ms['r']:>+7.2f} {mexp:>+6.3f}")


def main():
    all_files = sorted(glob.glob(os.path.join(RAW_DIR, "2026-*.txt")))
    print(f"V17 DOM-CONFIRMED BACKTEST - Jan to June 2026")
    print(f"Files: {len(all_files)} days")
    if all_files:
        print(f"Range: {os.path.basename(all_files[0])[:10]} to {os.path.basename(all_files[-1])[:10]}")
    print("=" * 70)

    # Run V17
    import reversal_algo_v17 as v17
    r17 = run_backtest(v17, all_files, "V17 (DOM Confirmation)")
    print_results(r17)

    # Run V16 for comparison
    import reversal_algo_v16 as v16
    r16 = run_backtest(v16, all_files, "V16 (No DOM filter)")
    print_results(r16)

    # Comparison
    print(f"\n{'='*70}")
    print(f"  V16 vs V17 COMPARISON (Jan-Jun 2026)")
    print(f"{'='*70}")
    wr16 = r16["wins"] / r16["total_trades"] * 100 if r16["total_trades"] > 0 else 0
    wr17 = r17["wins"] / r17["total_trades"] * 100 if r17["total_trades"] > 0 else 0
    exp16 = r16["total_r"] / r16["total_trades"] if r16["total_trades"] > 0 else 0
    exp17 = r17["total_r"] / r17["total_trades"] if r17["total_trades"] > 0 else 0

    print(f"  {'Metric':<20} {'V16':>12} {'V17':>12} {'Change':>12}")
    print(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*12}")
    print(f"  {'Trades':<20} {r16['total_trades']:>12} {r17['total_trades']:>12} {r17['total_trades']-r16['total_trades']:>+12}")
    print(f"  {'Win Rate':<20} {wr16:>11.1f}% {wr17:>11.1f}% {wr17-wr16:>+11.1f}%")
    print(f"  {'Total R':<20} {r16['total_r']:>+11.2f} {r17['total_r']:>+11.2f} {r17['total_r']-r16['total_r']:>+11.2f}")
    print(f"  {'Expectancy':<20} {exp16:>+11.3f} {exp17:>+11.3f} {exp17-exp16:>+11.3f}")
    print(f"  {'Max Drawdown':<20} {r16['max_dd']:>11.1f}R {r17['max_dd']:>11.1f}R {r17['max_dd']-r16['max_dd']:>+11.1f}R")

    # Show removed trades analysis
    removed = r16["total_trades"] - r17["total_trades"]
    if removed > 0:
        removed_r = r16["total_r"] - r17["total_r"]
        print(f"\n  DOM Filter Impact:")
        print(f"    Trades removed: {removed}")
        print(f"    R removed:      {removed_r:+.2f} (negative = filter removed losing trades)")
        if removed > 0:
            print(f"    Avg R removed:  {removed_r/removed:+.3f} per removed trade")
            if removed_r < 0:
                print(f"    --> DOM filter successfully removed net-losing trades!")
            else:
                print(f"    --> WARNING: DOM filter removed net-winning trades")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
