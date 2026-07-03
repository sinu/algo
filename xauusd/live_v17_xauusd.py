"""Live V17 XAUUSD — Integrated footprint + V17 signal detection for Gold.

Uses footprint_v5.19 (XAUUSD) and reversal_algo_v17_xauusd.
Completely separate from Nifty pipeline.

Settings:
    REGION = "ap-south-1"
    COGNITO_URL = cognito-idp.ap-south-1.amazonaws.com
    SYMBOL = "EXNESS:SPOT:XAUUSD"
    STEP_SIZE = 0.4
    CENTER_GRID = False
    PRICE_DIVISOR = 1000.0
    VOLUME_MULTIPLIER = 1.0

Usage:
    python live_v17_xauusd.py              # Live mode (today)
    python live_v17_xauusd.py 2026-07-01   # Specific date
"""
import sys
import os
import threading
import time

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import statistics
from datetime import datetime
from reversal_algo_v17_xauusd import compute_session_features, detect_signals


class SignalFilter(io.TextIOBase):
    """Filters out footprint's own alert lines from stdout."""

    def __init__(self, stream):
        self._stream = stream
        self._suppress_lines = 0

    def write(self, text):
        if '2B REVERSAL' in text or 'BAND TOUCH' in text:
            self._suppress_lines = 3
            return len(text)
        if self._suppress_lines > 0:
            if '\n' in text:
                self._suppress_lines -= text.count('\n')
            return len(text)
        return self._stream.write(text)

    def flush(self):
        self._stream.flush()

    def fileno(self):
        return self._stream.fileno()

    @property
    def encoding(self):
        return self._stream.encoding


class V17RunnerXAUUSD:
    """Accumulates candle dicts and runs V17 XAUUSD signal detection."""

    def __init__(self):
        self.candles = []
        self.reported_indices = set()
        self.signals_fired = []
        self.active_trades = []
        self.last_signal_idx = -3

    def on_candle(self, candle_dict):
        self.candles.append(candle_dict)
        n = len(self.candles)

        self._update_active_trades()

        if n < 10:
            return

        feats = compute_session_features(self.candles)
        signals = detect_signals(self.candles, feats, live_mode=True)

        for sig in signals:
            idx = sig["candle_idx"]
            if idx in self.reported_indices:
                continue
            if idx - self.last_signal_idx < 2:
                continue

            self.reported_indices.add(idx)
            self.last_signal_idx = idx
            self.signals_fired.append(sig)
            self.active_trades.append({
                "signal": sig, "entry_idx": n - 1,
                "status": "ACTIVE", "bars_held": 0,
            })
            self._print_signal(sig)

    def _update_active_trades(self):
        if not self.active_trades or not self.candles:
            return
        c = self.candles[-1]
        for trade in self.active_trades:
            if trade["status"] != "ACTIVE":
                continue
            trade["bars_held"] += 1
            sig = trade["signal"]

            if sig["side"] == "LONG":
                if c["low"] <= sig["stop"]:
                    trade["status"] = "STOPPED"
                    trade["r_pnl"] = -1.0
                    self._print_exit(sig, "STOP HIT", -1.0)
                elif c["high"] >= sig["target"]:
                    trade["status"] = "TARGET"
                    trade["r_pnl"] = 1.2
                    self._print_exit(sig, "TARGET HIT", 1.2)
                elif trade["bars_held"] >= 15:
                    r_pnl = (c["close"] - sig["entry"]) / sig["R"] if sig["R"] > 0 else 0
                    trade["status"] = "TIMEOUT"
                    trade["r_pnl"] = r_pnl
                    self._print_exit(sig, "TIMEOUT", r_pnl)
            else:
                if c["high"] >= sig["stop"]:
                    trade["status"] = "STOPPED"
                    trade["r_pnl"] = -1.0
                    self._print_exit(sig, "STOP HIT", -1.0)
                elif c["low"] <= sig["target"]:
                    trade["status"] = "TARGET"
                    trade["r_pnl"] = 1.2
                    self._print_exit(sig, "TARGET HIT", 1.2)
                elif trade["bars_held"] >= 15:
                    r_pnl = (sig["entry"] - c["close"]) / sig["R"] if sig["R"] > 0 else 0
                    trade["status"] = "TIMEOUT"
                    trade["r_pnl"] = r_pnl
                    self._print_exit(sig, "TIMEOUT", r_pnl)

    def _print_signal(self, sig):
        sig_type = "CASCADE" if sig.get("signal_type") == "cascade" else "DOUBLE-PUSH"
        print("\n" + "=" * 70)
        print(f"  >>> V17 XAUUSD SIGNAL: {sig['side']} at {sig['time']} [{sig_type}] <<<")
        print(f"  Grade: {sig['grade']} | Score: {sig['score']}")
        print(f"  Entry: {sig['entry']:.2f}")
        print(f"  Stop:  {sig['stop']:.2f}")
        print(f"  Target: {sig['target']:.2f}")
        print(f"  R: ${sig['R']:.2f}")
        if 'abs_score' in sig:
            print(f"  Absorption: {sig['abs_score']} | Push1: {sig['push1_score']} | Push2: {sig['push2_score']}")
        print(f"  Reasons: {', '.join(sig.get('reasons', [])[:6])}")
        print("=" * 70 + "\n")

    def _print_exit(self, sig, reason, r_pnl):
        color = "\033[92m" if r_pnl > 0 else "\033[91m"
        reset = "\033[0m"
        print(f"\n  {color}>>> XAUUSD {sig['side']} {sig['time']} -> {reason} ({r_pnl:+.2f}R){reset}")

    def print_summary(self):
        print("\n" + "=" * 70)
        print(f"  V17 XAUUSD SESSION SUMMARY")
        print(f"  Candles processed: {len(self.candles)}")
        print(f"  Signals fired: {len(self.signals_fired)}")
        if self.signals_fired:
            longs = sum(1 for s in self.signals_fired if s['side'] == 'LONG')
            shorts = sum(1 for s in self.signals_fired if s['side'] == 'SHORT')
            cascades = sum(1 for s in self.signals_fired if s.get('signal_type') == 'cascade')
            print(f"  LONG: {longs} | SHORT: {shorts} (Cascade: {cascades})")
            print(f"\n  All signals:")
            for sig in self.signals_fired:
                sig_type = "C" if sig.get("signal_type") == "cascade" else "DP"
                print(f"    {sig['time']} {sig['side']:5s} {sig['grade']} "
                      f"Score={sig['score']:2d} Entry={sig['entry']:.2f} "
                      f"Stop={sig['stop']:.2f} Tgt={sig['target']:.2f} [{sig_type}]")
        completed = [t for t in self.active_trades if t["status"] != "ACTIVE"]
        if completed:
            total_r = sum(t.get("r_pnl", 0) for t in completed)
            print(f"\n  Completed trades: {len(completed)} | Total: {total_r:+.1f}R")
            for t in completed:
                sig = t["signal"]
                print(f"    {sig['time']} {sig['side']:5s} -> {t['status']} ({t.get('r_pnl', 0):+.2f}R)")
        print("=" * 70)


