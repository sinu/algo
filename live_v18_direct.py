"""Live V18 Direct — Integrated footprint + V18 signal detection.

Identical to live_v17_direct.py but drives reversal_algo_v18, which layers the
node-volume high-conviction filter on top of V17.  It additionally computes the
per-candle node volumes (trapped_ask_low / trapped_bid_high) the filter needs.

The V17 live runner is left completely untouched.

Usage:
    python live_v18_direct.py                 # Live mode (today), node_vol>=10000
    python live_v18_direct.py 2026-06-30      # Specific date
    V18_MIN_NODE_VOL=5000 python live_v18_direct.py   # override threshold
    V18_MIN_NODE_VOL=0 python live_v18_direct.py      # fall back to pure V17
"""
import sys
import os
import threading
import time

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io
import statistics
from datetime import datetime
from reversal_algo_v18 import compute_session_features, detect_signals, MIN_NODE_VOL as _DEFAULT_NODE_VOL

# Node-volume threshold: env override, else V18 default (10000). 0 = pure V17.
MIN_NODE_VOL = int(os.environ.get("V18_MIN_NODE_VOL", str(_DEFAULT_NODE_VOL)))


class SignalFilter(io.TextIOBase):
    """Filters out footprint's own '2B REVERSAL' alert lines from stdout."""

    def __init__(self, stream):
        self._stream = stream
        self._suppress_lines = 0

    def write(self, text):
        if '2B REVERSAL' in text:
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


class V18Runner:
    """Accumulates candle dicts and runs V18 signal detection."""

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
        signals = detect_signals(self.candles, feats, live_mode=True,
                                 min_node_vol=MIN_NODE_VOL)

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
        print(f"  >>> V18 SIGNAL: {sig['side']} at {sig['time']} [{sig_type}] <<<")
        print(f"  Grade: {sig['grade']} | Score: {sig['score']}")
        print(f"  Entry: {sig['entry']:.2f}")
        print(f"  Stop:  {sig['stop']:.2f}")
        print(f"  Target: {sig['target']:.2f}")
        print(f"  R: {sig['R']:.1f} pts")
        if 'node_vol' in sig:
            print(f"  Node vol: {sig['node_vol']:.0f} (>= {MIN_NODE_VOL})")
        if 'abs_score' in sig:
            print(f"  Absorption: {sig['abs_score']} | Push1: {sig['push1_score']} | Push2: {sig['push2_score']}")
        print(f"  Reasons: {', '.join(sig.get('reasons', [])[:6])}")
        print("=" * 70 + "\n")

    def _print_exit(self, sig, reason, r_pnl):
        color = "\033[92m" if r_pnl > 0 else "\033[91m"
        reset = "\033[0m"
        print(f"\n  {color}>>> {sig['side']} {sig['time']} -> {reason} ({r_pnl:+.2f}R){reset}")

    def print_summary(self):
        print("\n" + "=" * 70)
        print(f"  V18 SESSION SUMMARY")
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


v18_runner = V18Runner()


def main():
    # Determine target date
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        target_date = datetime.now().strftime('%Y-%m-%d')

    # Footprint reads sys.argv[1] at import time for FOOTPRINT_DATE
    # Ensure it picks up our target date
    orig_argv = sys.argv[:]
    sys.argv = [sys.argv[0], target_date]

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "footprint_v5_84_nifty",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "footprint_v5.84_nifty.py")
    )
    fp = importlib.util.module_from_spec(spec)
    sys.modules["footprint_v5_84_nifty"] = fp
    spec.loader.exec_module(fp)

    sys.argv = orig_argv

    # Patch render_candle to feed V18
    original_render = fp.FootprintRenderer.render_candle

    def patched_render(self, candle, prev_candle=None):
        original_render(self, candle, prev_candle)

        # Extract data and feed V18
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
            if bid_v > ask_v * 2 and bid_v > 500:
                bid_dom_levels += 1
            if ask_v > bid_v * 2 and ask_v > 500:
                ask_dom_levels += 1
            dist = abs(price_lv - c) + 2.5
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

        # Node volume absorbed at the reversal extremes (matches validate_v5_full.parse_day)
        # trapped_ask_low  = buy (ask) volume in the bottom 20% of the candle range
        # trapped_bid_high = sell (bid) volume in the top 20% of the candle range
        candle_range = (h - l) if h > l else 1.0
        trapped_ask_low = 0.0
        trapped_bid_high = 0.0
        for price_lv, bid_v, ask_v in levels:
            if price_lv <= l + candle_range * 0.2:
                trapped_ask_low += ask_v
            if price_lv >= h - candle_range * 0.2:
                trapped_bid_high += bid_v

        local_dg = 0
        local_dr = 0
        data_rows = [(p, b, a) for p, b, a in levels if b > 0 or a > 0]
        if data_rows:
            all_buy = [a for _, _, a in data_rows]
            all_sell = [b for _, b, _ in data_rows]
            candle_min_buy = min(all_buy)
            candle_max_buy = max(all_buy)
            candle_min_sell = min(all_sell)
            candle_max_sell = max(all_sell)
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
        # Churn uses z-score (not ratio) with body_ratio < 0.4, matching footprint
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

        v18_runner.on_candle({
            "time": time_str,
            "open": o, "high": h, "low": l, "close": c,
            "volume": vol, "delta": delta, "rvol": rvol, "poc": poc,
            "local_dg": local_dg, "local_dr": local_dr,
            "floor_abs": floor_abs, "ceil_abs": ceil_abs,
            "is_churn": is_churn, "multi_absorb": multi_absorb,
            "bid_dom_levels": bid_dom_levels, "ask_dom_levels": ask_dom_levels,
            "book_pressure_ratio": book_pressure_ratio,
            "large_bid_count": large_bid_count, "large_ask_count": large_ask_count,
            "trapped_ask_low": trapped_ask_low, "trapped_bid_high": trapped_bid_high,
        })

    fp.FootprintRenderer.render_candle = patched_render

    # Suppress footprint's telegram alerts, input() prompt, and 2B REVERSAL print output
    fp.send_telegram = lambda msg: None
    import builtins
    _original_input = builtins.input
    builtins.input = lambda *a, **kw: None
    sys.stdout = SignalFilter(sys.stdout)

    # Print V18 header
    print("=" * 70)
    print(f"  V18 DIRECT MODE - {target_date}")
    print(f"  Footprint + V18 integrated (no subprocess)")
    print(f"  Signals: Double-Push (LONG/SHORT) + Cascade (SHORT)")
    print(f"  Filters: SHORT DOM (cumulative 3-bar net)"
          + (f" | node_vol>={MIN_NODE_VOL}" if MIN_NODE_VOL > 0 else " | node_vol OFF (pure V17)"))
    print("=" * 70)

    # Run footprint (it handles token, OHLC, websocket)
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
        print("Step 2: Starting Footprint + V18 Analysis...")
        try:
            fp.FootprintRenderer(token).start()
        except (KeyboardInterrupt, SystemExit):
            pass
    else:
        print("ERROR: OHLC download timed out.")

    # Restore stdout/input and print V18 summary
    if isinstance(sys.stdout, SignalFilter):
        sys.stdout = sys.stdout._stream
    builtins.input = _original_input
    v18_runner.print_summary()


if __name__ == "__main__":
    main()
