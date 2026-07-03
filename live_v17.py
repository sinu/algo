"""Live V17 Signal Runner.

Runs footprint_v5.84_nifty.py in live mode and monitors output in real-time.
After each new candle completes, runs V17 signal detection (with DOM filter)
and alerts when a trade setup is found.

Usage:
    python live_v17.py              # Live mode
    python live_v17.py <file.txt>   # Test on existing raw log
"""
import sys
import os
import re
import subprocess
import time
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reversal_algo_v17 import compute_session_features, detect_signals, evaluate_trade

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FOOTPRINT_SCRIPT = os.path.join(SCRIPT_DIR, "footprint_v5.84_nifty.py")

# --- Regex patterns ---
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
TIME_RE = re.compile(r"TIME \(IST\):\s*(\d{2}:\d{2}:\d{2})")
POC_RE = re.compile(r"POC:\s*([\d.]+)")
OHLC_RE = re.compile(r"O:\s*([\d.]+)\s*H:\s*([\d.]+)\s*L:\s*([\d.]+)\s*C:\s*([\d.]+)")
DELTA_RE = re.compile(r"DELTA:\s*(-?[\d.]+)")
VOL_RE = re.compile(r"VOL:\s*([\d.]+)([KM]?)")
RVOL_RE = re.compile(r"RVOL:\s*([\d.]+)x\s*\(Z:\s*(-?[\d.]+)\)")
EFF_RE = re.compile(r"Eff:\s*(-?[\d.]+)")
ACCEL_RE = re.compile(r"Accel:\s*(-?[\d.,]+)")
VOIDS_RE = re.compile(r"Voids:\s*(\d+)")
CHURN_RE = re.compile(r"\[CHURN\]")
MULTI_ABSORB_RE = re.compile(r"MULTI-ABSORB x(\d+)")
TRAP_RE = re.compile(r"TRAP ACTIVE|NEW TRAP")
CEIL_RE = re.compile(r"CEIL ACTIVE|NEW CEIL")
DG_RE = re.compile(r"\[DG\]")
DR_RE = re.compile(r"\[DR\]")
TRAP_AGE_RE = re.compile(r"TRAP ACTIVE.*?age:(\d+)")
FLOOR_ABS_RE = re.compile(r"Selling absorbed at bottom \(([\d.]+)K? over")
CEIL_ABS_RE = re.compile(r"Buying absorbed at top \(([\d.]+)K? over")
LEVEL_RE = re.compile(
    r"^\s*([\d.]+)\s+\|\s+"
    r"([\d.]+[KM]?)\s+x\s+"
    r"([\d.]+[KM]?)\s+"
    r"\|\s*(-?[\d.]+[KM]?)\s+"
    r"\|"
)


def parse_vol_str(s):
    s = s.strip()
    if not s or s == '0':
        return 0.0
    if s.endswith('K'):
        return float(s[:-1]) * 1000
    if s.endswith('M'):
        return float(s[:-1]) * 1000000
    return float(s)


