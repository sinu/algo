"""Initiative Drive — Continuation pattern detection module.

Detects explosive candle + pocket pullback setups for both LONG and SHORT.
Designed to run alongside V17 reversal signals sharing the same position manager.

Key pattern:
  1. Explosive candle: body >= 70% of range, strong delta in direction
  2. DR pocket (LONG) or DG pocket (SHORT) confirms institutional interest
  3. Pullback into pocket zone → limit entry
  4. Target: 1.5R

Usage:
    from initiative_drive import InitiativeDriveDetector
    detector = InitiativeDriveDetector()
    detector.on_candle(candle_dict)  # returns signal or None
"""

TARGET_R_INIT = 1.5
BODY_MIN = 0.70
PULLBACK_WINDOW = 6  # max bars to wait for pullback
TIMEOUT_BARS = 13    # max bars to hold after entry


def compute_positional_dr_dg(candle_dict):
    """Compute dr_above_mid / dg_below_mid from level_tags and levels.

    This allows the live script to provide these fields without rewriting
    the entire candle extraction. The merged backtest data already has them.

    Note: level_tags corresponds to data_rows (levels filtered to have volume),
    so we must filter levels the same way before aligning by index.
    """
    if 'dr_above_mid' in candle_dict:
        return candle_dict

    levels = candle_dict.get('levels', [])
    level_tags = candle_dict.get('level_tags', [])
    h = candle_dict['high']
    l = candle_dict['low']
    bar_mid = (h + l) / 2.0

    dr_above_mid = 0
    dr_below_mid = 0
    dg_above_mid = 0
    dg_below_mid = 0

    # level_tags is built from data_rows (levels with volume > 0)
    data_rows = [(p, b, a) for p, b, a in levels if b > 0 or a > 0]

    for idx, tag in enumerate(level_tags):
        if idx >= len(data_rows):
            break
        price_lv = data_rows[idx][0]
        if tag == "DR":
            if price_lv >= bar_mid:
                dr_above_mid += 1
            else:
                dr_below_mid += 1
        elif tag == "DG":
            if price_lv >= bar_mid:
                dg_above_mid += 1
            else:
                dg_below_mid += 1

    candle_dict['dr_above_mid'] = dr_above_mid
    candle_dict['dr_below_mid'] = dr_below_mid
    candle_dict['dg_above_mid'] = dg_above_mid
    candle_dict['dg_below_mid'] = dg_below_mid
    return candle_dict


def _compute_atr_from_candles(candles, i, lookback=10):
    """ATR = average bar range over lookback bars."""
    start = max(0, i - lookback)
    ranges = [c['high'] - c['low'] for c in candles[start:i]]
    return sum(ranges) / len(ranges) if ranges else 0


