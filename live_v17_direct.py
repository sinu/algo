"""Live V17 Direct — Cycle-based footprint polling + V17 signal detection.

Polls GoCharting every 5 minutes (aligned to candle close), fetches ALL
candles for the day, renders only new ones through the footprint pipeline,
and runs V17 signal detection. Stays alive indefinitely.

Usage:
    python live_v17_direct.py              # Live mode (today)
    python live_v17_direct.py 2026-07-01   # Specific date
"""
import sys
import os
import threading
import time
import json
import math
import io

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import statistics
from datetime import datetime, timedelta
from reversal_algo_v17 import compute_session_features, detect_signals


class AlertFilter(io.TextIOBase):
    """Suppresses footprint's '2B REVERSAL' alert lines from stdout."""

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


class V17Runner:
    """Accumulates candle dicts and runs V17 signal detection."""

    def __init__(self):
        self.candles = []
        self.reported_indices = set()
        self.signals_fired = []
        self.active_trades = []
        self.last_signal_idx = -3
        self.silent = False  # suppresses printing during initial batch load

    def on_candle(self, candle_dict):
        self.candles.append(candle_dict)
        n = len(self.candles)

        self._update_active_trades()

        if n < 7:
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
            if not self.silent:
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
                    if not self.silent:
                        self._print_exit(sig, "STOP HIT", -1.0)
                elif c["high"] >= sig["target"]:
                    trade["status"] = "TARGET"
                    trade["r_pnl"] = 1.2
                    if not self.silent:
                        self._print_exit(sig, "TARGET HIT", 1.2)
                elif trade["bars_held"] >= 15:
                    r_pnl = (c["close"] - sig["entry"]) / sig["R"] if sig["R"] > 0 else 0
                    trade["status"] = "TIMEOUT"
                    trade["r_pnl"] = r_pnl
                    if not self.silent:
                        self._print_exit(sig, "TIMEOUT", r_pnl)
            else:
                if c["high"] >= sig["stop"]:
                    trade["status"] = "STOPPED"
                    trade["r_pnl"] = -1.0
                    if not self.silent:
                        self._print_exit(sig, "STOP HIT", -1.0)
                elif c["low"] <= sig["target"]:
                    trade["status"] = "TARGET"
                    trade["r_pnl"] = 1.2
                    if not self.silent:
                        self._print_exit(sig, "TARGET HIT", 1.2)
                elif trade["bars_held"] >= 15:
                    r_pnl = (sig["entry"] - c["close"]) / sig["R"] if sig["R"] > 0 else 0
                    trade["status"] = "TIMEOUT"
                    trade["r_pnl"] = r_pnl
                    if not self.silent:
                        self._print_exit(sig, "TIMEOUT", r_pnl)

    def _print_signal(self, sig):
        sig_type = "CASCADE" if sig.get("signal_type") == "cascade" else "DOUBLE-PUSH"
        print("\n" + "=" * 70)
        print(f"  >>> V17 SIGNAL: {sig['side']} at {sig['time']} [{sig_type}] <<<")
        print(f"  Grade: {sig['grade']} | Score: {sig['score']}")
        print(f"  Entry: {sig['entry']:.2f}")
        print(f"  Stop:  {sig['stop']:.2f}")
        print(f"  Target: {sig['target']:.2f}")
        print(f"  R: {sig['R']:.1f} pts")
        if 'abs_score' in sig:
            print(f"  Absorption: {sig['abs_score']} | Push1: {sig['push1_score']} | Push2: {sig['push2_score']}")
        print(f"  Reasons: {', '.join(sig.get('reasons', [])[:6])}")
        print("=" * 70 + "\n")
        sys.stdout.flush()

    def _print_exit(self, sig, reason, r_pnl):
        color = "\033[92m" if r_pnl > 0 else "\033[91m"
        reset = "\033[0m"
        print(f"\n  {color}>>> {sig['side']} {sig['time']} -> {reason} ({r_pnl:+.2f}R){reset}")
        sys.stdout.flush()

    def print_summary(self):
        print("\n" + "=" * 70)
        print(f"  V17 SESSION SUMMARY")
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


v17_runner = V17Runner()


def get_seconds_to_next_bar():
    """Seconds until next 5-min candle closes (+ 5s buffer for server)."""
    now = datetime.now()
    remainder = now.minute % 5
    wait_minutes = 5 - remainder - 1
    wait_seconds = 60 - now.second
    total = (wait_minutes * 60) + wait_seconds + 5
    if total <= 0:
        total = 5
    return total