def parse_candle_section(section_lines):
    """Parse a single candle section from footprint output lines."""
    section_text = "\n".join(section_lines)

    # Time
    tm = TIME_RE.search(section_lines[0] if section_lines else "")
    if not tm:
        for ln in section_lines[:3]:
            tm = TIME_RE.search(ln)
            if tm:
                break
    if not tm:
        return None
    time_val = tm.group(1)

    # OHLC
    o = h = l = c_val = 0.0
    delta = 0.0
    vol = 0.0
    for ln in section_lines[:5]:
        oh = OHLC_RE.search(ln)
        if oh:
            o, h, l, c_val = (float(x) for x in oh.groups())
            dm = DELTA_RE.search(ln)
            delta = float(dm.group(1)) if dm else 0.0
            vm = VOL_RE.search(ln)
            if vm:
                vol = float(vm.group(1))
                if vm.group(2) == "K":
                    vol *= 1000
                elif vm.group(2) == "M":
                    vol *= 1000000
            break

    if h == 0 and l == 0:
        return None

    # RVOL
    rv = RVOL_RE.search(section_text[:500])
    rvol = float(rv.group(1)) if rv else 1.0

    # POC
    poc_m = POC_RE.search(section_lines[0] if section_lines else "")
    if not poc_m:
        for ln in section_lines[:3]:
            poc_m = POC_RE.search(ln)
            if poc_m:
                break
    poc = float(poc_m.group(1)) if poc_m else None

    # Churn
    is_churn = bool(CHURN_RE.search(section_text[:500]))

    # Multi-absorb
    ma = MULTI_ABSORB_RE.search(section_text[:500])
    multi_absorb = int(ma.group(1)) if ma else 0

    # DG/DR counts
    local_dg = len(DG_RE.findall(section_text))
    local_dr = len(DR_RE.findall(section_text))

    # Floor/Ceil absorption
    floor_abs_m = FLOOR_ABS_RE.findall(section_text)
    floor_abs = sum(int(float(x)) for x in floor_abs_m)
    ceil_abs_m = CEIL_ABS_RE.findall(section_text)
    ceil_abs = sum(int(float(x)) for x in ceil_abs_m)

    # --- DOM level parsing (V17 addition) ---
    levels = []
    for ln in section_lines:
        lm = LEVEL_RE.match(ln)
        if lm:
            price_lv = float(lm.group(1))
            bid_v = parse_vol_str(lm.group(2))
            ask_v = parse_vol_str(lm.group(3))
            levels.append((price_lv, bid_v, ask_v))

    # Bid/Ask dominant level counts
    bid_dom_levels = 0
    ask_dom_levels = 0
    for price_lv, bid_v, ask_v in levels:
        if bid_v > ask_v * 2 and bid_v > 500:
            bid_dom_levels += 1
        if ask_v > bid_v * 2 and ask_v > 500:
            ask_dom_levels += 1

    # Book pressure ratio
    candle_range = h - l
    weighted_bid_pressure = 0.0
    weighted_ask_pressure = 0.0
    for price_lv, bid_v, ask_v in levels:
        dist = abs(price_lv - c_val) + 2.5
        weighted_bid_pressure += bid_v / dist
        weighted_ask_pressure += ask_v / dist
    book_pressure_ratio = weighted_bid_pressure / weighted_ask_pressure if weighted_ask_pressure > 0 else 1.0

    # Large order detection
    avg_level_vol = sum(bid_v + ask_v for _, bid_v, ask_v in levels) / max(len(levels), 1) if levels else 0
    large_bid_count = 0
    large_ask_count = 0
    for price_lv, bid_v, ask_v in levels:
        if avg_level_vol > 0:
            if bid_v > avg_level_vol * 3:
                large_bid_count += 1
            if ask_v > avg_level_vol * 3:
                large_ask_count += 1

    return {
        "time": time_val,
        "open": o, "high": h, "low": l, "close": c_val,
        "volume": vol, "delta": delta,
        "rvol": rvol,
        "poc": poc,
        "local_dg": local_dg,
        "local_dr": local_dr,
        "floor_abs": floor_abs,
        "ceil_abs": ceil_abs,
        "is_churn": is_churn,
        "multi_absorb": multi_absorb,
        "bid_dom_levels": bid_dom_levels,
        "ask_dom_levels": ask_dom_levels,
        "book_pressure_ratio": book_pressure_ratio,
        "large_bid_count": large_bid_count,
        "large_ask_count": large_ask_count,
    }


class LiveV17Runner:
    def __init__(self):
        self.candles = []
        self.current_section = []
        self.signals_fired = []
        self.reported_indices = set()
        self.active_trades = []
        self.last_signal_idx = -3

    def on_new_candle(self, candle):
        self.candles.append(candle)
        n = len(self.candles)

        # Update active trades
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
                "signal": sig,
                "entry_idx": n - 1,
                "status": "ACTIVE",
                "bars_held": 0,
            })
            self.print_signal(sig)

    def _update_active_trades(self):
        """Check if active trades hit target/stop/timeout."""
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
                    self._print_trade_exit(sig, "STOP HIT", -1.0)
                elif c["high"] >= sig["target"]:
                    trade["status"] = "TARGET"
                    self._print_trade_exit(sig, "TARGET HIT", 1.2)
                elif trade["bars_held"] >= 15:
                    exit_price = c["close"]
                    r_pnl = (exit_price - sig["entry"]) / sig["R"] if sig["R"] > 0 else 0
                    trade["status"] = "TIMEOUT"
                    self._print_trade_exit(sig, f"TIMEOUT", r_pnl)
            else:
                if c["high"] >= sig["stop"]:
                    trade["status"] = "STOPPED"
                    self._print_trade_exit(sig, "STOP HIT", -1.0)
                elif c["low"] <= sig["target"]:
                    trade["status"] = "TARGET"
                    self._print_trade_exit(sig, "TARGET HIT", 1.2)
                elif trade["bars_held"] >= 15:
                    exit_price = c["close"]
                    r_pnl = (sig["entry"] - exit_price) / sig["R"] if sig["R"] > 0 else 0
                    trade["status"] = "TIMEOUT"
                    self._print_trade_exit(sig, f"TIMEOUT", r_pnl)

    def _print_trade_exit(self, sig, reason, r_pnl):
        color = "\033[92m" if r_pnl > 0 else "\033[91m"
        reset = "\033[0m"
        print(f"\n  {color}>>> {sig['side']} {sig['time']} -> {reason} ({r_pnl:+.2f}R){reset}")

    def print_signal(self, sig):
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

    def process_line(self, line):
        """Process a line from footprint output."""
        clean = ANSI_RE.sub("", line)

        if TIME_RE.search(clean):
            if self.current_section:
                candle = parse_candle_section(self.current_section)
                if candle:
                    self.on_new_candle(candle)
            self.current_section = [clean]
        elif self.current_section:
            self.current_section.append(clean)

    def flush(self):
        """Parse any remaining section."""
        if self.current_section:
            candle = parse_candle_section(self.current_section)
            if candle:
                self.on_new_candle(candle)
            self.current_section = []