class InitiativeDriveDetector:
    """Stateful detector that accumulates candles and fires signals."""

    def __init__(self):
        self.candles = []
        self.pending_setups = []  # explosive bars awaiting pullback
        self.signals_fired = []
        self.active_trade = None  # only one active at a time

    def on_candle(self, candle_dict):
        """Process a new candle. Returns a signal dict if one fires, else None.

        Call this AFTER V17 has processed the same candle (so V17 gets priority).
        """
        candle_dict = compute_positional_dr_dg(candle_dict)
        self.candles.append(candle_dict)
        n = len(self.candles)

        if n < 7:
            return None

        # Update active trade
        if self.active_trade:
            self._update_active_trade()

        # Check if any pending setup gets a pullback fill this bar
        signal = self._check_pullback_fills()

        # Scan current bar as potential new explosive candle
        self._scan_explosive(n - 1)

        # Expire old pending setups
        self._expire_setups()

        return signal

    def _scan_explosive(self, i):
        """Check if bar i qualifies as an Initiative Drive explosive candle."""
        c = self.candles[i]
        br = c['high'] - c['low']
        if br <= 0:
            return

        body_pct = abs(c['close'] - c['open']) / br
        if body_pct < BODY_MIN:
            return

        atr = _compute_atr_from_candles(self.candles, i)
        if atr <= 0:
            return

        is_bullish = c['close'] > c['open']

        if is_bullish and c['delta'] > 0:
            dr_above = c.get('dr_above_mid', 0)
            if dr_above >= 1:
                # LONG setup: zone = 50-75% of bar range
                pl = c['low'] + br * 0.50
                ph = c['low'] + br * 0.75
                pm = (pl + ph) / 2
                stop = pl - atr * 0.10
                risk = pm - stop
                if risk > 0 and risk <= atr * 1.5:
                    self.pending_setups.append({
                        'side': 'LONG',
                        'explosive_idx': i,
                        'zone_low': pl,
                        'zone_high': ph,
                        'zone_mid': pm,
                        'stop': stop,
                        'risk': risk,
                        'target': pm + risk * TARGET_R_INIT,
                        'atr': atr,
                        'body_pct': body_pct,
                        'dr_above': dr_above,
                        'delta': c['delta'],
                        'time': c.get('time', ''),
                    })

        elif not is_bullish and c['delta'] < 0:
            dg_below = c.get('dg_below_mid', 0)
            if dg_below >= 1:
                # SHORT setup: zone = 35-60% of bar range
                pl = c['low'] + br * 0.35
                ph = c['low'] + br * 0.60
                pm = (pl + ph) / 2
                stop = ph + atr * 0.10
                risk = stop - pm
                if risk > 0 and risk <= atr * 1.5:
                    self.pending_setups.append({
                        'side': 'SHORT',
                        'explosive_idx': i,
                        'zone_low': pl,
                        'zone_high': ph,
                        'zone_mid': pm,
                        'stop': stop,
                        'risk': risk,
                        'target': pm - risk * TARGET_R_INIT,
                        'atr': atr,
                        'body_pct': body_pct,
                        'dg_below': dg_below,
                        'delta': c['delta'],
                        'time': c.get('time', ''),
                    })

    def _check_pullback_fills(self):
        """Check if current bar fills any pending limit order."""
        if not self.pending_setups:
            return None
        if self.active_trade:
            return None

        n = len(self.candles)
        c = self.candles[-1]
        current_idx = n - 1

        for setup in self.pending_setups[:]:
            bars_since = current_idx - setup['explosive_idx']
            if bars_since < 1 or bars_since > PULLBACK_WINDOW:
                continue

            filled = False
            if setup['side'] == 'LONG':
                if c['low'] <= setup['zone_mid']:
                    if c['low'] < setup['stop']:
                        self.pending_setups.remove(setup)
                        continue
                    filled = True
            else:
                if c['high'] >= setup['zone_mid']:
                    if c['high'] > setup['stop']:
                        self.pending_setups.remove(setup)
                        continue
                    filled = True

            if filled:
                # Pullback bar quality check (the key discriminator)
                pb_range = c['high'] - c['low']
                pb_close_pos = (c['close'] - c['low']) / pb_range if pb_range > 0 else 0.5

                quality_ok = False
                if setup['side'] == 'LONG':
                    # LONG: pb bar should close strong (>= 0.5) or be green
                    quality_ok = pb_close_pos >= 0.5 or c['close'] > c['open']
                else:
                    # SHORT: pb bar should close weak (<= 0.5) or be red
                    quality_ok = pb_close_pos <= 0.5 or c['close'] < c['open']

                if not quality_ok:
                    continue

                signal = {
                    'side': setup['side'],
                    'entry': setup['zone_mid'],
                    'stop': setup['stop'],
                    'target': setup['target'],
                    'R': setup['risk'],
                    'time': setup['time'],
                    'entry_time': c.get('time', ''),
                    'entry_idx': current_idx,
                    'explosive_idx': setup['explosive_idx'],
                    'signal_type': 'initiative_drive',
                    'body_pct': setup['body_pct'],
                    'pb_close_pos': pb_close_pos,
                    'pb_bars': bars_since,
                    'atr': setup['atr'],
                }

                self.signals_fired.append(signal)
                self.active_trade = {
                    'signal': signal,
                    'entry_idx': current_idx,
                    'status': 'ACTIVE',
                    'bars_held': 0,
                }
                self.pending_setups.remove(setup)
                return signal

        return None

    def _update_active_trade(self):
        """Update active trade status against current bar."""
        if not self.active_trade or self.active_trade['status'] != 'ACTIVE':
            return

        c = self.candles[-1]
        self.active_trade['bars_held'] += 1
        sig = self.active_trade['signal']

        if sig['side'] == 'LONG':
            if c['low'] <= sig['stop']:
                self.active_trade['status'] = 'STOPPED'
                self.active_trade['r_pnl'] = -1.0
            elif c['high'] >= sig['target']:
                self.active_trade['status'] = 'TARGET'
                self.active_trade['r_pnl'] = TARGET_R_INIT
            elif self.active_trade['bars_held'] >= TIMEOUT_BARS:
                r_pnl = (c['close'] - sig['entry']) / sig['R'] if sig['R'] > 0 else 0
                self.active_trade['status'] = 'TIMEOUT'
                self.active_trade['r_pnl'] = r_pnl
        else:
            if c['high'] >= sig['stop']:
                self.active_trade['status'] = 'STOPPED'
                self.active_trade['r_pnl'] = -1.0
            elif c['low'] <= sig['target']:
                self.active_trade['status'] = 'TARGET'
                self.active_trade['r_pnl'] = TARGET_R_INIT
            elif self.active_trade['bars_held'] >= TIMEOUT_BARS:
                r_pnl = (sig['entry'] - c['close']) / sig['R'] if sig['R'] > 0 else 0
                self.active_trade['status'] = 'TIMEOUT'
                self.active_trade['r_pnl'] = r_pnl

        if self.active_trade['status'] != 'ACTIVE':
            self.active_trade = None

    def _expire_setups(self):
        """Remove setups older than PULLBACK_WINDOW bars."""
        current_idx = len(self.candles) - 1
        self.pending_setups = [s for s in self.pending_setups
                               if current_idx - s['explosive_idx'] <= PULLBACK_WINDOW]

    def has_active_trade(self):
        """Check if there's an active Initiative Drive trade."""
        return self.active_trade is not None

    def get_active_side(self):
        """Return side of active trade, or None."""
        if self.active_trade and self.active_trade['status'] == 'ACTIVE':
            return self.active_trade['signal']['side']
        return None

    def get_pending_sides(self):
        """Return set of sides with pending setups (awaiting pullback)."""
        return set(s['side'] for s in self.pending_setups)

    def print_summary(self):
        """Print session summary."""
        n_signals = len(self.signals_fired)
        if n_signals == 0:
            print("  Initiative Drive: No signals this session")
            return

        longs = sum(1 for s in self.signals_fired if s['side'] == 'LONG')
        shorts = n_signals - longs
        print(f"\n  Initiative Drive: {n_signals} signals (LONG={longs} SHORT={shorts})")
        for sig in self.signals_fired:
            print(f"    {sig['time']} exp -> {sig['entry_time']} entry | "
                  f"{sig['side']:5s} | Entry={sig['entry']:.2f} "
                  f"Stop={sig['stop']:.2f} Tgt={sig['target']:.2f} "
                  f"[body={sig['body_pct']:.0%} pb@{sig['pb_close_pos']:.2f}]")