v17_runner = V17RunnerXAUUSD()


def main():
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        target_date = datetime.now().strftime('%Y-%m-%d')

    orig_argv = sys.argv[:]
    sys.argv = [sys.argv[0], target_date]

    # Ensure footprint can find refresh_token.txt in parent directory
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    orig_cwd = os.getcwd()
    os.chdir(parent_dir)

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "footprint_v5_19_xauusd",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "footprint_v5.19.py")
    )
    fp = importlib.util.module_from_spec(spec)
    sys.modules["footprint_v5_19_xauusd"] = fp
    spec.loader.exec_module(fp)

    sys.argv = orig_argv

    # Patch render_candle to feed V17
    original_render = fp.FootprintRenderer.render_candle

    def patched_render(self, candle, prev_candle=None):
        original_render(self, candle, prev_candle)

        if not self.ohlc_cache:
            return
        last_ohlc = self.ohlc_cache[-1]
        o, h, l, c = last_ohlc['o'], last_ohlc['h'], last_ohlc['l'], last_ohlc['c']
        if h == 0 and l == 0:
            return

        try:
            dt_utc = datetime.fromisoformat(candle.date.replace('Z', '+00:00'))
            dt_ist = dt_utc + fp.IST_OFFSET
            time_str = dt_ist.strftime('%H:%M:%S')
        except:
            return

        vol = self.volume_history[-1] if self.volume_history else 0
        delta = self.delta_history[-1] if self.delta_history else 0
        avg_vol = sum(self.volume_history) / len(self.volume_history) if self.volume_history else 1
        rvol = vol / avg_vol if avg_vol > 0 else 1.0

        levels = []
        if hasattr(candle, 'footprint'):
            agg = {}
            for row in candle.footprint:
                bucket_price = self.get_bucket(row.level)
                key = f"{bucket_price:.2f}"
                if key not in agg:
                    agg[key] = {'price': bucket_price, 'bid': 0, 'ask': 0}
                agg[key]['bid'] += row.sell.volume * fp.VOLUME_MULTIPLIER
                agg[key]['ask'] += row.buy.volume * fp.VOLUME_MULTIPLIER
            levels = [(d['price'], d['bid'], d['ask']) for d in agg.values()]

        bid_dom_levels = 0
        ask_dom_levels = 0
        weighted_bid = 0.0
        weighted_ask = 0.0
        large_bid_count = 0
        large_ask_count = 0

        for price_lv, bid_v, ask_v in levels:
            if bid_v > ask_v * 2 and bid_v > 50:
                bid_dom_levels += 1
            if ask_v > bid_v * 2 and ask_v > 50:
                ask_dom_levels += 1
            dist = abs(price_lv - c) + 0.4
            weighted_bid += bid_v / dist
            weighted_ask += ask_v / dist

        book_pressure_ratio = weighted_bid / weighted_ask if weighted_ask > 0 else 1.0

        avg_level_vol = sum(bv + av for _, bv, av in levels) / max(len(levels), 1) if levels else 0
        for price_lv, bid_v, ask_v in levels:
            if avg_level_vol > 0:
                if bid_v > avg_level_vol * 3:
                    large_bid_count += 1
                if ask_v > avg_level_vol * 3:
                    large_ask_count += 1

        # DG/DR via luminance
        local_dg = 0
        local_dr = 0
        data_rows = [(p, b, a) for p, b, a in levels if b > 0 or a > 0]
        if data_rows:
            candle_min_buy = min(a for _, _, a in data_rows)
            candle_max_buy = max(a for _, _, a in data_rows)
            candle_min_sell = min(b for _, b, _ in data_rows)
            candle_max_sell = max(b for _, b, _ in data_rows)
            green_denom = abs(candle_min_buy - candle_max_sell)
            red_denom = abs(candle_max_buy - candle_min_sell)
            for price_lv, bid_v, ask_v in data_rows:
                row_delta = ask_v - bid_v
                abs_d = abs(row_delta)
                if ask_v > bid_v:
                    denom = green_denom
                else:
                    denom = red_denom
                intensity = min(abs_d / denom, 1.0) if denom > 0 else 0
                if row_delta >= 0:
                    rr = int(143 - 125 * intensity)
                    rg = int(175 - 5 * intensity)
                    rb = int(142 - 129 * intensity)
                else:
                    rr = int(211 + 28 * intensity)
                    rg = max(0, int(124 - 105 * intensity))
                    rb = max(0, int(133 - 92 * intensity))
                lu = 0.299 * rr + 0.587 * rg + 0.114 * rb
                if lu <= 125 and row_delta > 0:
                    local_dg += 1
                elif lu <= 125 and row_delta < 0:
                    local_dr += 1

        floor_abs = getattr(self, 'bottom_absorb_cumul', 0) if getattr(self, 'bottom_absorb_streak', 0) >= 2 else 0
        ceil_abs = getattr(self, 'bear_top_absorb_cumul', 0) if getattr(self, 'bear_top_absorb_streak', 0) >= 2 else 0
        multi_absorb = 0
        if hasattr(self, 'absorption_zones'):
            multi_absorb = sum(1 for z in self.absorption_zones.values()
                               if z['count'] >= 2)
        body = abs(c - o)
        spread = h - l
        if len(self.volume_history) >= 10:
            _mean = statistics.mean(self.volume_history)
            _stdev = statistics.stdev(self.volume_history)
            _zscore = (vol - _mean) / _stdev if _stdev > 0 else 0
        else:
            _zscore = 0
        is_churn = (_zscore > 1.5 and spread > 0 and body / spread < 0.4)

        poc = None
        if levels:
            poc = max(levels, key=lambda x: x[1] + x[2])[0]

        v17_runner.on_candle({
            "time": time_str,
            "open": o, "high": h, "low": l, "close": c,
            "volume": vol, "delta": delta, "rvol": rvol, "poc": poc,
            "local_dg": local_dg, "local_dr": local_dr,
            "floor_abs": floor_abs, "ceil_abs": ceil_abs,
            "is_churn": is_churn, "multi_absorb": multi_absorb,
            "bid_dom_levels": bid_dom_levels, "ask_dom_levels": ask_dom_levels,
            "book_pressure_ratio": book_pressure_ratio,
            "large_bid_count": large_bid_count, "large_ask_count": large_ask_count,
        })

    fp.FootprintRenderer.render_candle = patched_render

    # Suppress footprint alerts and input prompts
    fp.send_telegram = lambda msg: None
    import builtins
    _original_input = builtins.input
    builtins.input = lambda *a, **kw: None
    sys.stdout = SignalFilter(sys.stdout)

    print("=" * 70)
    print(f"  V17 XAUUSD DIRECT MODE - {target_date}")
    print(f"  Footprint (v5.19) + V17 XAUUSD integrated")
    print(f"  Symbol: EXNESS:SPOT:XAUUSD | Step: 0.4 | Divisor: 1000.0")
    print(f"  Signals: Double-Push (LONG/SHORT) + Cascade (SHORT)")
    print(f"  Filters: DOM + POC + Z-Score adaptive counter-push")
    print("=" * 70)

    token = fp.get_fresh_token()
    if not token:
        print("CRITICAL: Failed to get token")
        sys.exit(1)

    print("Step 1: Fetching Official OHLC...")
    ohlc_thread = threading.Thread(target=lambda: fp.OHLCFetcher(token).start())
    ohlc_thread.daemon = True
    ohlc_thread.start()

    wait_time = 0
    while not fp.ohlc_complete and wait_time < 30:
        time.sleep(1)
        wait_time += 1

    if fp.ohlc_complete:
        print("Step 2: Starting Footprint + V17 XAUUSD Analysis...")
        try:
            fp.FootprintRenderer(token).start()
        except (KeyboardInterrupt, SystemExit):
            pass
    else:
        print("ERROR: OHLC download timed out.")

    if isinstance(sys.stdout, SignalFilter):
        sys.stdout = sys.stdout._stream
    builtins.input = _original_input
    v17_runner.print_summary()


if __name__ == "__main__":
    main()