def main():
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        target_date = datetime.now().strftime('%Y-%m-%d')

    # Load footprint module
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

    # Suppress footprint's telegram and input
    fp.send_telegram = lambda msg: None
    import builtins
    builtins.input = lambda *a, **kw: None

    # State persisted across cycles
    rendered_timestamps = set()
    renderer = None

    def create_renderer(token):
        nonlocal renderer
        renderer = fp.FootprintRenderer(token)
        return renderer

    def extract_candle_data(renderer_inst, candle):
        """Extract V17 candle dict from a rendered footprint candle."""
        if not renderer_inst.ohlc_cache:
            return None
        last_ohlc = renderer_inst.ohlc_cache[-1]
        o, h, l, c = last_ohlc['o'], last_ohlc['h'], last_ohlc['l'], last_ohlc['c']
        if h == 0 and l == 0:
            return None

        try:
            dt_utc = datetime.fromisoformat(candle.date.replace('Z', '+00:00'))
            dt_ist = dt_utc + fp.IST_OFFSET
            time_str = dt_ist.strftime('%H:%M:%S')
        except:
            return None

        vol = renderer_inst.volume_history[-1] if renderer_inst.volume_history else 0
        delta = renderer_inst.delta_history[-1] if renderer_inst.delta_history else 0
        avg_vol = sum(renderer_inst.volume_history) / len(renderer_inst.volume_history) if renderer_inst.volume_history else 1
        rvol = vol / avg_vol if avg_vol > 0 else 1.0

        levels = []
        if hasattr(candle, 'footprint'):
            agg = {}
            for row in candle.footprint:
                bucket_price = renderer_inst.get_bucket(row.level)
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

        local_dg = 0
        local_dr = 0
        data_rows = [(p, b, a) for p, b, a in levels if b > 0 or a > 0]
        if data_rows:
            all_buy = [a for _, _, a in data_rows]
            all_sell = [b for _, b, _ in data_rows]
            candle_max_buy = max(all_buy)
            candle_max_sell = max(all_sell)
            green_denom = candle_max_sell
            red_denom = candle_max_buy
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

        floor_abs = getattr(renderer_inst, 'bottom_absorb_cumul', 0) if getattr(renderer_inst, 'bottom_absorb_streak', 0) >= 2 else 0
        ceil_abs = getattr(renderer_inst, 'bear_top_absorb_cumul', 0) if getattr(renderer_inst, 'bear_top_absorb_streak', 0) >= 2 else 0
        multi_absorb = 0
        if hasattr(renderer_inst, 'absorption_zones'):
            multi_absorb = sum(1 for z in renderer_inst.absorption_zones.values()
                               if z['count'] >= 2)
        body = abs(c - o)
        spread = h - l
        if len(renderer_inst.volume_history) >= 10:
            _mean = statistics.mean(renderer_inst.volume_history)
            _stdev = statistics.stdev(renderer_inst.volume_history)
            _zscore = (vol - _mean) / _stdev if _stdev > 0 else 0
        else:
            _zscore = 0
        is_churn = (_zscore > 1.5 and spread > 0 and body / spread < 0.4)

        poc = None
        if levels:
            poc = max(levels, key=lambda x: x[1] + x[2])[0]

        return {
            "time": time_str,
            "open": o, "high": h, "low": l, "close": c,
            "volume": vol, "delta": delta, "rvol": rvol, "poc": poc,
            "local_dg": local_dg, "local_dr": local_dr,
            "floor_abs": floor_abs, "ceil_abs": ceil_abs,
            "is_churn": is_churn, "multi_absorb": multi_absorb,
            "bid_dom_levels": bid_dom_levels, "ask_dom_levels": ask_dom_levels,
            "book_pressure_ratio": book_pressure_ratio,
            "large_bid_count": large_bid_count, "large_ask_count": large_ask_count,
        }

    def run_cycle(token):
        """One polling cycle: fetch candles, render new ones, run V17."""
        nonlocal renderer, rendered_timestamps

        # Reset OHLC for fresh data
        fp.ohlc_data.clear()
        fp.ohlc_complete = False

        # Fetch fresh OHLC
        ohlc_thread = threading.Thread(target=lambda: fp.OHLCFetcher(token).start())
        ohlc_thread.daemon = True
        ohlc_thread.start()
        ohlc_thread.join(timeout=10)

        if not fp.ohlc_complete:
            print("  OHLC timeout - skipping cycle")
            return

        # Create renderer on first cycle (persists across cycles for state)
        if renderer is None:
            create_renderer(token)

        # Fetch footprint candles
        candles_received = []
        fetch_done = threading.Event()

        def on_msg(ws, message):
            if isinstance(message, str):
                if "Welcome" in message:
                    req = {"command": "FOOTPRINT/V2", "request_id": 1,
                           "payload": {"exchange": "NSE", "segment": "FUTURE",
                                       "symbol": "NIFTY-I", "interval": "5m",
                                       "dates": [renderer.curr_date], "session": "RTH"}}
                    ws.send(json.dumps(req))
                return
            if b'~b' in message:
                try:
                    raw = message[message.find(b'~b') + 2:]
                    resp = fp.footprint_pb2.FootPrintForDateResponse()
                    resp.ParseFromString(raw)
                    if resp.candles:
                        candles_received.extend(resp.candles)
                except Exception as e:
                    print(f"  Parse error: {e}")
                fetch_done.set()
                try:
                    ws.close()
                except:
                    pass

        import websocket as _ws_mod
        ws_app = _ws_mod.WebSocketApp(
            renderer.ws_url,
            header=renderer.headers,
            on_open=lambda ws: None,
            on_message=on_msg,
            on_error=lambda ws, e: fetch_done.set(),
            on_close=lambda ws, code, msg: fetch_done.set(),
        )
        ws_thread = threading.Thread(target=lambda: ws_app.run_forever(ping_timeout=10))
        ws_thread.daemon = True
        ws_thread.start()
        fetch_done.wait(timeout=15)
        try:
            ws_app.close()
        except:
            pass

        if not candles_received:
            print("  No candles received")
            return

        # Sort and render only NEW CLOSED candles (skip in-progress last bar)
        all_sorted = sorted(candles_received, key=lambda c: c.date)
        # Drop the last candle if it might still be forming
        if all_sorted:
            try:
                last_dt = datetime.fromisoformat(all_sorted[-1].date.replace('Z', '+00:00'))
                now_utc = datetime.now(last_dt.tzinfo) if last_dt.tzinfo else datetime.utcnow()
                if (now_utc - last_dt).total_seconds() < 300:
                    all_sorted = all_sorted[:-1]
            except:
                pass

        new_count = 0
        for c in all_sorted:
            if c.date not in rendered_timestamps:
                rendered_timestamps.add(c.date)
                renderer.render_candle(c)
                candle_data = extract_candle_data(renderer, c)
                if candle_data:
                    v17_runner.on_candle(candle_data)
                    new_count += 1

        if new_count > 0:
            n = len(v17_runner.candles)
            last_t = v17_runner.candles[-1]["time"] if v17_runner.candles else "?"
            active = sum(1 for t in v17_runner.active_trades if t['status'] == 'ACTIVE')
            print(f"  [{last_t}] +{new_count} new | {n} total | "
                  f"{len(v17_runner.signals_fired)} signals | active: {active}")
            sys.stdout.flush()

    # === MAIN LOOP ===
    print("=" * 70)
    print(f"  V17 LIVE MODE - {target_date}")
    print(f"  Cycle-based polling (aligned to 5-min candle close)")
    print(f"  Signals: Double-Push (LONG/SHORT) + Cascade (SHORT)")
    print(f"  Filters: SHORT DOM (cumulative 3-bar net)")
    print("=" * 70)

    token = fp.get_fresh_token()
    if not token:
        print("CRITICAL: Failed to get token")
        sys.exit(1)

    # Install filter to suppress footprint's own '2B REVERSAL' alerts
    sys.stdout = AlertFilter(sys.stdout)

    # First cycle — silent mode only for live (today), print signals for backtest dates
    is_live = (target_date == datetime.now().strftime('%Y-%m-%d'))
    if is_live:
        v17_runner.silent = True
    print("  Running initial cycle...")
    run_cycle(token)
    v17_runner.silent = False
    n = len(v17_runner.candles)
    past_sigs = len(v17_runner.signals_fired)
    print(f"  Loaded {n} candles ({past_sigs} past signals)." +
          (" Entering live loop.\n" if is_live else "\n"))
    sys.stdout.flush()

    try:
        while True:
            wait_sec = get_seconds_to_next_bar()
            next_time = (datetime.now() + timedelta(seconds=wait_sec)).strftime('%H:%M:%S')
            print(f"  Next poll at {next_time} ({wait_sec}s)...")
            sys.stdout.flush()
            time.sleep(wait_sec)

            # Refresh token every cycle (it may expire)
            token = fp.get_fresh_token()
            if not token:
                print("  Token refresh failed, retrying in 30s...")
                time.sleep(30)
                continue

            run_cycle(token)
    except KeyboardInterrupt:
        pass

    v17_runner.print_summary()


if __name__ == "__main__":
    main()