def run_live():
    """Run footprint script in live mode and process output."""
    runner = LiveV17Runner()

    today = datetime.now().strftime('%Y-%m-%d')
    print("=" * 70)
    print(f"  V17 LIVE SIGNAL MONITOR - {today}")
    print(f"  Signals: Double-Push (LONG/SHORT) + Cascade (SHORT)")
    print(f"  Filters: SHORT DOM (cumulative 3-bar net)")
    print(f"  Target: 1.2R | Timeout: 12 bars")
    print("=" * 70)
    print(f"  Starting footprint_v5.84_nifty.py in LIVE mode...")
    print(f"  Waiting for candle data...\n")

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'

    proc = subprocess.Popen(
        [sys.executable, '-u', FOOTPRINT_SCRIPT, today],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=SCRIPT_DIR,
    )

    suppress_count = 0
    try:
        for raw_line in iter(proc.stdout.readline, b''):
            try:
                line = raw_line.decode('utf-8', errors='replace').rstrip('\n\r')
            except:
                continue
            runner.process_line(line)
            # Suppress footprint's own signal alerts (only V17 signals shown)
            if '2B REVERSAL' in line:
                suppress_count = 3
            if suppress_count > 0:
                suppress_count -= 1
                continue
            print(line)

    except KeyboardInterrupt:
        print("\n\n  Stopping...")
    finally:
        proc.terminate()
        runner.flush()

        # Summary
        print("\n" + "=" * 70)
        print(f"  SESSION SUMMARY")
        print(f"  Candles processed: {len(runner.candles)}")
        print(f"  Signals fired: {len(runner.signals_fired)}")
        if runner.signals_fired:
            longs = sum(1 for s in runner.signals_fired if s['side'] == 'LONG')
            shorts = sum(1 for s in runner.signals_fired if s['side'] == 'SHORT')
            cascades = sum(1 for s in runner.signals_fired if s.get('signal_type') == 'cascade')
            print(f"  LONG: {longs} | SHORT: {shorts} (Cascade: {cascades})")
            print(f"\n  All signals:")
            for sig in runner.signals_fired:
                sig_type = "C" if sig.get("signal_type") == "cascade" else "DP"
                print(f"    {sig['time']} {sig['side']:5s} {sig['grade']} "
                      f"Score={sig['score']:2d} Entry={sig['entry']:.2f} "
                      f"Stop={sig['stop']:.2f} Tgt={sig['target']:.2f} [{sig_type}]")

        # Active trade results
        completed = [t for t in runner.active_trades if t["status"] != "ACTIVE"]
        if completed:
            total_r = 0
            print(f"\n  Trade results:")
            for t in completed:
                sig = t["signal"]
                if t["status"] == "TARGET":
                    r = 1.2
                elif t["status"] == "STOPPED":
                    r = -1.0
                else:
                    r = 0
                total_r += r
                print(f"    {sig['time']} {sig['side']:5s} -> {t['status']} ({r:+.1f}R)")
            print(f"  Total: {total_r:+.1f}R")

        print("=" * 70)


def run_on_file(filepath):
    """Run V17 on an existing raw log file (for testing)."""
    runner = LiveV17Runner()

    print(f"  Processing: {filepath}")
    print(f"  Using V17 (DOM filter enabled)\n")
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            clean = ANSI_RE.sub("", line.rstrip('\n\r'))
            if TIME_RE.search(clean):
                if runner.current_section:
                    candle = parse_candle_section(runner.current_section)
                    if candle:
                        runner.on_new_candle(candle)
                runner.current_section = [clean]
            elif runner.current_section:
                runner.current_section.append(clean)

    runner.flush()
    print(f"\n  Candles: {len(runner.candles)} | Signals: {len(runner.signals_fired)}")
    if runner.signals_fired:
        for sig in runner.signals_fired:
            sig_type = "CASCADE" if sig.get("signal_type") == "cascade" else "DP"
            print(f"    {sig['time']} {sig['side']:5s} {sig['grade']} Score={sig['score']:2d} "
                  f"Entry={sig['entry']:.2f} Stop={sig['stop']:.2f} [{sig_type}]")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        if os.path.isfile(filepath):
            run_on_file(filepath)
        else:
            print(f"File not found: {filepath}")
    else:
        run_live()
