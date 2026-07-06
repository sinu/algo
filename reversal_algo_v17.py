"""V17: DOM Confirmation Filters.

Improvements over V16:
1. DOM confirmation for SHORT signals:
   - Require bid_dom_levels >= 4 on push candle (70.3% WR vs 52% baseline)
   - Sellers hitting bids at 4+ price levels = directional conviction confirmed
   - Removes ~30% of losing SHORT trades

2. DOM confirmation for LONG signals:
   - Require trapped_ask_low >= 10K on push candle (66.7% WR vs 53% baseline)
   - Heavy ask volume trapped at the low = fuel for reversal
   - OR ask_dom_levels >= 5 (buyers lifting offers at 5+ levels)

Retains from V16:
- Multi-bar cascade SHORT (R/ATR 1.5 standard, 2.5 for strong abs)
- Trend filter override for SHORT when absorption >= 4
- Target = 1.2R, Stop cap 1.5 ATR, No entry after 14:50
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_v5_full import parse_day


TARGET_R = 1.2
SHORT_TREND_MAX_ATR = 3.0
MAX_STOP_ATR = 1.5
MAX_STOP_ATR_CASCADE = 2.5
LAST_ENTRY_TIME = "14:50"


def compute_session_features(candles):
    n = len(candles)
    if n == 0:
        return {}
    avg_vol = sum(c["volume"] for c in candles) / n

    cum_pv = 0.0
    cum_vol = 0.0
    vwap = []
    for c in candles:
        poc = c.get("poc") or (c["high"] + c["low"]) / 2.0
        tp = (c["high"] + c["low"] + poc) / 3.0
        cum_pv += tp * c["volume"]
        cum_vol += c["volume"]
        vwap.append(cum_pv / cum_vol if cum_vol > 0 else poc)

    return {"avg_vol": avg_vol, "n_candles": n, "vwap": vwap}


def _compute_atr(candles, i, lookback=10):
    start = max(0, i - lookback)
    count = i - start + 1
    return sum(candles[k]["high"] - candles[k]["low"] for k in range(start, i + 1)) / count


def _get_ref_price(c):
    poc = c.get("poc")
    if poc is not None:
        return poc
    return (c["high"] + c["low"]) / 2.0


def _detect_seller_absorption(candles, i, atr):
    best_score = 0
    best_reasons = []

    for lookback in range(1, 8):
        if i - lookback < 0:
            break
        zone = candles[max(0, i - lookback - 2):i]
        zone_floor_abs = sum(x.get("floor_abs", 0) for x in zone)
        zone_churn = any(x.get("is_churn", False) for x in zone)
        zone_multi_abs = max((x.get("multi_absorb", 0) for x in zone), default=0)

        if zone_floor_abs > 0 or zone_churn or zone_multi_abs >= 3:
            prior_zone = candles[max(0, i - lookback - 5):i - lookback + 1]
            if not prior_zone:
                continue
            neg_delta_candles = sum(1 for x in prior_zone if x["delta"] < 0)
            total_selling = sum(x["delta"] for x in prior_zone if x["delta"] < 0)

            if neg_delta_candles >= len(prior_zone) * 0.35 or total_selling < -10000:
                score = 0
                reasons = []
                if zone_floor_abs > 0:
                    score += 2
                    reasons.append(f"fl_abs={zone_floor_abs}")
                if zone_churn:
                    score += 3
                    reasons.append("churn")
                if zone_multi_abs >= 3:
                    score += 1
                    reasons.append(f"mul={zone_multi_abs}")
                if score > best_score:
                    best_score = score
                    best_reasons = reasons
                break

    for window_size in range(3, 15):
        start = i - window_size
        if start < 0:
            break
        window = candles[start:i]
        neg_count = sum(1 for c in window if c["delta"] < 0)
        sell_pct = neg_count / len(window)
        total_neg_delta = sum(c["delta"] for c in window if c["delta"] < 0)

        if total_neg_delta > -12000:
            continue

        lows = [c["low"] for c in window]
        floor_spread = max(lows) - min(lows)
        if atr <= 0:
            continue
        spread_ratio = floor_spread / atr

        if sell_pct >= 0.45 and spread_ratio <= 3.0:
            score = 0
            reasons = []

            if total_neg_delta < -100000:
                score += 3
                reasons.append(f"sell={total_neg_delta/1000:.0f}K")
            elif total_neg_delta < -50000:
                score += 2
                reasons.append(f"sell={total_neg_delta/1000:.0f}K")
            elif total_neg_delta < -20000:
                score += 1
                reasons.append(f"sell={total_neg_delta/1000:.0f}K")

            if spread_ratio < 1.0:
                score += 2
                reasons.append(f"floor_tight={spread_ratio:.1f}")
            elif spread_ratio < 1.8:
                score += 1
                reasons.append(f"floor={spread_ratio:.1f}")

            if sell_pct >= 0.7:
                score += 1
                reasons.append(f"sell%={sell_pct:.0%}")

            if window_size >= 6:
                score += 1
                reasons.append(f"dur={window_size}")

            if score > best_score:
                best_score = score
                best_reasons = reasons

    for window_size in range(4, 20):
        start = i - window_size
        if start < 0:
            break
        window = candles[start:i]
        burst_candles_idx = [j for j in range(len(window)) if window[j]["delta"] < -25000]
        if not burst_candles_idx:
            continue

        last_burst = max(burst_candles_idx)
        hold_zone = window[last_burst + 1:]
        if len(hold_zone) < 2:
            continue

        hold_lows = [c["low"] for c in hold_zone]
        hold_spread = max(hold_lows) - min(hold_lows)
        hold_ratio = hold_spread / atr if atr > 0 else 99

        if hold_ratio > 4.5:
            continue

        burst_delta = sum(window[j]["delta"] for j in burst_candles_idx)
        score = 0
        reasons = []

        if burst_delta < -100000:
            score += 3
            reasons.append(f"burst={burst_delta/1000:.0f}K")
        elif burst_delta < -50000:
            score += 2
            reasons.append(f"burst={burst_delta/1000:.0f}K")
        else:
            score += 1
            reasons.append(f"burst={burst_delta/1000:.0f}K")

        if hold_ratio < 1.5:
            score += 2
            reasons.append(f"hold_tight={hold_ratio:.1f}")
        elif hold_ratio < 2.5:
            score += 1
            reasons.append(f"hold={hold_ratio:.1f}")

        if len(hold_zone) >= 8:
            score += 2
            reasons.append(f"hold_dur={len(hold_zone)}")
        elif len(hold_zone) >= 4:
            score += 1
            reasons.append(f"hold_dur={len(hold_zone)}")

        if score > best_score:
            best_score = score
            best_reasons = reasons

    return best_score, best_reasons


def _detect_buyer_absorption(candles, i, atr):
    best_score = 0
    best_reasons = []

    for lookback in range(1, 8):
        if i - lookback < 0:
            break
        zone = candles[max(0, i - lookback - 2):i]
        zone_ceil_abs = sum(x.get("ceil_abs", 0) for x in zone)
        zone_churn = any(x.get("is_churn", False) for x in zone)
        zone_multi_abs = max((x.get("multi_absorb", 0) for x in zone), default=0)

        if zone_ceil_abs > 0 or zone_churn or zone_multi_abs >= 3:
            prior_zone = candles[max(0, i - lookback - 5):i - lookback + 1]
            if not prior_zone:
                continue
            pos_delta_candles = sum(1 for x in prior_zone if x["delta"] > 0)
            total_buying = sum(x["delta"] for x in prior_zone if x["delta"] > 0)

            if pos_delta_candles >= len(prior_zone) * 0.35 or total_buying > 10000:
                score = 0
                reasons = []
                if zone_ceil_abs > 0:
                    score += 2
                    reasons.append(f"cl_abs={zone_ceil_abs}")
                if zone_churn:
                    score += 3
                    reasons.append("churn")
                if zone_multi_abs >= 3:
                    score += 1
                    reasons.append(f"mul={zone_multi_abs}")
                if score > best_score:
                    best_score = score
                    best_reasons = reasons
                break

    for window_size in range(3, 15):
        start = i - window_size
        if start < 0:
            break
        window = candles[start:i]
        pos_count = sum(1 for c in window if c["delta"] > 0)
        buy_pct = pos_count / len(window)
        total_pos_delta = sum(c["delta"] for c in window if c["delta"] > 0)

        if total_pos_delta < 12000:
            continue

        highs = [c["high"] for c in window]
        ceil_spread = max(highs) - min(highs)
        if atr <= 0:
            continue
        spread_ratio = ceil_spread / atr

        if buy_pct >= 0.45 and spread_ratio <= 3.0:
            score = 0
            reasons = []

            if total_pos_delta > 100000:
                score += 3
                reasons.append(f"buy={total_pos_delta/1000:.0f}K")
            elif total_pos_delta > 50000:
                score += 2
                reasons.append(f"buy={total_pos_delta/1000:.0f}K")
            elif total_pos_delta > 20000:
                score += 1
                reasons.append(f"buy={total_pos_delta/1000:.0f}K")

            if spread_ratio < 1.0:
                score += 2
                reasons.append(f"ceil_tight={spread_ratio:.1f}")
            elif spread_ratio < 1.8:
                score += 1
                reasons.append(f"ceil={spread_ratio:.1f}")

            if buy_pct >= 0.7:
                score += 1
                reasons.append(f"buy%={buy_pct:.0%}")

            if window_size >= 6:
                score += 1
                reasons.append(f"dur={window_size}")

            if score > best_score:
                best_score = score
                best_reasons = reasons

    for window_size in range(4, 20):
        start = i - window_size
        if start < 0:
            break
        window = candles[start:i]
        burst_candles_idx = [j for j in range(len(window)) if window[j]["delta"] > 25000]
        if not burst_candles_idx:
            continue

        last_burst = max(burst_candles_idx)
        hold_zone = window[last_burst + 1:]
        if len(hold_zone) < 2:
            continue

        hold_highs = [c["high"] for c in hold_zone]
        hold_spread = max(hold_highs) - min(hold_highs)
        hold_ratio = hold_spread / atr if atr > 0 else 99

        if hold_ratio > 4.5:
            continue

        burst_delta = sum(window[j]["delta"] for j in burst_candles_idx)
        score = 0
        reasons = []

        if burst_delta > 100000:
            score += 3
            reasons.append(f"burst={burst_delta/1000:.0f}K")
        elif burst_delta > 50000:
            score += 2
            reasons.append(f"burst={burst_delta/1000:.0f}K")
        else:
            score += 1
            reasons.append(f"burst={burst_delta/1000:.0f}K")

        if hold_ratio < 1.5:
            score += 2
            reasons.append(f"hold_tight={hold_ratio:.1f}")
        elif hold_ratio < 2.5:
            score += 1
            reasons.append(f"hold={hold_ratio:.1f}")

        if len(hold_zone) >= 8:
            score += 2
            reasons.append(f"hold_dur={len(hold_zone)}")
        elif len(hold_zone) >= 4:
            score += 1
            reasons.append(f"hold_dur={len(hold_zone)}")

        if score > best_score:
            best_score = score
            best_reasons = reasons

    return best_score, best_reasons


def _is_push_candle_long(c, avg_vol):
    if c["delta"] <= 0:
        return False, 0, []
    rng = c["high"] - c["low"]
    if rng < 2:
        return False, 0, []

    score = 0
    reasons = []

    push_rvol = c.get("rvol", 1.0)
    if push_rvol >= 2.0:
        score += 3
        reasons.append("rvol>=2.0")
    elif push_rvol >= 1.5:
        score += 2
        reasons.append("rvol>=1.5")

    push_dg = c.get("local_dg", 0)
    if push_dg >= 4:
        score += 3
        reasons.append(f"dg={push_dg}")
    elif push_dg >= 3:
        score += 2
        reasons.append(f"dg={push_dg}")
    elif push_dg >= 2:
        score += 1
        reasons.append(f"dg={push_dg}")

    if c["delta"] > 50000:
        score += 3
        reasons.append("delta>50K")
    elif c["delta"] > 30000:
        score += 2
        reasons.append("delta>30K")
    elif c["delta"] > 15000:
        score += 1
        reasons.append("delta>15K")

    push_vol_ratio = c["volume"] / avg_vol if avg_vol > 0 else 1.0
    if push_vol_ratio > 2.0:
        score += 2
        reasons.append("vol>2.0x")
    elif push_vol_ratio > 1.5:
        score += 1
        reasons.append("vol>1.5x")

    return score >= 2, score, reasons


def _is_push_candle_short(c, avg_vol):
    if c["delta"] >= 0:
        return False, 0, []
    rng = c["high"] - c["low"]
    if rng < 2:
        return False, 0, []

    score = 0
    reasons = []

    push_rvol = c.get("rvol", 1.0)
    if push_rvol >= 2.0:
        score += 3
        reasons.append("rvol>=2.0")
    elif push_rvol >= 1.5:
        score += 2
        reasons.append("rvol>=1.5")

    push_dr = c.get("local_dr", 0)
    if push_dr >= 4:
        score += 3
        reasons.append(f"dr={push_dr}")
    elif push_dr >= 3:
        score += 2
        reasons.append(f"dr={push_dr}")
    elif push_dr >= 2:
        score += 1
        reasons.append(f"dr={push_dr}")

    abs_delta = abs(c["delta"])
    if abs_delta > 50000:
        score += 3
        reasons.append("delta<-50K")
    elif abs_delta > 30000:
        score += 2
        reasons.append("delta<-30K")
    elif abs_delta > 15000:
        score += 1
        reasons.append("delta<-15K")

    push_vol_ratio = c["volume"] / avg_vol if avg_vol > 0 else 1.0
    if push_vol_ratio > 2.0:
        score += 2
        reasons.append("vol>2.0x")
    elif push_vol_ratio > 1.5:
        score += 1
        reasons.append("vol>1.5x")

    return score >= 2, score, reasons


def _check_short_trend_filter(candles, i, atr):
    lookback = min(20, i)
    if lookback < 5:
        return False
    window = candles[i - lookback:i]
    prior_rise = window[-1]["high"] - min(c["low"] for c in window)
    if atr > 0 and prior_rise / atr > SHORT_TREND_MAX_ATR:
        return True
    return False


def _detect_multi_bar_cascade_short(candles, i):
    """Detect multi-bar cascading sell pressure."""
    c = candles[i]
    if c["delta"] >= 0:
        return False, 0, []

    for lookback in range(2, 5):
        start = i - lookback + 1
        if start < 1:
            continue
        window = candles[start:i + 1]

        neg_count = sum(1 for x in window if x["delta"] < 0)
        if neg_count < len(window) * 0.7:
            continue

        cum_delta = sum(x["delta"] for x in window)
        if cum_delta > -20000:
            continue

        high_before = max(candles[k]["high"] for k in range(max(0, start - 2), start + 1))
        low_end = min(x["low"] for x in window)
        displacement = high_before - low_end

        atr = _compute_atr(candles, i)
        if atr <= 0:
            continue
        disp_atr = displacement / atr
        if disp_atr < 1.0:
            continue

        seq_range = max(x["high"] for x in window) - min(x["low"] for x in window)
        bounces = [x["close"] - x["low"] for x in window if x["delta"] < 0]
        max_bounce = max(bounces) if bounces else 0
        if max_bounce > seq_range * 0.5:
            continue

        score = 0
        reasons = []

        if cum_delta < -50000:
            score += 3
            reasons.append(f"cascade={cum_delta/1000:.0f}K")
        elif cum_delta < -30000:
            score += 2
            reasons.append(f"cascade={cum_delta/1000:.0f}K")
        else:
            score += 1
            reasons.append(f"cascade={cum_delta/1000:.0f}K")

        if disp_atr >= 2.0:
            score += 2
            reasons.append(f"disp={disp_atr:.1f}ATR")
        elif disp_atr >= 1.5:
            score += 1
            reasons.append(f"disp={disp_atr:.1f}ATR")

        if neg_count == len(window):
            score += 1
            reasons.append(f"all_neg({lookback})")

        if score >= 3:
            return True, score, reasons

    return False, 0, []


def _detect_multi_bar_cascade_long(candles, i):
    """Detect multi-bar cascading buy pressure."""
    c = candles[i]
    if c["delta"] <= 0:
        return False, 0, []

    for lookback in range(2, 5):
        start = i - lookback + 1
        if start < 1:
            continue
        window = candles[start:i + 1]

        pos_count = sum(1 for x in window if x["delta"] > 0)
        if pos_count < len(window) * 0.7:
            continue

        cum_delta = sum(x["delta"] for x in window)
        if cum_delta < 20000:
            continue

        low_before = min(candles[k]["low"] for k in range(max(0, start - 2), start + 1))
        high_end = max(x["high"] for x in window)
        displacement = high_end - low_before

        atr = _compute_atr(candles, i)
        if atr <= 0:
            continue
        disp_atr = displacement / atr
        if disp_atr < 1.0:
            continue

        seq_range = max(x["high"] for x in window) - min(x["low"] for x in window)
        pullbacks = [x["high"] - x["close"] for x in window if x["delta"] > 0]
        max_pullback = max(pullbacks) if pullbacks else 0
        if max_pullback > seq_range * 0.5:
            continue

        score = 0
        reasons = []

        if cum_delta > 50000:
            score += 3
            reasons.append(f"cascade={cum_delta/1000:.0f}K")
        elif cum_delta > 30000:
            score += 2
            reasons.append(f"cascade={cum_delta/1000:.0f}K")
        else:
            score += 1
            reasons.append(f"cascade={cum_delta/1000:.0f}K")

        if disp_atr >= 2.0:
            score += 2
            reasons.append(f"disp={disp_atr:.1f}ATR")
        elif disp_atr >= 1.5:
            score += 1
            reasons.append(f"disp={disp_atr:.1f}ATR")

        if pos_count == len(window):
            score += 1
            reasons.append(f"all_pos({lookback})")

        if score >= 3:
            return True, score, reasons

    return False, 0, []


def detect_signals(candles, feats, min_score=7, live_mode=False):
    """Detect signals: double-push + multi-bar cascade.

    V16 additions:
    - Multi-bar cascade push (SHORT/LONG) with relaxed stop (2.5 ATR)
    - Trend filter override when absorption >= 4
    """
    n = len(candles)
    signals = []
    if n < (7 if live_mode else 10):
        return signals

    avg_vol = feats["avg_vol"]
    vwap = feats["vwap"]

    for i in range(6, n if live_mode else n - 3):
        c = candles[i]

        candle_time = c.get("time", "")
        _hhmm = candle_time[11:16] if len(candle_time) > 11 else candle_time[0:5]
        if _hhmm >= LAST_ENTRY_TIME:
            continue

        # === TRY LONG (standard double-push) ===
        is_push2_long, push2_score_l, push2_reasons_l = _is_push_candle_long(c, avg_vol)
        if is_push2_long and push2_score_l >= 3:
            atr = _compute_atr(candles, i)

            # PEAK guard: block LONG when making new session high (breakout, not reversal)
            session_high = max(candles[k]["high"] for k in range(0, i))
            if c["high"] >= session_high:
                pass
            else:
                session_low = min(candles[k]["low"] for k in range(0, i + 1))
                session_range = session_high - session_low
                entry_depth = (session_high - c["close"]) / session_range if session_range > 0 else 0
                if entry_depth < 0.15:
                    pass
                # Block when making new local high (buying into rally, not reversal from support)
                elif c["high"] >= max(candles[k]["high"] for k in range(max(0, i - 6), i)):
                    pass
                else:
                    # Filter A: trapped-at-low distribution blocker
                    _bars_near_low = sum(1 for _k in range(max(0, i - 8), i + 1) if (candles[_k]["low"] - session_low) < atr * 1.5)
                    _cum_delta_9 = sum(candles[_k]["delta"] for _k in range(max(0, i - 8), i + 1))
                    _trapped_at_low = (_bars_near_low >= 7 and _cum_delta_9 > 0)

                    # Filter C: spike-bounce dead-cat blocker
                    _sr_atr = session_range / atr if atr > 0 else 0
                    _eh = (_get_ref_price(c) - session_low) / session_range if session_range > 0 else 0
                    _cum6 = sum(candles[_k]["delta"] for _k in range(max(0, i - 6), i))
                    _sb_ratio = abs(c["delta"] / _cum6) if _cum6 < 0 else 0
                    _spike_bounce = (_sr_atr >= 3.0 and _cum6 < 0 and _sb_ratio >= 0.60 and 0.40 <= _eh < 0.65)

                    if not _trapped_at_low and not _spike_bounce:
                        for gap in range(1, 4):
                            p1_idx = i - gap
                            if p1_idx < 5:
                                break
                            p1 = candles[p1_idx]

                            if p1["delta"] <= 0:
                                continue
                            _, push1_score_l, push1_reasons_l = _is_push_candle_long(p1, avg_vol)

                            between = candles[p1_idx + 1:i]
                            counter_push = any(x["delta"] < -15000 for x in between)
                            if counter_push:
                                continue

                            initiative_score = push2_score_l + max(1, push1_score_l // 2)

                            abs_atr = _compute_atr(candles, p1_idx)
                            abs_score, abs_reasons = _detect_seller_absorption(candles, p1_idx, abs_atr)
                            if abs_score == 0:
                                continue

                            total_score = initiative_score + abs_score
                            if total_score < min_score:
                                continue

                            entry = _get_ref_price(c)
                            push_low = min(p1["low"], c["low"])
                            pre_push_low = candles[max(0, p1_idx - 1)]["low"]
                            stop = min(push_low, pre_push_low) - atr * 0.1
                            R = entry - stop

                            if R <= atr * 0.1 or R > atr * 2.5:
                                continue

                            if R > atr * MAX_STOP_ATR:
                                continue

                            current_vwap = vwap[i]
                            target = entry + R * TARGET_R

                            if current_vwap > entry and (current_vwap - entry) < R:
                                continue

                            vwap_support = current_vwap < entry and (entry - current_vwap) < R * 0.5

                            if total_score >= 11:
                                grade = "A+"
                            elif total_score >= 9:
                                grade = "A"
                            elif total_score >= 7:
                                grade = "B+"
                            else:
                                grade = "B"

                            all_reasons = abs_reasons + push1_reasons_l + push2_reasons_l

                            signals.append({
                                "side": "LONG",
                                "candle_idx": i,
                                "push1_idx": p1_idx,
                                "time": c.get("time", ""),
                                "entry": entry,
                                "stop": stop,
                                "target": target,
                                "R": R,
                                "score": total_score,
                                "grade": grade,
                                "initiative_score": initiative_score,
                                "abs_score": abs_score,
                                "push1_score": push1_score_l,
                                "push2_score": push2_score_l,
                                "reasons": all_reasons,
                                "vwap": current_vwap,
                                "vwap_support": vwap_support,
                                "push_rvol": c.get("rvol", 1.0),
                                "push_dg": c.get("local_dg", 0),
                                "push_dr": 0,
                                "push_delta": c["delta"],
                                "signal_type": "double_push",
                            })
                            break

        # === TRY LONG (absorption-confirmed bounce) ===
        # Narrow path: floor_abs on signal candle + NOT making new local low = bounce confirmed
        if not any(s["candle_idx"] == i and s["side"] == "LONG" for s in signals):
            _has_floor = c.get("floor_abs", 0) > 0
            if _has_floor and c["delta"] > 0:
                _local_lows = [candles[k]["low"] for k in range(max(0, i - 6), i)]
                _not_new_low = c["low"] > min(_local_lows) if _local_lows else False
                if _not_new_low:
                    atr = _compute_atr(candles, i)
                    session_high = max(candles[k]["high"] for k in range(0, i))
                    session_low = min(candles[k]["low"] for k in range(0, i + 1))
                    session_range = session_high - session_low
                    entry_depth = (session_high - c["close"]) / session_range if session_range > 0 else 0
                    if c["high"] < session_high and entry_depth >= 0.30:
                        # Filter A: trapped-at-low distribution blocker
                        _bnl = sum(1 for _k in range(max(0, i - 8), i + 1)
                                   if (candles[_k]["low"] - session_low) < atr * 1.5)
                        _cd9 = sum(candles[_k]["delta"] for _k in range(max(0, i - 8), i + 1))
                        if _bnl >= 7 and _cd9 > 0:
                            pass
                        else:
                            # Filter C: spike-bounce dead-cat blocker
                            _sr_atr2 = session_range / atr if atr > 0 else 0
                            _eh2 = (_get_ref_price(c) - session_low) / session_range if session_range > 0 else 0
                            _cum6_2 = sum(candles[_k]["delta"] for _k in range(max(0, i - 6), i))
                            _sb_ratio2 = abs(c["delta"] / _cum6_2) if _cum6_2 < 0 else 0
                            _spike_bounce_block2 = (_sr_atr2 >= 3.0 and _cum6_2 < 0
                                                    and _sb_ratio2 >= 0.60
                                                    and 0.40 <= _eh2 < 0.65)
                            if _spike_bounce_block2:
                                pass
                            else:
                                for gap in range(1, 4):
                                    p1_idx = i - gap
                                    if p1_idx < 5:
                                        break
                                    p1 = candles[p1_idx]
                                    if p1["delta"] <= 0:
                                        continue

                                    abs_atr = _compute_atr(candles, p1_idx)
                                    abs_score, abs_reasons = _detect_seller_absorption(candles, p1_idx, abs_atr)
                                    if abs_score < 3:
                                        continue

                                    _, push1_score_l, push1_reasons_l = _is_push_candle_long(p1, avg_vol)
                                    entry = _get_ref_price(c)
                                    push_low = min(p1["low"], c["low"])
                                    pre_push_low = candles[max(0, p1_idx - 1)]["low"]
                                    stop = min(push_low, pre_push_low) - atr * 0.1
                                    R = entry - stop

                                    if R <= atr * 0.1 or R > atr * 2.5:
                                        continue
                                    if R > atr * MAX_STOP_ATR:
                                        continue

                                    current_vwap = vwap[i]
                                    target = entry + R * TARGET_R

                                    if current_vwap > entry and (current_vwap - entry) < R:
                                        continue

                                    vwap_support = current_vwap < entry and (entry - current_vwap) < R * 0.5
                                    total_score = abs_score + 1 + max(1, push1_score_l // 2)

                                    if total_score >= 9:
                                        grade = "A"
                                    elif total_score >= 7:
                                        grade = "B+"
                                    else:
                                        grade = "B"

                                    all_reasons = abs_reasons + push1_reasons_l + ["floor_bounce"]
                                    signals.append({
                                        "side": "LONG",
                                        "candle_idx": i,
                                        "push1_idx": p1_idx,
                                        "time": c.get("time", ""),
                                        "entry": entry,
                                        "stop": stop,
                                        "target": target,
                                        "R": R,
                                        "score": total_score,
                                        "grade": grade,
                                        "initiative_score": 1 + max(1, push1_score_l // 2),
                                        "abs_score": abs_score,
                                        "push1_score": push1_score_l,
                                        "push2_score": 0,
                                        "reasons": all_reasons,
                                        "vwap": current_vwap,
                                        "vwap_support": vwap_support,
                                        "push_rvol": c.get("rvol", 1.0),
                                        "push_dg": c.get("local_dg", 0),
                                        "push_dr": 0,
                                        "push_delta": c["delta"],
                                        "signal_type": "floor_bounce",
                                    })
                                    break

        # === TRY LONG (VWAP pullback) ===
        # Price broke above VWAP, rallied, pulled back to VWAP, DG-L-DG at VWAP support
        # DG-L-DG = buyer presence at multiple levels (dg>=3) with no seller disruption (dr==0)
        if not any(s["candle_idx"] == i and s["side"] == "LONG" for s in signals):
            if (c["delta"] > 0 and c.get("local_dg", 0) >= 3
                    and c.get("local_dr", 0) == 0 and c["close"] > vwap[i]):
                _atr_vp = _compute_atr(candles, i)
                _low_near_vwap = c["low"] <= vwap[i] + _atr_vp * 0.3
                _bars_above = sum(1 for k in range(max(0, i - 8), i)
                                  if candles[k]["close"] > vwap[k])
                if _low_near_vwap and _bars_above >= 5:
                    _sh = max(candles[k]["high"] for k in range(0, i))
                    _local_h = max(candles[k]["high"] for k in range(max(0, i - 6), i))
                    if c["high"] < _sh and c["high"] < _local_h:
                        _best_abs = 0
                        _best_abs_reasons = []
                        for _chk in range(max(0, i - 3), i + 1):
                            _a, _ar = _detect_seller_absorption(candles, _chk, _atr_vp)
                            if _a > _best_abs:
                                _best_abs = _a
                                _best_abs_reasons = _ar
                        if _best_abs >= 3:
                            _entry = _get_ref_price(c)
                            _recent_low = min(candles[k]["low"] for k in range(max(0, i - 3), i + 1))
                            _stop = _recent_low - _atr_vp * 0.1
                            _R = _entry - _stop
                            if _R > _atr_vp * 0.15 and _R <= _atr_vp * MAX_STOP_ATR:
                                _target = _entry + _R * TARGET_R
                                _total = _best_abs + 2 + c.get("local_dg", 0)
                                _grade = "A" if _total >= 9 else "B+" if _total >= 7 else "B"
                                _all_reasons = _best_abs_reasons + [f"dg={c.get('local_dg',0)}", "vwap_pullback"]
                                signals.append({
                                    "side": "LONG",
                                    "candle_idx": i,
                                    "push1_idx": i - 1,
                                    "time": c.get("time", ""),
                                    "entry": _entry,
                                    "stop": _stop,
                                    "target": _target,
                                    "R": _R,
                                    "score": _total,
                                    "grade": _grade,
                                    "initiative_score": 2 + c.get("local_dg", 0),
                                    "abs_score": _best_abs,
                                    "push1_score": 0,
                                    "push2_score": c.get("local_dg", 0),
                                    "reasons": _all_reasons,
                                    "vwap": vwap[i],
                                    "vwap_support": True,
                                    "push_rvol": c.get("rvol", 1.0),
                                    "push_dg": c.get("local_dg", 0),
                                    "push_dr": 0,
                                    "push_delta": c["delta"],
                                    "signal_type": "vwap_pullback",
                                })

        # === TRY SHORT (standard double-push) ===
        is_push2_short, push2_score_s, push2_reasons_s = _is_push_candle_short(c, avg_vol)
        if is_push2_short and push2_score_s >= 3:
            atr = _compute_atr(candles, i)

            # V16: trend filter override when absorption is strong
            trend_blocked = _check_short_trend_filter(candles, i, atr)

            for gap in range(1, 4):
                p1_idx = i - gap
                if p1_idx < 5:
                    break
                p1 = candles[p1_idx]

                if p1["delta"] >= 0:
                    continue
                _, push1_score_s, push1_reasons_s = _is_push_candle_short(p1, avg_vol)

                between = candles[p1_idx + 1:i]
                counter_push = any(x["delta"] > 15000 for x in between)
                if counter_push:
                    continue

                initiative_score = push2_score_s + max(1, push1_score_s // 2)

                abs_atr = _compute_atr(candles, p1_idx)
                abs_score, abs_reasons = _detect_buyer_absorption(candles, p1_idx, abs_atr)
                if abs_score == 0:
                    continue

                # V16: allow through trend filter if absorption >= 4
                if trend_blocked and abs_score < 4:
                    continue

                total_score = initiative_score + abs_score
                if total_score < min_score:
                    continue

                entry = _get_ref_price(c)
                recent_high = max(candles[k]["high"] for k in range(max(0, p1_idx - 5), p1_idx + 1))
                stop = recent_high + atr * 0.2
                R = stop - entry

                if R <= atr * 0.15 or R > atr * 3.5:
                    continue

                if R > atr * MAX_STOP_ATR:
                    continue

                current_vwap = vwap[i]
                target = entry - R * TARGET_R
                vwap_support = current_vwap > entry

                if not vwap_support:
                    continue

                if total_score >= 12:
                    grade = "A+"
                elif total_score >= 10:
                    grade = "A"
                elif total_score >= 8:
                    grade = "B+"
                else:
                    grade = "B"

                all_reasons = abs_reasons + push1_reasons_s + push2_reasons_s

                # V17: DOM contradiction filter for SHORT double-push
                # Block if buyers dominate DOM on both signal candle AND cumulative 3-bar
                dom_single_net = c.get("bid_dom_levels", 0) - c.get("ask_dom_levels", 0)
                dom_cum_bid = sum(candles[k].get("bid_dom_levels", 0) for k in range(max(0, i - 2), i + 1))
                dom_cum_ask = sum(candles[k].get("ask_dom_levels", 0) for k in range(max(0, i - 2), i + 1))
                dom_cum_net = dom_cum_bid - dom_cum_ask
                if dom_single_net <= 0 and dom_cum_net <= 0:
                    continue

                signals.append({
                    "side": "SHORT",
                    "candle_idx": i,
                    "push1_idx": p1_idx,
                    "time": c.get("time", ""),
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "R": R,
                    "score": total_score,
                    "grade": grade,
                    "initiative_score": initiative_score,
                    "abs_score": abs_score,
                    "push1_score": push1_score_s,
                    "push2_score": push2_score_s,
                    "reasons": all_reasons,
                    "vwap": current_vwap,
                    "vwap_support": vwap_support,
                    "push_rvol": c.get("rvol", 1.0),
                    "push_dg": 0,
                    "push_dr": c.get("local_dr", 0),
                    "push_delta": c["delta"],
                    "signal_type": "double_push",
                })
                break

        # === TRY SHORT (multi-bar cascade) ===
        # Only if standard push didn't already fire on this bar
        if not (is_push2_short and push2_score_s >= 3):
            is_cascade_s, cascade_score_s, cascade_reasons_s = _detect_multi_bar_cascade_short(candles, i)
            if is_cascade_s:
                atr = _compute_atr(candles, i)

                # Cascade must be near resistance (upper portion of range), not chasing a crash
                _s_high = max(candles[k]["high"] for k in range(0, i))
                _s_low = min(candles[k]["low"] for k in range(0, i + 1))
                _s_range = _s_high - _s_low
                _entry_height = (c["close"] - _s_low) / _s_range if _s_range > 0 else 0.5
                if _entry_height < 0.35:
                    continue

                # For cascade: override trend filter if absorption >= 4
                trend_blocked = _check_short_trend_filter(candles, i, atr)

                # Find best absorption in the 4 bars before cascade end
                best_abs = 0
                best_abs_reasons = []
                for check in range(max(0, i - 4), i):
                    a_score, a_reasons = _detect_buyer_absorption(candles, check, atr)
                    if a_score > best_abs:
                        best_abs = a_score
                        best_abs_reasons = a_reasons

                if best_abs > 0:
                    if trend_blocked and best_abs < 4:
                        pass  # blocked
                    else:
                        total_score = cascade_score_s + best_abs
                        if total_score >= 7:
                            entry = _get_ref_price(c)
                            recent_high = max(candles[k]["high"] for k in range(max(0, i - 6), i + 1))
                            stop = recent_high + atr * 0.2
                            R = stop - entry

                            # Cascade stop: 1.5 ATR standard, 2.5 ATR if absorption >= 5
                            max_stop = MAX_STOP_ATR_CASCADE if best_abs >= 5 else MAX_STOP_ATR
                            if R > atr * 0.15 and R <= atr * max_stop:
                                current_vwap = vwap[i]
                                if current_vwap > entry:
                                    target = entry - R * TARGET_R

                                    if total_score >= 12:
                                        grade = "A+"
                                    elif total_score >= 10:
                                        grade = "A"
                                    elif total_score >= 8:
                                        grade = "B+"
                                    else:
                                        grade = "B"

                                    all_reasons = cascade_reasons_s + best_abs_reasons

                                    # V17: DOM contradiction filter for SHORT cascade
                                    dom_single_net_c = c.get("bid_dom_levels", 0) - c.get("ask_dom_levels", 0)
                                    dom_cum_bid_c = sum(candles[k].get("bid_dom_levels", 0) for k in range(max(0, i - 2), i + 1))
                                    dom_cum_ask_c = sum(candles[k].get("ask_dom_levels", 0) for k in range(max(0, i - 2), i + 1))
                                    dom_cum_net_c = dom_cum_bid_c - dom_cum_ask_c
                                    if dom_single_net_c <= 0 and dom_cum_net_c <= 0:
                                        continue

                                    signals.append({
                                        "side": "SHORT",
                                        "candle_idx": i,
                                        "push1_idx": i - 1,
                                        "time": c.get("time", ""),
                                        "entry": entry,
                                        "stop": stop,
                                        "target": target,
                                        "R": R,
                                        "score": total_score,
                                        "grade": grade,
                                        "initiative_score": cascade_score_s,
                                        "abs_score": best_abs,
                                        "push1_score": 0,
                                        "push2_score": cascade_score_s,
                                        "reasons": all_reasons,
                                        "vwap": current_vwap,
                                        "vwap_support": True,
                                        "push_rvol": c.get("rvol", 1.0),
                                        "push_dg": 0,
                                        "push_dr": c.get("local_dr", 0),
                                        "push_delta": c["delta"],
                                        "signal_type": "cascade",
                                    })

        # === LONG cascade intentionally omitted (negative expectancy in backtest) ===


    # === TRY DOM-BASED STRATEGIES AFTER FULL LOOP ===
    for i in range(6, n if live_mode else n - 3):
        c = candles[i]
        
        # 1. LAST_ENTRY_TIME check
        candle_time = c.get("time", "")
        _hhmm = candle_time[11:16] if len(candle_time) > 11 else candle_time[0:5]
        if _hhmm >= LAST_ENTRY_TIME:
            break

        # Recompute push2 variables for current candle (must not use stale values from first loop)
        avg_vol = sum(candles[k]["volume"] for k in range(max(0, i - 6), i)) / min(i, 6)
        is_push2_short, push2_score_s, push2_reasons_s = _is_push_candle_short(c, avg_vol)

        # === TRY SHORT (stale distribution — relaxed push2 threshold) ===
        # When session high is stale (>10 bars ago) and VWAP near/above entry,
        # allow push2_score >= 2 (the rally is over, distribution confirmed)
        if not any(s["candle_idx"] == i and s["side"] == "SHORT" for s in signals):
            if is_push2_short and push2_score_s == 2:
                _sd_atr = _compute_atr(candles, i)
                if _sd_atr > 0:
                    _sd_sh = max(candles[k]["high"] for k in range(0, i + 1))
                    _sd_hm = max(range(0, i + 1), key=lambda k: candles[k]["high"])
                    _sd_bars_since = i - _sd_hm
                    if _sd_bars_since > 10:
                        _sd_entry = _get_ref_price(c)
                        _sd_vwap = vwap[i]
                        _sd_vwap_ok = _sd_vwap > _sd_entry or abs(_sd_vwap - _sd_entry) <= _sd_atr * 0.3
                        _sd_sl = min(candles[k]["low"] for k in range(0, i + 1))
                        _sd_sr = _sd_sh - _sd_sl
                        _sd_eh = (c["close"] - _sd_sl) / _sd_sr if _sd_sr > 0 else 0.5
                        if _sd_vwap_ok and _sd_eh >= 0.35 and abs(c["delta"]) >= 5000:
                            _sd_trend_blocked = _check_short_trend_filter(candles, i, _sd_atr)

                            for _sd_gap in range(1, 4):
                                _sd_p1_idx = i - _sd_gap
                                if _sd_p1_idx < 5:
                                    break
                                _sd_p1 = candles[_sd_p1_idx]
                                if _sd_p1["delta"] >= 0:
                                    continue

                                _sd_is_p1, _sd_p1_score, _sd_p1_reasons = _is_push_candle_short(_sd_p1, avg_vol)
                                if not _sd_is_p1:
                                    continue

                                _sd_between = candles[_sd_p1_idx + 1:i]
                                if any(x["delta"] > 15000 for x in _sd_between):
                                    continue

                                _sd_init = push2_score_s + max(1, _sd_p1_score // 2)
                                _sd_abs_atr = _compute_atr(candles, _sd_p1_idx)
                                _sd_abs_score, _sd_abs_reasons = _detect_buyer_absorption(candles, _sd_p1_idx, _sd_abs_atr)
                                if _sd_abs_score == 0:
                                    continue
                                if _sd_trend_blocked and _sd_abs_score < 4:
                                    continue

                                _sd_total = _sd_init + _sd_abs_score
                                if _sd_total < 7:
                                    continue

                                _sd_recent_high = max(candles[k]["high"] for k in range(max(0, _sd_p1_idx - 5), _sd_p1_idx + 1))
                                _sd_stop = _sd_recent_high + _sd_atr * 0.2
                                _sd_R = _sd_stop - _sd_entry
                                if _sd_R <= _sd_atr * 0.15 or _sd_R > _sd_atr * 3.5:
                                    continue
                                if _sd_R > _sd_atr * 1.6:
                                    continue

                                _sd_target = _sd_entry - _sd_R * TARGET_R
                                _sd_grade = "A" if _sd_total >= 9 else "B+" if _sd_total >= 7 else "B"
                                _sd_all_reasons = _sd_abs_reasons + _sd_p1_reasons + push2_reasons_s + ["stale_distribution"]

                                signals.append({
                                    "side": "SHORT",
                                    "candle_idx": i,
                                    "push1_idx": _sd_p1_idx,
                                    "time": c.get("time", ""),
                                    "entry": _sd_entry,
                                    "stop": _sd_stop,
                                    "target": _sd_target,
                                    "R": _sd_R,
                                    "score": _sd_total,
                                    "grade": _sd_grade,
                                    "initiative_score": _sd_init,
                                    "abs_score": _sd_abs_score,
                                    "push1_score": _sd_p1_score,
                                    "push2_score": push2_score_s,
                                    "reasons": _sd_all_reasons,
                                    "vwap": _sd_vwap,
                                    "vwap_support": _sd_vwap > _sd_entry,
                                    "push_rvol": c.get("rvol", 1.0),
                                    "push_dg": 0,
                                    "push_dr": c.get("local_dr", 0),
                                    "push_delta": c["delta"],
                                    "signal_type": "double_push",
                                })
                                break

        # === TRY SHORT (ceiling rejection) ===
        # Mirror of floor_bounce for LONG: first selling at session high with absorption
        # No double-push needed — the ceiling rejection IS the signal
        if not any(s["candle_idx"] == i and s["side"] == "SHORT" for s in signals):
            _has_ceil = c.get("ceil_abs", 0) > 0
            _dr_strong = c.get("local_dr", 0) >= 3
            if c["delta"] < 0 and _dr_strong:
                atr = _compute_atr(candles, i)
                session_high = max(candles[k]["high"] for k in range(0, i + 1))
                session_low = min(candles[k]["low"] for k in range(0, i + 1))
                session_range = session_high - session_low

                # Must be near session high (upper 30% of range)
                entry_height = (c["close"] - session_low) / session_range if session_range > 0 else 0.5
                if entry_height >= 0.70:
                    # Session high must have been made within last 3 candles
                    high_maker_idx = max(range(0, i + 1), key=lambda k: candles[k]["high"])
                    if i - high_maker_idx <= 2:
                        # NOT making new session low
                        _local_lows = [candles[k]["low"] for k in range(max(0, i - 6), i)]
                        _not_new_low = c["low"] > min(_local_lows) if _local_lows else False
                        if _not_new_low:
                            # Buyer absorption confirmation (buyers tried, got absorbed)
                            abs_atr = _compute_atr(candles, i)
                            abs_score, abs_reasons = _detect_buyer_absorption(candles, i, abs_atr)
                            if abs_score >= 3 or _has_ceil:
                                abs_score = max(abs_score, 3 if _has_ceil else 0)
                                entry = _get_ref_price(c)
                                stop = session_high + atr * 0.2
                                R = stop - entry

                                if R > atr * 0.15 and R <= atr * 1.6:
                                    current_vwap = vwap[i]
                                    if current_vwap < entry:
                                        target = entry - R * TARGET_R

                                        total_score = abs_score + 1 + c.get("local_dr", 0) // 2
                                        if total_score >= 9:
                                            grade = "A"
                                        elif total_score >= 7:
                                            grade = "B+"
                                        else:
                                            grade = "B"

                                        all_reasons = abs_reasons + [f"dr={c.get('local_dr',0)}", "ceiling_rejection"]

                                        # Trend filter: block low-score CR in early session on strong trend-up days
                                        _cr_trend_blocked = False
                                        if total_score < 7 and i < 15:
                                            _cr_trend_blocked = _check_short_trend_filter(candles, i, atr)

                                        if not _cr_trend_blocked:
                                            # DOM filter (same as double-push)
                                            dom_single_net = c.get("bid_dom_levels", 0) - c.get("ask_dom_levels", 0)
                                            dom_cum_bid = sum(candles[k].get("bid_dom_levels", 0) for k in range(max(0, i - 2), i + 1))
                                            dom_cum_ask = sum(candles[k].get("ask_dom_levels", 0) for k in range(max(0, i - 2), i + 1))
                                            dom_cum_net = dom_cum_bid - dom_cum_ask
                                            if dom_single_net > 0 or dom_cum_net > 0:
                                                signals.append({
                                                    "side": "SHORT",
                                                    "candle_idx": i,
                                                    "push1_idx": i,
                                                    "time": c.get("time", ""),
                                                    "entry": entry,
                                                    "stop": stop,
                                                    "target": target,
                                                    "R": R,
                                                    "score": total_score,
                                                    "grade": grade,
                                                    "initiative_score": 1 + c.get("local_dr", 0) // 2,
                                                    "abs_score": abs_score,
                                                    "push1_score": 0,
                                                    "push2_score": c.get("local_dr", 0),
                                                    "reasons": all_reasons,
                                                    "vwap": current_vwap,
                                                    "vwap_support": True,
                                                    "push_rvol": c.get("rvol", 1.0),
                                                    "push_dg": 0,
                                                    "push_dr": c.get("local_dr", 0),
                                                    "push_delta": c["delta"],
                                                    "signal_type": "ceiling_rejection",
                                                })

        # === TRY SHORT (failed breakout) ===
        # Prior bar = strong buy push (breakout attempt), signal bar = immediate rejection
        if not any(s["candle_idx"] == i and s["side"] == "SHORT" for s in signals):
            _prior = candles[i - 1] if i >= 1 else None
            if _prior and _prior["delta"] > 15000 and _prior.get("local_dg", 0) >= 3:
                if c["delta"] < 0 and c.get("local_dr", 0) >= 3:
                    _fb_atr = _compute_atr(candles, i)
                    _fb_sh = max(candles[k]["high"] for k in range(0, i + 1))
                    _fb_sl = min(candles[k]["low"] for k in range(0, i + 1))
                    _fb_range = _fb_sh - _fb_sl
                    if _fb_range > 0 and _fb_atr > 0:
                        _fb_height = (c["close"] - _fb_sl) / _fb_range
                        if _fb_height >= 0.70 and abs(c["delta"]) >= 10000:
                            _fb_entry = c.get("poc") or (c["high"] + c["low"]) / 2.0
                            _fb_stop = max(_prior["high"], c["high"]) + _fb_atr * 0.2
                            _fb_R = _fb_stop - _fb_entry
                            if _fb_R > _fb_atr * 0.15 and _fb_R <= _fb_atr * 2.5:
                                _fb_target = _fb_entry - _fb_R * TARGET_R
                                _fb_score = 3 + c.get("local_dr", 0) // 2
                                _fb_grade = "A" if _fb_score >= 6 else "B+"
                                signals.append({
                                    "side": "SHORT",
                                    "candle_idx": i,
                                    "push1_idx": i - 1,
                                    "time": c.get("time", ""),
                                    "entry": _fb_entry,
                                    "stop": _fb_stop,
                                    "target": _fb_target,
                                    "R": _fb_R,
                                    "score": _fb_score,
                                    "grade": _fb_grade,
                                    "initiative_score": 3,
                                    "abs_score": 0,
                                    "push1_score": 0,
                                    "push2_score": c.get("local_dr", 0),
                                    "reasons": [f"fb_prior_dg={_prior.get('local_dg', 0)}",
                                                f"fb_prior_delta={_prior['delta']/1000:.0f}K",
                                                f"dr={c.get('local_dr', 0)}",
                                                "failed_breakout"],
                                    "vwap": vwap[i],
                                    "vwap_support": False,
                                    "push_rvol": c.get("rvol", 1.0),
                                    "push_dg": 0,
                                    "push_dr": c.get("local_dr", 0),
                                    "push_delta": c["delta"],
                                    "signal_type": "failed_breakout",
                                })

        # === LONG cascade intentionally omitted (negative expectancy in backtest) ===

        atr = _compute_atr(candles, i)
        avg_vol = sum(candles[k]["volume"] for k in range(max(0, i - 6), i)) / min(i, 6)
        
        # Calculate Session Context
        session_high = max(candles[k]["high"] for k in range(0, i))
        session_low = min(candles[k]["low"] for k in range(0, i + 1))
        session_range = session_high - session_low
        entry_height = (c["close"] - session_low) / session_range if session_range > 0 else 0.5
        
        # === TRY LONG (Iceberg Squeeze) ===
        if not any(s["candle_idx"] == i and s["side"] == "LONG" for s in signals):
            body = c["close"] - c["open"]
            if c.get("ceil_abs", 0) >= 50 and 0 < c["delta"] < 20000:
                recent_dr_zero = all(candles[k].get("local_dr", 0) == 0 for k in range(max(0, i-2), i+1))
                _isq_context = session_range >= 2.0 * atr or vwap[i] < c["close"]
                if recent_dr_zero and entry_height <= 0.70 and _isq_context:
                    entry = _get_ref_price(c)
                    recent_low = min(candles[k]["low"] for k in range(max(0, i-3), i+1))
                    stop = recent_low - atr * 0.1
                    R = entry - stop

                    if R > atr * 0.5 and R <= atr * 2.5:
                        target = entry + R * TARGET_R
                        signals.append({
                            "side": "LONG",
                            "candle_idx": i,
                            "push1_idx": i,
                            "time": c.get("time", ""),
                            "entry": entry,
                            "stop": stop,
                            "target": target,
                            "R": R,
                            "score": 10,
                            "grade": "A",
                            "initiative_score": 0,
                            "abs_score": 0,
                            "push1_score": 0,
                            "push2_score": 0,
                            "reasons": ["iceberg_squeeze"],
                            "vwap": vwap[i],
                            "vwap_support": False,
                            "push_rvol": 1.0,
                            "push_dg": 0,
                            "push_dr": 0,
                            "push_delta": c["delta"],
                            "signal_type": "iceberg_squeeze",
                        })
                        
        # === TRY SHORT (Iceberg Squeeze) ===
        if not any(s["candle_idx"] == i and s["side"] == "SHORT" for s in signals):
            body = c["close"] - c["open"]
            if c.get("floor_abs", 0) >= 50 and -20000 < c["delta"] < 0:
                recent_dg_zero = all(candles[k].get("local_dg", 0) == 0 for k in range(max(0, i-2), i+1))
                _isq_s_context = session_range >= 2.0 * atr or vwap[i] > c["close"]
                if recent_dg_zero and entry_height >= 0.30 and _isq_s_context:
                    entry = _get_ref_price(c)
                    recent_high = max(candles[k]["high"] for k in range(max(0, i-3), i+1))
                    stop = recent_high + atr * 0.1
                    R = stop - entry

                    if R > atr * 0.5 and R <= atr * 2.5:
                        target = entry - R * TARGET_R
                        signals.append({
                            "side": "SHORT",
                            "candle_idx": i,
                            "push1_idx": i,
                            "time": c.get("time", ""),
                            "entry": entry,
                            "stop": stop,
                            "target": target,
                            "R": R,
                            "score": 10,
                            "grade": "A",
                            "initiative_score": 0,
                            "abs_score": 0,
                            "push1_score": 0,
                            "push2_score": 0,
                            "reasons": ["iceberg_squeeze"],
                            "vwap": vwap[i],
                            "vwap_support": False,
                            "push_rvol": 1.0,
                            "push_dg": 0,
                            "push_dr": 0,
                            "push_delta": c["delta"],
                            "signal_type": "iceberg_squeeze",
                        })
                        
        # === TRY LONG (DOM Sweep Breakout) ===
        if not any(s["candle_idx"] == i and s["side"] == "LONG" for s in signals):
            body = c["close"] - c["open"]
            if body >= atr * 0.8 and c.get("ask_dom_levels", 0) >= 8 and c["volume"] > avg_vol * 1.5:
                _dsb_peak = c["high"] >= session_high
                _dsb_depth = (session_high - c["close"]) / session_range if session_range > 0 else 0
                if entry_height >= 0.50 and entry_height <= 0.85 and not _dsb_peak and _dsb_depth >= 0.15:
                    entry = _get_ref_price(c)
                    stop = c["open"] - atr * 0.1
                    R = entry - stop
                    
                    if R > atr * 0.5 and R <= atr * 2.5:
                        target = entry + R * TARGET_R
                        signals.append({
                            "side": "LONG",
                            "candle_idx": i,
                            "push1_idx": i,
                            "time": c.get("time", ""),
                            "entry": entry,
                            "stop": stop,
                            "target": target,
                            "R": R,
                            "score": 10,
                            "grade": "A",
                            "initiative_score": 0,
                            "abs_score": 0,
                            "push1_score": 0,
                            "push2_score": 0,
                            "reasons": ["dom_sweep_breakout"],
                            "vwap": vwap[i],
                            "vwap_support": False,
                            "push_rvol": c["volume"] / avg_vol if avg_vol > 0 else 1.0,
                            "push_dg": 0,
                            "push_dr": 0,
                            "push_delta": c["delta"],
                            "signal_type": "dom_sweep_breakout",
                        })
                        
        # === TRY SHORT (DOM Sweep Breakout) ===
        if not any(s["candle_idx"] == i and s["side"] == "SHORT" for s in signals):
            body = c["open"] - c["close"]
            if body >= atr * 0.8 and c.get("bid_dom_levels", 0) >= 8 and c["volume"] > avg_vol * 1.5:
                _dsb_s_trough = c["low"] <= session_low
                _dsb_s_depth = (c["close"] - session_low) / session_range if session_range > 0 else 0
                if entry_height <= 0.50 and entry_height >= 0.15 and not _dsb_s_trough and _dsb_s_depth >= 0.15:
                    entry = _get_ref_price(c)
                    stop = c["open"] + atr * 0.1
                    R = stop - entry
                    
                    if R > atr * 0.5 and R <= atr * 2.5:
                        target = entry - R * TARGET_R
                        signals.append({
                            "side": "SHORT",
                            "candle_idx": i,
                            "push1_idx": i,
                            "time": c.get("time", ""),
                            "entry": entry,
                            "stop": stop,
                            "target": target,
                            "R": R,
                            "score": 10,
                            "grade": "A",
                            "initiative_score": 0,
                            "abs_score": 0,
                            "push1_score": 0,
                            "push2_score": 0,
                            "reasons": ["dom_sweep_breakout"],
                            "vwap": vwap[i],
                            "vwap_support": False,
                            "push_rvol": c["volume"] / avg_vol if avg_vol > 0 else 1.0,
                            "push_dg": 0,
                            "push_dr": 0,
                            "push_delta": c["delta"],
                            "signal_type": "dom_sweep_breakout",
                        })

    # === FILTER G: Proximity & Momentum Guards ===
    filtered = []
    for sig in signals:
        i = sig["candle_idx"]
        _g_atr = _compute_atr(candles, i)
        if _g_atr <= 0:
            filtered.append(sig)
            continue

        _g_bypass = sig["score"] >= 9 or (abs(sig.get("push_delta", 0)) > 35000 and sig.get("push_rvol", 0) > 1.5)

        if sig["side"] == "SHORT" and not _g_bypass:
            _g_sl = min(candles[k]["low"] for k in range(0, i + 1))
            _g_prox = (sig["entry"] - _g_sl) / _g_atr
            if _g_prox < 1.25:
                continue

        if sig["side"] == "LONG" and not _g_bypass:
            _g_sh = max(candles[k]["high"] for k in range(0, i + 1))
            _g_sl = min(candles[k]["low"] for k in range(0, i + 1))
            _g_sr = _g_sh - _g_sl
            _g_room = (_g_sh - sig["entry"]) / _g_atr
            if _g_room < 2.0 and _g_sr > 6.0 * _g_atr and sig.get("signal_type") != "floor_bounce":
                continue

        filtered.append(sig)

    return filtered


def evaluate_trade(sig, candles, max_bars=15):
    idx = sig["candle_idx"]
    entry = sig["entry"]
    stop = sig["stop"]
    target = sig["target"]
    side = sig["side"]
    n = len(candles)

    if idx + 1 >= n:
        return "SKIPPED", 0.0

    for j in range(idx + 1, min(idx + max_bars, n)):
        if side == "LONG":
            if candles[j]["low"] <= stop:
                return "LOSS", -1.0
            if candles[j]["high"] >= target:
                return "WIN", TARGET_R
        else:
            if candles[j]["high"] >= stop:
                return "LOSS", -1.0
            if candles[j]["low"] <= target:
                return "WIN", TARGET_R

    last_idx = min(idx + max_bars, n - 1)
    if last_idx > idx:
        cp = _get_ref_price(candles[last_idx])
        if side == "LONG":
            return "TIMEOUT", round((cp - entry) / sig["R"], 2)
        else:
            return "TIMEOUT", round((entry - cp) / sig["R"], 2)

    return "SKIPPED", 0.0
