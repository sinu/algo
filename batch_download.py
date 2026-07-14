"""Batch download footprint data for date range and save as JSON candle files.

Downloads data using the same pipeline as live_v17_direct.py (GoCharting
footprint websocket -> FootprintRenderer -> V17 candle dicts), then saves
each day as a clean JSON file with no encoding issues.

Usage:
    python batch_download.py                    # Dec 3 2025 to Jun 23 2026
    python batch_download.py 2026-01-05 2026-01-10  # Custom range

Output:
    v17_candle_data/YYYY-MM-DD.json  (list of candle dicts per day)
"""
import sys
import os
import json
import threading
import time
import io
import statistics
from datetime import datetime, timedelta, date

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v17_candle_data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Suppress all footprint module prints during import
_real_stdout = sys.stdout
_real_stderr = sys.stderr


class SilentIO(io.TextIOBase):
    def write(self, text):
        return len(text)
    def flush(self):
        pass
    def reconfigure(self, **kwargs):
        pass
    def fileno(self):
        raise io.UnsupportedOperation("fileno")
    def isatty(self):
        return False
    @property
    def encoding(self):
        return 'utf-8'


def load_footprint_module(target_date):
    """Load footprint module for a specific date."""
    import importlib.util
    orig_argv = sys.argv[:]
    sys.argv = [sys.argv[0], target_date]

    spec = importlib.util.spec_from_file_location(
        "footprint_v5_84_nifty",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "footprint_v5.84_nifty.py")
    )
    fp = importlib.util.module_from_spec(spec)

    # Suppress output during module load
    sys.stdout = SilentIO()
    sys.stderr = SilentIO()
    try:
        spec.loader.exec_module(fp)
    finally:
        sys.stdout = _real_stdout
        sys.stderr = _real_stderr
        sys.argv = orig_argv

    fp.send_telegram = lambda msg: None
    import builtins
    builtins.input = lambda *a, **kw: None

    return fp


def extract_candle_data(renderer_inst, candle, fp_module):
    """Extract V17 candle dict from a rendered footprint candle."""
    if not renderer_inst.ohlc_cache:
        return None
    last_ohlc = renderer_inst.ohlc_cache[-1]
    o, h, l, c = last_ohlc['o'], last_ohlc['h'], last_ohlc['l'], last_ohlc['c']
    if h == 0 and l == 0:
        return None

    try:
        dt_utc = datetime.fromisoformat(candle.date.replace('Z', '+00:00'))
        dt_ist = dt_utc + fp_module.IST_OFFSET
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
            agg[key]['bid'] += row.sell.volume * fp_module.VOLUME_MULTIPLIER
            agg[key]['ask'] += row.buy.volume * fp_module.VOLUME_MULTIPLIER
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
    has_dg_l_dg = False
    has_dr_l_dr = False
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
        level_tags = []
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
                level_tags.append("DG")
            elif lu <= 125 and row_delta < 0:
                local_dr += 1
                level_tags.append("DR")
            else:
                level_tags.append("L")
        if local_dg >= 2:
            found_first_dg = False
            found_gap = False
            for tag in level_tags:
                if not found_first_dg:
                    if tag == "DG":
                        found_first_dg = True
                elif not found_gap:
                    if tag != "DG":
                        found_gap = True
                else:
                    if tag == "DG":
                        has_dg_l_dg = True
                        break
        if local_dr >= 2:
            found_first_dr = False
            found_gap = False
            for tag in level_tags:
                if not found_first_dr:
                    if tag == "DR":
                        found_first_dr = True
                elif not found_gap:
                    if tag != "DR":
                        found_gap = True
                else:
                    if tag == "DR":
                        has_dr_l_dr = True
                        break

    floor_abs = getattr(renderer_inst, 'bottom_absorb_cumul', 0) if getattr(renderer_inst, 'bear_top_absorb_streak', 0) >= 2 or getattr(renderer_inst, 'bottom_absorb_streak', 0) >= 2 else 0
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
        "has_dg_l_dg": has_dg_l_dg, "has_dr_l_dr": has_dr_l_dr,
        "floor_abs": floor_abs, "ceil_abs": ceil_abs,
        "is_churn": is_churn, "multi_absorb": multi_absorb,
        "bid_dom_levels": bid_dom_levels, "ask_dom_levels": ask_dom_levels,
        "book_pressure_ratio": book_pressure_ratio,
        "large_bid_count": large_bid_count, "large_ask_count": large_ask_count,
    }


