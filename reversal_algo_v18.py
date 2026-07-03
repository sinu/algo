"""V18: V17 + optional node-volume high-conviction filter.

V18 leaves V17 completely untouched and layers one additional, empirically
validated quality filter on top:

    Require absorbed volume at the reversal extreme node to exceed a threshold.
        LONG  -> trapped_ask_low  (buy volume absorbed at the candle low)
        SHORT -> trapped_bid_high (sell volume absorbed at the candle high)

Why only this filter?  Across 2023-2026 (855 sessions) the node volume is the
ONLY order-flow feature that separates winners from losers consistently
out-of-sample.  Entropy, efficiency-ratio, delta-efficiency and VPOC/value-area
alignment all showed ~zero WIN/LOSS separation and removed net-positive R
(i.e. they threw away winners together with losers) — so they are excluded.

The node filter does not magically delete only losers; it trades trade
frequency for per-trade quality:
    node_vol >= 5000  : WR 56.6% -> ~59%, exp/trade +0.38 -> +0.44
    node_vol >= 10000 : WR 56.6% -> ~63%, exp/trade +0.38 -> +0.51 (~75% fewer trades)

The wrapper is behaviourally identical to inlining the check inside V17's
detection loop, because the filter depends only on the entry candle
(candle_idx), not on detection order, gap selection or scoring.

Set MIN_NODE_VOL = 0 to fall back to exact V17 behaviour.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Re-export V17 primitives unchanged so V18 is a drop-in replacement.
from reversal_algo_v17 import (  # noqa: F401
    compute_session_features,
    evaluate_trade,
    _compute_atr,
    _get_ref_price,
    TARGET_R,
    MAX_STOP_ATR,
    MAX_STOP_ATR_CASCADE,
    LAST_ENTRY_TIME,
    detect_signals as _detect_signals_v17,
)

# Default high-conviction threshold (validated sweet spot). 0 = pure V17.
MIN_NODE_VOL = 10000


def _node_vol(candle, side):
    """Absorbed volume at the reversal extreme for the entry candle."""
    if side == "LONG":
        return candle.get("trapped_ask_low", 0)   # buy vol absorbed at the low
    return candle.get("trapped_bid_high", 0)       # sell vol absorbed at the high


def detect_signals(candles, feats, min_score=7, use_dom_filter=True,
                   live_mode=False, min_node_vol=MIN_NODE_VOL):
    """V17 detection + node-volume quality gate.

    min_node_vol <= 0 returns V17 signals unchanged.
    """
    signals = _detect_signals_v17(
        candles, feats,
        min_score=min_score,
        use_dom_filter=use_dom_filter,
        live_mode=live_mode,
    )
    if min_node_vol <= 0:
        return signals

    filtered = []
    for sig in signals:
        c = candles[sig["candle_idx"]]
        if _node_vol(c, sig["side"]) >= min_node_vol:
            sig = dict(sig)
            sig["node_vol"] = _node_vol(c, sig["side"])
            filtered.append(sig)
    return filtered