def fetch_day(target_date, fp_module, token):
    """Fetch all candles for a single day and return list of candle dicts."""
    # Reset OHLC state
    fp_module.ohlc_data.clear()
    fp_module.ohlc_complete = False

    # Fetch OHLC
    sys.stdout = SilentIO()
    sys.stderr = SilentIO()
    try:
        ohlc_thread = threading.Thread(target=lambda: fp_module.OHLCFetcher(token).start())
        ohlc_thread.daemon = True
        ohlc_thread.start()
        ohlc_thread.join(timeout=15)
    finally:
        sys.stdout = _real_stdout
        sys.stderr = _real_stderr

    if not fp_module.ohlc_complete:
        return None, "OHLC timeout"

    # Create renderer
    sys.stdout = SilentIO()
    sys.stderr = SilentIO()
    try:
        renderer = fp_module.FootprintRenderer(token)
    finally:
        sys.stdout = _real_stdout
        sys.stderr = _real_stderr

    # Fetch footprint candles via websocket
    candles_received = []
    fetch_done = threading.Event()
    import websocket as _ws_mod

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
                resp = fp_module.footprint_pb2.FootPrintForDateResponse()
                resp.ParseFromString(raw)
                if resp.candles:
                    candles_received.extend(resp.candles)
            except Exception:
                pass
            fetch_done.set()
            try:
                ws.close()
            except:
                pass

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
    fetch_done.wait(timeout=20)
    try:
        ws_app.close()
    except:
        pass

    if not candles_received:
        return None, "No footprint data"

    # Sort candles chronologically and render
    all_sorted = sorted(candles_received, key=lambda c: c.date)
    candle_dicts = []

    sys.stdout = SilentIO()
    sys.stderr = SilentIO()
    try:
        for candle in all_sorted:
            renderer.render_candle(candle)
            cd = extract_candle_data(renderer, candle, fp_module)
            if cd:
                candle_dicts.append(cd)
    finally:
        sys.stdout = _real_stdout
        sys.stderr = _real_stderr

    return candle_dicts, None


def get_market_days(start_date, end_date):
    """Generate weekday dates (Mon-Fri) in range. Holidays not filtered."""
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # Mon=0, Fri=4
            days.append(current)
        current += timedelta(days=1)
    return days


def main():
    if len(sys.argv) >= 3:
        start_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
        end_date = datetime.strptime(sys.argv[2], '%Y-%m-%d').date()
    else:
        start_date = date(2025, 6, 9)
        end_date = date(2026, 7, 14)

    market_days = get_market_days(start_date, end_date)
    print(f"Batch download: {start_date} to {end_date}")
    print(f"Market days (weekdays): {len(market_days)}")
    print(f"Output: {OUTPUT_DIR}")
    print("=" * 60)

    # Skip days already downloaded
    existing = set()
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith('.json'):
            existing.add(f.replace('.json', ''))
    pending = [d for d in market_days if d.strftime('%Y-%m-%d') not in existing]
    print(f"Already downloaded: {len(existing)}")
    print(f"Remaining: {len(pending)}")
    print("=" * 60)

    if not pending:
        print("All days already downloaded. Nothing to do.")
        return

    # Load footprint module once with first pending date
    first_date = pending[0].strftime('%Y-%m-%d')
    print(f"Loading footprint module...")
    fp_module = load_footprint_module(first_date)

    # Get token
    token = fp_module.get_fresh_token()
    if not token:
        print("CRITICAL: Failed to get auth token. Check your refresh token.")
        sys.exit(1)
    print(f"Token acquired. Starting downloads...\n")

    success = 0
    failed = 0
    no_data = 0
    token_refresh_interval = 50  # refresh token every N days

    for i, day in enumerate(pending):
        date_str = day.strftime('%Y-%m-%d')
        out_path = os.path.join(OUTPUT_DIR, f"{date_str}.json")

        # Refresh token periodically
        if i > 0 and i % token_refresh_interval == 0:
            new_token = fp_module.get_fresh_token()
            if new_token:
                token = new_token

        # Update the footprint module's target date
        fp_module.FOOTPRINT_DATE = date_str

        candles, error = fetch_day(date_str, fp_module, token)

        if error:
            print(f"  [{i+1}/{len(pending)}] {date_str}: SKIP ({error})")
            failed += 1
            # Brief pause before next attempt
            time.sleep(1)
            continue

        if not candles or len(candles) < 5:
            print(f"  [{i+1}/{len(pending)}] {date_str}: NO DATA ({len(candles) if candles else 0} candles)")
            # Save empty marker so we don't retry holidays
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump([], f)
            no_data += 1
            time.sleep(1)
            continue

        # Save candle data as JSON
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(candles, f, indent=1)

        print(f"  [{i+1}/{len(pending)}] {date_str}: OK ({len(candles)} candles)")
        success += 1

        # Small delay to avoid rate limiting
        time.sleep(2)

    print("\n" + "=" * 60)
    print(f"DONE: {success} downloaded, {no_data} no-data (holidays), {failed} failed")
    print(f"Files saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
