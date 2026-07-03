import websocket
import json
import footprint_pb2
from datetime import datetime, timedelta, date
import math
import sys
import requests
import threading
import time
import statistics
from collections import deque
import os
import csv
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, ROUND_CEILING, getcontext

# Fix Windows console encoding for emoji output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ==============================================================================
# VERSION 5.84 NIFTY - V5.83 + robustness hardening (no strategy change)
# ==============================================================================
# V5.84 ROBUSTNESS FIXES (no trading-logic change):
#   (a) AUTOMATION GUARD: Final input() prompt only runs in an interactive TTY
#       (sys.stdin.isatty()). Batch runners no longer hang on "Press Enter".
#   (b) INSTANCE ATTR INIT: All lazily-created instance attributes
#       (last_range_ratio, last_exhaust_recovery_pct) are initialized in
#       __init__ to prevent latent AttributeError on refactor or early-return
#       paths.
#   (c) ERROR VISIBILITY: Bare `except:` blocks that silently swallowed errors
#       now catch Exception and log a concise warning, aiding signal forensics.
# ==============================================================================
# 1. SIMPLIFIED: Signal = Trap Detection + DG->L->DG Pattern only
# 2. STRICT: D1/D2 must be actual DG-tagged rows (dark green luminance)
# 3. ENHANCED: Broader trap detection (lower half of candle, not just wick)
# 4. REVERSAL CRITERIA: Absorption at support + Buyer aggression + Quality grading
# 5. FILTER: Consolidation range check (grade B, not blocker)
# 6. ADAPTED: NIFTY FUTURES settings (Step 2.5, Divisor 10, IST timezone)
# 7. WARMUP BLOCKING: Filters return BLOCK during warmup (no unfiltered signals)
# 8. ADAPTIVE HEIGHT: ATR-scaled, relaxed for grade C (max(1.5x ATR, 40pts))
# 9. OPTIMIZED: HEIGHT 2.5x(A)/1.5x(C), SUPPORT 5.0x, RANGE 2.5x ATR thresholds
# 10. ADAPTIVE WARMUP: ATR from 5 candles, exhaustion from 8 candles
# 11. SELLING CLIMAX: Volume spike + extreme delta at session low = selling exhaustion
# 12. IMMEDIATE FIRE: Signal fires on D1-L-D2 formation, always full reset
# 13. STRONG TRAP PERSISTENCE: High-delta traps get extended age (8 vs 5 candles)
# 14. GRADE SYSTEM: A+=golden, A=selling+trend, B=partial, C=noselling+consol=BLOCKED
# 15. TRAP RECOVERY: Broken traps get 3-candle recovery window; on recovery,
#     trap shifts to break low for wider D1-L-D2 scan (captures 2B reversals)
# 16. BULLISH DRIVE: D1/D2 blocks only form in bullish candles (close >= open)
# 17. SIGNAL COOLDOWN: After signal fires, next signal blocked for 12 candles
#     unless new trap is at a genuinely lower price (prevents rapid-fire noise)
# 18. V5.31 ABSORPTION GATE: 3-layer absorption validation wired into signal path
# 19. V5.31 D2 CONFIRMATION: Signal candle close position + delta direction check
# 20. V5.31 RVOL FLOOR: Minimum volume participation required on signal candle
# 21. V5.31 GRADE-C BLOCK: No exhaust + consolidation = hard block (worst combo)
# 22. V5.31 GOLDEN ENTRY: Session extreme + exhaustion + vol/absorption bypasses
#     secondary filters (VWAP, Chase, Cooldown, Consol) — best setups always fire
# 23. V5.32 DYNAMIC CHASE: ATR-adaptive body ratio (small patterns get relaxed limit)
# 24. V5.32 LOCAL RVOL: Recent-window RVOL normalizes for intraday volume decay
# 25. V5.32 RISK BANDS: Tightened max risk from backtest data (sweet spot 16-35pts)
# 26. V5.32 TIME GATE: Afternoon (14:xx) signals require exhaustion evidence
# 27. V5.32 GRADE FIX: Bullish Grade A requires absorption + exhaustion (exhaust-only=43% WR)
# 28. V5.33 HARD RISK CAP: MAX_RISK=30 (risk>30 = 20% WR, -217.5 PnL in V5.32)
# 29. V5.33 RVOL FLOOR RAISED: 0.50→0.60 (cuts 0.50-0.59 losers while keeping local normalization)
# 30. V5.33 CHASE TIGHTENED: Cap 0.85→0.75 (over-relaxation let in bad chases)
# 31. V5.33 GRADE REVERT: Removed absorb requirement for Grade A (demotion to B hurt WR)
# 32. V5.34 ABSORPTION GATE: Signals with NO exhaustion AND NO absorption = blocked (WEAK-EVIDENCE)
# 33. V5.34 BEAR ABSORPTION: Full 3-layer absorption mirror for bearish (buy absorption at ceiling)
# 34. V5.35 RVOL DEAD ZONE: Block RVOL 1.00-1.30 signals (36% WR death zone vs 80%+ outside)
# 35. V5.35 GOLDEN TIGHTEN: Require absorption + volume (not OR) for golden qualification
# 36. V5.35 CHASE RELAXATION: Raise cap 0.75→0.82 for proven setups (exhaust + absorb)
# 37. V5.35 AFTERNOON B-BLOCK: Grade B at 14:xx = 25% WR → hard block
# 38. V5.36 RVOL DEAD ZONE SOFTENED: Risk bypass lowered 25→20 (recovers Feb 18 WIN +20)
# 39. V5.36 AFTERNOON B ABSORB BYPASS: Allow Grade B at 14:xx if absorb_passed (recovers Dec 9 WIN +25)
# 40. V5.36 CHASE RELAXATION REMOVED: Dead code (recovered 0 signals in V5.35 backtest)
# 41. V5.37 RVOL HIGH CEILING: Block session RVOL ≥ 2.0 (0% WR, 0 wins lost — catches chaotic markets)
# 42. V5.37 DEAD ZONE FIX: Revert risk bypass to 25, add absorb bypass score ≥ 5
#     (prevents Aug 05 LOSS regression, recovers Feb 18 WIN via high absorption)
# 43. V5.37 NO GOLDEN BYPASS for HIGH-RVOL ceiling (A+ at RVOL 2.0+ = 0% WR)
# 44. V5.38 CONFIRMED RISK EXTENSION: Exhaust+extreme D2 close → HEIGHT cap 30→32.5
# 45. V5.38 CHASE CONFIRMATION BYPASS: Exhaust+extreme D2 close → bypass CHASE filter
# 46. V5.43 VWAP ROOM-TO-TRAVEL: Bull signals blocked when VWAP caps upside < risk (R:R < 1:1)
# 47. V5.43 CROSS-CANDLE PATTERN CONTAMINATION: Track DG/DR blocks from prior candles
#     between D1-D2 — if opposing block exists, pattern is killed (prevents false patterns)
# 48. V5.43 VWAP CONFLUENCE HEIGHT: Bear signals with D2 below VWAP get +7.5pt HEIGHT cap
#     extension (VWAP as resistance confirms short direction)
# 49. V5.44 VWAP CONFIRMED LONG: When D2 reclaims VWAP + strong D2 close (≥70%) + positive
#     delta, bypasses GRADE-C block, extends Grade C HEIGHT cap by +7.5pts, and bypasses
#     RVOL-GATE — VWAP reclaim proves institutional support (recovers Mar 04 12:50 WIN)
# 50. V5.44 DYNAMIC EXHAUST LOOKBACK (BULL ONLY): For bull signals, anchors exhaustion
#     lookback to the swing high candle (where selling originated). Dynamically expands
#     window to capture selling that aged out of the 8-candle window during recovery.
#     Bears keep fixed 8-candle window — expanded bear window captures stale buying
#     from prior rallies, falsely promoting Grade C → A (Mar 05 13:55 regression).
# 51. V5.44 SWING HIGH EXCLUSION: Dynamic lookback now starts AFTER the swing high candle
#     (not including it). The swing high candle has the largest positive delta (peak buying),
#     which overwhelmed subsequent selling and prevented exhaustion detection.
#     (Fixes Mar 04 12:50 where delta_nadir was +22685 due to 11:10 candle delta +72670)
# 52. V5.44 GOLDEN CASCADE MIN AGE: Golden signals can no longer bypass CASCADE if the
#     last new session high/low was within 3 candles. Prevents shorting into parabolic
#     rallies or buying into waterfall sells. (Blocks Mar 04 14:20 bear — 1c after new
#     session high at 14:15, price rallied from 24637 to 24690 = 53pt loss)
# 53. V5.45 NO-CLEAR-BLOCK FIX: Signals with no clear single blocker now route through
#     full filter chain instead of being silently dropped as UNKNOWN.
# 54. V5.45 BEAR GOLDEN SESSION LOW ATR: Golden bear entry requires session high within
#     0.75 * ATR of candle high (tighter proximity for bearish golden qualification).
# 55. V5.46 SIGNAL-CD CANDLE COUNTER: Use monotonic render count (not clock-based) for
#     signal cooldown — prevents premature cooldown expiry from data gaps.
# 56. V5.46 CASCADE CANDLE COUNTER: Same render-count fix for waterfall/rally-cascade
#     cooldown — ensures 6 real candles between cascade signals, not 6 time intervals.
# 57. V5.47 BEAR CHASE CAP 0.80: Raise bear CHASE dynamic limit cap 0.75→0.80
#     (forensic: CHASE+5% = +292 CF PnL from 28 multi-fail signals, 14W/12L)
# 58. V5.47 HIGH-RVOL GOLDEN BYPASS: Golden entries bypass HIGH-RVOL blocker on both
#     bull and bear sides (forensic: +245.3 CF PnL from 19 signals, 8W/6L)
# 59. V5.48 EXTREME DELTA CANDLE DG OVERRIDE (BULL ONLY): When a single outlier
#     sell block skews luminance normalization (preventing all DG tags), allow dual
#     volume-drive D1+D2 pair under extreme conditions: trap recovered + RVOL >= 2.0
#     + delta/volume >= 15%. Catches institutional accumulation candles where buying
#     is spread across many levels but tagging produces zero DG. Bear side excluded
#     (DR tags already generate reliably; bear override caused cascade regressions).
# 60. V5.49 EXTREME DELTA SIGNAL BYPASS (BULL ONLY): Even after Item 59 fixes pattern
#     detection, signals from extreme delta candles are blocked by HEIGHT (V5.45 cap=60),
#     CHASE (body=84% > 55% limit), and RVOL-HIGH (>=2.0). For candles meeting extreme
#     conditions (trap_recovered + RVOL>=2.0 + delta/vol>=15% + exhaustion), relax:
#     - HEIGHT: raise cap from 60 → ATR*5 capped at 100
#     - CHASE: bypass (like override_allowed) — extreme buying IS the signal
#     - RVOL-HIGH: bypass (like golden) — extreme delta proves direction despite volatility
# 61. V5.50 FLOOR-CONFIRMED SINGLE DG PATTERN (BULL ONLY): When FLOOR absorption
#     confirms institutional defense at trap (selling absorbed >= 2 candles), a single
#     genuine DG breakout above trap + L above it = sufficient for pattern completion.
#     No D2 required. Conceptually: FLOOR = D1 (defense), gap = L, DG = D2 (offense).
#     V5.50b FIX: Added two safety guards to prevent premature firing:
#     (a) trap_age >= MAX_TRAP_AGE (always 5) — fire on or after the base expiry age.
#         Always uses base max-age, NOT strong-trap extended max (8). The floor
#         absorption IS the evidence the strong-trap extension was searching for.
#     (b) Floor recency — FLOOR absorption must have been active within 1 candle,
#         preventing stale floor_confirmed flags from triggering overrides.
#     V5.50c FIX: Floor-confirmed signals bypass RVOL-GATE (local RVOL check).
#         Floor absorption proves institutional activity at trap; low RVOL on the
#         breakout candle does not invalidate the setup.
#     Pattern status: "FLOOR→L→DG ✓ (Absorbed)" instead of "DG→L→DG ✓ (Clean)".
# 62. V5.51 FLOOR RETRY ON BLOCKED SIGNAL (BULL ONLY): When a bull signal is
#     blocked by a CANDLE-QUALITY filter but floor_confirmed is True, the trap is
#     NOT fully reset. Instead, only pattern state (DG1/L/DG2) is cleared — the
#     trap survives with its current age, allowing a NEW pattern to form on the
#     same trap. ONE retry allowed (floor_retry_used flag prevents loops).
#     Retry ONLY for candle-quality blocks: D2-CLOSE, LOW-RVOL, CHASE, D2-DELTA,
#     WEAK-EVIDENCE. NOT for structural/timing blocks (DROP, SUPPORT, HEIGHT,
#     WATERFALL, LATE, COOLDOWN, VWAP, GRADE-C, RVOL-ZONE, HIGH-RVOL, AFTERNOON)
#     — those reflect fundamental setup problems that won't fix next candle.
#     Rationale: floor absorption = institutional defense of the trap level. A bad
#     D2 candle (weak close, low RVOL) doesn't invalidate the trap — only the
#     specific pattern attempt. The next candle may produce a valid D2.
#     Safety: trap age continues counting → MAX_TRAP_AGE still enforces natural expiry.
# 63. V5.65 CEILING-ABSORBED THRESHOLD RELAXED (BEAR): Lower bear_ceiling_absorbed
#     score threshold 4→2. Signal candle absorption score rarely reaches 4 because
#     the D2/DR2 pattern-completion candle is NOT the ceiling-test candle — historical
#     streak (≥2 candles at top with buying ≥3K) already provides sufficient multi-candle
#     evidence. The score-2 requirement confirms at least minimal ceiling-zone row
#     absorption was detected. Fixes: March 20 missed shorts blocked at CASCADE/RVOL.
# 64. V5.65 CEILING-ABSORBED HEIGHT EXTENSION (BEAR): When ceiling absorption confirmed,
#     extend bear_max_height and bear_risk_cap by +7.5pts (CEILING_ABSORB_HEIGHT_EXT).
#     Rationale: institutional sellers building at top justify slightly wider HEIGHT
#     tolerance — the absorption pattern itself is the setup confirmation. Fixes: March
#     20 11:00 SHORT blocked by [HEIGHT] 46.5 > 45.0 (now 45.0+7.5=52.5 cap).
# 65. V5.65 VWAP-BYPASS MIN RVOL (BULL): VWAP-confirmed-long bypass for RVOL-GATE
#     now requires local_rvol ≥ 0.40x (MIN_VWAP_LONG_BYPASS_RVOL). Previously any
#     RVOL with VWAP reclaim could bypass the RVOL gate, allowing false longs on
#     quiet sessions (0.33-0.44x local RVOL). On March 20, longs at 13:00 (0.56x)
#     and 13:35 (0.33x) fired with VWAP bypass while market trended lower. The 0.33x
#     case is now blocked; 0.56x still passes so valid VWAP reclaims are preserved.
# 66. V5.66 DYNAMIC CONTEXT SCALING (BULL March 18 + BEAR March 19):
#     SIX targeted fixes to recover missed trades blocked by over-rigid rules:
#     BULL (March 18 V-bottom):
#     (a) DECAY HISTORICAL BLOCKERS: V5.43 Prior-candle DR blocks now decay if ≥2
#         candles old AND current delta ≥10,000 AND floor absorption confirmed.
#         Explosive buying proves historical sellers have been overrun.
#     (b) VOLUME-ACCELERATED FLOOR OVERRIDE: V5.50b trap_age≥5 bypassed if
#         cumulative absorption > 3× avg session volume. V-bottoms reverse before
#         the 5-candle age gate triggers; volume IS the confirmation.
#     (c) FLOOR-ANCHORED HEIGHT: Grade A + floor confirmed → measure height from
#         D2 to L (pause row), not D2 to trap (V-bottom). L is the structural
#         support formed during the explosive reversal candle — true risk level.
#     BEAR (March 19 slow grind):
#     (d) ABSORPTION-DRIVEN RVOL BYPASS: If absorb_score≥3 AND vwap_broken →
#         bypass RVOL gate. Institutional passive selling needs no volume spike.
#     (e) NEAR-MISS HEIGHT GRACE MARGIN: Grade A + absorb≥3 + height within 10%
#         of cap → grant +3pt grace. 2-3pt miss twice per session is model
#         rigidity, not a bad trade.
#     (f) DECOUPLED RISK EXTENSION: bear_override_allowed RVOL check now skipped
#         when bear_absorb_score≥3. Strong absorption grants height extension
#         independent of session RVOL on quiet institutional selling days.
# 67. V5.67 AMNESIA BUG FIX — CEILING_CONFIRMED STICKY FLAG (BEAR MIRROR of V5.50):
#     bear_ceiling_absorbed used a TRANSIENT streak counter. On breakout candles,
#     price drops fast → top rows have thin volume → bear_top_absorb_streak resets
#     to 0 before pattern eval → bear_ceiling_absorbed = False → all RVOL/CASCADE/
#     HEIGHT bypasses fail despite heavy institutional selling 20 min earlier.
#     FIX: Added self.ceiling_confirmed (exact mirror of self.floor_confirmed V5.50):
#      - Set True when bear_top_absorb_streak≥2 (in absorption tracking block)
#      - Persists as sticky state — NOT reset on low-top-volume breakout candles
#      - Reset only at ceiling lifecycle events: DEAD, EXPIRED, new ceiling, signal
#      - bear_ceiling_absorbed = (streak≥2 AND score≥2) OR self.ceiling_confirmed
#     Fixes: March 19 10:55/12:00/12:40 shorts blocked by RVOL-GATE despite
#     heavy ceiling absorption confirmed at 10:30.
# 68. V5.68 SHORT-SIDE DISCIPLINE — 3 targeted filters from 153-day backtest analysis:
#     (a) LOW-RVOL GRADE B BLOCK: Block Grade B shorts when session RVOL is 0.30-0.50
#         unless golden or climax. This bucket is 38.1% WR = net -91.8 pts over 21 trades.
#         Grade B wins in this zone: 3W for +92.5; losses: 6L for -147.8. The bypass
#         (ceiling_absorbed/override) lets them through but low volume means no follow-through.
#         Golden/climax shorts are exempt — they carry independent conviction.
#     (b) SHORT RISK CAP: Non-golden, non-climax shorts capped at 45pts risk.
#         RVOL 35-50 bucket: 50% WR, -7.0 PnL. >=50 bucket: 40% WR.
#         Catastrophic losses: Sep 5 -55, Oct 17 -62.5, Mar 9 -50 — all non-golden.
#         Golden/climax/extreme-conviction exempt — they have structural confirmation.
#     (c) MIDDAY SHORT HARDENING: 12:00-13:59 shorts require absorb_score>=3 OR
#         session RVOL>=0.65 OR golden/climax. 12-13xx shorts: 52% WR, -59.8 PnL.
#         14xx shorts: 76.5% WR — the pattern works when afternoon volume returns.
#         This adds a minimum conviction bar for the weakest time window.
# 69. V5.69 CLIMAX VETO + VWAP CLEARING BUFFER — 2 institutional-logic fixes:
#     (a) CLIMAX VETO: Block shorts on selling-climax D2 candles, block longs on
#         buying-climax D2 candles. When delta is intensely negative at the bottom
#         of a move, it's retail capitulation — institutions passively absorb.
#         Shorting into that is "dumb money". Mirror logic for buying climax.
#         Check: D2 candle |delta| > 2.0x avg_abs_delta AND local RVOL >= 1.3x.
#         Golden/extreme_conviction exempt (independent structural confirmation).
#         Mar 20 10:00 SHORT lost -37.5 shorting into -74K delta selling climax.
#     (b) VWAP CLEARING BUFFER: VWAP is a thick liquidity band, not a thin line.
#         D2 must clear VWAP by 0.25x ATR to count as genuinely reclaimed/broken.
#         Prevents fakeout signals where D2 barely touches VWAP surface.
#         Mar 20 13:00 LONG lost -47.5: D2 was only 3pts above VWAP (fakeout).
# 71. V5.71 MICRO-RVOL CLIMAX VETO + VWAP AGGRESSION — immunize against 10:00 selling climax & 11:15 VWAP fakeout:
#     (a) CLIMAX VETO now uses 3-candle Micro-RVOL (volume_history[-4:-1]) instead of
#         get_local_rvol() 20-candle avg that gets distorted by the 09:15 open spike.
#         This correctly detects the 10:00 selling climax (Micro-RVOL will be high
#         relative to recent candles, not diluted by the massive open candle).
#     (b) VWAP Confirmed Long now requires:
#         - D2 >= VWAP + ATR buffer (not just >= VWAP flat)
#         - total_delta >= VWAP_RECLAIM_MIN_DELTA (8000) — must show actual aggression
#         Kills the 11:15 low-volume VWAP fakeout where D2 barely touches VWAP.
#     (c) MIN_VWAP_LONG_BYPASS_RVOL raised from 0.40 to 0.75 — RVOL-GATE bypass
#         for VWAP-confirmed longs requires real volume participation.
#     (d) Bear VWAP Broken now mirrors with buffer + negative delta requirement.
# 70. V5.70 RISK-CAP GRACE + HEIGHT OR-LOGIC — 2 fixes for Mar 20 blocked shorts:
#     (a) RISK-CAP GRACE MARGIN: The V5.68 SHORT_RISK_CAP_NON_GOLDEN (45pts) was
#         a hard wall. Mar 20 11:00 SHORT had risk 46.5 — missed by 1.5pts with
#         44% exhaustion, 13% D2 close, full ceiling absorption. The +3pt grace
#         margin (V5.66) is now applied dynamically to RISK-CAP when the signal
#         has effective exhaust + institutional presence (ceiling_absorbed OR
#         absorb≥3) + miss is within 3pts.
#     (b) HEIGHT OR-LOGIC: The V5.65 CEILING_ABSORB_HEIGHT_EXT (+7.5pts) required
#         bear_ceiling_absorbed (multi-candle streak ≥2). Mar 20 12:40 SHORT had
#         absorb_score=3 entirely within the single D2 candle — no multi-candle
#         streak, so the extension was denied and height 40.0 > 37.5 blocked it.
#         Institutional presence is EITHER multi-candle accumulation OR a single
#         violent absorption candle: changed AND to OR (ceiling_absorbed OR
#         (absorb_score≥3 AND effective_exhaust)).
# 72. V5.72 MOMENTUM INITIATION PATCH — 3 institutional-logic fixes:
#     (a) MICRO-RVOL computed early (before climax veto) and unified as effective_rvol =
#         max(local_rvol, micro_rvol). Used for RVOL gate, momentum HEIGHT tier, and
#         extreme_conviction. Prevents 09:15 open spike distortion in all paths.
#     (b) INITIATION OVERRIDE: VWAP breakdowns/reclaims bypass climax veto. A massive
#         delta spike exactly as price cracks through VWAP is institutional initiation
#         (aggressive momentum forcing a breakdown), NOT exhaustion/capitulation.
#         Mar 20 13:45 SHORT blocked by selling-climax veto despite VWAP breaking down.
#     (c) VWAP INFLATION CORRECTION: Close inflation correction (V5.55) was locked to
#         trend-day only. VWAP breakdowns with strong confirmation also deserve D2-based
#         height measurement—the VWAP break is momentum, not pattern slippage.
#         Mar 20 13:45 had D2 at 23247.5 (60pt risk) but close at 23230 (77.5pt) — 
#         the extra 17.5pts is initiation momentum, not pattern width.
# 73. V5.73 LOW-RVOL-B WIDENING — Backtest Aug25-Apr26 (170 days, 166 fired):
#     Grade-B SHORTs in RVOL 0.30-0.65 had 33.3% WR (7W/14L, -180 pts, p=0.026).
#     Widened SHORT_LOW_RVOL_GRADE_B_MAX from 0.50 → 0.65. Statistically significant
#     at 97.4% confidence. Tepid volume = insufficient conviction for Grade-B setups.
# 74. V5.74 ABSORPTION ORDERING REVERT — V5.73 backtest (170 days, +293.2 pts)
#     showed -521.8 pts degradation vs V5.72 (+815.0). Root cause: two "bug fixes"
#     in V5.73 that changed absorption computation ordering and display tracking.
#     (a) REVERTED: bear_absorb_score computation moved back AFTER bear_override_allowed.
#         The V5.66 decoupling check (absorb_score<3) was effectively dead code in V5.72,
#         and that behavior produced superior results. Restoring original ordering.
#     (b) REVERTED: track_multi_candle_absorption() display call restored. The "double
#         aging" side effect was part of the V5.72 baseline that produced +815 pts.
# 75. V5.75 VWAP RECLAIM DRIVE POWER (BULL ONLY) — vwap_confirmed_long bypasses:
#     (a) DROP filter: VWAP reclaim itself proves reversal context — price was below
#         VWAP and aggressively reclaimed it with positive delta + strong close. The
#         DROP filter measures prior move depth, but VWAP reclaim IS the institutional
#         proof that the prior move is over. Fixes: Apr 17 9:45 blocked at DROP 1.3x.
#     (b) HEIGHT risk_cap extension: risk_cap gets VWAP_CONFLUENCE_HEIGHT_EXTENSION
#         (+7.5pts), mirroring the max_height extension already applied. Previously
#         risk_cap stayed at 30 while max_height got 42.5 — inconsistent. Now risk_cap
#         = 37.5, allowing patterns up to 37.5pts through. Fixes: HEIGHT 35.0 > 30.
#     (c) CHASE bypass: The VWAP reclaim drive IS the signal — the D2 body covering
#         most of the pattern height is expected, not a chase. Same logic as
#         override_allowed bypassing CHASE. Fixes: CHASE 94% > 75%.
#     (d) WEAK-EVIDENCE bypass: vwap_confirmed_long already requires delta ≥ 8000 +
#         close ≥ 70% + VWAP buffer — this IS institutional evidence. The WEAK-EVIDENCE
#         filter blocks when no absorption AND no exhaustion, but early-session warmup
#         prevents exhaustion measurement. VWAP reclaim proves the setup.
# 76. V5.76 LONG SIGNAL RECOVERY — V5.75 backtest (171 days): 140 fired, 58.6% WR,
#     +496.2 pts. 86 blocked (ALL LONGs). Biggest CF opportunities:
#     (a) RELAX DROP FOR LONGS: MIN_DROP_ATR_MULT_LONG = 1.0 (vs 2.0 for shorts).
#         38 LONGs blocked by DROP, CF: 62.2% WR, +606.3 pts. The 2.0x threshold
#         was set when LONGs were rare — but LONGs in rally markets naturally have
#         smaller drops from session highs. 1.0x still requires meaningful pullback.
#     (b) FLOOR-ABSORBED CASCADE BYPASS: Mirrors bear_ceiling_absorbed (V5.64).
#         Bull CASCADE had 2 bypasses (time, tested) vs bear's 3 (time, tested,
#         absorbed). New low + institutional buying at the bottom = floor forming,
#         not a momentum cascade. 18 LONGs blocked by WATERFALL, CF: 50% WR +142 pts.
# 77. V5.77 REGRESSION INVESTIGATION — REVERTED:
#     V5.72→V5.76 regression investigated. Two root causes found:
#     (a) INTERNAL OHLC: Estimation from delta-ratio generated 168 LONGs (-249 pts).
#         Estimation too inaccurate for pattern detection → REVERTED.
#     (b) Bear override ordering: Moving override AFTER absorb added 27 bad SHORTs
#         (-187.5 pts) because INTERNAL OHLC inflates absorb_score → REVERTED.
#     Both fixes are theoretically correct but INTERNAL OHLC corruption in backtests
#     makes them produce garbage signals. Code is now back to V5.76 state.
# 78. V5.79 CROSS-CANDLE D1 RE-VALIDATION + PEAK/TROUGH BLOCK:
#     (a) D1 RE-VALIDATION: When DG→L→DG pattern fires, re-validate D1 and L in
#         current candle. D1 fails if delta ≤ 0 (demand gone), L if sell% > 80%.
#         Bug: D1@24295 was DG(+8.9K) in 11:30, delta=0 in 11:40.
#     (b) PEAK BLOCK: LONG signal blocked when candle high ≥ session high.
#         Buying at new session highs is chasing the peak, not reversing from trap.
#         Example: 2026-04-17 11:50 — DG→L→DG fires at 24320 (new session high)
#         from trap@24277.50 age:5. This is continuation, not reversal.
#     (c) TROUGH BLOCK: SHORT signal blocked when candle low ≤ session low.
#         Mirror of PEAK — selling at new session lows is chasing the bottom.
#     Both PEAK/TROUGH bypassed by GOLDEN (session extreme reversals).
# 79. V5.80 AUDIT FIXES (10 items):
#     (a) CLIMAX-VETO golden/extreme-conviction bypass was dead code (is_golden
#         always False when veto computed). Moved bypass to blocker chain where
#         is_golden has its real value. Now golden entries at session extremes
#         correctly bypass the climax veto.
#     (b) Bull MIN_DROP_ATR_MULT_RECOVERED was dead logic: min(1.5, 1.0) = 1.0.
#         Removed dead branch (V5.76 set longs to 1.0x, below recovered 1.5x).
#     (c) track_multi_candle_absorption() called twice per candle (bull only) —
#         display section double-counted zones and double-aged them. Display now
#         reads cached absorption_zones dict directly (no mutation).
#     (d) PEAK/TROUGH blocks used proxy vars (bear_session_highest_ceiling /
#         session_lowest_trap). Now use actual OHLC session high/low tracked via
#         session_ohlc_high / session_ohlc_low.
#     (e) format_vol() misformatted negative values. Now uses abs() + sign prefix.
#     (f) Version header updated to V5.80 (was V5.38 in header, v5.17 in connect).
#     (g) Dead code removed: passes_core_filters(), calculate_quality_score(),
#         get_linear_gradient() — all defined but never called.
#     (h) Unused variables removed: session_deltas, session_max_delta_green/red,
#         body_history, ohlc_source, session_new_low_trap_count,
#         bear_session_new_high_count.
#     (i) Bear cooldown missing lower-ceiling bypass (asymmetric with bull's
#         trap_is_higher from V5.59). Added ceil_is_lower bypass.
#     (j) INTERNAL OHLC fallback always created bearish candles (open=highest,
#         close=lowest). Now uses delta sign to infer candle direction.
# ==============================================================================

# 🔵 TELEGRAM (Disabled)
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

# AUTHENTICATION
TOKEN_FILE = "refresh_token.txt"

def load_refresh_token():
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r') as f:
                return f.read().strip()
        return "YOUR_MANUAL_TOKEN_HERE"
    except Exception as e:
        print(f"⚠️ load_refresh_token failed: {e}")
        return None

REFRESH_TOKEN = load_refresh_token()
CLIENT_ID = "3fqhvm22ea8pjsr2spbnv484pr"
REGION = "ap-south-1"
COGNITO_URL = f"https://cognito-idp.{REGION}.amazonaws.com/"

# 🔥 NIFTY SYMBOL
SYMBOL = "NSE:FUTURE:NIFTY-I"

# 🧪 CORE-ONLY EXPERIMENT MODE (env CORE_ONLY=1)
# Bypasses ALL ~20 secondary quality gates and fires a signal on the pure core
# concept only: STRUCTURE (pattern at swing extreme) + EXHAUSTION + ABSORPTION.
# Used to measure how many trades the gates suppress and whether they add edge.
# Has NO effect on normal runs (flag unset) — purely additive, opt-in.
CORE_ONLY = os.environ.get("CORE_ONLY") == "1"

# 📅 BACKTEST SETTING
if len(sys.argv) > 1:
    FOOTPRINT_DATE = sys.argv[1]
else:
    FOOTPRINT_DATE = "2026-02-19"

# 🛑 NIFTY TIMEZONE: Data is already in IST (despite Z suffix), no conversion needed
IST_OFFSET = timedelta(0)
MARKET_START_SHIFT = timedelta(hours=9, minutes=15)

# 🔥 NIFTY SETTINGS
STEP_SIZE = 2.5
STEP_SIZE_DEC = Decimal("2.5")  # Decimal for precise bucketing
getcontext().prec = 12  # Set decimal precision
CENTER_GRID = False
PRICE_DIVISOR = 10.0
VOLUME_MULTIPLIER = 1.0

# 🕵️ STRATEGY PARAMETERS
DARK_INTENSITY = 0.54
LIGHT_INTENSITY = 0.54

MIN_TRAP_PCT = 0.005
MIN_DRIVE_PCT = 0.005
DRIVE_RATIO = 1.0
ABSORPTION_ROWS = 15
MIN_SIGNAL_DELTA = 5
# MIN_DRIVE_DELTA_ABS removed — tagging is now purely luminance-based
VOLUME_DRIVE_MULT = 1.1           # 🔥 V5.26e: volume-drive [L] threshold (delta >= avg_row_vol * this)
EXTREME_PAIR_MIN_RVOL = 2.0       # 🔥 V5.48: Min RVOL for dual volume-drive D1+D2 (zero-DG override)
EXTREME_PAIR_MIN_DELTA_PCT = 0.15 # 🔥 V5.48: Min |delta|/volume ratio for extreme directional candle
EXTREME_PAIR_DRIVE_MULT = 0.80    # 🔥 V5.48: Relaxed drive mult for D2 in extreme candles (vs 1.1 normal)
STRONG_CLOSE_PCT = 0.60

# 🛡️ FILTERS
MIN_TRAP_AGE = 1
MAX_TRAP_AGE = 5
MIN_DRIVE_BLOCKS = 2
MIN_DELTA_ACCELERATION = 5
VOID_VOLUME_PCT = 0.15
FILTER_LOOKBACK = 24                     # 🔥 V5.44: Aligned with DROP_LOOKBACK_CANDLES for dynamic exhaust window

# 🔥 V5.13 PATTERN QUALITY FILTERS
MIN_DG_DELTA = 10
MIN_DG_SPACING_STEPS = 2
COOLDOWN_THRESHOLD = -50
COOLDOWN_CANDLES = 3
MOMENTUM_OVERRIDE_THRESHOLD = 100

# 🔥 V5.20 DRIVE BLOCK DETECTION (strict DG-only)
# D1 and D2 must be actual DG-tagged rows (dark green, luminance <= threshold)
# No buy-dominance fallback — only true DG blocks qualify as drive
L_MAX_SELL_DOMINANCE = 0.80  # L (pause) row rejected if sell/total > this (heavy selling, not a pause)

# 🔥 V5.20 CONSOLIDATION FILTER
CONSOL_LOOKBACK = 12              # candles (1 hour) for range check
CONSOL_MIN_RANGE_ATR = 2.5        # range/ATR ratio threshold (below = consolidation)

# 🔥 V5.20 SELLING PRESSURE FILTERS (replaces ATR drop)
# Selling: cumulative -ve delta must reach threshold, then partial recovery = absorption
EXHAUSTION_LOOKBACK = 8           # candles (~40 min) to check for selling pressure
MIN_SELLING_MULT = 1.5            # cum delta nadir must reach -1.5x avg|delta|
DELTA_RECOVERY_PCT = 0.05         # min 5% recovery from nadir = absorption started
CLIMAX_RVOL_MULT = 1.3            # volume spike threshold for selling climax detection

# 🔥 V5.52 TREND-EXHAUST FILTER (Item 63): Block premature countertrend on trend days
# Low exhaust recovery + wide range + low RVOL = don't fight the trend
TREND_EXHAUST_MAX_RECOVERY_PCT = 0.15   # recovery ≤ 15% = barely any exhaustion
TREND_EXHAUST_MIN_RANGE_ATR = 3.0       # range ≥ 3.0x ATR = strong trend day
TREND_EXHAUST_MAX_RVOL = 0.70           # RVOL < 0.70x = no volume conviction

# 🔥 V5.21 INSTITUTIONAL TRAP PERSISTENCE
STRONG_TRAP_MULT = 3.0            # trap delta > 3x threshold = strong trap
MAX_TRAP_AGE_STRONG = 8           # strong traps persist 8 candles (vs 5 default)

# 🔥 V5.23 TRAP RECOVERY (2B break-and-recover)
MAX_RECOVERY_CANDLES = 3          # candles to wait for price to recover above broken trap

# 🔥 V5.24 SHALLOW PULLBACK FILTERS (pure order-flow)
CASCADE_COOLDOWN_CANDLES = 6        # candles since new session low to allow LONG (avoids catching falling knives)
GOLDEN_CASCADE_MIN_AGE = 3          # 🔥 V5.44: Golden signals still need 3c since last new session high/low

# 🔥 V5.27 SIGNAL COOLDOWN (prevents rapid-fire noise signals in same zone)
SIGNAL_COOLDOWN_CANDLES = 12        # block signals for 12 candles (~60 min) after the last fired signal
                                    # unless new trap is BELOW previous signal's trap (genuine new low)

# 🔥 V5.39b SIGNAL TIME CUTOFF — block ALL signals after this time
# 🔥 V5.84: Hard 14:50 cutoff for EVERY signal (golden included). 15:xx had 0/8 WR
#           (-2.0R) in the Oct'25-Jun'26 outcome backtest; golden's 15:10 extension
#           was feeding those losers. All cutoffs aligned to 14:50 IST.
SIGNAL_CUTOFF_HOUR = 14             # 14:50 IST = last allowed signal time
SIGNAL_CUTOFF_MINUTE = 50
GOLDEN_SIGNAL_CUTOFF_HOUR = 14      # 🔥 V5.84: GOLDEN no longer extends past 14:50 (was 15:10, 0% WR)
GOLDEN_SIGNAL_CUTOFF_MINUTE = 50

# 🔥 V5.28 VWAP RESISTANCE FILTER (ensures room to travel above D2)
VWAP_MIN_CLEARANCE_ATR = 0.5        # block if D2 is within 0.5x ATR below VWAP (VWAP = ceiling)
                                    # pass if D2 >= VWAP (reclaimed) or D2 is far enough below

# 🔥 V5.20 SUPPORT PROXIMITY FILTERS
ATR_PERIOD = 14
DROP_LOOKBACK_CANDLES = 24         # lookback for swing high/low detection
MIN_DROP_ATR_MULT = 2.0            # trap must be at least 2.0x ATR below recent swing high
MIN_DROP_ATR_MULT_LONG = 0.8      # 🔥 V5.81: Relaxed from 1.0 — CF data: DROP blocked +106 at 60% WR
MIN_DROP_ATR_MULT_RECOVERED = 1.5  # recovered traps need less drop (break+recover = institutional proof)
MAX_TRAP_DIST_ATR_MULT = 5.75     # 🔥 V5.81: Widened from 5.0 — CF data: SUPPORT blocked +61.5 at 66.7% WR
MAX_PATTERN_HEIGHT_ATR = 2.5      # D2 must be within 2.5x ATR of trap (price hasn't left reversal zone)
MAX_RISK_ABSOLUTE = 30            # 🔥 V5.33: Risk>30 = 20% WR, -217.5 PnL in V5.32 backtest (V5.81 tried 40→regressed)
MIN_PATTERN_HEIGHT_PTS = 15       # minimum D2-trap distance (pts) — filters tiny noise patterns

# 🔥 V5.32 CHASE FILTER — DYNAMIC body ratio based on pattern size vs ATR
# Small patterns (< 1x ATR) naturally have large D2 bodies → relaxed limit (~85%)
# Large patterns (> 2x ATR) with huge D2 → genuine chasing → tight limit (~55%)
# Formula: max(0.55, min(0.85, 1.0 - pattern_height / (4 * ATR)))
D2_MAX_BODY_RATIO_FALLBACK = 0.65  # fallback when ATR unavailable

# 🔥 V5.31 SIGNAL QUALITY GATES (improves win rate, reduces drawdown)
D2_MIN_CLOSE_PCT = 0.40            # D2 candle close must be in upper 40% (bullish) / lower 40% (bearish)
REQUIRE_D2_DELTA_CONFIRM = True    # D2 candle must have net positive delta (bullish) / negative (bearish)
MIN_SIGNAL_RVOL = 0.60             # 🔥 V5.33: Raised from 0.50 (0.50-0.59 signals mostly losers)
LOCAL_RVOL_WINDOW = 20             # 🔥 V5.32: Recent candle window for local RVOL normalization
BLOCK_GRADE_C_CONSOL = True        # hard-block signals graded C + in consolidation (worst combo)

# 🔥 V5.35 RVOL DEAD ZONE — RVOL 1.00-1.30 has 36% WR (noise zone) vs 80%+ outside
# Low RVOL (<1.0) = quiet market, traps stand out clearly
# High RVOL (>1.3) = strong institutional participation
# Dead zone (1.0-1.3) = average activity, no clear institutional edge
RVOL_DEAD_ZONE_LOW = 1.00          # lower bound of dead zone (inclusive)
RVOL_DEAD_ZONE_HIGH = 1.30         # upper bound of dead zone (exclusive)
RVOL_DEAD_ZONE_RISK_BYPASS = 25    # 🔥 V5.37: Reverted to 25 (V5.36's 20 caused Aug 05 regression)
RVOL_DEAD_ZONE_ABSORB_BYPASS = 5   # 🔥 V5.37: High absorption (score≥5) passes dead zone (recovers Feb 18 WIN absorb=5)
RVOL_HIGH_CEILING = 2.0             # 🔥 V5.37: Block session RVOL ≥ 2.0 (0% WR in V5.34 + V5.35, 0 wins lost)

# 🔥 V5.39 PRECISION OVERRIDE — Dynamic confirmation with safety gates
# When exhaust confirmed AND D2 closes in extreme position (≥85% bull, ≤15% bear):
#   1. HEIGHT cap extends by 2.5pts (30 → 32.5) — allows slightly larger confirmed setups
#   2. CHASE filter bypassed — large D2 body is directional confirmation, not chasing
# V5.38 fired too broadly (31 new: 18W/12L = 60% WR). V5.39 adds safety gates:
#   - RVOL ≥ 0.65 (removes 2L: Nov25 0.60x, Jan29 0.62x — 0% WR below 0.65)
#   - Time 11:00-14:59 (removes 1L: Nov11 15:05 — 0% WR outside this window)
#   - |D2-DELTA| ≥ 5000 (removes 1L: Sep11 δ=2625 — low conviction)
# Result: 18W/8L = 69% WR on new signals, 0 wins lost by gates
RISK_EXTENSION_CONFIRMED = 2.5      # Extra risk pts for confirmed setups
EXTREME_D2_CLOSE_PCT = 0.85         # D2 close position threshold (bull: ≥85%, bear: ≤15%)
OVERRIDE_MIN_RVOL = 0.65            # 🔥 V5.39: Min session RVOL for override (0% WR below)
TREND_OVERRIDE_MIN_RVOL = 0.45      # 🔥 V5.53: Trend-day override RVOL (trend structure provides conviction)
VWAP_CONFLUENCE_HEIGHT_EXTENSION = 7.5  # 🔥 V5.43: Extra HEIGHT when VWAP confirms direction (broken=short, reclaimed=long)
VWAP_CONFIRMED_MIN_D2_CLOSE = 0.70      # 🔥 V5.44: D2 close threshold for VWAP confirmed long (reclaim + strong close = support)
MIN_VWAP_LONG_BYPASS_RVOL = 0.75        # 🔥 V5.71: Raised from 0.40. VWAP reclaims require volume.
VWAP_RECLAIM_MIN_DELTA = 8000           # 🔥 V5.71: Must show actual aggression to reclaim VWAP
CEILING_ABSORB_HEIGHT_EXT = 7.5         # 🔥 V5.65: Extra HEIGHT when ceiling absorption confirmed (streak≥2) — institutional sellers at top justify wider entry tolerance
SHORT_LOW_RVOL_GRADE_B_MIN = 0.30       # 🔥 V5.68: Grade B shorts blocked when session RVOL in [0.30, 0.65) — 33% WR bucket
SHORT_LOW_RVOL_GRADE_B_MAX = 0.65       # 🔥 V5.73: Widened from 0.50→0.65 (backtest: 21 signals, 33% WR, -180 pts, p=0.026)
SHORT_RISK_CAP_NON_GOLDEN = 45.0        # 🔥 V5.68: Max risk for non-golden/non-climax shorts (50% WR at 35-50, 40% at >=50)
SHORT_MIDDAY_HOUR_START = 12            # 🔥 V5.68: Midday window start (12:00) — shorts need extra conviction
SHORT_MIDDAY_HOUR_END = 13              # 🔥 V5.68: Midday window end (13:59) — 52% WR vs 76.5% at 14:xx
SHORT_MIDDAY_MIN_ABSORB = 3             # 🔥 V5.68: Min absorb_score for midday shorts
SHORT_MIDDAY_MIN_RVOL = 0.65            # 🔥 V5.68: Min session RVOL for midday shorts (alternative to absorb)

# 🔥 V5.81: LONG QUALITY GATES — data-driven from V5.79 backtest analysis
LONG_HIGH_RISK_THRESHOLD = 35.0         # LONGs above this risk need extra conviction
LONG_HIGH_RISK_MIN_ABSORB = 4           # Required absorb score for high-risk LONGs (unless golden/RVOL sweet)
LONG_HIGH_RISK_RVOL_SWEET_LO = 0.65     # RVOL sweet spot lower bound (bypass absorb gate)
LONG_HIGH_RISK_RVOL_SWEET_HI = 1.0      # RVOL sweet spot upper bound
LOW_RVOL_QUAL_LO = 0.30                 # Low-RVOL range lower bound (below = already blocked by LOW-RVOL)
LOW_RVOL_QUAL_HI = 0.65                 # Low-RVOL range upper bound
LOW_RVOL_QUAL_MIN_ABSORB = 3            # Required absorb for low-RVOL signals
MIDDAY_BULL_HOUR = 13                   # 13:xx Grade B bull signals need absorb>=3

CLIMAX_VETO_MIN_DELTA_MULT = 2.0       # 🔥 V5.69: D2 candle |delta| must exceed 2.0x avg|delta| to trigger climax veto
CLIMAX_VETO_MIN_LOCAL_RVOL = 1.3       # 🔥 V5.69: D2 local RVOL must be >= 1.3x to confirm climax volume (matches CLIMAX_RVOL_MULT)
VWAP_RECLAIM_BUFFER_ATR = 0.25         # 🔥 V5.69: D2 must clear VWAP by 0.25x ATR to count as reclaimed/broken (thick liquidity band)
# DROP_EXHAUST_PROXY_ATR removed in V5.44 — replaced by dynamic swing-anchored exhaustion lookback
# OVERRIDE_MIN_TIME_HOUR removed in V5.39b — user prefers no time filter
# OVERRIDE_MAX_TIME_HOUR removed in V5.39b — user prefers no time filter
# OVERRIDE_MIN_D2_DELTA_ABS removed in V5.39b — only 1 data point, not reliable

# 🔥 V5.40 CLIMAX OVERRIDE — Climax reversals get special treatment
# Climax = volume spike + extreme delta + divergence (strongest exhaustion signal)
# On climax candles, RVOL is naturally LOW (volume dried up after the climax candle)
# so standard RVOL gate penalizes the normal climax reversal pattern.
# Effect: larger HEIGHT extension (+12.5) AND RVOL-GATE bypass
# Does NOT require extreme D2 close — climax alone is sufficient confirmation
CLIMAX_HEIGHT_EXTENSION = 12.5      # Extra pts for climax setups (cap: 30 → 42.5)

# 🔥 V5.41 MOMENTUM OVERRIDE — High-RVOL confirmed signals tolerate more height
# When override active (exhaust + extreme D2 close) AND RVOL ≥ 1.0x:
#   HEIGHT cap extends by +7.5 (instead of +2.5) → cap: 30 → 37.5
# Rationale: High RVOL = institutional participation. Combined with exhaust + extreme close,
# this is high-conviction signal that justifies more risk tolerance.
# Tier system: No override(30) < Standard(32.5) < Momentum(37.5) < Climax(42.5)
MOMENTUM_HEIGHT_EXTENSION = 7.5     # Extra pts for high-RVOL confirmed signals (cap: 30 → 37.5)
MOMENTUM_OVERRIDE_MIN_RVOL = 1.0    # Min RVOL for momentum tier

# 🔥 V5.42 EXTREME CONVICTION — volatile sessions where fixed caps are inadequate
# When exhaust confirmed AND RVOL ≥ 1.5x, HEIGHT uses pure ATR-based cap (3.5x ATR)
# instead of fixed risk_cap. This lets volatile-day reversals through while maintaining
# the constraint that patterns must be proportional to current market volatility.
# Tier system: No(30) < Std(32.5) < Momentum(37.5) < Climax(42.5) < Extreme(3.5xATR)
EXTREME_CONVICTION_MIN_RVOL = 1.5   # Min RVOL for extreme conviction tier
EXTREME_CONVICTION_ATR_MULT = 3.5   # ATR multiplier (removes fixed cap)
EXTREME_CONVICTION_MAX_RISK = 60    # 🔥 V5.45: Hard absolute ceiling even for extreme conviction
EXTREME_DELTA_HEIGHT_ATR_MULT = 5.0 # 🔥 V5.49: ATR mult for extreme delta signal HEIGHT (wider than 3.5x)
EXTREME_DELTA_HEIGHT_CAP = 100      # 🔥 V5.49: Hard cap for extreme delta signal HEIGHT
GOLDEN_HEIGHT_CAP = 100             # 🔥 V5.61: HEIGHT cap for GOLDEN entries at session extremes
TREND_INFLATE_MIN_PTS = 20           # 🔥 V5.55: Min close inflation (pts) for D2-based height correction

# 🔥 V5.56 WIDE-RANGE EXHAUST HEIGHT EXTENSION
# On volatile/trend days (range ≥ 2.5x ATR), confirmed exhaustion justifies wider HEIGHT tolerance.
# Patterns on wide-range days are naturally taller because range is expanded.
# Triple gate: effective_exhaust + wide range + min inflation/cap safety.
WIDE_RANGE_EXHAUST_HEIGHT_EXT = 15   # 🔥 V5.56: Extra HEIGHT tolerance on wide-range exhaust days
WIDE_RANGE_MIN_RATIO = 2.5           # 🔥 V5.56: Min range/ATR ratio for wide-range extension

# 🔥 V5.31 GOLDEN ENTRY DETECTION (preserves high-conviction session extreme reversals)
GOLDEN_SESSION_LOW_ATR = 0.75      # trap within 0.75x ATR of session low → "at session extreme"
GOLDEN_MIN_RVOL = 1.2              # minimum RVOL for golden entry qualification
GOLDEN_ABSORPTION_SCORE = 4        # minimum absorption score for golden entry

# 🔥 V5.20 MULTI-LAYER ABSORPTION PARAMETERS
ABSORPTION_SELL_PCT = 0.55       # Min sell% of row volume for absorption
ABSORPTION_ROW_VOL_MULT = 1.3   # Row vol must be this x avg to qualify
ABSORPTION_DELTA_CAP = 0.25     # Max |delta|/vol ratio (contained = absorbed)
ABSORPTION_MEMORY = 5           # Track absorption zones across N candles
MULTI_HIT_THRESHOLD = 2         # Min hits at same price for strong zone
ABSORPTION_WICK_VOL_PCT = 0.25  # Min % of candle vol in lower wick for candle absorption

# 🔥 V5.17 ADVANCED SCORING THRESHOLDS
RVOL_ZSCORE_CLIMAX = 2.5
RVOL_ZSCORE_STRONG = 1.2
ABSORPTION_SCORE_HIGH = 5       # Candle absorption score threshold (high)
ABSORPTION_SCORE_MOD = 3        # Candle absorption score threshold (moderate)
EFFICIENCY_LOW_THRESHOLD = 0.3
CHURN_RVOL_THRESHOLD = 1.5
CHURN_BODY_RATIO = 0.4

# SHARED DATA
ohlc_data = {}
ohlc_complete = False

# COLORS
RGB = {'START_R': (255, 245, 245), 'START_G': (245, 255, 245), 'END_R': (220, 40, 40), 'END_G': (40, 180, 40)}
C = {
    'W_TEXT': '\033[38;2;255;255;255m', 'B_TEXT': '\033[38;2;0;0;0m', 'POC_TEXT': '\033[38;2;0;0;255m',
    'G_DELTA': '\033[92m', 'R_DELTA': '\033[91m', 'RESET': '\033[0m', 'BOLD': '\033[1m',
    'ALERT_BG_G': '\033[42m', 'ALERT_BG_R': '\033[41m', 'ALERT_FG': '\033[97m', 'WARN': '\033[43m',
    'GOLD': '\033[93m', 'CYAN': '\033[96m',
    'TAG_RED': '\033[41m[DR]\033[0m',
    'TAG_GREEN': '\033[42m[DG]\033[0m',
    'TAG_LIGHT': '\033[100m[L]\033[0m'
}

def get_fresh_token():
    headers = {"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"}
    payload = {"ClientId": CLIENT_ID, "AuthFlow": "REFRESH_TOKEN_AUTH", "AuthParameters": {"REFRESH_TOKEN": REFRESH_TOKEN}}
    try:
        response = requests.post(COGNITO_URL, headers=headers, json=payload)
        data = response.json()
        if response.status_code == 200:
            return data.get("AuthenticationResult", {}).get("IdToken")
    except Exception as e:
        print(f"⚠️ get_fresh_token failed: {e}")
    return None

def send_telegram(message):
    return

# ==============================================================================
# 🛠️ UTILS
# ==============================================================================

class RobustDecoder:
    def __init__(self, data):
        self.data = data; self.pos = 0; self.len = len(data)
    def read_varint(self):
        result = 0; shift = 0
        while True:
            if self.pos >= self.len: raise IndexError("read_varint: out of bounds")
            b = self.data[self.pos]; self.pos += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80): return result
            shift += 7
    def skip_field(self, wt):
        if wt == 0: self.read_varint()
        elif wt == 1: self.pos += 8
        elif wt == 2: skip = self.read_varint(); self.pos += skip
        elif wt == 5: self.pos += 4
        else: raise ValueError(f"Unknown wire type {wt}")
    def decode_root(self):
        for i in range(self.len - 1):
            if self.data[i] == 0x22:
                checkpoint = i
                try:
                    self.pos = i + 1; length = self.read_varint(); end_pos = self.pos + length
                    if end_pos > self.len or length < 10: continue
                    self.process_map(end_pos)
                except Exception: self.pos = checkpoint; continue
    def process_map(self, end_pos):
        key = None
        while self.pos < end_pos:
            try:
                tag = self.read_varint(); fid = tag >> 3; wt = tag & 7
                if fid == 1:
                    slen = self.read_varint(); raw = self.data[self.pos:self.pos + slen]; self.pos += slen
                    try: key = raw.decode()
                    except Exception: key = str(int.from_bytes(raw, 'little'))
                elif fid == 2:
                    vlen = self.read_varint()
                    if key: self.process_intraday_bars(vlen, key)
                    else: self.pos += vlen
                else: self.skip_field(wt)
            except Exception: return
    def process_intraday_bars(self, length, date_key):
        end = self.pos + length; price_precision = None; candles = []
        try: base_dt = datetime.strptime(date_key, "%Y-%m-%d")
        except Exception: base_dt = None
        try:
            while self.pos < end:
                tag = self.read_varint(); fid = tag >> 3; wt = tag & 7
                if fid == 4: price_precision = self.read_varint()
                elif fid == 5:
                    clen = self.read_varint(); cend = self.pos + clen
                    c = {'off':0,'o':0,'h':0,'l':0,'c':0,'v':0}
                    while self.pos < cend:
                        ctag = self.read_varint(); cfid = ctag >> 3; cwt = ctag & 7
                        if cfid == 1: c['off'] = self.read_varint()
                        elif cfid == 2: c['o'] = self.read_varint()
                        elif cfid == 3: c['h'] = self.read_varint()
                        elif cfid == 4: c['l'] = self.read_varint()
                        elif cfid == 5: c['c'] = self.read_varint()
                        elif cfid == 6: c['v'] = self.read_varint()
                        else: self.skip_field(cwt)
                    candles.append(c)
                else: self.skip_field(wt)
        except Exception: return

        # 🔥 NIFTY: Smart price divisor detection
        def get_smart_divisor(raw_price):
            val = float(raw_price)
            if val > 2000000: return 100.0
            if val > 200000: return 10.0
            return 1.0

        price_div = get_smart_divisor(candles[0]['o']) if candles else 1.0

        for c in candles:
            if base_dt:
                # 🔥 NIFTY: MARKET_START_SHIFT (09:15) + offset in minutes
                exact_time = base_dt + MARKET_START_SHIFT + timedelta(minutes=c['off'])
                time_key = exact_time.strftime('%Y-%m-%d %H:%M:%S')
                ohlc_data[time_key] = {'o': c['o']/price_div, 'h': c['h']/price_div, 'l': c['l']/price_div, 'c': c['c']/price_div, 'v': c['v']}

class OHLCFetcher:
    def __init__(self, token):
        self.token = token
        # 🔥 NIFTY: Use BLR1 endpoint for NSE data
        self.ws_url = f"wss://origin.ws.prodb.blr1.gocharting.com/blr1/ws?token={self.token}&tag=McXNUaCmXM"
        self.headers = ["User-Agent: Mozilla/5.0", "Accept: */*", "Origin: https://gocharting.com"]
        self.ws = None
        self.is_finished = False

    def on_error(self, ws, error):
        if not self.is_finished: print(f"❌ OHLC Connection Error: {error}")

    def on_close(self, ws, c, m): pass

    def on_message(self, ws, msg):
        global ohlc_complete
        if isinstance(msg, bytes):
            RobustDecoder(msg).decode_root()
            if len(ohlc_data) > 0:
                print(f"✅ OHLC: Loaded {len(ohlc_data)} candles. Checking coverage...")
                has_target_date = False
                for key in ohlc_data:
                    if FOOTPRINT_DATE in key:
                        has_target_date = True
                        break

                if has_target_date:
                    print(f"✅ Target Date {FOOTPRINT_DATE} found in OHLC data.")
                    ohlc_complete = True
                    self.is_finished = True
                    ws.close()
                else:
                    if len(ohlc_data) > 1000:
                        ohlc_complete = True
                        self.is_finished = True
                        ws.close()
                    else:
                        print(f"⚠️ Target Date {FOOTPRINT_DATE} NOT found yet. Waiting...")
        else:
            if "Welcome" in msg:
                rows_needed = 10000
                if FOOTPRINT_DATE:
                    try:
                        target_dt = datetime.strptime(FOOTPRINT_DATE, '%Y-%m-%d').date()
                        today = datetime.now().date()
                        delta_days = (today - target_dt).days
                        rows_needed = (delta_days + 3) * 300
                        if rows_needed < 600: rows_needed = 600
                        print(f"📅 Backtest Mode: Requesting {rows_needed} rows...")
                    except Exception as e:
                        print(f"⚠️ rows_needed calc failed, using default {rows_needed}: {e}")

                req = {"request_id": 1, "command": "TS/V2", "action": "add", "payload": {"msg_type": "OHLCV/V2", "symbol": SYMBOL, "interval": "5m", "session": "RTH", "hint": f"rows={rows_needed}", "idxs": [0]}}
                ws.send(json.dumps(req))

    def start(self):
        self.ws = websocket.WebSocketApp(self.ws_url, header=self.headers, on_message=self.on_message, on_error=self.on_error, on_close=self.on_close)
        self.ws.run_forever()

# ==============================================================================
# 🎨 FOOTPRINT RENDERER
# ==============================================================================

class FootprintRenderer:
    def __init__(self, token):
        self.token = token
        # 🔥 NIFTY: Use BLR1 endpoint for NSE data
        self.ws_url = f"wss://origin.ws.prodb.blr1.gocharting.com/blr1/ws?token={self.token}&tag=McXNUaCmXM"
        self.headers = ["User-Agent: Mozilla/5.0", "Accept: */*", "Origin: https://gocharting.com"]
        self.shutting_down = False

        if FOOTPRINT_DATE:
            self.target_ist_date = datetime.strptime(FOOTPRINT_DATE, '%Y-%m-%d').date()
            print(f"📅 BACKTESTING MODE: {self.target_ist_date}")
        else:
            self.target_ist_date = datetime.now().date()
            print(f"🔴 LIVE MODE: {self.target_ist_date}")

        self.curr_date = self.target_ist_date.strftime('%Y-%m-%d')
        self.prev_date = (self.target_ist_date - timedelta(days=1)).strftime('%Y-%m-%d')

        self.all_candles = []
        self.dates_fetched = 0
        self.active_trap_price = None
        self.active_trap_delta = 0
        self.delta_history = deque(maxlen=FILTER_LOOKBACK)
        self.volume_history = deque(maxlen=FILTER_LOOKBACK)
        self.trap_age = 0

        # 🔥 V5.23: Trap recovery state
        self.trap_broken_age = 0
        self.trap_break_low = None
        self.trap_recovered = False  # True when trap broke & recovered (= absorption proof)

        self.state_highest_dg1 = None
        self.state_has_light = False
        self.state_light_price = None
        self.state_dg1_is_genuine_dg = True   # V5.26e: D1 is genuine DG (vs volume-drive [L])
        self.historical_dr_between = set()    # 🔥 V5.43: Track DR blocks between D1/D2 from prior candles
        self.historical_dr_first_recorded_age = None  # 🔥 V5.66: Trap age when first DR block was recorded (for decay check)

        self.ohlc_cache = deque(maxlen=ATR_PERIOD + DROP_LOOKBACK_CANDLES)

        # 🔥 V5.20: Multi-candle absorption tracking
        self.absorption_zones = {}              # {price_bucket: {'count', 'total_sell', 'total_buy', 'age'}}
        self.absorption_zones_bear = {}         # 🔥 V5.34: Bear-side multi-candle absorption
        self.candle_index = 0                   # Running candle counter for absorption tracking

        # 🔥 V5.25: Bottom selling absorption tracking
        self.bottom_absorb_streak = 0           # Consecutive candles with heavy bottom selling
        self.bottom_absorb_cumul = 0            # Cumulative sell volume at bottom across streak
        self.floor_confirmed = False             # 🔥 V5.50: Sticky flag — True once FLOOR detected, persists until trap resets
        self.floor_last_active_age = None        # 🔥 V5.50b: Trap age when FLOOR was last actively detected
        self.floor_retry_used = False             # 🔥 V5.51: One retry allowed when signal blocked + floor confirmed

        # 🔥 Monotonic candle counter (increments once per render_candle call)
        # Used for SIGNAL-CD and CASCADE timing — NOT len(ohlc_cache) which saturates at maxlen
        self.render_candle_count = 0

        # 🔥 V5.24: Session waterfall detection
        self.session_lowest_trap = None          # running session lowest trap price
        self.last_new_low_candle_idx = None      # candle index when last new-session-low trap formed

        # 🔥 V5.27: Signal cooldown (prevents rapid-fire noise in same zone)
        self.last_signal_candle_idx = None       # candle index when last signal fired
        self.last_signal_trap_price = None       # trap price of last fired signal

        # 🔥 V5.28: Session VWAP tracking
        self.session_cum_tp_vol = 0.0            # Σ(typical_price × volume)
        self.session_cum_vol = 0.0               # Σ(volume)
        self.session_vwap = None                 # current session VWAP

        # 🔥 V5.84: Pre-initialize lazily-created attributes to avoid latent
        # AttributeError on refactor / early-return paths. These are normally
        # (re)assigned inside is_consolidation() / is_delta_exhausted() /
        # is_buying_exhausted().
        self.last_range_ratio = None             # set in is_consolidation()
        self.last_exhaust_recovery_pct = None    # set in is_(delta|buying)_exhausted()

        self.stats = {'total': 0, 'rendered': 0, 'skipped_date': 0, 'skipped_empty': 0}

        # =====================================================================
        # 🔻 BEARISH STATE — mirrors bullish trap tracking for short setups
        # Ceiling = DG cluster at TOP of candle (buyer exhaustion / trapped buying)
        # Pattern = DR→L→DR below ceiling (sellers stepping in)
        # =====================================================================
        self.bear_active_ceiling_price = None
        self.bear_active_ceiling_delta = 0
        self.bear_ceiling_age = 0

        # Bear ceiling recovery state (mirror of trap recovery)
        self.bear_ceiling_broken_age = 0
        self.bear_ceiling_break_high = None
        self.bear_ceiling_recovered = False  # True when ceiling broke & recovered

        # Bear pattern state: DR→L→DR (descending from ceiling)
        self.bear_state_lowest_dr1 = None
        self.bear_state_has_light = False
        self.bear_state_light_price = None
        self.bear_state_dr1_is_genuine_dr = True
        self.bear_historical_dg_between = set()  # 🔥 V5.43: Track DG blocks between D1/D2 from prior candles

        # Bear bottom absorption tracking (buying at top absorbed by sellers)
        self.bear_top_absorb_streak = 0
        self.bear_top_absorb_cumul = 0
        self.ceiling_confirmed = False               # 🔥 V5.67: Sticky flag — True once CEILING absorbed (streak≥2), persists until ceiling resets

        # Bear cascade detection (session rally / new highs)
        self.bear_session_highest_ceiling = None
        self.bear_last_new_high_candle_idx = None

        # Bear signal cooldown
        self.bear_last_signal_candle_idx = None
        self.bear_last_signal_ceiling_price = None

    def format_vol(self, vol):
        abs_vol = abs(vol)
        sign = '-' if vol < 0 else ''
        if abs_vol >= 10000: return f"{sign}{int(abs_vol/1000)}K"
        if abs_vol >= 1000: return f"{sign}{abs_vol/1000:.1f}K"
        return str(int(vol))

    def get_bucket(self, raw_price):
        # 🔥 NIFTY: Smart divisor detection using Decimal for precision
        val = float(raw_price)
        if val > 2000000: divisor = Decimal("100.0")
        elif val > 200000: divisor = Decimal("10.0")
        else: divisor = Decimal("1.0")

        price_dec = Decimal(str(raw_price)) / divisor
        # 🔥 Round UP to next STEP_SIZE bucket (ROUND_CEILING matches GoCharting)
        bucket = (price_dec / STEP_SIZE_DEC).to_integral_value(rounding=ROUND_CEILING) * STEP_SIZE_DEC
        return float(bucket)


    # =========================================================================
    # 🔥 V5.17: ADVANCED RVOL Z-SCORE
    # =========================================================================
    def get_rvol_zscore(self, current_volume):
        if len(self.volume_history) < 10:
            if len(self.volume_history) < 5:
                return 0, 1.0
            avg_vol = sum(self.volume_history) / len(self.volume_history)
            ratio = current_volume / avg_vol if avg_vol > 0 else 1.0
            return 0, ratio

        mean = statistics.mean(self.volume_history)
        stdev = statistics.stdev(self.volume_history)

        rvol_ratio = current_volume / mean if mean > 0 else 1.0
        z_score = (current_volume - mean) / stdev if stdev > 0 else 0

        return z_score, rvol_ratio

    # =========================================================================
    # 🔥 V5.32: LOCAL RVOL — adapts to time-of-day volume patterns
    # =========================================================================
    def get_local_rvol(self, current_volume, window=None):
        """RVOL against recent N candles instead of full session.
        Normalizes for intraday volume decay (avoids penalizing afternoon signals
        against high opening-hour volumes)."""
        if window is None:
            window = LOCAL_RVOL_WINDOW
        if len(self.volume_history) < 5:
            return 1.0
        recent = list(self.volume_history)[-window:]
        local_mean = sum(recent) / len(recent)
        return current_volume / local_mean if local_mean > 0 else 1.0

    # =========================================================================
    # 🔥 V5.20: LAYER 1 - ROW-LEVEL ABSORPTION DETECTION
    # =========================================================================
    def detect_row_absorption(self, complete_rows, row_tags):
        """Detect absorption at individual price rows within a candle.
        Absorption = heavy sell volume but delta stays contained (passive buyer absorbing)."""
        absorptions = []
        row_volumes = [r['buy'] + r['sell'] for r in complete_rows]
        avg_row_vol = sum(row_volumes) / len(row_volumes) if row_volumes else 1

        for i, row in enumerate(complete_rows):
            sell, buy = row['sell'], row['buy']
            total = sell + buy
            delta = buy - sell
            if total == 0:
                continue

            sell_pct = sell / total
            delta_ratio = abs(delta) / total

            # Seller absorption: sellers aggressive, volume elevated, delta contained
            is_absorbing = (
                sell_pct >= ABSORPTION_SELL_PCT and
                total >= avg_row_vol * ABSORPTION_ROW_VOL_MULT and
                delta_ratio < ABSORPTION_DELTA_CAP
            )

            if is_absorbing:
                strength = total / avg_row_vol
                absorptions.append({
                    'price': row['price'],
                    'sell_vol': sell,
                    'buy_vol': buy,
                    'strength': strength,
                    'row_idx': i,
                    'tag': row_tags[i]
                })

        return absorptions

    # =========================================================================
    # 🔥 V5.20: LAYER 2 - CANDLE-LEVEL ABSORPTION SCORE
    # =========================================================================
    def get_candle_absorption_score(self, complete_rows, ohlc_open, ohlc_close,
                                     ohlc_low, ohlc_high, total_vol, total_delta):
        """Enhanced candle-level absorption: combines delta/vol ratio,
        close position, and lower-wick volume concentration."""
        spread = ohlc_high - ohlc_low
        if spread == 0 or total_vol == 0:
            return 0, {}

        # 1. Delta-to-Volume Ratio: Low = both sides fighting = absorption
        delta_vol_ratio = abs(total_delta) / total_vol

        # 2. Close Position: Buyers winning if close is near the high
        close_position = (ohlc_close - ohlc_low) / spread

        # 3. Lower-wick volume concentration
        body_bottom = min(ohlc_open, ohlc_close)
        lower_wick_vol = 0
        for row in complete_rows:
            if row['price'] < body_bottom:
                lower_wick_vol += (row['buy'] + row['sell'])

        wick_dominance = lower_wick_vol / total_vol if total_vol > 0 else 0

        # Build score
        score = 0
        details = {}

        if delta_vol_ratio < 0.15:
            score += 3
            details['delta_vol'] = 'TIGHT'
        elif delta_vol_ratio < 0.30:
            score += 1
            details['delta_vol'] = 'moderate'

        if close_position > 0.70:
            score += 2
            details['close_pos'] = 'STRONG'
        elif close_position > 0.50:
            score += 1
            details['close_pos'] = 'ok'

        if wick_dominance > ABSORPTION_WICK_VOL_PCT:
            score += 2
            details['wick_vol'] = f'HIGH({wick_dominance:.0%})'

        return score, details

    # =========================================================================
    # 🔥 V5.20: LAYER 3 - MULTI-CANDLE ABSORPTION TRACKING
    # =========================================================================
    def track_multi_candle_absorption(self, complete_rows, row_tags):
        """Track absorption at price levels across multiple candles.
        Returns list of strong zones hit 2+ times."""
        # Age existing zones and expire old ones
        expired = [p for p, z in self.absorption_zones.items() if z['age'] > ABSORPTION_MEMORY]
        for p in expired:
            del self.absorption_zones[p]

        # Scan current candle for absorption rows
        row_volumes = [r['buy'] + r['sell'] for r in complete_rows]
        avg_row_vol = sum(row_volumes) / len(row_volumes) if row_volumes else 1

        for i, row in enumerate(complete_rows):
            sell, buy = row['sell'], row['buy']
            total = sell + buy
            if total < avg_row_vol * ABSORPTION_ROW_VOL_MULT:
                continue

            delta = buy - sell
            sell_pct = sell / total if total > 0 else 0
            delta_ratio = abs(delta) / total if total > 0 else 1

            if sell_pct >= ABSORPTION_SELL_PCT and delta_ratio < ABSORPTION_DELTA_CAP:
                price_key = round(row['price'], 2)

                if price_key not in self.absorption_zones:
                    self.absorption_zones[price_key] = {
                        'count': 0, 'total_sell': 0, 'total_buy': 0,
                        'first_seen': self.candle_index, 'age': 0
                    }

                zone = self.absorption_zones[price_key]
                zone['count'] += 1
                zone['total_sell'] += sell
                zone['total_buy'] += buy
                zone['age'] = 0  # Reset age on fresh hit

        # Increment age for all zones not hit this candle
        for price_key, zone in self.absorption_zones.items():
            if zone['age'] == 0 and zone['count'] > 0:
                pass  # Just updated this candle
            else:
                zone['age'] += 1

        self.candle_index += 1

        # Find strong multi-candle absorption zones
        strong_zones = []
        for price, zone in self.absorption_zones.items():
            if zone['count'] >= MULTI_HIT_THRESHOLD:
                strong_zones.append({
                    'price': price,
                    'hits': zone['count'],
                    'total_sell_absorbed': zone['total_sell'],
                    'strength': zone['count'] * (zone['total_sell'] / max(avg_row_vol, 1))
                })

        return sorted(strong_zones, key=lambda z: z['strength'], reverse=True)

    # =========================================================================
    # 🔥 V5.20: COMBINED ABSORPTION VALIDATION
    # =========================================================================
    def is_valid_absorption_context(self, complete_rows, row_tags, trap_price,
                                     ohlc_open, ohlc_close, ohlc_low, ohlc_high,
                                     total_vol, total_delta):
        """Combined check: Is there sufficient absorption evidence to confirm the setup?
        Returns (passed, status_string, absorption_score)."""
        # Layer 1: Row-level absorption in this candle
        row_absorptions = self.detect_row_absorption(complete_rows, row_tags)

        # Filter to absorptions near the trap price (within a few steps)
        trap_zone_absorptions = [
            a for a in row_absorptions
            if abs(a['price'] - trap_price) <= STEP_SIZE * 3
        ]

        # Layer 2: Candle-level absorption score
        candle_score, candle_details = self.get_candle_absorption_score(
            complete_rows, ohlc_open, ohlc_close, ohlc_low, ohlc_high,
            total_vol, total_delta
        )

        # Layer 3: Multi-candle zones near trap
        multi_zones = self.track_multi_candle_absorption(complete_rows, row_tags)
        trap_multi_zones = [
            z for z in multi_zones
            if abs(z['price'] - trap_price) <= STEP_SIZE * 3
        ]

        # Build combined verdict
        evidence = []
        total_score = candle_score

        if trap_zone_absorptions:
            best = max(trap_zone_absorptions, key=lambda a: a['strength'])
            evidence.append(f"Row({best['strength']:.1f}x @ {best['price']:.2f})")
            total_score += 2

        if trap_multi_zones:
            best_multi = trap_multi_zones[0]
            evidence.append(f"Multi({best_multi['hits']}hits @ {best_multi['price']:.2f})")
            total_score += 3

        details_str = ", ".join(f"{k}={v}" for k, v in candle_details.items())
        if details_str:
            evidence.append(f"Candle({details_str})")

        # Pass if candle score alone is moderate, OR row/multi absorption present
        passed = total_score >= ABSORPTION_SCORE_MOD

        if passed:
            status = f"Absorb ✓ (score:{total_score}) {' | '.join(evidence)}"
        else:
            status = f"Weak absorb (score:{total_score}) {' | '.join(evidence) if evidence else 'none'}"

        return passed, status, total_score

    # =========================================================================
    # 🔥 V5.34: BEARISH LAYER 1 - ROW-LEVEL BUY ABSORPTION DETECTION
    # =========================================================================
    def detect_row_absorption_bear(self, complete_rows, row_tags):
        """Detect buying absorption at individual price rows within a candle.
        Buy absorption = heavy buy volume but delta stays contained (passive seller absorbing)."""
        absorptions = []
        row_volumes = [r['buy'] + r['sell'] for r in complete_rows]
        avg_row_vol = sum(row_volumes) / len(row_volumes) if row_volumes else 1

        for i, row in enumerate(complete_rows):
            sell, buy = row['sell'], row['buy']
            total = sell + buy
            delta = buy - sell
            if total == 0:
                continue

            buy_pct = buy / total
            delta_ratio = abs(delta) / total

            # Buyer absorption: buyers aggressive, volume elevated, delta contained
            is_absorbing = (
                buy_pct >= ABSORPTION_SELL_PCT and
                total >= avg_row_vol * ABSORPTION_ROW_VOL_MULT and
                delta_ratio < ABSORPTION_DELTA_CAP
            )

            if is_absorbing:
                strength = total / avg_row_vol
                absorptions.append({
                    'price': row['price'],
                    'sell_vol': sell,
                    'buy_vol': buy,
                    'strength': strength,
                    'row_idx': i,
                    'tag': row_tags[i]
                })

        return absorptions

    # =========================================================================
    # 🔥 V5.34: BEARISH LAYER 2 - CANDLE-LEVEL ABSORPTION SCORE
    # =========================================================================
    def get_candle_absorption_score_bear(self, complete_rows, ohlc_open, ohlc_close,
                                          ohlc_low, ohlc_high, total_vol, total_delta):
        """Bearish candle-level absorption: combines delta/vol ratio,
        close position (near low = sellers winning), and upper-wick volume concentration."""
        spread = ohlc_high - ohlc_low
        if spread == 0 or total_vol == 0:
            return 0, {}

        # 1. Delta-to-Volume Ratio: Low = both sides fighting = absorption
        delta_vol_ratio = abs(total_delta) / total_vol

        # 2. Close Position: Sellers winning if close is near the low
        close_position = (ohlc_close - ohlc_low) / spread

        # 3. Upper-wick volume concentration (mirror of lower-wick for bullish)
        body_top = max(ohlc_open, ohlc_close)
        upper_wick_vol = 0
        for row in complete_rows:
            if row['price'] > body_top:
                upper_wick_vol += (row['buy'] + row['sell'])

        wick_dominance = upper_wick_vol / total_vol if total_vol > 0 else 0

        # Build score
        score = 0
        details = {}

        if delta_vol_ratio < 0.15:
            score += 3
            details['delta_vol'] = 'TIGHT'
        elif delta_vol_ratio < 0.30:
            score += 1
            details['delta_vol'] = 'moderate'

        if close_position < 0.30:
            score += 2
            details['close_pos'] = 'STRONG'
        elif close_position < 0.50:
            score += 1
            details['close_pos'] = 'ok'

        if wick_dominance > ABSORPTION_WICK_VOL_PCT:
            score += 2
            details['wick_vol'] = f'HIGH({wick_dominance:.0%})'

        return score, details

    # =========================================================================
    # 🔥 V5.34: BEARISH LAYER 3 - MULTI-CANDLE ABSORPTION TRACKING
    # =========================================================================
    def track_multi_candle_absorption_bear(self, complete_rows, row_tags):
        """Track buying absorption at price levels across multiple candles (bearish).
        Returns list of strong zones hit 2+ times."""
        # Age existing zones and expire old ones
        expired = [p for p, z in self.absorption_zones_bear.items() if z['age'] > ABSORPTION_MEMORY]
        for p in expired:
            del self.absorption_zones_bear[p]

        # Scan current candle for buy absorption rows
        row_volumes = [r['buy'] + r['sell'] for r in complete_rows]
        avg_row_vol = sum(row_volumes) / len(row_volumes) if row_volumes else 1

        for i, row in enumerate(complete_rows):
            sell, buy = row['sell'], row['buy']
            total = sell + buy
            if total < avg_row_vol * ABSORPTION_ROW_VOL_MULT:
                continue

            delta = buy - sell
            buy_pct = buy / total if total > 0 else 0
            delta_ratio = abs(delta) / total if total > 0 else 1

            if buy_pct >= ABSORPTION_SELL_PCT and delta_ratio < ABSORPTION_DELTA_CAP:
                price_key = round(row['price'], 2)

                if price_key not in self.absorption_zones_bear:
                    self.absorption_zones_bear[price_key] = {
                        'count': 0, 'total_sell': 0, 'total_buy': 0,
                        'first_seen': self.candle_index, 'age': 0
                    }

                zone = self.absorption_zones_bear[price_key]
                zone['count'] += 1
                zone['total_sell'] += sell
                zone['total_buy'] += buy
                zone['age'] = 0  # Reset age on fresh hit

        # Increment age for all zones not hit this candle
        for price_key, zone in self.absorption_zones_bear.items():
            if zone['age'] == 0 and zone['count'] > 0:
                pass  # Just updated this candle
            else:
                zone['age'] += 1

        # Find strong multi-candle absorption zones
        strong_zones = []
        for price, zone in self.absorption_zones_bear.items():
            if zone['count'] >= MULTI_HIT_THRESHOLD:
                strong_zones.append({
                    'price': price,
                    'hits': zone['count'],
                    'total_buy_absorbed': zone['total_buy'],
                    'strength': zone['count'] * (zone['total_buy'] / max(avg_row_vol, 1))
                })

        return sorted(strong_zones, key=lambda z: z['strength'], reverse=True)

    # =========================================================================
    # 🔥 V5.34: COMBINED BEARISH ABSORPTION VALIDATION
    # =========================================================================
    def is_valid_absorption_context_bear(self, complete_rows, row_tags, ceiling_price,
                                          ohlc_open, ohlc_close, ohlc_low, ohlc_high,
                                          total_vol, total_delta):
        """Combined bearish check: Is there sufficient buying absorption evidence at ceiling?
        Returns (passed, status_string, absorption_score)."""
        # Layer 1: Row-level buy absorption in this candle
        row_absorptions = self.detect_row_absorption_bear(complete_rows, row_tags)

        # Filter to absorptions near the ceiling price (within a few steps)
        ceiling_zone_absorptions = [
            a for a in row_absorptions
            if abs(a['price'] - ceiling_price) <= STEP_SIZE * 3
        ]

        # Layer 2: Candle-level absorption score (bearish)
        candle_score, candle_details = self.get_candle_absorption_score_bear(
            complete_rows, ohlc_open, ohlc_close, ohlc_low, ohlc_high,
            total_vol, total_delta
        )

        # Layer 3: Multi-candle zones near ceiling
        multi_zones = self.track_multi_candle_absorption_bear(complete_rows, row_tags)
        ceiling_multi_zones = [
            z for z in multi_zones
            if abs(z['price'] - ceiling_price) <= STEP_SIZE * 3
        ]

        # Build combined verdict
        evidence = []
        total_score = candle_score

        if ceiling_zone_absorptions:
            best = max(ceiling_zone_absorptions, key=lambda a: a['strength'])
            evidence.append(f"Row({best['strength']:.1f}x @ {best['price']:.2f})")
            total_score += 2

        if ceiling_multi_zones:
            best_multi = ceiling_multi_zones[0]
            evidence.append(f"Multi({best_multi['hits']}hits @ {best_multi['price']:.2f})")
            total_score += 3

        details_str = ", ".join(f"{k}={v}" for k, v in candle_details.items())
        if details_str:
            evidence.append(f"Candle({details_str})")

        # Pass if candle score alone is moderate, OR row/multi absorption present
        passed = total_score >= ABSORPTION_SCORE_MOD

        if passed:
            status = f"Absorb ✓ (score:{total_score}) {' | '.join(evidence)}"
        else:
            status = f"Weak absorb (score:{total_score}) {' | '.join(evidence) if evidence else 'none'}"

        return passed, status, total_score

    # =========================================================================
    # 🔥 V5.17: EFFICIENCY MULTIPLIER
    # =========================================================================
    def get_efficiency_multiplier(self, body_size, current_volume, atr):
        if atr is None or atr == 0 or current_volume == 0:
            return 1.0

        if len(self.volume_history) < 5:
            return 1.0

        avg_vol = sum(self.volume_history) / len(self.volume_history)

        result = body_size / atr
        effort = current_volume / avg_vol

        return result / effort if effort > 0 else 1.0

    # =========================================================================
    # 🔥 V5.17: CHURN DETECTION
    # =========================================================================
    def is_churn_candle(self, rvol_zscore, body_size, spread):
        if spread == 0:
            return False
        body_ratio = body_size / spread
        return rvol_zscore > CHURN_RVOL_THRESHOLD and body_ratio < CHURN_BODY_RATIO

    def get_rvol(self, current_volume):
        if len(self.volume_history) < 5: return 1.0
        avg_vol = sum(self.volume_history) / len(self.volume_history)
        return current_volume / avg_vol if avg_vol > 0 else 1.0

    def get_delta_acceleration(self):
        if len(self.delta_history) < 3: return 0
        recent_velocity = self.delta_history[-1] - self.delta_history[-2]
        prev_velocity = self.delta_history[-2] - self.delta_history[-3]
        return recent_velocity - prev_velocity

    def detect_liquidity_voids(self, complete_rows):
        if not complete_rows: return []
        avg_vol = sum(r['buy'] + r['sell'] for r in complete_rows) / len(complete_rows)
        voids = []
        for row in complete_rows:
            row_vol = row['buy'] + row['sell']
            if row_vol < avg_vol * VOID_VOLUME_PCT:
                voids.append(row['price'])
        return voids

    # =========================================================================
    # 🔥 V5.15: DELTA EXHAUSTION DETECTION
    # =========================================================================
    def is_delta_exhausted(self):
        self.last_exhaust_recovery_pct = None  # 🔥 V5.52: expose for trend-exhaust filter
        if len(self.delta_history) < EXHAUSTION_LOOKBACK:
            return False, "Warmup (need more delta data)"

        deltas = list(self.delta_history)
        candles = list(self.ohlc_cache)

        # 🔥 V5.44: Dynamic lookback anchored to swing high (where selling started)
        # Instead of fixed 8-candle window, find the swing high and look back to that
        # candle. This ensures selling that started early is never missed.
        # 🔥 V5.44 Item 51: EXCLUDE swing high candle — it has the largest positive delta
        # (peak buying), which overwhelms subsequent selling in the cumulative window.
        dynamic_lookback = EXHAUSTION_LOOKBACK  # minimum floor
        prior_candles = candles[:-1] if len(candles) > 1 else candles
        lookback_window = prior_candles[-DROP_LOOKBACK_CANDLES:]
        if lookback_window:
            swing_high = max(c['h'] for c in lookback_window)
            for i in range(len(lookback_window) - 1, -1, -1):
                if lookback_window[i]['h'] == swing_high:
                    # Candles AFTER swing high (exclude swing high candle itself)
                    candles_since_swing = len(lookback_window) - i
                    dynamic_lookback = max(candles_since_swing, EXHAUSTION_LOOKBACK)
                    break
        dynamic_lookback = min(dynamic_lookback, len(deltas))

        recent_deltas = deltas[-dynamic_lookback:]
        avg_abs_delta = sum(abs(d) for d in recent_deltas) / len(recent_deltas)
        dynamic_threshold = -avg_abs_delta * MIN_SELLING_MULT

        running_cum = []
        cum = 0
        for d in recent_deltas:
            cum += d
            running_cum.append(cum)

        delta_nadir = min(running_cum)
        current_cum = running_cum[-1]

        if delta_nadir > dynamic_threshold:
            # Cumulative selling not reached - check for selling climax candle
            climax_passed, climax_status = self._check_selling_climax(avg_abs_delta, dynamic_lookback)
            if climax_passed:
                return True, climax_status
            return False, f"No selling ({int(delta_nadir)} > {int(dynamic_threshold)})"

        recovery = current_cum - delta_nadir
        recovery_pct = recovery / abs(delta_nadir) if delta_nadir != 0 else 0
        self.last_exhaust_recovery_pct = recovery_pct  # 🔥 V5.52: store for trend-exhaust filter

        if recovery_pct >= DELTA_RECOVERY_PCT:
            return True, f"Exhaust ✓ ({recovery_pct*100:.0f}% from {int(delta_nadir)})"

        # Recovery not sufficient - check for selling climax as alternative
        climax_passed, climax_status = self._check_selling_climax(avg_abs_delta, dynamic_lookback)
        if climax_passed:
            return True, climax_status

        return False, f"Still selling ({recovery_pct*100:.0f}% recovery)"

    # =========================================================================
    # 🔥 V5.21: SELLING CLIMAX DETECTION (institutional grade)
    # =========================================================================
    def _check_selling_climax(self, avg_abs_delta, lookback_override=None):
        """Detect institutional selling climax pattern:
        A candle with volume spike + extreme negative delta near session low,
        followed by delta improvement (divergence). Confirms selling exhaustion
        without requiring cumulative recovery threshold."""
        lookback = min(lookback_override or EXHAUSTION_LOOKBACK,
                       len(self.ohlc_cache),
                       len(self.delta_history),
                       len(self.volume_history))
        if lookback < 3:
            return False, "No climax (warmup)"

        avg_vol = sum(self.volume_history) / len(self.volume_history)
        all_candles = list(self.ohlc_cache)
        session_low = min(c['l'] for c in all_candles)
        session_high = max(c['h'] for c in all_candles)
        day_range = session_high - session_low

        if day_range <= 0:
            return False, "No climax (flat)"

        candles = all_candles[-lookback:]
        deltas = list(self.delta_history)[-lookback:]
        vols = list(self.volume_history)[-lookback:]

        # Find the most extreme negative delta candle near the session low
        climax_idx = None
        climax_delta = 0
        for i in range(lookback - 1):  # Exclude current candle (it's the recovery)
            c = candles[i]
            d = deltas[i] if i < len(deltas) else 0
            v = vols[i] if i < len(vols) else 0

            near_low = (c['l'] - session_low) <= day_range * 0.15
            vol_elevated = v >= avg_vol * CLIMAX_RVOL_MULT
            selling_extreme = d < -avg_abs_delta

            if near_low and vol_elevated and selling_extreme and d < climax_delta:
                climax_delta = d
                climax_idx = i

        if climax_idx is None:
            return False, "No climax"

        # Verify: delta improving after climax (institutional divergence signal)
        latest_delta = deltas[-1]
        if latest_delta > climax_delta * 0.5:
            return True, f"Climax \u2713 (peak:{int(climax_delta)}, now:{int(latest_delta)}, vol:{vols[climax_idx]/avg_vol:.1f}x)"

        return False, f"Climax weak (peak:{int(climax_delta)}, now:{int(latest_delta)})"

    # =========================================================================
    # 🔥 V5.15: ATR CALCULATION
    # =========================================================================
    def calculate_atr(self):
        MIN_ATR_CANDLES = 5  # adaptive warmup: allow ATR with fewer candles
        if len(self.ohlc_cache) < MIN_ATR_CANDLES:
            return None

        true_ranges = []
        candles = list(self.ohlc_cache)[-ATR_PERIOD:]
        for i in range(1, len(candles)):
            prev_close = candles[i-1]['c']
            curr = candles[i]
            tr = max(
                curr['h'] - curr['l'],
                abs(curr['h'] - prev_close),
                abs(curr['l'] - prev_close)
            )
            true_ranges.append(tr)

        return sum(true_ranges) / len(true_ranges) if true_ranges else None



    # =========================================================================
    # 🔥 V5.15: REVERSAL CONTEXT VALIDATION
    # =========================================================================
    def is_valid_reversal_context(self, trap_price):
        atr = self.calculate_atr()
        if atr is None or atr == 0:
            return False, "Warmup (need ATR)", 0.0

        recent_candles = list(self.ohlc_cache)[:-1][-DROP_LOOKBACK_CANDLES:]
        if not recent_candles:
            return False, "Warmup (no candle data)", 0.0

        swing_high = max(c['h'] for c in recent_candles)
        drop = swing_high - trap_price
        drop_atr_mult = drop / atr

        # 🔥 V5.76: LONGs use relaxed MIN_DROP_ATR_MULT_LONG (1.0x) — always below RECOVERED (1.5x), so recovered bypass is redundant
        base_drop = MIN_DROP_ATR_MULT_LONG  # Bull side uses relaxed threshold
        required_drop = base_drop
        if drop_atr_mult < required_drop:
            return False, f"\u2717 Drop {drop_atr_mult:.1f}x < {required_drop}x ATR", drop_atr_mult

        return True, f"Drop ✓ ({drop_atr_mult:.1f}x ATR)", drop_atr_mult

    def check_trap_proximity(self, trap_price):
        atr = self.calculate_atr()
        if atr is None or atr == 0: return False, "Warmup (need ATR)"

        recent_candles = list(self.ohlc_cache)[:-1][-DROP_LOOKBACK_CANDLES:]
        if not recent_candles: return False, "Warmup (no candle data)"

        swing_low = min(c['l'] for c in recent_candles)
        dist_from_low = trap_price - swing_low

        if dist_from_low < 0: return True, f"Prox ✓ (New Low)"

        max_dist = atr * MAX_TRAP_DIST_ATR_MULT
        if dist_from_low > max_dist:
            return False, f"\u2717 Trap too high ({dist_from_low:.2f} > {max_dist:.2f} [{MAX_TRAP_DIST_ATR_MULT}x ATR])"

        return True, f"Prox ✓ ({dist_from_low:.2f} < {max_dist:.2f})"

    # =========================================================================
    # � BEARISH FILTERS — mirrors of bullish reversal/proximity/exhaustion
    # =========================================================================
    def is_valid_bear_reversal_context(self, ceiling_price):
        """Mirror of is_valid_reversal_context: ceiling must be above swing low (rally)."""
        atr = self.calculate_atr()
        if atr is None or atr == 0:
            return False, "Warmup (need ATR)", 0.0

        recent_candles = list(self.ohlc_cache)[:-1][-DROP_LOOKBACK_CANDLES:]
        if not recent_candles:
            return False, "Warmup (no candle data)", 0.0

        swing_low = min(c['l'] for c in recent_candles)
        rally = ceiling_price - swing_low
        rally_atr_mult = rally / atr

        required_rally = MIN_DROP_ATR_MULT_RECOVERED if self.bear_ceiling_recovered else MIN_DROP_ATR_MULT
        if rally_atr_mult < required_rally:
            return False, f"\u2717 Rally {rally_atr_mult:.1f}x < {required_rally}x ATR", rally_atr_mult

        return True, f"Rally ✓ ({rally_atr_mult:.1f}x ATR)", rally_atr_mult

    def check_ceiling_proximity(self, ceiling_price):
        """Mirror of check_trap_proximity: ceiling must be near swing high."""
        atr = self.calculate_atr()
        if atr is None or atr == 0: return False, "Warmup (need ATR)"

        recent_candles = list(self.ohlc_cache)[:-1][-DROP_LOOKBACK_CANDLES:]
        if not recent_candles: return False, "Warmup (no candle data)"

        swing_high = max(c['h'] for c in recent_candles)
        dist_from_high = swing_high - ceiling_price

        if dist_from_high < 0: return True, f"Prox ✓ (New High)"

        max_dist = atr * MAX_TRAP_DIST_ATR_MULT
        if dist_from_high > max_dist:
            return False, f"\u2717 Ceiling too low ({dist_from_high:.2f} > {max_dist:.2f} [{MAX_TRAP_DIST_ATR_MULT}x ATR])"

        return True, f"Prox ✓ ({dist_from_high:.2f} < {max_dist:.2f})"

    def is_buying_exhausted(self):
        """Mirror of is_delta_exhausted: looks for cumulative POSITIVE delta exhaustion.
        Uses fixed EXHAUSTION_LOOKBACK (not dynamic) — bear signals at extended distance
        from ceiling don't benefit from expanded windows (captures stale buying)."""
        self.last_exhaust_recovery_pct = None  # 🔥 V5.52: expose for trend-exhaust filter
        if len(self.delta_history) < EXHAUSTION_LOOKBACK:
            return False, "Warmup (need more delta data)"

        recent_deltas = list(self.delta_history)[-EXHAUSTION_LOOKBACK:]
        avg_abs_delta = sum(abs(d) for d in recent_deltas) / len(recent_deltas)
        dynamic_threshold = avg_abs_delta * MIN_SELLING_MULT  # positive threshold

        running_cum = []
        cum = 0
        for d in recent_deltas:
            cum += d
            running_cum.append(cum)

        delta_peak = max(running_cum)  # highest cumulative buying
        current_cum = running_cum[-1]

        if delta_peak < dynamic_threshold:
            # Cumulative buying not reached - check for buying climax candle
            climax_passed, climax_status = self._check_buying_climax(avg_abs_delta)
            if climax_passed:
                return True, climax_status
            return False, f"No buying ({int(delta_peak)} < {int(dynamic_threshold)})"

        recovery = delta_peak - current_cum  # how much buying has faded
        recovery_pct = recovery / abs(delta_peak) if delta_peak != 0 else 0
        self.last_exhaust_recovery_pct = recovery_pct  # 🔥 V5.52: store for trend-exhaust filter

        if recovery_pct >= DELTA_RECOVERY_PCT:
            return True, f"Exhaust ✓ ({recovery_pct*100:.0f}% from {int(delta_peak)})"

        climax_passed, climax_status = self._check_buying_climax(avg_abs_delta)
        if climax_passed:
            return True, climax_status

        return False, f"Still buying ({recovery_pct*100:.0f}% recovery)"

    def _check_buying_climax(self, avg_abs_delta, lookback_override=None):
        """Mirror of _check_selling_climax: detect buying climax near session high."""
        lookback = min(lookback_override or EXHAUSTION_LOOKBACK,
                       len(self.ohlc_cache),
                       len(self.delta_history),
                       len(self.volume_history))
        if lookback < 3:
            return False, "No climax (warmup)"

        avg_vol = sum(self.volume_history) / len(self.volume_history)
        all_candles = list(self.ohlc_cache)
        session_low = min(c['l'] for c in all_candles)
        session_high = max(c['h'] for c in all_candles)
        day_range = session_high - session_low

        if day_range <= 0:
            return False, "No climax (flat)"

        candles = all_candles[-lookback:]
        deltas = list(self.delta_history)[-lookback:]
        vols = list(self.volume_history)[-lookback:]

        # Find the most extreme POSITIVE delta candle near the session HIGH
        climax_idx = None
        climax_delta = 0
        for i in range(lookback - 1):
            c = candles[i]
            d = deltas[i] if i < len(deltas) else 0
            v = vols[i] if i < len(vols) else 0

            near_high = (session_high - c['h']) <= day_range * 0.15
            vol_elevated = v >= avg_vol * CLIMAX_RVOL_MULT
            buying_extreme = d > avg_abs_delta

            if near_high and vol_elevated and buying_extreme and d > climax_delta:
                climax_delta = d
                climax_idx = i

        if climax_idx is None:
            return False, "No climax"

        latest_delta = deltas[-1]
        if latest_delta < climax_delta * 0.5:
            return True, f"Climax ✓ (peak:{int(climax_delta)}, now:{int(latest_delta)}, vol:{vols[climax_idx]/avg_vol:.1f}x)"

        return False, f"Climax weak (peak:{int(climax_delta)}, now:{int(latest_delta)})"


    # =========================================================================
    # �🔥 V5.20: CONSOLIDATION DETECTION
    # =========================================================================
    def is_consolidation(self):
        """Detect narrow-range consolidation: if last N candles trade within
        a tight range relative to ATR, market is chopping — skip signals."""
        self.last_range_ratio = None  # 🔥 V5.52: reset before early returns
        MIN_CONSOL_CANDLES = 8  # adaptive warmup
        if len(self.ohlc_cache) < MIN_CONSOL_CANDLES:
            return True, "Warmup (need range data)"

        atr = self.calculate_atr()
        if atr is None or atr == 0:
            return False, "Trend ✓ (no ATR)"

        lookback = min(CONSOL_LOOKBACK, len(self.ohlc_cache))
        recent = list(self.ohlc_cache)[-lookback:]
        range_high = max(c['h'] for c in recent)
        range_low = min(c['l'] for c in recent)
        total_range = range_high - range_low
        range_ratio = total_range / atr
        self.last_range_ratio = range_ratio  # 🔥 V5.52: expose for trend-exhaust filter

        if range_ratio < CONSOL_MIN_RANGE_ATR:
            return True, f"Consolidation ({range_ratio:.1f}x < {CONSOL_MIN_RANGE_ATR}x ATR)"
        return False, f"Trend ✓ ({range_ratio:.1f}x ATR range)"

    # =========================================================================
    # 🔥 V5.31: GOLDEN ENTRY DETECTION (bullish)
    # =========================================================================
    def is_golden_entry(self, trap_price, rvol_ratio, exhaust_passed, absorption_score):
        """Detect high-conviction 2B reversal at session extreme.
        Golden entries bypass secondary filters (VWAP, Chase, Cooldown, Consol).
        🔥 V5.35: Tightened — require ALL: extreme + exhaustion + volume + absorption."""
        atr = self.calculate_atr()
        if atr is None or atr == 0:
            return False, "No ATR"

        all_candles = list(self.ohlc_cache)
        if not all_candles:
            return False, "No data"

        session_low = min(c['l'] for c in all_candles)
        dist_from_low = trap_price - session_low

        reasons = []
        # 1. Trap at/near session low
        at_extreme = dist_from_low <= atr * GOLDEN_SESSION_LOW_ATR
        if at_extreme:
            reasons.append(f"SessionLow({dist_from_low:.1f}≤{atr*GOLDEN_SESSION_LOW_ATR:.1f})")

        # 2. Selling exhaustion confirmed
        if exhaust_passed:
            reasons.append("Exhaustion")

        # 3. Elevated volume
        vol_ok = rvol_ratio >= GOLDEN_MIN_RVOL
        if vol_ok:
            reasons.append(f"RVOL({rvol_ratio:.1f}x)")

        # 4. Absorption evidence
        absorb_ok = absorption_score >= ABSORPTION_SCORE_MOD  # 🔥 V5.35: Lowered from GOLDEN_ABSORPTION_SCORE to ABSORPTION_SCORE_MOD (3)
        if absorb_ok:
            reasons.append(f"Absorb({absorption_score})")

        # 🔥 V5.35: Need ALL four: session extreme + exhaustion + volume + absorption
        # V5.34: was (vol OR absorb) — too permissive, A+ had 54.5% WR
        is_golden = at_extreme and exhaust_passed and vol_ok and absorb_ok

        if is_golden:
            return True, f"GOLDEN ⭐ ({', '.join(reasons)})"
        else:
            missing = []
            if not at_extreme: missing.append("not at low")
            if not exhaust_passed: missing.append("no exhaustion")
            if not vol_ok: missing.append("no volume")
            if not absorb_ok: missing.append(f"no absorb(score:{absorption_score})")
            return False, f"Not golden ({', '.join(missing)})"

    # =========================================================================
    # 🔥 V5.31: GOLDEN ENTRY DETECTION (bearish mirror)
    # =========================================================================
    def is_golden_entry_bear(self, ceiling_price, rvol_ratio, exhaust_passed, absorb_score=0):
        """Detect high-conviction bearish 2B reversal at session high.
        Golden entries bypass secondary filters.
        🔥 V5.35: Tightened — require ALL: extreme + exhaustion + volume + absorption."""
        atr = self.calculate_atr()
        if atr is None or atr == 0:
            return False, "No ATR"

        all_candles = list(self.ohlc_cache)
        if not all_candles:
            return False, "No data"

        session_high = max(c['h'] for c in all_candles)
        dist_from_high = session_high - ceiling_price

        reasons = []
        at_extreme = dist_from_high <= atr * GOLDEN_SESSION_LOW_ATR
        if at_extreme:
            reasons.append(f"SessionHigh({dist_from_high:.1f}≤{atr*GOLDEN_SESSION_LOW_ATR:.1f})")

        if exhaust_passed:
            reasons.append("Exhaustion")

        vol_ok = rvol_ratio >= GOLDEN_MIN_RVOL
        if vol_ok:
            reasons.append(f"RVOL({rvol_ratio:.1f}x)")

        # 🔥 V5.35: Require absorption for golden (was missing on bear side entirely)
        absorb_ok = absorb_score >= ABSORPTION_SCORE_MOD
        if absorb_ok:
            reasons.append(f"Absorb({absorb_score})")

        # 🔥 V5.35: Need ALL four: extreme + exhaustion + volume + absorption
        is_golden = at_extreme and exhaust_passed and vol_ok and absorb_ok

        if is_golden:
            return True, f"GOLDEN ⭐ ({', '.join(reasons)})"
        else:
            missing = []
            if not at_extreme: missing.append("not at high")
            if not exhaust_passed: missing.append("no exhaustion")
            if not vol_ok: missing.append("no volume")
            if not absorb_ok: missing.append(f"no absorb(score:{absorb_score})")
            return False, f"Not golden ({', '.join(missing)})"

    def check_layered_drive_pattern(self, row_tags, complete_rows, trap_price, is_bullish=True,
                                      total_delta=0, rvol_ratio=0.0):
        # 🔥 V5.20: Compute avg row volume for drive block detection
        data_rows_vol = [r['buy'] + r['sell'] for r in complete_rows if r['buy'] > 0 or r['sell'] > 0]
        avg_row_vol = sum(data_rows_vol) / len(data_rows_vol) if data_rows_vol else 1

        # 🔥 V5.48: Allow dual volume-drive D1+D2 when candle overwhelmingly confirms direction
        # (single outlier sell block can skew luminance normalization, preventing all DG tags)
        total_vol_func = sum(data_rows_vol) if data_rows_vol else 1
        delta_vol_pct = abs(total_delta) / total_vol_func if total_vol_func > 0 else 0
        extreme_delta_candle = (
            self.trap_recovered
            and total_delta > 0
            and rvol_ratio >= EXTREME_PAIR_MIN_RVOL
            and delta_vol_pct >= EXTREME_PAIR_MIN_DELTA_PCT
        )

        rows_above = []
        for i, row in enumerate(complete_rows):
            if row['price'] > trap_price:
                delta = row['buy'] - row['sell']
                rows_above.append({
                    'price': row['price'],
                    'tag': row_tags[i],
                    'delta': delta,
                    'buy': row['buy'],
                    'sell': row['sell'],
                    'idx': i
                })

        def is_drive(tag, buy, sell, delta):
            """A row qualifies as 'drive block' ONLY if it has the DG tag.
            D1 and D2 must be genuinely dark green (high luminance intensity)."""
            return tag == 'DG'

        def is_volume_drive(tag, delta, relaxed=False):
            """⚜ V5.26e2: [L] row with strong positive delta can serve as ONE side
            of DG→L→DG pattern, but ONLY when:
            1. Paired with a genuine DG on the other side (no zero-DG patterns)
            2. Trap is recovered (break+recover = institutional proof context)
            Normal active traps stay strict DG-only (proven quality filter).
            🔥 V5.48: relaxed=True uses lower threshold for D2 in extreme candles."""
            if not self.trap_recovered:
                return False
            mult = EXTREME_PAIR_DRIVE_MULT if relaxed else VOLUME_DRIVE_MULT
            return tag == 'L' and delta > 0 and delta >= avg_row_vol * mult

        rows_above.sort(key=lambda x: x['price'])

        # 🔥 V5.43: Track DR blocks above D1 from current candle (cross-candle contamination check)
        if self.state_highest_dg1 is not None:
            for row_data in rows_above:
                if row_data['price'] > self.state_highest_dg1 and row_data['tag'] == 'DR':
                    dr_delta = abs(row_data['delta'])
                    if dr_delta >= 10:
                        self.historical_dr_between.add(row_data['price'])
                        # 🔥 V5.66: Record first age so decay check knows how stale the block is
                        if self.historical_dr_first_recorded_age is None:
                            self.historical_dr_first_recorded_age = self.trap_age

        matched_prices = {}
        if self.state_highest_dg1: matched_prices['DG1'] = self.state_highest_dg1
        if self.state_light_price: matched_prices['L'] = self.state_light_price

        dg1_data = None
        dg2_data = None
        found_dg2 = False
        rejection_reason = None

        for row_data in rows_above:
            price = row_data['price']
            tag = row_data['tag']
            delta = row_data['delta']
            buy = row_data['buy']
            sell = row_data['sell']
            row_is_drive = is_drive(tag, buy, sell, delta)

            if self.state_highest_dg1 is None:
                if is_bullish and row_is_drive and delta >= MIN_DG_DELTA:
                    self.state_highest_dg1 = price
                    self.state_dg1_is_genuine_dg = True
                    dg1_data = row_data
                    matched_prices['DG1'] = price
                elif is_bullish and is_volume_drive(tag, delta):
                    # V5.26e: Strong [L] as D1 — D2 must be genuine DG
                    self.state_highest_dg1 = price
                    self.state_dg1_is_genuine_dg = False
                    dg1_data = row_data
                    matched_prices['DG1'] = price

            elif not self.state_has_light:
                if is_bullish and row_is_drive and price > self.state_highest_dg1 and delta >= MIN_DG_DELTA:
                    self.state_highest_dg1 = price
                    self.state_dg1_is_genuine_dg = True  # V5.26e: upgrade to genuine
                    dg1_data = row_data
                    matched_prices['DG1'] = price
                elif not row_is_drive and tag != 'DR' and price > self.state_highest_dg1:
                    # Reject L rows with extreme sell dominance (not a genuine pause)
                    l_total = buy + sell
                    if l_total > 0 and sell > buy:
                        sell_pct = sell / l_total
                        if sell_pct > L_MAX_SELL_DOMINANCE:
                            continue  # Skip — heavy selling, not a pause
                    self.state_has_light = True
                    self.state_light_price = price
                    matched_prices['L'] = price

            else:
                # ⚜ V5.26e: D2 check first — genuine DG or volume-drive paired with genuine D1
                # 🔥 V5.48: extreme_delta_candle bypasses genuine-DG requirement for D2
                is_d2_candidate = False
                if is_bullish and row_is_drive and price > self.state_light_price:
                    is_d2_candidate = True
                elif (is_bullish and (self.state_dg1_is_genuine_dg or extreme_delta_candle)
                      and is_volume_drive(tag, delta, relaxed=extreme_delta_candle)
                      and price > self.state_light_price):
                    is_d2_candidate = True

                if is_d2_candidate:
                    if delta < MIN_DG_DELTA:
                        rejection_reason = f"DG2 weak ({delta} < {MIN_DG_DELTA})"
                        continue

                    min_spacing = MIN_DG_SPACING_STEPS * STEP_SIZE
                    spacing = price - self.state_highest_dg1
                    if spacing < min_spacing:
                        rejection_reason = f"Spacing {spacing:.2f} < {min_spacing:.2f}"
                        continue

                    for check_row in rows_above:
                        if check_row['price'] > self.state_highest_dg1 and check_row['price'] < price:
                            if check_row['tag'] == 'DR':
                                dr_delta = abs(check_row['delta'])
                                if dr_delta >= 10:
                                    rejection_reason = f"Strong DR ({int(dr_delta)}) @ {check_row['price']:.2f} - Pattern Killed"
                                    self.state_highest_dg1 = None
                                    self.state_has_light = False
                                    self.state_light_price = None
                                    self.state_dg1_is_genuine_dg = True
                                    self.historical_dr_between = set()
                                    self.historical_dr_first_recorded_age = None
                                    return False, f"Pattern Invalid: {rejection_reason}", matched_prices

                    # 🔥 V5.43: Check historical DR blocks from prior candles between D1 and D2
                    for hist_price in self.historical_dr_between:
                        if hist_price > self.state_highest_dg1 and hist_price < price:
                            # 🔥 V5.66: Decay historical blockers — stale DR blocks (≥2 candles old) are
                            # overrun when buyers show extreme delta AND floor absorption confirmed.
                            # Extreme buying proves the historical sellers have been absorbed.
                            _hist_block_age = self.trap_age - (self.historical_dr_first_recorded_age or self.trap_age)
                            _buyers_overrunning = total_delta >= 10000
                            if _hist_block_age >= 2 and _buyers_overrunning and self.floor_confirmed:
                                continue  # Decayed — historical sellers absorbed by current buying
                            rejection_reason = f"Prior-candle DR @ {hist_price:.2f} between D1-D2 - Pattern Killed"
                            self.state_highest_dg1 = None
                            self.state_has_light = False
                            self.state_light_price = None
                            self.state_dg1_is_genuine_dg = True
                            self.historical_dr_between = set()
                            self.historical_dr_first_recorded_age = None
                            return False, f"Pattern Invalid: {rejection_reason}", matched_prices

                    found_dg2 = True
                    dg2_data = row_data
                    matched_prices['DG2'] = price
                    break

                elif not row_is_drive and tag != 'DR' and price > self.state_highest_dg1:
                    # Reject L rows with extreme sell dominance
                    l_total = buy + sell
                    if l_total > 0 and sell > buy:
                        sell_pct = sell / l_total
                        if sell_pct > L_MAX_SELL_DOMINANCE:
                            continue  # Skip — heavy selling
                    if self.state_light_price is None or price < self.state_light_price:
                        self.state_light_price = price
                        matched_prices['L'] = price

        if found_dg2:
            # 🔥 V5.79: Re-validate D1 and L in current candle — demand may have evaporated
            # D1 was set as DG in a prior candle; if demand is gone, pattern is invalid
            # 🔥 V5.82: Skip check if D1 volume is trivial (opening tick noise, not real demand shift)
            avg_row_vol = sum(r['buy'] + r['sell'] for r in rows_above) / max(1, len(rows_above))
            if self.state_highest_dg1 is not None:
                for row_data in rows_above:
                    if row_data['price'] == self.state_highest_dg1:
                        d1_delta = row_data['buy'] - row_data['sell']
                        d1_total = row_data['buy'] + row_data['sell']
                        # D1 fails if: (a) net selling, or (b) no net demand (delta ≤ 0)
                        # But only if volume is meaningful (above avg row volume)
                        if d1_total > 0 and d1_delta <= 0 and d1_total >= avg_row_vol:
                            d1_sell_pct = row_data['sell'] / d1_total if d1_total > 0 else 0
                            # D1 has lost its demand — was DG, now neutral or selling
                            self.state_highest_dg1 = None
                            self.state_has_light = False
                            self.state_light_price = None
                            self.state_dg1_is_genuine_dg = True
                            return False, f"Pattern Invalid: D1 demand evaporated (delta:{d1_delta}, sell:{d1_sell_pct:.0%} @ {row_data['price']:.2f}, vol:{d1_total})", matched_prices
                        break
            # Re-validate L row — should not be sell-dominant in current candle
            if self.state_light_price is not None:
                for row_data in rows_above:
                    if row_data['price'] == self.state_light_price:
                        l_total = row_data['buy'] + row_data['sell']
                        if l_total > 0 and row_data['sell'] > row_data['buy']:
                            l_sell_pct = row_data['sell'] / l_total
                            if l_sell_pct > L_MAX_SELL_DOMINANCE:
                                self.state_highest_dg1 = None
                                self.state_has_light = False
                                self.state_light_price = None
                                self.state_dg1_is_genuine_dg = True
                                return False, f"Pattern Invalid: L row sell-dominant (sell:{l_sell_pct:.0%} @ {row_data['price']:.2f})", matched_prices
                        break
            return True, "DG→L→DG ✓ (Clean)", matched_prices
        elif rejection_reason:
            return False, f"Pattern Invalid: {rejection_reason}", matched_prices
        elif self.state_has_light:
            return False, "Waiting for DG2", matched_prices
        elif self.state_highest_dg1 is not None:
            return False, "Waiting for L", matched_prices
        else:
            return False, "Waiting for DG1", matched_prices

    # =========================================================================
    # 🔻 BEARISH PATTERN: DR→L→DR below ceiling (sellers stepping in)
    # Mirror of check_layered_drive_pattern but scans BELOW ceiling
    # =========================================================================
    def check_bear_drive_pattern(self, row_tags, complete_rows, ceiling_price, is_bearish=True):
        """Detect DR→L→DR pattern below the ceiling.
        D1 = first DR row below ceiling (sellers start)
        L  = pause row (reduced selling)
        D2 = second DR row below L (sellers confirm)
        A strong DG between D1 and D2 kills the pattern (buyer defense)."""
        data_rows_vol = [r['buy'] + r['sell'] for r in complete_rows if r['buy'] > 0 or r['sell'] > 0]
        avg_row_vol = sum(data_rows_vol) / len(data_rows_vol) if data_rows_vol else 1

        rows_below = []
        for i, row in enumerate(complete_rows):
            if row['price'] < ceiling_price:
                delta = row['buy'] - row['sell']
                rows_below.append({
                    'price': row['price'],
                    'tag': row_tags[i],
                    'delta': delta,
                    'buy': row['buy'],
                    'sell': row['sell'],
                    'idx': i
                })

        def is_drive(tag, buy, sell, delta):
            """A row qualifies as 'drive block' ONLY if it has the DR tag."""
            return tag == 'DR'

        def is_volume_drive(tag, delta):
            """Mirror of volume drive: [L] row with strong negative delta for recovered ceilings."""
            if not self.bear_ceiling_recovered:
                return False
            return tag == 'L' and delta < 0 and abs(delta) >= avg_row_vol * VOLUME_DRIVE_MULT

        # Sort descending (highest price first — scanning down from ceiling)
        rows_below.sort(key=lambda x: x['price'], reverse=True)

        # 🔥 V5.43: Track DG blocks below D1 from current candle (cross-candle contamination check)
        if self.bear_state_lowest_dr1 is not None:
            for row_data in rows_below:
                if row_data['price'] < self.bear_state_lowest_dr1 and row_data['tag'] == 'DG':
                    dg_delta = abs(row_data['delta'])
                    if dg_delta >= 10:
                        self.bear_historical_dg_between.add(row_data['price'])

        matched_prices = {}
        if self.bear_state_lowest_dr1: matched_prices['DR1'] = self.bear_state_lowest_dr1
        if self.bear_state_light_price: matched_prices['L'] = self.bear_state_light_price

        dr1_data = None
        dr2_data = None
        found_dr2 = False
        rejection_reason = None

        for row_data in rows_below:
            price = row_data['price']
            tag = row_data['tag']
            delta = row_data['delta']
            buy = row_data['buy']
            sell = row_data['sell']
            row_is_drive = is_drive(tag, buy, sell, delta)

            if self.bear_state_lowest_dr1 is None:
                # Looking for D1 (first DR below ceiling)
                if is_bearish and row_is_drive and abs(delta) >= MIN_DG_DELTA:
                    self.bear_state_lowest_dr1 = price
                    self.bear_state_dr1_is_genuine_dr = True
                    dr1_data = row_data
                    matched_prices['DR1'] = price
                elif is_bearish and is_volume_drive(tag, delta):
                    self.bear_state_lowest_dr1 = price
                    self.bear_state_dr1_is_genuine_dr = False
                    dr1_data = row_data
                    matched_prices['DR1'] = price

            elif not self.bear_state_has_light:
                # Looking for D1 upgrade or L (pause)
                if is_bearish and row_is_drive and price < self.bear_state_lowest_dr1 and abs(delta) >= MIN_DG_DELTA:
                    self.bear_state_lowest_dr1 = price
                    self.bear_state_dr1_is_genuine_dr = True
                    dr1_data = row_data
                    matched_prices['DR1'] = price
                elif not row_is_drive and tag != 'DG' and price < self.bear_state_lowest_dr1:
                    # L row: reject if extreme BUY dominance (not a genuine pause)
                    l_total = buy + sell
                    if l_total > 0 and buy > sell:
                        buy_pct = buy / l_total
                        if buy_pct > L_MAX_SELL_DOMINANCE:
                            continue  # Skip — heavy buying, not a pause
                    self.bear_state_has_light = True
                    self.bear_state_light_price = price
                    matched_prices['L'] = price

            else:
                # Looking for D2 (second DR below L)
                is_d2_candidate = False
                if is_bearish and row_is_drive and price < self.bear_state_light_price:
                    is_d2_candidate = True
                elif (is_bearish and self.bear_state_dr1_is_genuine_dr
                      and is_volume_drive(tag, delta)
                      and price < self.bear_state_light_price):
                    is_d2_candidate = True

                if is_d2_candidate:
                    if abs(delta) < MIN_DG_DELTA:
                        rejection_reason = f"DR2 weak ({abs(delta)} < {MIN_DG_DELTA})"
                        continue

                    min_spacing = MIN_DG_SPACING_STEPS * STEP_SIZE
                    spacing = self.bear_state_lowest_dr1 - price  # D1 is above D2
                    if spacing < min_spacing:
                        rejection_reason = f"Spacing {spacing:.2f} < {min_spacing:.2f}"
                        continue

                    # Check for strong DG between D1 and D2 (buyers defending = kills pattern)
                    for check_row in rows_below:
                        if check_row['price'] < self.bear_state_lowest_dr1 and check_row['price'] > price:
                            if check_row['tag'] == 'DG':
                                dg_delta = abs(check_row['delta'])
                                if dg_delta >= 10:
                                    rejection_reason = f"Strong DG ({int(dg_delta)}) @ {check_row['price']:.2f} - Pattern Killed"
                                    self.bear_state_lowest_dr1 = None
                                    self.bear_state_has_light = False
                                    self.bear_state_light_price = None
                                    self.bear_state_dr1_is_genuine_dr = True
                                    self.bear_historical_dg_between = set()
                                    return False, f"Pattern Invalid: {rejection_reason}", matched_prices

                    # 🔥 V5.43: Check historical DG blocks from prior candles between D1 and D2
                    for hist_price in self.bear_historical_dg_between:
                        if hist_price < self.bear_state_lowest_dr1 and hist_price > price:
                            rejection_reason = f"Prior-candle DG @ {hist_price:.2f} between D1-D2 - Pattern Killed"
                            self.bear_state_lowest_dr1 = None
                            self.bear_state_has_light = False
                            self.bear_state_light_price = None
                            self.bear_state_dr1_is_genuine_dr = True
                            self.bear_historical_dg_between = set()
                            return False, f"Pattern Invalid: {rejection_reason}", matched_prices

                    found_dr2 = True
                    dr2_data = row_data
                    matched_prices['DR2'] = price
                    break

                elif not row_is_drive and tag != 'DG' and price < self.bear_state_lowest_dr1:
                    # Update L position (closest to D1)
                    l_total = buy + sell
                    if l_total > 0 and buy > sell:
                        buy_pct = buy / l_total
                        if buy_pct > L_MAX_SELL_DOMINANCE:
                            continue
                    if self.bear_state_light_price is None or price > self.bear_state_light_price:
                        self.bear_state_light_price = price
                        matched_prices['L'] = price

        if found_dr2:
            # 🔥 V5.79: Re-validate D1 and L in current candle — supply may have evaporated
            # 🔥 V5.82: Skip check if D1 volume is trivial (opening tick noise, not real supply shift)
            avg_row_vol_bear = sum(r['buy'] + r['sell'] for r in rows_below) / max(1, len(rows_below))
            if self.bear_state_lowest_dr1 is not None:
                for row_data in rows_below:
                    if row_data['price'] == self.bear_state_lowest_dr1:
                        d1_delta = row_data['buy'] - row_data['sell']
                        d1_total = row_data['buy'] + row_data['sell']
                        # D1 fails if: (a) net buying, or (b) no net supply (delta ≥ 0)
                        # But only if volume is meaningful (above avg row volume)
                        if d1_total > 0 and d1_delta >= 0 and d1_total >= avg_row_vol_bear:
                            d1_buy_pct = row_data['buy'] / d1_total if d1_total > 0 else 0
                            self.bear_state_lowest_dr1 = None
                            self.bear_state_has_light = False
                            self.bear_state_light_price = None
                            self.bear_state_dr1_is_genuine_dr = True
                            return False, f"Pattern Invalid: D1 supply evaporated (delta:{d1_delta}, buy:{d1_buy_pct:.0%} @ {row_data['price']:.2f}, vol:{d1_total})", matched_prices
                        break
            # Re-validate L row — should not be buy-dominant in current candle
            if self.bear_state_light_price is not None:
                for row_data in rows_below:
                    if row_data['price'] == self.bear_state_light_price:
                        l_total = row_data['buy'] + row_data['sell']
                        if l_total > 0 and row_data['buy'] > row_data['sell']:
                            l_buy_pct = row_data['buy'] / l_total
                            if l_buy_pct > L_MAX_SELL_DOMINANCE:
                                self.bear_state_lowest_dr1 = None
                                self.bear_state_has_light = False
                                self.bear_state_light_price = None
                                self.bear_state_dr1_is_genuine_dr = True
                                return False, f"Pattern Invalid: L row buy-dominant (buy:{l_buy_pct:.0%} @ {row_data['price']:.2f})", matched_prices
                        break
            return True, "DR→L→DR ✓ (Clean)", matched_prices
        elif rejection_reason:
            return False, f"Pattern Invalid: {rejection_reason}", matched_prices
        elif self.bear_state_has_light:
            return False, "Waiting for DR2", matched_prices
        elif self.bear_state_lowest_dr1 is not None:
            return False, "Waiting for L", matched_prices
        else:
            return False, "Waiting for DR1", matched_prices

    def render_candle(self, candle, prev_candle=None):
        self.stats['total'] += 1
        try:
            dt_utc = datetime.fromisoformat(candle.date.replace('Z', '+00:00'))
            dt_ist = dt_utc + IST_OFFSET
            dt_ist_norm = dt_ist.replace(second=0, microsecond=0)
            time_str = dt_ist.strftime('%H:%M:%S')
            time_key = dt_ist_norm.strftime('%Y-%m-%d %H:%M:%S')

            # 🔥 NIFTY TIME FILTER: ONLY 09:15 to 15:30
            current_time = dt_ist_norm.time()
            market_start = datetime.strptime("09:15", "%H:%M").time()
            market_end = datetime.strptime("15:30", "%H:%M").time()
            if not (market_start <= current_time <= market_end): return
        except Exception as e:
            print(f"⚠️ render_candle time parse skipped: {e}")
            return

        if dt_ist.date() != self.target_ist_date:
            self.stats['skipped_date'] += 1
            return

        aggregated_data = {}
        if not hasattr(candle, 'footprint'):
            self.stats['skipped_empty'] += 1
            return

        for row in candle.footprint:
            bucket_price = self.get_bucket(row.level)
            bucket_key = f"{bucket_price:.2f}"
            if bucket_key not in aggregated_data:
                aggregated_data[bucket_key] = {'buy': 0, 'sell': 0, 'price': bucket_price}
            aggregated_data[bucket_key]['buy'] += row.buy.volume * VOLUME_MULTIPLIER
            aggregated_data[bucket_key]['sell'] += row.sell.volume * VOLUME_MULTIPLIER
        if not aggregated_data:
            self.stats['skipped_empty'] += 1
            return

        row_prices = [d['price'] for d in aggregated_data.values()]
        if not row_prices: return

        fp_max = max(row_prices)
        fp_min = min(row_prices)
        complete_rows = []
        poc_vol = 0
        poc_price_key = ""
        max_delta_in_candle = 0
        total_vol_candle = 0
        total_delta_candle = 0

        current_price = fp_max
        while current_price >= fp_min - 0.01:
            key = f"{current_price:.2f}"
            if key in aggregated_data: complete_rows.append(aggregated_data[key])
            else: complete_rows.append({'buy': 0, 'sell': 0, 'price': current_price})
            current_price -= STEP_SIZE

        for row in complete_rows:
            total_vol_candle += (row['buy'] + row['sell'])
            row_delta = abs(row['buy'] - row['sell'])
            total_delta_candle += (row['buy'] - row['sell'])
            if row_delta > max_delta_in_candle: max_delta_in_candle = row_delta
            if (row['buy'] + row['sell']) > poc_vol:
                poc_vol = (row['buy'] + row['sell'])
                poc_price_key = f"{row['price']:.2f}"

        ohlc_open = ohlc_high = ohlc_low = ohlc_close = 0
        if time_key in ohlc_data:
            d = ohlc_data[time_key]
            ohlc_open, ohlc_high, ohlc_low, ohlc_close = d['o'], d['h'], d['l'], d['c']
        else:
            # INTERNAL fallback: use footprint price extremes
            # complete_rows sorted HIGH→LOW, so [0]=highest, [-1]=lowest
            first_row_price = complete_rows[0]['price'] if complete_rows else fp_max
            last_row_price = complete_rows[-1]['price'] if complete_rows else fp_min
            ohlc_open = first_row_price
            ohlc_high = fp_max
            ohlc_low = fp_min
            ohlc_close = last_row_price

        self.volume_history.append(total_vol_candle)
        self.delta_history.append(total_delta_candle)
        self.ohlc_cache.append({'o': ohlc_open, 'h': ohlc_high, 'l': ohlc_low, 'c': ohlc_close})
        self.render_candle_count += 1  # 🔥 Monotonic counter for SIGNAL-CD / CASCADE timing

        # 🔥 V5.28: Update session VWAP
        typical_price = (ohlc_high + ohlc_low + ohlc_close) / 3.0
        self.session_cum_tp_vol += typical_price * total_vol_candle
        self.session_cum_vol += total_vol_candle
        self.session_vwap = self.session_cum_tp_vol / self.session_cum_vol if self.session_cum_vol > 0 else ohlc_close

        body_size = abs(ohlc_close - ohlc_open)
        spread = ohlc_high - ohlc_low

        atr = self.calculate_atr()
        rvol_zscore, rvol_ratio = self.get_rvol_zscore(total_vol_candle)
        efficiency = self.get_efficiency_multiplier(body_size, total_vol_candle, atr)
        is_churn = self.is_churn_candle(rvol_zscore, body_size, spread)

        dynamic_trap_strength = total_vol_candle * MIN_TRAP_PCT
        dynamic_drive_strength = total_vol_candle * MIN_DRIVE_PCT

        # 🔥 GoCharting "default" colorMatrix algorithm (reverse-engineered from app.js Da function)
        # bid_ask view with colorMatrix="default": p() returns null, fallback logic applies.
        # GoCharting Da() bid_ask fallback:
        #   GREEN (buy > sell): A = Ma(|minBuy - maxSell|, 0, |delta|) → intensity = |delta| / |minBuy - maxSell|
        #   RED   (sell >= buy): E = Ma(|maxBuy - minSell|, 0, |delta|) → intensity = |delta| / |maxBuy - minSell|
        #   where minBuy, maxBuy, minSell, maxSell are candle-level min/max across all data rows.
        # Per-channel slopes (derived from GoCharting extracted color endpoints):
        # GREEN: r = max(0, 255-255*i), g = max(0, 255-74*i), b = max(0, 255-255*i)
        # RED:   r = 255-11*i,          g = max(0, 255-255*i), b = max(0, 255-230*i)
        # Tag = luminance from resulting RGB
        # Threshold tuned to match GoCharting visual intensity:
        DARK_LU_THRESHOLD = 125

        # Compute candle-level min/max buy/sell (only data rows, skip zero-fill rows)
        data_rows = [r for r in complete_rows if r['buy'] > 0 or r['sell'] > 0]
        if not data_rows:
            data_rows = complete_rows  # fallback
        candle_max_buy = max(r['buy'] for r in data_rows)
        candle_max_sell = max(r['sell'] for r in data_rows)
        green_denom = candle_max_sell
        red_denom = candle_max_buy
        # 🔥 V5.85 DISPLAY-ONLY denominator: GoCharting normalizes each candle by its
        # single max |delta| (same scale for green & red) -> only the biggest imbalance
        # cell goes black, others scale proportionally. Not used for tagging/signals.
        disp_denom = max((abs(r['buy'] - r['sell']) for r in data_rows), default=0)

        row_tags = [''] * len(complete_rows)
        row_colors = [None] * len(complete_rows)  # Store (r, g, b, lu) per row
        for i, row in enumerate(complete_rows):
            delta = row['buy'] - row['sell']
            abs_delta = abs(delta)
            if row['buy'] > row['sell']:
                denom = green_denom
            else:
                denom = red_denom
            intensity = abs_delta / denom if denom > 0 else 0
            intensity = min(intensity, 1.0)

            if delta >= 0:
                rr = int(143 - 125 * intensity)
                rg = int(175 - 5 * intensity)
                rb = int(142 - 129 * intensity)
            else:
                rr = int(211 + 28 * intensity)
                rg = max(0, int(124 - 105 * intensity))
                rb = max(0, int(133 - 92 * intensity))

            lu = 0.299 * rr + 0.587 * rg + 0.114 * rb

            # 🔥 V5.85 DISPLAY-ONLY color: GoCharting-accurate "white -> hue -> black" ramp.
            # Does NOT affect lu/tags/signals — purely what the terminal background shows.
            #   low intensity  -> near white (faint tint)
            #   mid intensity  -> saturated green / red
            #   high intensity -> black (matches GoCharting's darkest cells, e.g. 12K x 0)
            disp_intensity = min(abs_delta / disp_denom, 1.0) if disp_denom > 0 else 0
            if delta >= 0:
                # GREEN hue: hold G longest, drop R & B twice as fast
                drr = max(0, int(255 - 510 * disp_intensity))
                drg = max(0, int(255 - 255 * disp_intensity))
                drb = max(0, int(255 - 510 * disp_intensity))
            else:
                # RED hue: hold R longest, drop G & B twice as fast
                drr = max(0, int(255 - 255 * disp_intensity))
                drg = max(0, int(255 - 510 * disp_intensity))
                drb = max(0, int(255 - 510 * disp_intensity))
            disp_lu = 0.299 * drr + 0.587 * drg + 0.114 * drb
            row_colors[i] = (drr, drg, drb, disp_lu)

            # Tagging: purely luminance-based (color intensity) — uses V5.84 lu, not display
            if lu <= DARK_LU_THRESHOLD and delta < 0:
                row_tags[i] = 'DR'
            elif lu <= DARK_LU_THRESHOLD and delta > 0:
                row_tags[i] = 'DG'
            else:
                row_tags[i] = 'L'

        trap_status_msg = ""
        if self.active_trap_price is not None:
            self.trap_age += 1
            if ohlc_close < self.active_trap_price:
                # 🔥 V5.23: Trap recovery — don't kill immediately, allow recovery window
                if self.trap_broken_age == 0:
                    # First break candle
                    self.trap_broken_age = 1
                    self.trap_break_low = ohlc_low
                else:
                    self.trap_broken_age += 1
                    self.trap_break_low = min(self.trap_break_low, ohlc_low)

                if self.trap_broken_age > MAX_RECOVERY_CANDLES:
                    # Too long below — kill trap
                    trap_status_msg = f"{C['WARN']}TRAP DEAD (no recovery){C['RESET']}"
                    self.active_trap_price = None
                    self.trap_age = 0
                    self.trap_broken_age = 0
                    self.trap_break_low = None
                    self.trap_recovered = False
                    self.state_highest_dg1 = None
                    self.state_has_light = False
                    self.state_light_price = None
                    self.state_dg1_is_genuine_dg = True
                    self.historical_dr_between = set()
                    self.historical_dr_first_recorded_age = None
                    self.absorption_zones = {}
                    self.floor_confirmed = False  # 🔥 V5.50: Reset floor on trap death
                    self.floor_last_active_age = None
                    self.floor_retry_used = False  # 🔥 V5.51: Reset retry on trap death
                else:
                    trap_status_msg = f"{C['WARN']}TRAP BROKEN{C['RESET']} (recovery {self.trap_broken_age}/{MAX_RECOVERY_CANDLES})"
            else:
                # Price is above trap
                if self.trap_broken_age > 0:
                    # 🔥 V5.23: Recovery! Shift trap to break low for wider D1-L-D2 scan
                    old_trap = self.active_trap_price
                    self.active_trap_price = self.trap_break_low
                    self.trap_age = 1  # Fresh start after recovery
                    self.trap_broken_age = 0
                    self.trap_break_low = None
                    self.trap_recovered = True  # Break+recover = absorption proof
                    # Clear pattern state — fresh scan from new (lower) trap reference
                    self.state_highest_dg1 = None
                    self.state_has_light = False
                    self.state_light_price = None
                    self.state_dg1_is_genuine_dg = True
                    self.historical_dr_between = set()
                    self.historical_dr_first_recorded_age = None
                    trap_status_msg = f"{C['WARN']}TRAP RECOVERED{C['RESET']} ({old_trap:.2f} -> {self.active_trap_price:.2f})"
                else:
                    # Normal active trap
                    # 🔥 V5.26c: Intra-candle trap test — candle opens below trap but closes above
                    # Open below = session started weak at trap level; close above = V-recovery
                    # (Just wick-dip is noise; open-below requires genuine test of the level)
                    if ohlc_open < self.active_trap_price:
                        self.trap_recovered = True  # Intra-candle V-recovery = absorption proof

                    # 🔥 V5.21: Dynamic trap persistence - strong traps get extended life
                    effective_max_age = MAX_TRAP_AGE
                    trap_delta = getattr(self, 'active_trap_delta', 0)
                    if trap_delta > dynamic_trap_strength * STRONG_TRAP_MULT:
                        effective_max_age = MAX_TRAP_AGE_STRONG

                    if self.trap_age > effective_max_age:
                        trap_status_msg = f"{C['WARN']}TRAP EXPIRED (age {self.trap_age}){C['RESET']}"
                        self.active_trap_price = None
                        self.trap_age = 0
                        self.trap_recovered = False
                        self.state_highest_dg1 = None
                        self.state_has_light = False
                        self.state_light_price = None
                        self.state_dg1_is_genuine_dg = True
                        self.historical_dr_between = set()
                        self.historical_dr_first_recorded_age = None
                        self.absorption_zones = {}
                        self.floor_confirmed = False  # 🔥 V5.50: Reset floor on trap expiry
                        self.floor_last_active_age = None
                        self.floor_retry_used = False  # 🔥 V5.51: Reset retry on trap expiry
                    else:
                        tested_tag = ", tested" if self.trap_recovered else ""
                        trap_status_msg = f"{C['WARN']}TRAP ACTIVE{C['RESET']} ({self.active_trap_price:.2f}, age:{self.trap_age}{tested_tag})"

        body_bottom = min(ohlc_open, ohlc_close)
        new_trap_idx = -1
        debug_trap_logs = []

        # 🔥 V5.25: Trap scan ceiling depends on candle type
        # Bearish candle (close < open): scan lower body too — DR blocks in lower body
        #   of bearish candles represent genuine seller exhaustion / trapped selling
        # Bullish candle (close >= open): wick only — DR in body of bullish candle is noise
        if ohlc_close < ohlc_open:
            candle_mid = (fp_max + fp_min) / 2
            trap_scan_ceiling = max(body_bottom, candle_mid)
        else:
            trap_scan_ceiling = body_bottom

        start_idx = len(complete_rows) - 1
        cluster_delta = 0
        found_dr_in_wick = False
        for i in range(start_idx, -1, -1):
            block_price = complete_rows[i]['price']
            if block_price >= trap_scan_ceiling:
                break
            current_delta = complete_rows[i]['buy'] - complete_rows[i]['sell']
            if current_delta < 0 and row_tags[i] == 'DR':
                cluster_delta += abs(current_delta)
                found_dr_in_wick = True
                if cluster_delta >= dynamic_trap_strength:
                    self.active_trap_price = block_price
                    self.active_trap_delta = cluster_delta
                    self.trap_age = 0
                    self.trap_broken_age = 0  # 🔥 V5.23: Reset recovery state on new trap
                    self.trap_break_low = None
                    self.trap_recovered = False
                    self.state_highest_dg1 = None
                    self.state_has_light = False
                    self.state_light_price = None
                    self.state_dg1_is_genuine_dg = True
                    self.historical_dr_between = set()
                    self.historical_dr_first_recorded_age = None
                    self.floor_confirmed = False  # 🔥 V5.50: Reset floor on new trap
                    self.floor_last_active_age = None
                    self.floor_retry_used = False  # 🔥 V5.51: Reset retry on new trap

                    # 🔥 V5.24: Track session waterfall
                    if self.session_lowest_trap is None or block_price < self.session_lowest_trap:
                        self.session_lowest_trap = block_price
                        self.last_new_low_candle_idx = self.render_candle_count

                    new_trap_idx = i
                    candles_ago = (self.render_candle_count - self.last_new_low_candle_idx) if self.last_new_low_candle_idx is not None else 999
                    cascade_tag = f" [newlow:{candles_ago}c ago]" if self.last_new_low_candle_idx is not None else ""
                    trap_status_msg = f"{C['WARN']}NEW TRAP{C['RESET']}{cascade_tag}"
                    break

        # 🔥 V5.25: Track bottom selling absorption (sellers hitting bottom but price holds)
        if self.active_trap_price is None:
            self.bottom_absorb_streak = 0
            self.bottom_absorb_cumul = 0
            self.floor_confirmed = False  # 🔥 V5.50: No trap = no floor
            self.floor_last_active_age = None
            self.floor_retry_used = False  # 🔥 V5.51: Reset retry when no trap
        elif new_trap_idx >= 0:
            self.bottom_absorb_streak = 0
            self.bottom_absorb_cumul = 0
            self.floor_confirmed = False  # 🔥 V5.50: New trap = reset floor
            self.floor_last_active_age = None
            self.floor_retry_used = False  # 🔥 V5.51: Reset retry on new trap
        else:
            # Active trap, no new trap — check for heavy selling at bottom rows
            bottom_n = min(3, len(complete_rows))
            bottom_rows_data = complete_rows[-bottom_n:]  # lowest prices (sorted high→low)
            bottom_sell = sum(r['sell'] for r in bottom_rows_data)
            if bottom_sell >= 3000:  # Significant selling at bottom
                self.bottom_absorb_streak += 1
                self.bottom_absorb_cumul += bottom_sell
            else:
                self.bottom_absorb_streak = 0
                self.bottom_absorb_cumul = 0
            if self.bottom_absorb_streak >= 2:
                self.floor_confirmed = True  # 🔥 V5.50: Sticky — persists until trap resets
                self.floor_last_active_age = self.trap_age  # 🔥 V5.50b: Track recency
                debug_trap_logs.append(
                    f"[FLOOR] Selling absorbed at bottom ({self.format_vol(self.bottom_absorb_cumul)} over {self.bottom_absorb_streak} candles)")

        alert_msg = None
        matched_prices = {}

        if self.active_trap_price is not None:
            target_trap = self.active_trap_price

            if new_trap_idx >= 0:
                # 🔥 V5.20: Skip pattern check on the candle where trap just formed
                debug_trap_logs.append(f"[PATTERN] New trap - scanning next candle")
            else:
                is_bullish = ohlc_close >= ohlc_open
                has_pattern, pattern_status, matched_prices = self.check_layered_drive_pattern(
                    row_tags, complete_rows, target_trap, is_bullish, total_delta_candle, rvol_ratio)
                debug_trap_logs.append(f"[PATTERN] {pattern_status}")

                # 🔥 V5.50 Item 61: FLOOR-CONFIRMED SINGLE DG PATTERN (Bull Only)
                # When FLOOR absorption confirms defense at trap (virtual D1), a single
                # genuine DG breakout + L above = sufficient (DG becomes D2 for downstream)
                # V5.50b: trap_age >= MAX_TRAP_AGE (always base, not strong) + floor recency
                # V5.50c: Bypasses RVOL-GATE (floor activity validates low D2-candle RVOL)
                # Floor absorption IS the evidence strong-trap extension was searching for
                # 🔥 V5.66: VOLUME-ACCELERATED FLOOR OVERRIDE — if cumulative absorption > 3x
                # average candle volume, the trap is confirmed immediately regardless of age.
                # V-bottoms reverse so fast that the 5-candle age wait misses the entire move.
                _floor_eff_max = MAX_TRAP_AGE
                _floor_recent = (self.floor_last_active_age is not None
                                 and self.trap_age - self.floor_last_active_age <= 1)
                _avg_session_vol = sum(self.volume_history) / len(self.volume_history) if self.volume_history else 1
                _massive_floor_absorb = self.bottom_absorb_cumul > _avg_session_vol * 3
                is_floor_dg_override = False
                if (not has_pattern and self.floor_confirmed
                        and _floor_recent
                        and (self.trap_age >= _floor_eff_max or _massive_floor_absorb)
                        and self.state_highest_dg1 is not None
                        and self.state_dg1_is_genuine_dg
                        and self.state_has_light
                        and total_delta_candle > 0
                        and is_bullish):
                    is_floor_dg_override = True
                    has_pattern = True
                    matched_prices['DG2'] = matched_prices['DG1']
                    pattern_status = "FLOOR→L→DG ✓ (Absorbed)"
                    _floor_age_tag = f", EARLY: volume {self.format_vol(self.bottom_absorb_cumul)} > 3x avg {self.format_vol(_avg_session_vol)}" if _massive_floor_absorb else ""
                    debug_trap_logs.append(
                        f"[FLOOR-DG] ✓ Floor-confirmed single DG override "
                        f"(DG={matched_prices['DG1']:.2f}, floor_cumul={self.format_vol(self.bottom_absorb_cumul)}, age:{self.trap_age}{_floor_age_tag})")

                if has_pattern:
                    # ===== 2B REVERSAL CRITERIA =====
                    # 0. DROP: Must have significant price drop from swing high (hard blocker)
                    drop_passed, drop_status, drop_atr_mult = self.is_valid_reversal_context(target_trap)
                    debug_trap_logs.append(f"[DROP] {drop_status}")

                    # 1. SELLING PRESSURE: Quality grade (A/C), NOT a blocker
                    exhaust_passed, exhaust_status = self.is_delta_exhausted()
                    debug_trap_logs.append(f"[SELLING] {exhaust_status}")

                    # 2. ABSORPTION AT SUPPORT: Trap near swing low (hard blocker)
                    prox_passed, prox_status = self.check_trap_proximity(target_trap)
                    debug_trap_logs.append(f"[SUPPORT] {prox_status}")

                    # 3. PATTERN HEIGHT: Grade-based height limits
                    #    Grade A (selling exhausted OR recovered trap): up to 2.5x ATR
                    #    Grade C (no selling): up to max(1.0x ATR, 30pts) - tight setups only
                    height_passed = True
                    chase_passed = True  # 🔥 V5.30
                    # 🔥 V5.23: Recovered traps get grade A height (break+recover = absorption proof)
                    effective_exhaust = exhaust_passed or self.trap_recovered
                    atr = self.calculate_atr()

                    # 🔥 V5.38: Compute D2 close position early for confirmed risk/chase bypass
                    d2_close_raw = (ohlc_close - ohlc_low) / spread if spread > 0 else None
                    strong_confirmation = (effective_exhaust and d2_close_raw is not None
                                           and d2_close_raw >= EXTREME_D2_CLOSE_PCT)

                    # 🔥 V5.44/V5.71: VWAP Confirmed Long — requires buffer AND delta aggression
                    vwap_confirmed_long = False
                    vwap_buffer = (atr * VWAP_RECLAIM_BUFFER_ATR) if atr else 5.0
                    
                    if (self.session_vwap is not None and 'DG2' in matched_prices and
                        d2_close_raw is not None and d2_close_raw >= VWAP_CONFIRMED_MIN_D2_CLOSE and
                        total_delta_candle >= VWAP_RECLAIM_MIN_DELTA and  # 🔥 V5.71: Aggression check
                        matched_prices['DG2'] >= (self.session_vwap + vwap_buffer)): # 🔥 V5.71: Buffer check
                        vwap_confirmed_long = True

                    # 🔥 V5.71: Early defaults for variables used by climax veto before full computation
                    is_golden = False
                    is_extreme_conviction = False

                    # 🔥 V5.72: MICRO-RVOL — 3-candle momentum detection (computed early for climax veto + RVOL gate)
                    _micro_vols_early = list(self.volume_history)[-4:-1] if len(self.volume_history) >= 4 else [1]
                    _micro_avg_early = sum(_micro_vols_early) / len(_micro_vols_early) if _micro_vols_early else 1
                    micro_rvol = total_vol_candle / _micro_avg_early if _micro_avg_early > 0 else 1.0
                    local_rvol = self.get_local_rvol(total_vol_candle)  # 🔥 V5.72: computed early for effective_rvol
                    effective_rvol = max(local_rvol, micro_rvol)  # 🔥 V5.72: Use highest for momentum scaling

                    # 🔥 V5.40: CLIMAX OVERRIDE — climax = strongest exhaustion, bypasses RVOL gate
                    is_climax = exhaust_passed and "Climax" in exhaust_status

                    # 🔥 V5.69/V5.71: CLIMAX VETO — block longs on buying-climax D2 candles
                    buying_climax_veto = False
                    if len(self.delta_history) >= 3:
                        _recent_deltas = list(self.delta_history)[-min(EXHAUSTION_LOOKBACK, len(self.delta_history)):]
                        _avg_abs_d = sum(abs(d) for d in _recent_deltas) / len(_recent_deltas) if _recent_deltas else 1
                        
                        if (total_delta_candle > _avg_abs_d * CLIMAX_VETO_MIN_DELTA_MULT
                                and micro_rvol >= CLIMAX_VETO_MIN_LOCAL_RVOL):
                            buying_climax_veto = True
                            debug_trap_logs.append(f"[CLIMAX-VETO] ✗ Buying climax on D2 (delta:{int(total_delta_candle)} > {_avg_abs_d*CLIMAX_VETO_MIN_DELTA_MULT:.0f}, Micro-RVOL:{micro_rvol:.2f}x) = blocked")
                        else:
                            debug_trap_logs.append(f"[CLIMAX-VETO] ✓ No buying climax (delta:{int(total_delta_candle)}, threshold:{_avg_abs_d*CLIMAX_VETO_MIN_DELTA_MULT:.0f})")

                    # 🔥 V5.72: INITIATION OVERRIDE — VWAP reclaims bypass climax veto
                    if buying_climax_veto and vwap_confirmed_long:
                        buying_climax_veto = False
                        debug_trap_logs.append(f"[CLIMAX-VETO] ⚠ Bypassed: VWAP Reclaimed (Initiation momentum, not exhaustion)")

                    # 🔥 V5.49: EXTREME DELTA SIGNAL — extreme buying with exhaustion bypasses HEIGHT/CHASE/RVOL-HIGH
                    extreme_delta_vol_pct = abs(total_delta_candle) / total_vol_candle if total_vol_candle > 0 else 0
                    is_extreme_delta_signal = (
                        self.trap_recovered and total_delta_candle > 0 and
                        rvol_ratio >= EXTREME_PAIR_MIN_RVOL and
                        extreme_delta_vol_pct >= EXTREME_PAIR_MIN_DELTA_PCT and
                        effective_exhaust
                    )

                    # 🔥 V5.61: GOLDEN HEIGHT BYPASS — absorb computed early so golden can gate HEIGHT
                    absorb_passed, absorb_status, absorb_score = self.is_valid_absorption_context(
                        complete_rows, row_tags, target_trap,
                        ohlc_open, ohlc_close, ohlc_low, ohlc_high,
                        total_vol_candle, total_delta_candle
                    )
                    is_golden, golden_status = self.is_golden_entry(
                        target_trap, rvol_ratio, effective_exhaust, absorb_score)

                    # 🔥 V5.53: Trend-day context — strong directional structure relaxes RVOL gate
                    # Requires REAL exhaust + VWAP reclaimed (D2 above VWAP = institutional support)
                    is_trend_day = False
                    _range_ratio = 0  # 🔥 V5.56: default for wide-range check
                    if atr and atr > 0 and len(self.ohlc_cache) >= 8:
                        _lookback = min(CONSOL_LOOKBACK, len(self.ohlc_cache))
                        _recent = list(self.ohlc_cache)[-_lookback:]
                        _range_ratio = (max(c['h'] for c in _recent) - min(c['l'] for c in _recent)) / atr
                        is_trend_day = _range_ratio >= TREND_EXHAUST_MIN_RANGE_ATR
                    vwap_reclaimed = (self.session_vwap is not None and 'DG2' in matched_prices
                                      and matched_prices['DG2'] >= self.session_vwap)
                    trend_day_override = exhaust_passed and is_trend_day and vwap_reclaimed  # 🔥 V5.53: triple gate

                    # 🔥 V5.39: Safety gates — strong_confirmation alone is too broad (60% WR)
                    # Override requires RVOL gate to pass (V5.53: trend day + real exhaust relaxes RVOL)
                    override_allowed = strong_confirmation
                    if override_allowed:
                        _override_rvol_min = TREND_OVERRIDE_MIN_RVOL if trend_day_override else OVERRIDE_MIN_RVOL
                        if rvol_ratio < _override_rvol_min and not is_climax:  # 🔥 V5.40: climax bypasses RVOL
                            override_allowed = False

                    if atr and atr > 0 and 'DG2' in matched_prices:
                        # 🔥 V5.30: Use actual entry point (candle close) for risk, not just D2
                        # Entry is at candle close; stop is below trap; real risk = max(D2, close) - trap
                        entry_price = max(matched_prices['DG2'], ohlc_close)
                        pattern_height = entry_price - target_trap
                        d2_pattern_height = matched_prices['DG2'] - target_trap  # for display
                        # 🔥 V5.55: Close inflation correction — on trend days, use D2 for height filter
                        # When close overshoots D2, the inflation is momentum confirmation
                        # D2 is the demand level; pattern quality measured from D2 to trap
                        # Gates: min inflation 20pts + exclude extreme-delta/conviction tiers
                        close_inflated = entry_price > matched_prices['DG2']
                        inflation_pts = (entry_price - matched_prices['DG2']) if close_inflated else 0
                        # 🔥 V5.42/V5.72: Extreme conviction — volatile session override (uses effective_rvol)
                        is_extreme_conviction = effective_exhaust and effective_rvol >= EXTREME_CONVICTION_MIN_RVOL
                        # 🔥 V5.72: VWAP breakouts use D2 height regardless of inflation points
                        can_inflate_correct = (close_inflated and not is_extreme_delta_signal and
                                              ((trend_day_override and inflation_pts >= TREND_INFLATE_MIN_PTS) or
                                               (vwap_confirmed_long and strong_confirmation)))
                        height_for_filter = d2_pattern_height if can_inflate_correct else pattern_height
                        # 🔥 V5.22: Stricter height for grade C (no selling)
                        # 🔥 V5.32: Dynamic risk bands — sweet spot 16-35pts from backtest
                        # 🔥 V5.41: Tiered HEIGHT extension: Climax(+12.5) > Momentum(+7.5) > Standard(+2.5)
                        if is_climax:
                            height_ext = CLIMAX_HEIGHT_EXTENSION
                        elif override_allowed and effective_rvol >= MOMENTUM_OVERRIDE_MIN_RVOL:  # 🔥 V5.72: uses effective_rvol
                            height_ext = MOMENTUM_HEIGHT_EXTENSION
                        elif override_allowed:
                            height_ext = RISK_EXTENSION_CONFIRMED
                        else:
                            height_ext = 0
                        # 🔥 V5.75: VWAP confirmed long extends risk_cap (mirrors max_height extension)
                        vwap_risk_ext = VWAP_CONFLUENCE_HEIGHT_EXTENSION if vwap_confirmed_long else 0
                        risk_cap = MAX_RISK_ABSOLUTE + height_ext + vwap_risk_ext
                        # 🔥 V5.56: Wide-range exhaust HEIGHT extension
                        # On wide-range days (≥2.5x ATR), confirmed exhaustion justifies more height tolerance
                        if effective_exhaust and _range_ratio >= WIDE_RANGE_MIN_RATIO:
                            risk_cap += WIDE_RANGE_EXHAUST_HEIGHT_EXT
                        if effective_exhaust:
                            if is_extreme_delta_signal:
                                max_height = min(atr * EXTREME_DELTA_HEIGHT_ATR_MULT, EXTREME_DELTA_HEIGHT_CAP)  # 🔥 V5.49: extreme delta gets wider cap
                            elif is_golden:
                                max_height = min(atr * EXTREME_DELTA_HEIGHT_ATR_MULT, GOLDEN_HEIGHT_CAP)  # 🔥 V5.61: GOLDEN session extreme gets wider HEIGHT cap
                            elif is_extreme_conviction:
                                max_height = min(atr * EXTREME_CONVICTION_ATR_MULT, EXTREME_CONVICTION_MAX_RISK)  # 🔥 V5.45: hard cap
                            else:
                                max_height = min(atr * 2.0, risk_cap)  # tightened from 2.5x
                        else:
                            # 🔥 V5.44: VWAP reclaim extends grade C cap (+7.5pts)
                            vwap_ht_ext = VWAP_CONFLUENCE_HEIGHT_EXTENSION if vwap_confirmed_long else 0
                            max_height = min(atr * 1.0 + vwap_ht_ext, 35 + vwap_ht_ext)  # tightened from max(1.5x, 40)
                        # 🔥 V5.63: GOLDEN at session extreme — tight snap-backs are valid, skip ATR scaling
                        min_height = MIN_PATTERN_HEIGHT_PTS if is_golden else max(atr * 0.5, MIN_PATTERN_HEIGHT_PTS)  # raised from 0.25x
                        grade_label = "A" if effective_exhaust else "C"
                        # 🔥 V5.55: height_for_filter may use D2-based height on trend days
                        inflate_tag = f" [TREND-D2: D2-ht={d2_pattern_height:.1f}, close-ht={pattern_height:.1f}]" if (height_for_filter != pattern_height) else ""
                        if pattern_height < min_height:
                            height_passed = False
                            debug_trap_logs.append(f"[HEIGHT] Too small ({pattern_height:.1f} < {min_height:.1f} pts)")
                        elif height_for_filter > max_height:
                            # 🔥 V5.66: FLOOR-ANCHORED HEIGHT — on V-bottom with floor absorption, measure
                            # risk from D2 to L (intraday support formed during the explosive candle),
                            # not D2 to trap (full V-bottom depth). L is the actual risk level market created.
                            _l_anchor_bypass = False
                            if (effective_exhaust and self.floor_confirmed
                                    and 'L' in matched_prices and 'DG2' in matched_prices):
                                l_anchor_height = max(matched_prices['DG2'], ohlc_close) - matched_prices['L']
                                if l_anchor_height > 0 and l_anchor_height <= max_height:
                                    _l_anchor_bypass = True
                                    debug_trap_logs.append(
                                        f"[HEIGHT] ✓ L-anchor grade {grade_label} ({l_anchor_height:.1f} ≤ {max_height:.1f}) "
                                        f"overrides full height {height_for_filter:.1f} [FLOOR-ABSORBED]")
                            if not _l_anchor_bypass:
                                height_passed = False
                                debug_trap_logs.append(f"[HEIGHT] Too far for grade {grade_label} ({height_for_filter:.1f} > {max_height:.1f}){inflate_tag}")
                        elif not is_extreme_conviction and not is_extreme_delta_signal and not is_golden and height_for_filter > risk_cap:  # 🔥 V5.42/V5.61: extreme conviction/delta/golden bypasses abs cap
                            height_passed = False
                            debug_trap_logs.append(f"[HEIGHT] Abs risk cap ({height_for_filter:.1f} > {risk_cap}){inflate_tag}")
                        else:
                            ec_tag = f" [EXTREME-DELTA: RVOL {rvol_ratio:.1f}x, Δ/vol {extreme_delta_vol_pct:.0%}, cap={max_height:.1f}]" if is_extreme_delta_signal else (f" [GOLDEN-HEIGHT: cap={max_height:.1f}]" if is_golden else (f" [EXTREME: RVOL {rvol_ratio:.1f}x, cap={max_height:.1f}]" if is_extreme_conviction else ""))
                            debug_trap_logs.append(f"[HEIGHT] OK grade {grade_label} ({height_for_filter:.1f} in [{min_height:.1f}, {max_height:.1f}]){ec_tag}{inflate_tag}")

                        # 🔥 V5.32: DYNAMIC CHASE FILTER — adaptive body ratio based on pattern size vs ATR
                        # Small patterns (< 1x ATR) naturally have larger D2 bodies → relaxed limit
                        d2_body = abs(ohlc_close - ohlc_open)
                        if pattern_height > 0:
                            body_ratio = d2_body / pattern_height
                            if atr and atr > 0:
                                dynamic_chase_limit = max(0.55, min(0.75, 1.0 - pattern_height / (4 * atr)))  # 🔥 V5.33: cap 0.85→0.75
                            else:
                                dynamic_chase_limit = D2_MAX_BODY_RATIO_FALLBACK
                            if body_ratio > dynamic_chase_limit:
                                if override_allowed:  # 🔥 V5.39: bypass chase with safety gates (was V5.38 strong_confirmation)
                                    debug_trap_logs.append(f"[CHASE] ⚠ D2 body {d2_body:.1f}pts = {body_ratio:.0%} > limit {dynamic_chase_limit:.0%}, BYPASSED: exhaust + extreme D2 close ({d2_close_raw:.0%})")
                                elif vwap_confirmed_long:  # 🔥 V5.75: VWAP reclaim drive IS the signal
                                    debug_trap_logs.append(f"[CHASE] ⚠ D2 body {d2_body:.1f}pts = {body_ratio:.0%} > limit {dynamic_chase_limit:.0%}, BYPASSED: VWAP reclaim drive")
                                elif trend_day_override:  # 🔥 V5.55: trend-day close inflation bypass
                                    debug_trap_logs.append(f"[CHASE] ⚠ D2 body {d2_body:.1f}pts = {body_ratio:.0%} > limit {dynamic_chase_limit:.0%}, BYPASSED: trend-day override (exhaust + trend + VWAP)")
                                elif is_extreme_delta_signal:  # 🔥 V5.49: extreme delta bypass
                                    debug_trap_logs.append(f"[CHASE] ⚠ D2 body {d2_body:.1f}pts = {body_ratio:.0%} > limit {dynamic_chase_limit:.0%}, BYPASSED: extreme delta signal (RVOL {rvol_ratio:.1f}x, Δ/vol {extreme_delta_vol_pct:.0%})")
                                else:
                                    chase_passed = False
                                    debug_trap_logs.append(f"[CHASE] ✗ D2 body {d2_body:.1f}pts = {body_ratio:.0%} of pattern ({pattern_height:.1f}pts), limit {dynamic_chase_limit:.0%}")
                            else:
                                debug_trap_logs.append(f"[CHASE] ✓ D2 body {d2_body:.1f}pts = {body_ratio:.0%} of pattern ({pattern_height:.1f}pts), limit {dynamic_chase_limit:.0%}")

                    # 4. RANGE: Consolidation check (quality grade, not blocker)
                    is_consol, consol_status = self.is_consolidation()
                    debug_trap_logs.append(f"[RANGE] {consol_status}")

                    # 🔥 V5.24: Shallow pullback filter status
                    # 🔥 V5.29: Tested traps bypass cascade — if the low was revisited and held,
                    #   the waterfall is confirmed over (no need to wait full cooldown)
                    candles_since_new_low = (self.render_candle_count - self.last_new_low_candle_idx) if self.last_new_low_candle_idx is not None else 999
                    cascade_time_ok = candles_since_new_low >= CASCADE_COOLDOWN_CANDLES
                    cascade_tested_bypass = self.trap_recovered  # tested = price revisited & held
                    # 🔥 V5.76: floor_absorbed bypass — mirrors bear_ceiling_absorbed (V5.64)
                    # New low was institutional buying building the floor — not a momentum cascade
                    floor_absorbed = (self.bottom_absorb_streak >= 2 and absorb_score >= 2) or self.floor_confirmed
                    cascade_gate = cascade_time_ok or cascade_tested_bypass or floor_absorbed
                    cascade_mark = '\u2713' if cascade_gate else '\u2717'
                    debug_trap_logs.append(f"[RVOL] ({rvol_ratio:.2f}x)")
                    if cascade_tested_bypass and not cascade_time_ok:
                        debug_trap_logs.append(f"[CASCADE] {cascade_mark} (last new low {candles_since_new_low}c ago, cooldown:{CASCADE_COOLDOWN_CANDLES}, BYPASSED: trap tested)")
                    elif floor_absorbed and not cascade_time_ok:
                        debug_trap_logs.append(f"[CASCADE] {cascade_mark} (last new low {candles_since_new_low}c ago, cooldown:{CASCADE_COOLDOWN_CANDLES}, BYPASSED: floor absorbed (streak:{self.bottom_absorb_streak}, absorb:{absorb_score}))")
                    else:
                        debug_trap_logs.append(f"[CASCADE] {cascade_mark} (last new low {candles_since_new_low}c ago, cooldown:{CASCADE_COOLDOWN_CANDLES})")

                    # 🔥 V5.27: Signal cooldown — block rapid-fire signals at same/higher levels
                    # 🔥 V5.59: Higher-low bypass — trap ↑ = bullish continuation (higher-low pattern), bypass cooldown
                    signal_cooldown_passed = True
                    if self.last_signal_candle_idx is not None:
                        candles_since_signal = self.render_candle_count - self.last_signal_candle_idx
                        trap_is_lower = target_trap < self.last_signal_trap_price
                        trap_is_higher = target_trap > self.last_signal_trap_price  # 🔥 V5.59
                        if candles_since_signal < SIGNAL_COOLDOWN_CANDLES and not trap_is_lower and not trap_is_higher:
                            signal_cooldown_passed = False
                        cooldown_mark = '✓' if signal_cooldown_passed else '✗'
                        trap_dir = '↓' if trap_is_lower else ('↑' if trap_is_higher else '=')
                        cd_detail = f"({candles_since_signal}c since last signal, trap {trap_dir})"
                        if not signal_cooldown_passed:
                            debug_trap_logs.append(f"[SIGNAL-CD] {cooldown_mark} {cd_detail}")
                        elif candles_since_signal < SIGNAL_COOLDOWN_CANDLES:
                            debug_trap_logs.append(f"[SIGNAL-CD] {cooldown_mark} {cd_detail}, BYPASSED: {'lower-trap' if trap_is_lower else 'higher-low'}")
                        else:
                            debug_trap_logs.append(f"[SIGNAL-CD] {cooldown_mark} {cd_detail}")

                    # 🔥 V5.28: VWAP resistance check — D2 must have room above before hitting VWAP
                    vwap_passed = True
                    if self.session_vwap is not None and atr and atr > 0 and 'DG2' in matched_prices:
                        d2_price = matched_prices['DG2']
                        vwap_gap = self.session_vwap - d2_price  # positive = VWAP is above D2
                        min_clearance = atr * VWAP_MIN_CLEARANCE_ATR
                        if vwap_gap > 0 and vwap_gap < min_clearance:
                            # D2 is just below VWAP — immediate overhead resistance, no room
                            vwap_passed = False
                            debug_trap_logs.append(f"[VWAP] ✗ Resistance ({vwap_gap:.1f}pts < {min_clearance:.1f}pts clearance, VWAP:{self.session_vwap:.2f})")
                        elif vwap_gap <= -(atr * VWAP_RECLAIM_BUFFER_ATR):
                            # 🔥 V5.69: D2 is clearly above VWAP by buffer — genuinely reclaimed
                            debug_trap_logs.append(f"[VWAP] ✓ Reclaimed (D2:{d2_price:.2f} ≥ VWAP:{self.session_vwap:.2f} + {atr*VWAP_RECLAIM_BUFFER_ATR:.1f}pts buffer)")
                        elif vwap_gap <= 0:
                            # 🔥 V5.69: D2 is above VWAP but within the buffer band — fakeout zone
                            vwap_passed = False
                            debug_trap_logs.append(f"[VWAP] ✗ VWAP fakeout (D2:{d2_price:.2f} only {-vwap_gap:.1f}pts above VWAP:{self.session_vwap:.2f}, need {atr*VWAP_RECLAIM_BUFFER_ATR:.1f}pts)")
                        else:
                            # 🔥 V5.43: D2 is below VWAP — VWAP caps upside room for longs
                            # Check if room to VWAP >= pattern risk (R:R must be ≥ 1:1)
                            if pattern_height > 0 and vwap_gap < pattern_height:
                                vwap_passed = False
                                debug_trap_logs.append(f"[VWAP] ✗ Room capped ({vwap_gap:.1f}pts room < {pattern_height:.1f}pts risk, VWAP:{self.session_vwap:.2f})")
                            else:
                                debug_trap_logs.append(f"[VWAP] ✓ Clearance ({vwap_gap:.1f}pts ≥ {min_clearance:.1f}pts, VWAP:{self.session_vwap:.2f})")

                    # 🔥 V5.31: ABSORPTION VALIDATION (computed early for V5.61 GOLDEN HEIGHT bypass)
                    debug_trap_logs.append(f"[ABSORB] {absorb_status}")

                    # 🔥 V5.36: Chase relaxation removed (recovered 0 signals in V5.35 backtest — dead code)

                    # 🔥 V5.31: D2 CANDLE CONFIRMATION — close position & delta direction
                    d2_close_passed = True
                    d2_delta_passed = True
                    if spread > 0:
                        close_pct = (ohlc_close - ohlc_low) / spread
                        if close_pct < D2_MIN_CLOSE_PCT:
                            d2_close_passed = False
                            debug_trap_logs.append(f"[D2-CLOSE] ✗ Close at {close_pct:.0%} (need ≥{D2_MIN_CLOSE_PCT:.0%})")
                        else:
                            debug_trap_logs.append(f"[D2-CLOSE] ✓ Close at {close_pct:.0%}")
                    if REQUIRE_D2_DELTA_CONFIRM and total_delta_candle < 0:
                        d2_delta_passed = False
                        debug_trap_logs.append(f"[D2-DELTA] ✗ Negative delta ({int(total_delta_candle)})")
                    else:
                        debug_trap_logs.append(f"[D2-DELTA] ✓ ({int(total_delta_candle)})")

                    # 🔥 V5.32/V5.72: LOCAL RVOL GATE — recent-window RVOL adapts to time-of-day
                    # local_rvol and effective_rvol already computed early (after micro_rvol)
                    rvol_gate_passed = effective_rvol >= MIN_SIGNAL_RVOL
                    # 🔥 V5.40: Climax bypasses RVOL gate (climax candle volume validates context)
                    # 🔥 V5.44: VWAP confirmed long bypasses RVOL gate (reclaim proves commitment)
                    if not rvol_gate_passed and is_climax:
                        rvol_gate_passed = True
                        debug_trap_logs.append(f"[RVOL-GATE] ⚠ local:{local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x, BYPASSED: Climax (session:{rvol_ratio:.2f}x)")
                    elif not rvol_gate_passed and vwap_confirmed_long:  # 🔥 V5.75: VWAP reclaim bypasses RVOL-GATE (delta+close already prove commitment)
                        rvol_gate_passed = True
                        debug_trap_logs.append(f"[RVOL-GATE] ⚠ local:{local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x, BYPASSED: VWAP confirmed long (session:{rvol_ratio:.2f}x)")
                    elif not rvol_gate_passed and is_floor_dg_override:
                        rvol_gate_passed = True
                        debug_trap_logs.append(f"[RVOL-GATE] ⚠ local:{local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x, BYPASSED: Floor-confirmed DG (session:{rvol_ratio:.2f}x)")
                    elif not rvol_gate_passed and override_allowed:  # 🔥 V5.53: override = exhaust+extreme D2+RVOL/trend
                        rvol_gate_passed = True
                        debug_trap_logs.append(f"[RVOL-GATE] ⚠ local:{local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x, BYPASSED: Override (session:{rvol_ratio:.2f}x)")
                    elif not rvol_gate_passed:
                        debug_trap_logs.append(f"[RVOL-GATE] ✗ local:{local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x (session:{rvol_ratio:.2f}x)")
                    else:
                        debug_trap_logs.append(f"[RVOL-GATE] ✓ local:{local_rvol:.2f}x (session:{rvol_ratio:.2f}x)")

                    # 🔥 V5.37: RVOL DEAD ZONE — 1.00-1.30 = 36% WR noise zone
                    # Bypass: risk ≥ 25 OR absorb_score ≥ 5 (institutional confirmation)
                    rvol_dead_zone_blocked = False
                    risk_val = pattern_height if ('DG2' in matched_prices and atr and atr > 0) else 0
                    if RVOL_DEAD_ZONE_LOW <= local_rvol < RVOL_DEAD_ZONE_HIGH:
                        if risk_val >= RVOL_DEAD_ZONE_RISK_BYPASS:
                            debug_trap_logs.append(f"[RVOL-ZONE] ⚠ Dead zone RVOL but risk {risk_val:.1f} ≥ {RVOL_DEAD_ZONE_RISK_BYPASS} → passing")
                        elif absorb_score >= RVOL_DEAD_ZONE_ABSORB_BYPASS:
                            debug_trap_logs.append(f"[RVOL-ZONE] ⚠ Dead zone RVOL but absorb {absorb_score} ≥ {RVOL_DEAD_ZONE_ABSORB_BYPASS} → passing")
                        else:
                            rvol_dead_zone_blocked = True
                            debug_trap_logs.append(f"[RVOL-ZONE] ✗ Dead zone ({local_rvol:.2f}x in [{RVOL_DEAD_ZONE_LOW}-{RVOL_DEAD_ZONE_HIGH}), risk:{risk_val:.1f}<{RVOL_DEAD_ZONE_RISK_BYPASS}, absorb:{absorb_score}<{RVOL_DEAD_ZONE_ABSORB_BYPASS})")
                    else:
                        debug_trap_logs.append(f"[RVOL-ZONE] ✓ Outside dead zone ({local_rvol:.2f}x)")

                    # 🔥 V5.37: RVOL HIGH CEILING — session RVOL ≥ 2.0 = 0% WR (chaotic market)
                    rvol_high_blocked = rvol_ratio >= RVOL_HIGH_CEILING
                    if rvol_high_blocked:
                        debug_trap_logs.append(f"[RVOL-HIGH] ✗ Session RVOL {rvol_ratio:.2f}x ≥ {RVOL_HIGH_CEILING} (extreme volatility)")
                    else:
                        debug_trap_logs.append(f"[RVOL-HIGH] ✓ Session RVOL {rvol_ratio:.2f}x")

                    # 🔥 V5.31: GOLDEN ENTRY DETECTION (computed earlier for V5.61 HEIGHT bypass)
                    debug_trap_logs.append(f"[GOLDEN] {golden_status}")

                    # 🔥 V5.62: TREND-EXHAUST — tightened, only GOLDEN bypasses on trend days
                    # Climax alone no longer sufficient — GOLDEN required to counter any trend-day exhaust
                    trend_exhaust_blocked = False
                    if (not is_golden and
                        self.last_range_ratio is not None and
                        self.last_range_ratio >= TREND_EXHAUST_MIN_RANGE_ATR and
                        exhaust_passed and (
                            is_climax or (
                                self.last_exhaust_recovery_pct is not None and
                                self.last_exhaust_recovery_pct <= TREND_EXHAUST_MAX_RECOVERY_PCT
                            )
                        )):
                        trend_exhaust_blocked = True
                        _te_type = "Climax" if is_climax else f"Low recovery ({self.last_exhaust_recovery_pct*100:.0f}%)"
                        debug_trap_logs.append(
                            f"[TREND-EXHAUST] ✗ {_te_type} "
                            f"+ trend day ({self.last_range_ratio:.1f}x ATR) = premature reversal (GOLDEN required)")
                    else:
                        te_reason = []
                        if not exhaust_passed:
                            te_reason.append("no-exhaust")
                        elif is_climax:
                            te_reason.append("climax")
                        if self.last_exhaust_recovery_pct is not None and self.last_exhaust_recovery_pct > TREND_EXHAUST_MAX_RECOVERY_PCT:
                            te_reason.append(f"recovery-ok({self.last_exhaust_recovery_pct*100:.0f}%)")
                        if self.last_range_ratio is not None and self.last_range_ratio < TREND_EXHAUST_MIN_RANGE_ATR:
                            te_reason.append(f"narrow({self.last_range_ratio:.1f}x)")
                        if rvol_ratio >= TREND_EXHAUST_MAX_RVOL:
                            te_reason.append(f"RVOL-ok({rvol_ratio:.2f}x)")
                        if is_golden:
                            te_reason.append("golden")
                        debug_trap_logs.append(f"[TREND-EXHAUST] ✓ Passed ({', '.join(te_reason)})")

                    # 🔥 V5.31: GRADE C + CONSOLIDATION BLOCK
                    # 🔥 V5.44: VWAP confirmed long bypasses grade C block (VWAP reclaim = support)
                    grade_c_consol_blocked = False
                    if BLOCK_GRADE_C_CONSOL and not effective_exhaust and is_consol and not is_golden and not vwap_confirmed_long:
                        grade_c_consol_blocked = True
                        debug_trap_logs.append(f"[GRADE-C] ✗ No exhaust + consolidation = blocked")
                    elif BLOCK_GRADE_C_CONSOL and not effective_exhaust and is_consol and vwap_confirmed_long:
                        debug_trap_logs.append(f"[GRADE-C] ⚠ No exhaust + consolidation, BYPASSED: VWAP confirmed long")

                    # 🔥 V5.36: AFTERNOON GATE — Grade B at 14:xx blocked UNLESS absorb_passed
                    # V5.35: hard block all Grade B at 14:xx (too aggressive, lost Dec 9 WIN +25.0 with absorb=3)
                    # V5.36: allow Grade B at 14:xx if absorption confirms institutional activity
                    afternoon_blocked = False
                    if dt_ist.hour >= 14 and not effective_exhaust and not is_golden:
                        afternoon_blocked = True
                        debug_trap_logs.append(f"[TIME] ✗ Afternoon ({dt_ist.hour}:xx) + no exhaustion = blocked")
                    elif dt_ist.hour >= 14 and not is_golden and (not effective_exhaust or is_consol):
                        # Grade B at 14:xx: needs absorption to pass
                        if absorb_passed:
                            debug_trap_logs.append(f"[TIME] ⚠ Afternoon Grade B ({dt_ist.hour}:xx) — absorb_passed, allowing")
                        elif effective_exhaust and is_consol:
                            afternoon_blocked = True
                            debug_trap_logs.append(f"[TIME] ✗ Afternoon Grade B ({dt_ist.hour}:xx) + exhaust+consol + no absorb = blocked")
                        elif not effective_exhaust and not is_consol:
                            afternoon_blocked = True
                            debug_trap_logs.append(f"[TIME] ✗ Afternoon Grade B ({dt_ist.hour}:xx) + no exhaust+trending + no absorb = blocked")
                    elif dt_ist.hour >= 14:
                        debug_trap_logs.append(f"[TIME] ⚠ Afternoon ({dt_ist.hour}:xx) — Grade A/A+ quality, passing")

                    # 🔥 V5.81: MIDDAY BULL GATE — 13:xx Grade B needs absorb≥3
                    midday_bull_blocked = False
                    if (dt_ist.hour == MIDDAY_BULL_HOUR and not is_golden
                            and (not effective_exhaust or is_consol)  # Grade B criteria
                            and absorb_score < LOW_RVOL_QUAL_MIN_ABSORB):
                        midday_bull_blocked = True
                        debug_trap_logs.append(f"[MIDDAY] ✗ 13:xx Grade B + absorb:{absorb_score}<{LOW_RVOL_QUAL_MIN_ABSORB} = blocked")

                    # 🔥 V5.81: LONG HIGH-RISK GATE — risk>35 needs golden/absorb≥4/RVOL sweet spot
                    long_risk_blocked = False
                    if (height_passed and pattern_height > LONG_HIGH_RISK_THRESHOLD
                            and not is_golden and not is_extreme_conviction
                            and absorb_score < LONG_HIGH_RISK_MIN_ABSORB
                            and not (LONG_HIGH_RISK_RVOL_SWEET_LO <= rvol_ratio <= LONG_HIGH_RISK_RVOL_SWEET_HI)):
                        long_risk_blocked = True
                        debug_trap_logs.append(
                            f"[LONG-RISK] ✗ Risk {pattern_height:.1f}>{LONG_HIGH_RISK_THRESHOLD} "
                            f"absorb:{absorb_score}<{LONG_HIGH_RISK_MIN_ABSORB} RVOL:{rvol_ratio:.2f}x not in [{LONG_HIGH_RISK_RVOL_SWEET_LO}-{LONG_HIGH_RISK_RVOL_SWEET_HI}]")

                    # 🔥 V5.81: LOW-RVOL QUALITY GATE — RVOL 0.30-0.65 needs absorb≥3 + Grade A/A+
                    low_rvol_qual_blocked = False
                    if (LOW_RVOL_QUAL_LO <= rvol_ratio < LOW_RVOL_QUAL_HI
                            and not is_golden
                            and (absorb_score < LOW_RVOL_QUAL_MIN_ABSORB or not effective_exhaust)):
                        low_rvol_qual_blocked = True
                        debug_trap_logs.append(
                            f"[LOW-RVOL-QUAL] ✗ RVOL {rvol_ratio:.2f}x in [{LOW_RVOL_QUAL_LO}-{LOW_RVOL_QUAL_HI}] "
                            f"absorb:{absorb_score}<{LOW_RVOL_QUAL_MIN_ABSORB} or no exhaust")

                    # 🔥 V5.79: PEAK BLOCK — LONG signal on candle making new session high = buying at peak
                    # The 2B reversal should fire during recovery from trap, not at the peak of a rally.
                    peak_blocked = False
                    if (self.bear_session_highest_ceiling is not None and
                        ohlc_high >= self.bear_session_highest_ceiling and
                        not is_golden):
                        peak_blocked = True
                        debug_trap_logs.append(
                            f"[PEAK] ✗ Candle high {ohlc_high:.2f} ≥ session high {self.bear_session_highest_ceiling:.2f} "
                            f"= buying at peak (trap age:{self.trap_age})")
                    elif self.bear_session_highest_ceiling is not None:
                        debug_trap_logs.append(
                            f"[PEAK] ✓ Below session high ({ohlc_high:.2f} < {self.bear_session_highest_ceiling:.2f})")

                    # 🔥 V5.31: Hard blockers — Golden entries bypass secondary filters
                    signal_blocked_reason = None
                    # 🔥 V5.54: WARMUP guard — no signals before ATR established (prevents premature fires)
                    if atr is None:
                        signal_blocked_reason = "WARMUP"
                    # 🔥 V5.62: LATE — hard cutoff 14:45; GOLDEN extends to 15:10 (session extreme at EOD)
                    elif (dt_ist.hour > SIGNAL_CUTOFF_HOUR or (dt_ist.hour == SIGNAL_CUTOFF_HOUR and dt_ist.minute > SIGNAL_CUTOFF_MINUTE)) and not is_golden:
                        signal_blocked_reason = "LATE"
                    elif (dt_ist.hour > GOLDEN_SIGNAL_CUTOFF_HOUR or (dt_ist.hour == GOLDEN_SIGNAL_CUTOFF_HOUR and dt_ist.minute > GOLDEN_SIGNAL_CUTOFF_MINUTE)):
                        signal_blocked_reason = "LATE"
                    elif not cascade_gate and not (is_golden and candles_since_new_low >= GOLDEN_CASCADE_MIN_AGE):
                        signal_blocked_reason = "WATERFALL"  # 🔥 V5.44: Golden bypass with minimum distance from new session low
                    elif not signal_cooldown_passed and not is_golden:
                        signal_blocked_reason = "COOLDOWN"
                    elif not drop_passed and not vwap_confirmed_long:  # 🔥 V5.75: VWAP reclaim bypasses DROP
                        signal_blocked_reason = "DROP"
                    elif not prox_passed:
                        signal_blocked_reason = "SUPPORT"
                    elif trend_exhaust_blocked:
                        signal_blocked_reason = "TREND-EXHAUST"  # 🔥 V5.52: premature countertrend on trend day
                    elif not height_passed:
                        signal_blocked_reason = "HEIGHT"
                    elif not chase_passed and not is_golden:
                        signal_blocked_reason = "CHASE"
                    elif not vwap_passed and not is_golden:
                        signal_blocked_reason = "VWAP"
                    elif grade_c_consol_blocked:
                        signal_blocked_reason = "GRADE-C"
                    elif not d2_close_passed and not is_golden:
                        signal_blocked_reason = "D2-CLOSE"
                    elif not d2_delta_passed and not is_golden:
                        signal_blocked_reason = "D2-DELTA"
                    elif not rvol_gate_passed and not is_golden:
                        signal_blocked_reason = "LOW-RVOL"
                    # 🔥 V5.35: RVOL dead zone — block noise signals in 1.00-1.30 RVOL band
                    elif rvol_dead_zone_blocked and not is_golden:
                        signal_blocked_reason = "RVOL-ZONE"
                    # 🔥 V5.47: HIGH-RVOL golden bypass (forensic: +245.3 CF PnL, symmetric with bear)
                    # 🔥 V5.49: Extreme delta signal also bypasses (extreme buying proves direction)
                    elif rvol_high_blocked and not is_golden and not is_extreme_delta_signal:
                        signal_blocked_reason = "HIGH-RVOL"
                    elif afternoon_blocked:
                        signal_blocked_reason = "AFTERNOON"
                    # 🔥 V5.81: MIDDAY bull gate — 13:xx Grade B needs absorb≥3
                    elif midday_bull_blocked:
                        signal_blocked_reason = "MIDDAY-BULL"
                    # 🔥 V5.81: LONG risk gate — risk>35 needs conviction
                    elif long_risk_blocked:
                        signal_blocked_reason = "LONG-RISK"
                    # 🔥 V5.81: LOW-RVOL quality gate — RVOL 0.30-0.65 needs quality
                    elif low_rvol_qual_blocked:
                        signal_blocked_reason = "LOW-RVOL-QUAL"
                    # 🔥 V5.69: CLIMAX VETO — block longs on buying-climax D2 candles
                    # 🔥 V5.80: Golden/extreme-conviction bypass (was dead code — is_golden computed after veto)
                    elif buying_climax_veto and not is_golden and not is_extreme_conviction:
                        signal_blocked_reason = "CLIMAX-VETO"
                    # 🔥 V5.79: PEAK — don't buy at new session highs (chasing, not reversing)
                    elif peak_blocked:
                        signal_blocked_reason = "PEAK"
                    # 🔥 V5.34: Absorption soft-blocker — no exhaustion AND no absorption = weak evidence
                    # 🔥 V5.75: vwap_confirmed_long bypasses (VWAP reclaim + delta + close = institutional proof)
                    elif not absorb_passed and not effective_exhaust and not is_golden and not vwap_confirmed_long:
                        signal_blocked_reason = "WEAK-EVIDENCE"

                    # 🧪 CORE-ONLY: override the entire gate chain — fire on the pure
                    # concept only. STRUCTURE is mandatory; require at least ONE of
                    # EXHAUSTION / ABSORPTION (so we capture more than the gated path).
                    # Ingredient flags are tagged on the alert for outcome segmentation.
                    if CORE_ONLY:
                        if atr is None:
                            signal_blocked_reason = "WARMUP"
                        elif not drop_passed:            # STRUCTURE: trap below swing high
                            signal_blocked_reason = "NO-STRUCT"
                        elif not (effective_exhaust or absorb_passed):  # EXHAUSTION or ABSORPTION
                            signal_blocked_reason = "NO-EVIDENCE"
                        else:
                            signal_blocked_reason = None

                    if signal_blocked_reason is None:
                        # 🔥 V5.33: Reverted — absorb requirement demoted good signals to B, hurting WR
                        if is_golden:
                            quality_grade = "A+"
                        elif effective_exhaust and not is_consol:
                            quality_grade = "A"
                        elif effective_exhaust or not is_consol:
                            quality_grade = "B"
                        else:
                            quality_grade = "C"
                        # 🔥 V5.27: Track signal for cooldown
                        self.last_signal_candle_idx = self.render_candle_count
                        self.last_signal_trap_price = target_trap
                        alert_msg = f"🚀 <b>2B REVERSAL:</b> Trap @ {target_trap:.2f} [⭐ {quality_grade}]"
                        if CORE_ONLY:
                            alert_msg += f" [CORE exh:{1 if effective_exhaust else 0} abs:{1 if absorb_passed else 0}]"
                        alert_msg += f"\n📊 RVOL: {rvol_ratio:.1f}x (Z:{rvol_zscore:.1f}) | EFF: {efficiency:.2f}"
                        alert_msg += f"\n🔥 TRAP → DG→L→DG"
                        send_telegram(alert_msg)

                    # 🔥 V5.51: Floor Retry — if blocked by candle-quality issue but floor confirms trap, preserve for one retry
                    # Only retry for candle-quality blocks that may fix on the next candle
                    FLOOR_RETRY_ALLOWED_BLOCKS = {'D2-CLOSE', 'LOW-RVOL', 'CHASE', 'D2-DELTA', 'WEAK-EVIDENCE'}
                    if (signal_blocked_reason is not None and
                        signal_blocked_reason in FLOOR_RETRY_ALLOWED_BLOCKS and
                        self.floor_confirmed and not self.floor_retry_used):
                        # Floor absorption proves trap is valid — give ONE more pattern chance
                        self.floor_retry_used = True
                        # Reset only pattern state (not the trap itself)
                        self.state_highest_dg1 = None
                        self.state_has_light = False
                        self.state_light_price = None
                        self.state_dg1_is_genuine_dg = True
                        self.historical_dr_between = set()
                        self.historical_dr_first_recorded_age = None
                        debug_trap_logs.append(f"[FLOOR-RETRY] ✓ Blocked by {signal_blocked_reason} but floor confirmed — preserving trap for retry")
                    else:
                        # 🔥 V5.22: Full reset — signal fired, or no floor retry available
                        self.active_trap_price = None
                        self.trap_age = 0
                        self.trap_broken_age = 0
                        self.trap_break_low = None
                        self.trap_recovered = False
                        self.state_highest_dg1 = None
                        self.state_has_light = False
                        self.state_light_price = None
                        self.state_dg1_is_genuine_dg = True
                        self.historical_dr_between = set()
                        self.historical_dr_first_recorded_age = None
                        self.floor_confirmed = False  # 🔥 V5.50: Reset floor on signal complete
                        self.floor_last_active_age = None
                        self.floor_retry_used = False  # 🔥 V5.51: Reset retry on full reset

        # =====================================================================
        # 🔻 BEARISH SIDE — Ceiling detection, lifecycle, and signal evaluation
        # Mirror of the bullish trap system above
        # =====================================================================
        bear_status_msg = ""
        bear_alert_msg = None
        bear_matched_prices = {}

        # --- Ceiling lifecycle management ---
        if self.bear_active_ceiling_price is not None:
            self.bear_ceiling_age += 1
            if ohlc_close > self.bear_active_ceiling_price:
                # Price closed above ceiling — broken
                if self.bear_ceiling_broken_age == 0:
                    self.bear_ceiling_broken_age = 1
                    self.bear_ceiling_break_high = ohlc_high
                else:
                    self.bear_ceiling_broken_age += 1
                    self.bear_ceiling_break_high = max(self.bear_ceiling_break_high, ohlc_high)

                if self.bear_ceiling_broken_age > MAX_RECOVERY_CANDLES:
                    bear_status_msg = f"{C['WARN']}CEIL DEAD (no recovery){C['RESET']}"
                    self.bear_active_ceiling_price = None
                    self.bear_ceiling_age = 0
                    self.bear_ceiling_broken_age = 0
                    self.bear_ceiling_break_high = None
                    self.bear_ceiling_recovered = False
                    self.bear_state_lowest_dr1 = None
                    self.bear_state_has_light = False
                    self.bear_state_light_price = None
                    self.bear_state_dr1_is_genuine_dr = True
                    self.bear_historical_dg_between = set()
                    self.absorption_zones_bear = {}
                    self.ceiling_confirmed = False  # 🔥 V5.67: Ceiling dead = reset absorption memory
                else:
                    bear_status_msg = f"{C['WARN']}CEIL BROKEN{C['RESET']} (recovery {self.bear_ceiling_broken_age}/{MAX_RECOVERY_CANDLES})"
            else:
                # Price is below ceiling
                if self.bear_ceiling_broken_age > 0:
                    # Recovery! Shift ceiling to break high
                    old_ceil = self.bear_active_ceiling_price
                    self.bear_active_ceiling_price = self.bear_ceiling_break_high
                    self.bear_ceiling_age = 1
                    self.bear_ceiling_broken_age = 0
                    self.bear_ceiling_break_high = None
                    self.bear_ceiling_recovered = True
                    self.bear_state_lowest_dr1 = None
                    self.bear_state_has_light = False
                    self.bear_state_light_price = None
                    self.bear_state_dr1_is_genuine_dr = True
                    self.bear_historical_dg_between = set()
                    bear_status_msg = f"{C['WARN']}CEIL RECOVERED{C['RESET']} ({old_ceil:.2f} -> {self.bear_active_ceiling_price:.2f})"
                else:
                    # Normal active ceiling
                    if ohlc_open > self.bear_active_ceiling_price:
                        self.bear_ceiling_recovered = True  # Intra-candle test

                    effective_max_age = MAX_TRAP_AGE
                    ceil_delta = getattr(self, 'bear_active_ceiling_delta', 0)
                    if ceil_delta > dynamic_trap_strength * STRONG_TRAP_MULT:
                        effective_max_age = MAX_TRAP_AGE_STRONG

                    if self.bear_ceiling_age > effective_max_age:
                        bear_status_msg = f"{C['WARN']}CEIL EXPIRED (age {self.bear_ceiling_age}){C['RESET']}"
                        self.bear_active_ceiling_price = None
                        self.bear_ceiling_age = 0
                        self.bear_ceiling_recovered = False
                        self.bear_state_lowest_dr1 = None
                        self.bear_state_has_light = False
                        self.bear_state_light_price = None
                        self.bear_state_dr1_is_genuine_dr = True
                        self.bear_historical_dg_between = set()
                        self.absorption_zones_bear = {}
                        self.ceiling_confirmed = False  # 🔥 V5.67: Ceiling expired = reset absorption memory
                    else:
                        tested_tag = ", tested" if self.bear_ceiling_recovered else ""
                        bear_status_msg = f"{C['WARN']}CEIL ACTIVE{C['RESET']} ({self.bear_active_ceiling_price:.2f}, age:{self.bear_ceiling_age}{tested_tag})"

        # --- Ceiling scan: DG clusters at TOP of candle (buyer exhaustion) ---
        body_top = max(ohlc_open, ohlc_close)
        new_ceil_idx = -1
        debug_bear_logs = []

        # Ceiling scan floor: for bullish candles scan upper wick only, for bearish scan upper body too
        if ohlc_close >= ohlc_open:
            ceil_scan_floor = body_top
        else:
            candle_mid = (fp_max + fp_min) / 2
            ceil_scan_floor = min(body_top, candle_mid)

        ceil_cluster_delta = 0
        for i in range(len(complete_rows)):
            block_price = complete_rows[i]['price']
            if block_price <= ceil_scan_floor:
                break
            current_delta = complete_rows[i]['buy'] - complete_rows[i]['sell']
            if current_delta > 0 and row_tags[i] == 'DG':
                ceil_cluster_delta += current_delta
                if ceil_cluster_delta >= dynamic_trap_strength:
                    self.bear_active_ceiling_price = block_price
                    self.bear_active_ceiling_delta = ceil_cluster_delta
                    self.bear_ceiling_age = 0
                    self.bear_ceiling_broken_age = 0
                    self.bear_ceiling_break_high = None
                    self.bear_ceiling_recovered = False
                    self.bear_state_lowest_dr1 = None
                    self.bear_state_has_light = False
                    self.bear_state_light_price = None
                    self.bear_state_dr1_is_genuine_dr = True
                    self.bear_historical_dg_between = set()
                    self.ceiling_confirmed = False  # 🔥 V5.67: New ceiling = reset absorption memory

                    # Track session rally (cascade for bears)
                    if self.bear_session_highest_ceiling is None or block_price > self.bear_session_highest_ceiling:
                        self.bear_session_highest_ceiling = block_price
                        self.bear_last_new_high_candle_idx = self.render_candle_count

                    new_ceil_idx = i
                    candles_ago = (self.render_candle_count - self.bear_last_new_high_candle_idx) if self.bear_last_new_high_candle_idx is not None else 999
                    cascade_tag = f" [newhigh:{candles_ago}c ago]" if self.bear_last_new_high_candle_idx is not None else ""
                    bear_status_msg = f"{C['WARN']}NEW CEIL{C['RESET']}{cascade_tag}"
                    break

        # --- Top buying absorption tracking ---
        if self.bear_active_ceiling_price is None:
            self.bear_top_absorb_streak = 0
            self.bear_top_absorb_cumul = 0
        elif new_ceil_idx >= 0:
            self.bear_top_absorb_streak = 0
            self.bear_top_absorb_cumul = 0
            self.ceiling_confirmed = False  # 🔥 V5.67: New ceiling = reset sticky absorption flag
        else:
            top_n = min(3, len(complete_rows))
            top_rows_data = complete_rows[:top_n]  # highest prices (sorted high→low)
            top_buy = sum(r['buy'] for r in top_rows_data)
            if top_buy >= 3000:
                self.bear_top_absorb_streak += 1
                self.bear_top_absorb_cumul += top_buy
            else:
                self.bear_top_absorb_streak = 0
                self.bear_top_absorb_cumul = 0
            if self.bear_top_absorb_streak >= 2:
                self.ceiling_confirmed = True  # 🔥 V5.67: Sticky — persists until ceiling resets
                debug_bear_logs.append(
                    f"[CEILING] Buying absorbed at top ({self.format_vol(self.bear_top_absorb_cumul)} over {self.bear_top_absorb_streak} candles)")

        # --- Bearish pattern evaluation ---
        if self.bear_active_ceiling_price is not None:
            target_ceiling = self.bear_active_ceiling_price

            if new_ceil_idx >= 0:
                debug_bear_logs.append(f"[BEAR-PATTERN] New ceiling - scanning next candle")
            else:
                is_bearish_candle = ohlc_close <= ohlc_open
                bear_has_pattern, bear_pattern_status, bear_matched_prices = self.check_bear_drive_pattern(
                    row_tags, complete_rows, target_ceiling, is_bearish_candle)
                debug_bear_logs.append(f"[BEAR-PATTERN] {bear_pattern_status}")

                if bear_has_pattern:
                    # ===== BEARISH 2B REVERSAL CRITERIA =====
                    bear_rally_passed, bear_rally_status, bear_rally_atr_mult = self.is_valid_bear_reversal_context(target_ceiling)
                    debug_bear_logs.append(f"[RALLY] {bear_rally_status}")

                    bear_exhaust_passed, bear_exhaust_status = self.is_buying_exhausted()
                    debug_bear_logs.append(f"[BUYING] {bear_exhaust_status}")

                    bear_prox_passed, bear_prox_status = self.check_ceiling_proximity(target_ceiling)
                    debug_bear_logs.append(f"[RESISTANCE] {bear_prox_status}")

                    # HEIGHT check (mirror: ceiling - D2 = pattern height)
                    bear_height_passed = True
                    bear_chase_passed = True
                    bear_effective_exhaust = bear_exhaust_passed or self.bear_ceiling_recovered
                    bear_atr = self.calculate_atr()
                    bear_ceiling_absorbed = False  # 🔥 V5.64: default; set after absorb_score known
                    # 🔥 V5.65 BUG FIX: Initialize absorb vars before the ATR+DR2 block to prevent
                    # UnboundLocalError when bear pattern exists but no DR2 or no ATR
                    bear_absorb_passed = False
                    bear_absorb_status = "No ATR or no DR2"
                    bear_absorb_score = 0
                    # 🔥 V5.67 BUG FIX: Initialize golden vars before ATR+DR2 block.
                    # ceiling_confirmed can now reach post-ATR log lines (line ~3430) even when
                    # bear_atr or DR2 are absent — these defaults prevent UnboundLocalError.
                    bear_is_golden = False
                    bear_golden_status = "No ATR or no DR2"
                    bear_is_extreme_conviction = False
                    bear_override_allowed = False  # 🔥 V5.77: Initialize before ATR+DR2 block (computed inside)

                    # 🔥 V5.72: MICRO-RVOL — 3-candle momentum detection (bear mirror, computed early for climax veto + RVOL gate)
                    _micro_vols_b_early = list(self.volume_history)[-4:-1] if len(self.volume_history) >= 4 else [1]
                    _micro_avg_b_early = sum(_micro_vols_b_early) / len(_micro_vols_b_early) if _micro_vols_b_early else 1
                    bear_micro_rvol = total_vol_candle / _micro_avg_b_early if _micro_avg_b_early > 0 else 1.0
                    bear_local_rvol = self.get_local_rvol(total_vol_candle)  # 🔥 V5.72: computed early for bear_effective_rvol
                    bear_effective_rvol = max(bear_local_rvol, bear_micro_rvol)  # 🔥 V5.72: Use highest for momentum scaling

                    # 🔥 V5.38: Compute D2 close position early for confirmed risk/chase bypass (bearish)
                    bear_d2_close_raw = (ohlc_close - ohlc_low) / spread if spread > 0 else None
                    bear_strong_confirmation = (bear_effective_exhaust and bear_d2_close_raw is not None
                                                and bear_d2_close_raw <= (1.0 - EXTREME_D2_CLOSE_PCT))

                    # 🔥 V5.40: CLIMAX OVERRIDE — climax = strongest exhaustion, bypasses RVOL gate
                    bear_is_climax = bear_exhaust_passed and "Climax" in bear_exhaust_status

                    # 🔥 V5.69/V5.71: CLIMAX VETO — block shorts on selling-climax D2 candles
                    selling_climax_veto = False
                    if len(self.delta_history) >= 3:
                        _recent_deltas_b = list(self.delta_history)[-min(EXHAUSTION_LOOKBACK, len(self.delta_history)):]
                        _avg_abs_d_b = sum(abs(d) for d in _recent_deltas_b) / len(_recent_deltas_b) if _recent_deltas_b else 1
                        
                        if (total_delta_candle < -_avg_abs_d_b * CLIMAX_VETO_MIN_DELTA_MULT
                                and bear_micro_rvol >= CLIMAX_VETO_MIN_LOCAL_RVOL):
                            selling_climax_veto = True
                            debug_bear_logs.append(f"[CLIMAX-VETO] ✗ Selling climax on D2 (delta:{int(total_delta_candle)} < -{_avg_abs_d_b*CLIMAX_VETO_MIN_DELTA_MULT:.0f}, Micro-RVOL:{bear_micro_rvol:.2f}x) = blocked")
                        else:
                            debug_bear_logs.append(f"[CLIMAX-VETO] ✓ No selling climax (delta:{int(total_delta_candle)}, threshold:-{_avg_abs_d_b*CLIMAX_VETO_MIN_DELTA_MULT:.0f})")

                    # 🔥 V5.53/V5.71: Trend-day context 
                    bear_is_trend_day = False
                    _range_ratio = 0  
                    if bear_atr and bear_atr > 0 and len(self.ohlc_cache) >= 8:
                        _lookback = min(CONSOL_LOOKBACK, len(self.ohlc_cache))
                        _recent = list(self.ohlc_cache)[-_lookback:]
                        _range_ratio = (max(c['h'] for c in _recent) - min(c['l'] for c in _recent)) / bear_atr
                        bear_is_trend_day = _range_ratio >= TREND_EXHAUST_MIN_RANGE_ATR
                        
                    # 🔥 V5.71: Bear VWAP Broken requires buffer and negative delta aggression
                    bear_vwap_buffer = (bear_atr * VWAP_RECLAIM_BUFFER_ATR) if bear_atr else 5.0
                    bear_vwap_broken = (self.session_vwap is not None and 'DR2' in bear_matched_prices
                                        and total_delta_candle <= -VWAP_RECLAIM_MIN_DELTA
                                        and bear_matched_prices['DR2'] <= (self.session_vwap - bear_vwap_buffer))
                    bear_trend_day_override = bear_exhaust_passed and bear_is_trend_day and bear_vwap_broken

                    # 🔥 V5.72: INITIATION OVERRIDE — VWAP breakdowns bypass climax veto
                    if selling_climax_veto and bear_vwap_broken:
                        selling_climax_veto = False
                        debug_bear_logs.append(f"[CLIMAX-VETO] ⚠ Bypassed: VWAP Broken (Initiation momentum, not exhaustion)")

                    if bear_atr and bear_atr > 0 and 'DR2' in bear_matched_prices:
                        # 🔥 V5.74: bear_override_allowed computed BEFORE absorb (V5.72 baseline ordering)
                        bear_override_allowed = bear_strong_confirmation
                        if bear_override_allowed:
                            _override_rvol_min = TREND_OVERRIDE_MIN_RVOL if bear_trend_day_override else OVERRIDE_MIN_RVOL
                            if rvol_ratio < _override_rvol_min and not bear_is_climax:
                                bear_override_allowed = False

                        # 🔥 V5.61: GOLDEN HEIGHT BYPASS — absorb computed early so golden can gate HEIGHT
                        bear_absorb_passed, bear_absorb_status, bear_absorb_score = self.is_valid_absorption_context_bear(
                            complete_rows, row_tags, target_ceiling,
                            ohlc_open, ohlc_close, ohlc_low, ohlc_high,
                            total_vol_candle, total_delta_candle
                        )
                        bear_is_golden, bear_golden_status = self.is_golden_entry_bear(
                            target_ceiling, rvol_ratio, bear_effective_exhaust, bear_absorb_score)

                        bear_entry_price = min(bear_matched_prices['DR2'], ohlc_close)
                        bear_pattern_height = target_ceiling - bear_entry_price
                        # 🔥 V5.55: Close inflation correction — bear mirror
                        # Gates: min inflation 20pts + exclude extreme conviction tier
                        bear_d2_pattern_height = target_ceiling - bear_matched_prices['DR2']
                        bear_close_inflated = bear_entry_price < bear_matched_prices['DR2']
                        bear_inflation_pts = (bear_matched_prices['DR2'] - bear_entry_price) if bear_close_inflated else 0
                        # 🔥 V5.42/V5.72: Extreme conviction — volatile session override (uses bear_effective_rvol)
                        bear_is_extreme_conviction = bear_effective_exhaust and bear_effective_rvol >= EXTREME_CONVICTION_MIN_RVOL
                        # 🔥 V5.64: ceiling absorbed = institutional sellers confirmed (streak≥2, score≥4)
                        # 🔥 V5.65: Lower score threshold 4→2 — streak already proves multi-candle evidence;
                        #           signal candle score 2 means minimal ceiling-zone absorption detected, sufficient
                        # 🔥 V5.67: AMNESIA BUG FIX — also accept sticky ceiling_confirmed flag.
                        # Absorption happens at the ceiling candles (e.g. 10:30), not during the breakaway
                        # (e.g. 10:55). On fast breakout candles, top rows have thin volume → streak resets
                        # to 0 before pattern eval. ceiling_confirmed was set when streak hit ≥2 and
                        # persists until ceiling resets — mirrors bull-side floor_confirmed (V5.50).
                        bear_ceiling_absorbed = (self.bear_top_absorb_streak >= 2 and bear_absorb_score >= 2) or self.ceiling_confirmed
                        # 🔥 V5.72: VWAP breakdowns use D2 height regardless of inflation points
                        bear_can_inflate_correct = (bear_close_inflated and
                                                   ((bear_trend_day_override and bear_inflation_pts >= TREND_INFLATE_MIN_PTS) or
                                                    (bear_vwap_broken and bear_strong_confirmation)))
                        bear_height_for_filter = bear_d2_pattern_height if bear_can_inflate_correct else bear_pattern_height
                        # 🔥 V5.41: Tiered HEIGHT extension: Climax(+12.5) > Momentum(+7.5) > Standard(+2.5)
                        if bear_is_climax:
                            bear_height_ext = CLIMAX_HEIGHT_EXTENSION
                        elif bear_override_allowed and bear_effective_rvol >= MOMENTUM_OVERRIDE_MIN_RVOL:  # 🔥 V5.72: uses bear_effective_rvol
                            bear_height_ext = MOMENTUM_HEIGHT_EXTENSION
                        elif bear_override_allowed:
                            bear_height_ext = RISK_EXTENSION_CONFIRMED
                        else:
                            bear_height_ext = 0
                        # 🔥 V5.43: VWAP confluence — D2 below VWAP means VWAP is resistance (confirms short)
                        bear_vwap_confluence = False
                        if self.session_vwap is not None and bear_entry_price <= self.session_vwap:
                            bear_vwap_confluence = True
                            bear_height_ext += VWAP_CONFLUENCE_HEIGHT_EXTENSION
                        bear_risk_cap = MAX_RISK_ABSOLUTE + bear_height_ext
                        # 🔥 V5.56: Wide-range exhaust HEIGHT extension (bear mirror)
                        if bear_effective_exhaust and _range_ratio >= WIDE_RANGE_MIN_RATIO:
                            bear_risk_cap += WIDE_RANGE_EXHAUST_HEIGHT_EXT
                        if bear_effective_exhaust:
                            if bear_is_extreme_conviction:
                                bear_max_height = min(bear_atr * EXTREME_CONVICTION_ATR_MULT, EXTREME_CONVICTION_MAX_RISK)  # 🔥 V5.45: hard cap
                            elif bear_is_golden:
                                bear_max_height = min(bear_atr * EXTREME_DELTA_HEIGHT_ATR_MULT, GOLDEN_HEIGHT_CAP)  # 🔥 V5.61: GOLDEN session extreme gets wider HEIGHT cap
                            else:
                                bear_max_height = min(bear_atr * 2.0, bear_risk_cap)  # 🔥 V5.32: tightened
                        else:
                            bear_max_height = min(bear_atr * 1.0, 35)  # 🔥 V5.32: tightened
                        # 🔥 V5.65: Ceiling absorption confirmed — institutional sellers at top justify wider HEIGHT tolerance
                        # 🔥 V5.70: OR-LOGIC — institutional presence = multi-candle accumulation OR single violent absorption candle
                        if bear_ceiling_absorbed or (bear_absorb_score >= 3 and bear_effective_exhaust):
                            bear_max_height += CEILING_ABSORB_HEIGHT_EXT
                            bear_risk_cap += CEILING_ABSORB_HEIGHT_EXT
                        # 🔥 V5.66: NEAR-MISS HEIGHT GRACE MARGIN — Grade A + strong absorption (≥3) + within 10% of cap
                        # Institutionals grind slowly; 2-3pt miss on height cap is model rounding, not bad trade.
                        # Only triggers when close to cap — keeps regular trades under normal limits.
                        if (bear_effective_exhaust and bear_absorb_score >= 3
                                and bear_height_for_filter > bear_max_height
                                and bear_height_for_filter <= bear_max_height * 1.10):
                            bear_max_height += 3.0
                            bear_risk_cap += 3.0
                        # 🔥 V5.63: GOLDEN bear — tight snap-backs at session high are valid, skip ATR scaling
                        bear_min_height = MIN_PATTERN_HEIGHT_PTS if bear_is_golden else max(bear_atr * 0.5, MIN_PATTERN_HEIGHT_PTS)  # 🔥 V5.32: raised
                        bear_grade_label = "A" if bear_effective_exhaust else "C"
                        # 🔥 V5.55: bear_height_for_filter may use D2-based height on trend days
                        bear_inflate_tag = f" [TREND-D2: D2-ht={bear_d2_pattern_height:.1f}, close-ht={bear_pattern_height:.1f}]" if (bear_height_for_filter != bear_pattern_height) else ""
                        if bear_pattern_height < bear_min_height:
                            bear_height_passed = False
                            debug_bear_logs.append(f"[HEIGHT] Too small ({bear_pattern_height:.1f} < {bear_min_height:.1f} pts)")
                        elif bear_height_for_filter > bear_max_height:
                            bear_height_passed = False
                            debug_bear_logs.append(f"[HEIGHT] Too far for grade {bear_grade_label} ({bear_height_for_filter:.1f} > {bear_max_height:.1f}){bear_inflate_tag}")
                        elif not bear_is_extreme_conviction and not bear_is_golden and bear_height_for_filter > bear_risk_cap:  # 🔥 V5.42/V5.61: extreme conviction/golden bypasses abs cap
                            bear_height_passed = False
                            debug_bear_logs.append(f"[HEIGHT] Abs risk cap ({bear_height_for_filter:.1f} > {bear_risk_cap}){bear_inflate_tag}")
                        else:
                            ec_tag = f" [EXTREME: RVOL {rvol_ratio:.1f}x, cap={bear_max_height:.1f}]" if bear_is_extreme_conviction else (f" [GOLDEN-HEIGHT: cap={bear_max_height:.1f}]" if bear_is_golden else "")
                            debug_bear_logs.append(f"[HEIGHT] OK grade {bear_grade_label} ({bear_height_for_filter:.1f} in [{bear_min_height:.1f}, {bear_max_height:.1f}]){ec_tag}{bear_inflate_tag}")

                        # 🔥 V5.32: DYNAMIC CHASE filter (mirror)
                        d2_body = abs(ohlc_close - ohlc_open)
                        if bear_pattern_height > 0:
                            body_ratio = d2_body / bear_pattern_height
                            if bear_atr and bear_atr > 0:
                                dynamic_chase_limit = max(0.55, min(0.80, 1.0 - bear_pattern_height / (4 * bear_atr)))  # 🔥 V5.47: bear cap 0.75→0.80 (forensic: CHASE+5% = +292 CF PnL)
                            else:
                                dynamic_chase_limit = D2_MAX_BODY_RATIO_FALLBACK
                            if body_ratio > dynamic_chase_limit:
                                if bear_override_allowed:  # 🔥 V5.39: bypass chase with safety gates (was V5.38 bear_strong_confirmation)
                                    debug_bear_logs.append(f"[CHASE] ⚠ D2 body {d2_body:.1f}pts = {body_ratio:.0%} > limit {dynamic_chase_limit:.0%}, BYPASSED: exhaust + extreme D2 close ({bear_d2_close_raw:.0%})")
                                elif bear_trend_day_override:  # 🔥 V5.55: trend-day close inflation bypass (bear mirror)
                                    debug_bear_logs.append(f"[CHASE] ⚠ D2 body {d2_body:.1f}pts = {body_ratio:.0%} > limit {dynamic_chase_limit:.0%}, BYPASSED: trend-day override (exhaust + trend + VWAP)")
                                else:
                                    bear_chase_passed = False
                                    debug_bear_logs.append(f"[CHASE] ✗ D2 body {d2_body:.1f}pts = {body_ratio:.0%} of pattern ({bear_pattern_height:.1f}pts), limit {dynamic_chase_limit:.0%}")
                            else:
                                debug_bear_logs.append(f"[CHASE] ✓ D2 body {d2_body:.1f}pts = {body_ratio:.0%} of pattern ({bear_pattern_height:.1f}pts), limit {dynamic_chase_limit:.0%}")

                    # RANGE check
                    bear_is_consol, bear_consol_status = self.is_consolidation()
                    debug_bear_logs.append(f"[RANGE] {bear_consol_status}")

                    # CASCADE (mirror: tracks new session highs instead of lows)
                    bear_candles_since_new_high = (self.render_candle_count - self.bear_last_new_high_candle_idx) if self.bear_last_new_high_candle_idx is not None else 999
                    bear_cascade_time_ok = bear_candles_since_new_high >= CASCADE_COOLDOWN_CANDLES
                    bear_cascade_tested_bypass = self.bear_ceiling_recovered
                    # 🔥 V5.64: New high was institutional selling building the ceiling — not a momentum cascade
                    bear_cascade_gate = bear_cascade_time_ok or bear_cascade_tested_bypass or bear_ceiling_absorbed
                    bear_cascade_mark = '✓' if bear_cascade_gate else '✗'
                    debug_bear_logs.append(f"[RVOL] ({rvol_ratio:.2f}x)")
                    if bear_cascade_tested_bypass and not bear_cascade_time_ok:
                        debug_bear_logs.append(f"[CASCADE] {bear_cascade_mark} (last new high {bear_candles_since_new_high}c ago, cooldown:{CASCADE_COOLDOWN_CANDLES}, BYPASSED: ceiling tested)")
                    elif bear_ceiling_absorbed and not bear_cascade_time_ok:
                        debug_bear_logs.append(f"[CASCADE] {bear_cascade_mark} (last new high {bear_candles_since_new_high}c ago, cooldown:{CASCADE_COOLDOWN_CANDLES}, BYPASSED: ceiling absorbed (streak:{self.bear_top_absorb_streak}, absorb:{bear_absorb_score}))")
                    else:
                        debug_bear_logs.append(f"[CASCADE] {bear_cascade_mark} (last new high {bear_candles_since_new_high}c ago, cooldown:{CASCADE_COOLDOWN_CANDLES})")
                    # SIGNAL-CD
                    bear_signal_cooldown_passed = True
                    if self.bear_last_signal_candle_idx is not None:
                        bear_candles_since_signal = self.render_candle_count - self.bear_last_signal_candle_idx
                        ceil_is_higher = target_ceiling > self.bear_last_signal_ceiling_price
                        if bear_candles_since_signal < SIGNAL_COOLDOWN_CANDLES and not ceil_is_higher:
                            bear_signal_cooldown_passed = False
                        cd_mark = '✓' if bear_signal_cooldown_passed else '✗'
                        debug_bear_logs.append(f"[SIGNAL-CD] {cd_mark} ({bear_candles_since_signal}c since last signal, ceiling {'↑' if ceil_is_higher else '↓'})")

                    # VWAP check (mirror: D2 should be near or below VWAP = support broken)
                    bear_vwap_passed = True
                    if self.session_vwap is not None and bear_atr and bear_atr > 0 and 'DR2' in bear_matched_prices:
                        d2_price = bear_matched_prices['DR2']
                        vwap_gap = d2_price - self.session_vwap  # positive = D2 is above VWAP
                        min_clearance = bear_atr * VWAP_MIN_CLEARANCE_ATR
                        if vwap_gap > 0 and vwap_gap < min_clearance:
                            # D2 is just above VWAP — immediate support below, no room to fall
                            bear_vwap_passed = False
                            debug_bear_logs.append(f"[VWAP] ✗ Support ({vwap_gap:.1f}pts < {min_clearance:.1f}pts clearance, VWAP:{self.session_vwap:.2f})")
                        elif vwap_gap <= -(bear_atr * VWAP_RECLAIM_BUFFER_ATR):
                            # 🔥 V5.69: D2 is clearly below VWAP by buffer — genuinely broken
                            debug_bear_logs.append(f"[VWAP] ✓ Broken (D2:{d2_price:.2f} ≤ VWAP:{self.session_vwap:.2f} - {bear_atr*VWAP_RECLAIM_BUFFER_ATR:.1f}pts buffer)")
                        elif vwap_gap <= 0:
                            # 🔥 V5.69: D2 is below VWAP but within the buffer band — fakeout zone
                            bear_vwap_passed = False
                            debug_bear_logs.append(f"[VWAP] ✗ VWAP fakeout (D2:{d2_price:.2f} only {-vwap_gap:.1f}pts below VWAP:{self.session_vwap:.2f}, need {bear_atr*VWAP_RECLAIM_BUFFER_ATR:.1f}pts)")
                        else:
                            # D2 is well above VWAP — room to fall
                            debug_bear_logs.append(f"[VWAP] ✓ Clearance ({vwap_gap:.1f}pts ≥ {min_clearance:.1f}pts, VWAP:{self.session_vwap:.2f})")

                    # 🔥 V5.31: D2 CANDLE CONFIRMATION (bearish mirror)
                    bear_d2_close_passed = True
                    bear_d2_delta_passed = True
                    if spread > 0:
                        close_pct = (ohlc_close - ohlc_low) / spread
                        if close_pct > (1.0 - D2_MIN_CLOSE_PCT):
                            bear_d2_close_passed = False
                            debug_bear_logs.append(f"[D2-CLOSE] ✗ Close at {close_pct:.0%} (need ≤{1.0-D2_MIN_CLOSE_PCT:.0%} for short)")
                        else:
                            debug_bear_logs.append(f"[D2-CLOSE] ✓ Close at {close_pct:.0%}")
                    if REQUIRE_D2_DELTA_CONFIRM and total_delta_candle > 0:
                        bear_d2_delta_passed = False
                        debug_bear_logs.append(f"[D2-DELTA] ✗ Positive delta ({int(total_delta_candle)})")
                    else:
                        debug_bear_logs.append(f"[D2-DELTA] ✓ ({int(total_delta_candle)})")

                    # 🔥 V5.32/V5.72: LOCAL RVOL GATE (bearish mirror)
                    # bear_local_rvol and bear_effective_rvol already computed early (after bear_micro_rvol)
                    bear_rvol_gate_passed = bear_effective_rvol >= MIN_SIGNAL_RVOL
                    # 🔥 V5.40: Climax bypasses RVOL gate (climax candle volume validates context)
                    if not bear_rvol_gate_passed and bear_is_climax:
                        bear_rvol_gate_passed = True
                        debug_bear_logs.append(f"[RVOL-GATE] ⚠ local:{bear_local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x, BYPASSED: Climax (session:{rvol_ratio:.2f}x)")
                    elif not bear_rvol_gate_passed and bear_override_allowed:  # 🔥 V5.53: override = exhaust+extreme D2+RVOL/trend
                        bear_rvol_gate_passed = True
                        debug_bear_logs.append(f"[RVOL-GATE] ⚠ local:{bear_local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x, BYPASSED: Override (session:{rvol_ratio:.2f}x)")
                    elif not bear_rvol_gate_passed and bear_ceiling_absorbed:  # 🔥 V5.64: institutional selling at ceiling confirmed
                        bear_rvol_gate_passed = True
                        debug_bear_logs.append(f"[RVOL-GATE] ⚠ local:{bear_local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x, BYPASSED: Ceiling absorbed (streak:{self.bear_top_absorb_streak}, absorb:{bear_absorb_score}, session:{rvol_ratio:.2f}x)")
                    elif not bear_rvol_gate_passed and bear_absorb_score >= 3 and bear_vwap_broken:  # 🔥 V5.66: strong absorption + VWAP resistance = institutional presence confirmed
                        bear_rvol_gate_passed = True
                        debug_bear_logs.append(f"[RVOL-GATE] ⚠ local:{bear_local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x, BYPASSED: High absorb({bear_absorb_score}≥3) + VWAP broken (session:{rvol_ratio:.2f}x)")
                    elif not bear_rvol_gate_passed:
                        debug_bear_logs.append(f"[RVOL-GATE] ✗ local:{bear_local_rvol:.2f}x < {MIN_SIGNAL_RVOL}x (session:{rvol_ratio:.2f}x)")
                    else:
                        debug_bear_logs.append(f"[RVOL-GATE] ✓ local:{bear_local_rvol:.2f}x (session:{rvol_ratio:.2f}x)")

                    # 🔥 V5.34: BEARISH ABSORPTION VALIDATION (computed early for V5.61 GOLDEN HEIGHT bypass)
                    debug_bear_logs.append(f"[ABSORB] {bear_absorb_status}")

                    # 🔥 V5.37: RVOL DEAD ZONE — 1.00-1.30 = 36% WR noise zone (bearish mirror)
                    # Bypass: risk ≥ 25 OR absorb_score ≥ 5 (institutional confirmation)
                    bear_rvol_dead_zone_blocked = False
                    bear_risk_val = bear_pattern_height if ('DR2' in bear_matched_prices and bear_atr and bear_atr > 0) else 0
                    if RVOL_DEAD_ZONE_LOW <= bear_local_rvol < RVOL_DEAD_ZONE_HIGH:
                        if bear_risk_val >= RVOL_DEAD_ZONE_RISK_BYPASS:
                            debug_bear_logs.append(f"[RVOL-ZONE] ⚠ Dead zone RVOL but risk {bear_risk_val:.1f} ≥ {RVOL_DEAD_ZONE_RISK_BYPASS} → passing")
                        elif bear_absorb_score >= RVOL_DEAD_ZONE_ABSORB_BYPASS:
                            debug_bear_logs.append(f"[RVOL-ZONE] ⚠ Dead zone RVOL but absorb {bear_absorb_score} ≥ {RVOL_DEAD_ZONE_ABSORB_BYPASS} → passing")
                        else:
                            bear_rvol_dead_zone_blocked = True
                            debug_bear_logs.append(f"[RVOL-ZONE] ✗ Dead zone ({bear_local_rvol:.2f}x in [{RVOL_DEAD_ZONE_LOW}-{RVOL_DEAD_ZONE_HIGH}), risk:{bear_risk_val:.1f}<{RVOL_DEAD_ZONE_RISK_BYPASS}, absorb:{bear_absorb_score}<{RVOL_DEAD_ZONE_ABSORB_BYPASS})")
                    else:
                        debug_bear_logs.append(f"[RVOL-ZONE] ✓ Outside dead zone ({bear_local_rvol:.2f}x)")

                    # 🔥 V5.37: RVOL HIGH CEILING — session RVOL ≥ 2.0 = 0% WR (bearish mirror)
                    bear_rvol_high_blocked = rvol_ratio >= RVOL_HIGH_CEILING
                    if bear_rvol_high_blocked:
                        debug_bear_logs.append(f"[RVOL-HIGH] ✗ Session RVOL {rvol_ratio:.2f}x ≥ {RVOL_HIGH_CEILING} (extreme volatility)")
                    else:
                        debug_bear_logs.append(f"[RVOL-HIGH] ✓ Session RVOL {rvol_ratio:.2f}x")

                    # 🔥 V5.36: Chase relaxation removed (recovered 0 signals in V5.35 backtest — dead code)

                    # 🔥 V5.31: GOLDEN ENTRY DETECTION — bearish mirror (computed earlier for V5.61 HEIGHT bypass)
                    debug_bear_logs.append(f"[GOLDEN] {bear_golden_status}")

                    # 🔥 V5.62: TREND-EXHAUST — tightened, only GOLDEN bypasses on trend days (bear mirror)
                    # Climax alone no longer sufficient — GOLDEN required to counter any trend-day exhaust
                    bear_trend_exhaust_blocked = False
                    if (not bear_is_golden and
                        self.last_range_ratio is not None and
                        self.last_range_ratio >= TREND_EXHAUST_MIN_RANGE_ATR and
                        bear_exhaust_passed and (
                            bear_is_climax or (
                                self.last_exhaust_recovery_pct is not None and
                                self.last_exhaust_recovery_pct <= TREND_EXHAUST_MAX_RECOVERY_PCT
                            )
                        )):
                        bear_trend_exhaust_blocked = True
                        _bear_te_type = "Climax" if bear_is_climax else f"Low recovery ({self.last_exhaust_recovery_pct*100:.0f}%)"
                        debug_bear_logs.append(
                            f"[TREND-EXHAUST] ✗ {_bear_te_type} "
                            f"+ trend day ({self.last_range_ratio:.1f}x ATR) = premature reversal (GOLDEN required)")
                    else:
                        te_reason = []
                        if not bear_exhaust_passed:
                            te_reason.append("no-exhaust")
                        elif bear_is_climax:
                            te_reason.append("climax")
                        if self.last_exhaust_recovery_pct is not None and self.last_exhaust_recovery_pct > TREND_EXHAUST_MAX_RECOVERY_PCT:
                            te_reason.append(f"recovery-ok({self.last_exhaust_recovery_pct*100:.0f}%)")
                        if self.last_range_ratio is not None and self.last_range_ratio < TREND_EXHAUST_MIN_RANGE_ATR:
                            te_reason.append(f"narrow({self.last_range_ratio:.1f}x)")
                        if rvol_ratio >= TREND_EXHAUST_MAX_RVOL:
                            te_reason.append(f"RVOL-ok({rvol_ratio:.2f}x)")
                        if bear_is_golden:
                            te_reason.append("golden")
                        debug_bear_logs.append(f"[TREND-EXHAUST] ✓ Passed ({', '.join(te_reason)})")

                    # 🔥 V5.31: GRADE C + CONSOLIDATION BLOCK
                    bear_grade_c_blocked = False
                    if BLOCK_GRADE_C_CONSOL and not bear_effective_exhaust and bear_is_consol and not bear_is_golden:
                        bear_grade_c_blocked = True
                        debug_bear_logs.append(f"[GRADE-C] ✗ No exhaust + consolidation = blocked")

                    # 🔥 V5.36: AFTERNOON GATE — Grade B at 14:xx blocked UNLESS absorb_passed (bearish mirror)
                    bear_afternoon_blocked = False
                    if dt_ist.hour >= 14 and not bear_effective_exhaust and not bear_is_golden:
                        bear_afternoon_blocked = True
                        debug_bear_logs.append(f"[TIME] ✗ Afternoon ({dt_ist.hour}:xx) + no exhaustion = blocked")
                    elif dt_ist.hour >= 14 and not bear_is_golden and (not bear_effective_exhaust or bear_is_consol):
                        if bear_absorb_passed:
                            debug_bear_logs.append(f"[TIME] ⚠ Afternoon Grade B ({dt_ist.hour}:xx) — absorb_passed, allowing")
                        elif bear_effective_exhaust and bear_is_consol:
                            bear_afternoon_blocked = True
                            debug_bear_logs.append(f"[TIME] ✗ Afternoon Grade B ({dt_ist.hour}:xx) + exhaust+consol + no absorb = blocked")
                        elif not bear_effective_exhaust and not bear_is_consol:
                            bear_afternoon_blocked = True
                            debug_bear_logs.append(f"[TIME] ✗ Afternoon Grade B ({dt_ist.hour}:xx) + no exhaust+trending + no absorb = blocked")
                    elif dt_ist.hour >= 14:
                        debug_bear_logs.append(f"[TIME] ⚠ Afternoon ({dt_ist.hour}:xx) — Grade A/A+ quality, passing")

                    # 🔥 V5.68: LOW-RVOL GRADE B BLOCK — Short Grade B at 0.30-0.50 RVOL blocked
                    bear_low_rvol_grade_b_blocked = False
                    if (SHORT_LOW_RVOL_GRADE_B_MIN <= rvol_ratio < SHORT_LOW_RVOL_GRADE_B_MAX
                            and not bear_is_golden and not bear_is_climax
                            and not bear_effective_exhaust):
                        bear_low_rvol_grade_b_blocked = True
                        debug_bear_logs.append(f"[LOW-RVOL-B] ✗ Grade B short RVOL {rvol_ratio:.2f}x in [{SHORT_LOW_RVOL_GRADE_B_MIN}-{SHORT_LOW_RVOL_GRADE_B_MAX}) = blocked")

                    # 🔥 V5.68: SHORT RISK CAP — non-golden/non-climax shorts capped at 45pts
                    # 🔥 V5.70: GRACE MARGIN — +3pts when effective exhaust + institutional presence + miss within 3pts
                    bear_risk_cap_blocked = False
                    bear_risk_cap_effective = SHORT_RISK_CAP_NON_GOLDEN
                    bear_institutional_presence = bear_ceiling_absorbed or (bear_absorb_score >= 3 and bear_effective_exhaust)
                    if (bear_effective_exhaust and bear_institutional_presence
                            and bear_risk_val > SHORT_RISK_CAP_NON_GOLDEN
                            and bear_risk_val <= SHORT_RISK_CAP_NON_GOLDEN + 3.0):
                        bear_risk_cap_effective = SHORT_RISK_CAP_NON_GOLDEN + 3.0
                    if (bear_risk_val > bear_risk_cap_effective
                            and not bear_is_golden and not bear_is_climax
                            and not bear_is_extreme_conviction):
                        bear_risk_cap_blocked = True
                        debug_bear_logs.append(f"[RISK-CAP] ✗ Short risk {bear_risk_val:.1f} > {bear_risk_cap_effective:.1f} (non-golden/non-climax) = blocked")
                    elif bear_risk_cap_effective > SHORT_RISK_CAP_NON_GOLDEN:
                        debug_bear_logs.append(f"[RISK-CAP] ⚠ Grace margin applied: risk {bear_risk_val:.1f} ≤ {bear_risk_cap_effective:.1f} (exhaust+institutional)")

                    # 🔥 V5.68: MIDDAY SHORT HARDENING — 12:00-13:59 needs absorb>=3 OR RVOL>=0.65
                    bear_midday_blocked = False
                    if (SHORT_MIDDAY_HOUR_START <= dt_ist.hour <= SHORT_MIDDAY_HOUR_END
                            and not bear_is_golden and not bear_is_climax
                            and bear_absorb_score < SHORT_MIDDAY_MIN_ABSORB
                            and rvol_ratio < SHORT_MIDDAY_MIN_RVOL):
                        bear_midday_blocked = True
                        debug_bear_logs.append(f"[MIDDAY] ✗ Short {dt_ist.hour}:xx absorb:{bear_absorb_score}<{SHORT_MIDDAY_MIN_ABSORB} RVOL:{rvol_ratio:.2f}<{SHORT_MIDDAY_MIN_RVOL} = blocked")

                    # 🔥 V5.79: TROUGH BLOCK — SHORT signal on candle making new session low = selling at trough
                    bear_trough_blocked = False
                    if (self.session_lowest_trap is not None and
                        ohlc_low <= self.session_lowest_trap and
                        not bear_is_golden):
                        bear_trough_blocked = True
                        debug_bear_logs.append(
                            f"[TROUGH] ✗ Candle low {ohlc_low:.2f} ≤ session low {self.session_lowest_trap:.2f} "
                            f"= selling at trough (ceiling age:{self.bear_ceiling_age})")
                    elif self.session_lowest_trap is not None:
                        debug_bear_logs.append(
                            f"[TROUGH] ✓ Above session low ({ohlc_low:.2f} > {self.session_lowest_trap:.2f})")

                    # 🔥 V5.31: Hard blockers — Golden entries bypass secondary filters
                    bear_blocked_reason = None
                    # 🔥 V5.54: WARMUP guard — no signals before ATR established (prevents premature fires)
                    if bear_atr is None:
                        bear_blocked_reason = "WARMUP"
                    # 🔥 V5.62: LATE — hard cutoff 14:45; GOLDEN extends to 15:10 (session extreme at EOD)
                    elif (dt_ist.hour > SIGNAL_CUTOFF_HOUR or (dt_ist.hour == SIGNAL_CUTOFF_HOUR and dt_ist.minute > SIGNAL_CUTOFF_MINUTE)) and not bear_is_golden:
                        bear_blocked_reason = "LATE"
                    elif (dt_ist.hour > GOLDEN_SIGNAL_CUTOFF_HOUR or (dt_ist.hour == GOLDEN_SIGNAL_CUTOFF_HOUR and dt_ist.minute > GOLDEN_SIGNAL_CUTOFF_MINUTE)):
                        bear_blocked_reason = "LATE"
                    elif not bear_cascade_gate and not (bear_is_golden and bear_candles_since_new_high >= GOLDEN_CASCADE_MIN_AGE):
                        bear_blocked_reason = "RALLY-CASCADE"  # 🔥 V5.44: Golden bypass with minimum distance from new session high
                    elif not bear_signal_cooldown_passed and not bear_is_golden:
                        bear_blocked_reason = "COOLDOWN"
                    elif not bear_rally_passed:
                        bear_blocked_reason = "RALLY"
                    elif not bear_prox_passed:
                        bear_blocked_reason = "RESISTANCE"
                    elif bear_trend_exhaust_blocked:
                        bear_blocked_reason = "TREND-EXHAUST"  # 🔥 V5.52: premature countertrend on trend day
                    elif not bear_height_passed:
                        bear_blocked_reason = "HEIGHT"
                    elif not bear_chase_passed and not bear_is_golden:
                        bear_blocked_reason = "CHASE"
                    elif not bear_vwap_passed and not bear_is_golden:
                        bear_blocked_reason = "VWAP"
                    elif bear_grade_c_blocked:
                        bear_blocked_reason = "GRADE-C"
                    elif not bear_d2_close_passed and not bear_is_golden:
                        bear_blocked_reason = "D2-CLOSE"
                    elif not bear_d2_delta_passed and not bear_is_golden:
                        bear_blocked_reason = "D2-DELTA"
                    elif not bear_rvol_gate_passed and not bear_is_golden:
                        bear_blocked_reason = "LOW-RVOL"
                    # 🔥 V5.35: RVOL dead zone (bearish mirror)
                    elif bear_rvol_dead_zone_blocked and not bear_is_golden:
                        bear_blocked_reason = "RVOL-ZONE"
                    # 🔥 V5.47: HIGH-RVOL golden bypass (forensic: +245.3 CF PnL from 19 signals 8W/6L)
                    elif bear_rvol_high_blocked and not bear_is_golden:
                        bear_blocked_reason = "HIGH-RVOL"
                    elif bear_afternoon_blocked:
                        bear_blocked_reason = "AFTERNOON"
                    # 🔥 V5.68: SHORT-side discipline filters
                    elif bear_low_rvol_grade_b_blocked:
                        bear_blocked_reason = "LOW-RVOL-B"
                    elif bear_risk_cap_blocked:
                        bear_blocked_reason = "RISK-CAP"
                    elif bear_midday_blocked:
                        bear_blocked_reason = "MIDDAY"
                    # 🔥 V5.69: CLIMAX VETO — block shorts on selling-climax D2 candles
                    # 🔥 V5.80: Golden/extreme-conviction bypass (was dead code — bear_is_golden computed after veto)
                    elif selling_climax_veto and not bear_is_golden and not bear_is_extreme_conviction:
                        bear_blocked_reason = "CLIMAX-VETO"
                    # 🔥 V5.79: TROUGH — don't sell at new session lows (chasing, not reversing)
                    elif bear_trough_blocked:
                        bear_blocked_reason = "TROUGH"
                    # 🔥 V5.34: Absorption soft-blocker (bearish mirror)
                    elif not bear_absorb_passed and not bear_effective_exhaust and not bear_is_golden:
                        bear_blocked_reason = "WEAK-EVIDENCE"

                    # 🧪 CORE-ONLY: override the entire gate chain — fire on the pure
                    # concept only. STRUCTURE is mandatory; require at least ONE of
                    # EXHAUSTION / ABSORPTION (so we capture more than the gated path).
                    if CORE_ONLY:
                        if bear_atr is None:
                            bear_blocked_reason = "WARMUP"
                        elif not bear_rally_passed:          # STRUCTURE: ceiling above swing low
                            bear_blocked_reason = "NO-STRUCT"
                        elif not (bear_effective_exhaust or bear_absorb_passed):  # EXHAUSTION or ABSORPTION
                            bear_blocked_reason = "NO-EVIDENCE"
                        else:
                            bear_blocked_reason = None

                    if bear_blocked_reason is None:
                        # 🔥 V5.34: Grade logic (now with absorption validation)
                        if bear_is_golden:
                            bear_quality_grade = "A+"
                        elif bear_effective_exhaust and not bear_is_consol:
                            bear_quality_grade = "A"
                        elif bear_effective_exhaust or not bear_is_consol:
                            bear_quality_grade = "B"
                        else:
                            bear_quality_grade = "C"
                        self.bear_last_signal_candle_idx = self.render_candle_count
                        self.bear_last_signal_ceiling_price = target_ceiling
                        bear_alert_msg = f"🔻 2B REVERSAL SHORT: Ceiling @ {target_ceiling:.2f} [⭐ {bear_quality_grade}]"
                        if CORE_ONLY:
                            bear_alert_msg += f" [CORE exh:{1 if bear_effective_exhaust else 0} abs:{1 if bear_absorb_passed else 0}]"
                        bear_alert_msg += f"\n📊 RVOL: {rvol_ratio:.1f}x (Z:{rvol_zscore:.1f}) | EFF: {efficiency:.2f}"
                        bear_alert_msg += f"\n🔥 CEILING → DR→L→DR"
                        send_telegram(bear_alert_msg)

                    # Always full reset after pattern evaluation
                    self.bear_active_ceiling_price = None
                    self.bear_ceiling_age = 0
                    self.bear_ceiling_broken_age = 0
                    self.bear_ceiling_break_high = None
                    self.bear_ceiling_recovered = False
                    self.bear_state_lowest_dr1 = None
                    self.bear_state_has_light = False
                    self.bear_state_light_price = None
                    self.bear_state_dr1_is_genuine_dr = True
                    self.bear_historical_dg_between = set()
                    self.ceiling_confirmed = False  # 🔥 V5.67: Reset after signal fires

        delta_color = C['G_DELTA'] if total_delta_candle > 0 else C['R_DELTA']
        # Combine bull and bear status messages
        combined_status = trap_status_msg
        if bear_status_msg:
            combined_status += f" | 🔻 {bear_status_msg}" if combined_status else bear_status_msg
        print(f"\n 🕒 TIME (IST): {time_str} | POC: {poc_price_key} | {combined_status}")
        print(f" 📊 O: {ohlc_open:.2f} H: {ohlc_high:.2f} L: {ohlc_low:.2f} C: {ohlc_close:.2f} | VOL: {self.format_vol(total_vol_candle)} | DELTA: {delta_color}{int(total_delta_candle)}{C['RESET']}")

        rvol_color = C['G_DELTA'] if rvol_zscore >= RVOL_ZSCORE_STRONG else (C['GOLD'] if rvol_ratio > 0.9 else C['R_DELTA'])
        eff_color = C['G_DELTA'] if efficiency < EFFICIENCY_LOW_THRESHOLD else C['RESET']
        churn_indicator = f" {C['CYAN']}[CHURN]{C['RESET']}" if is_churn else ""

        # 🔥 V5.20: Row-level absorption summary for display
        row_absorptions = self.detect_row_absorption(complete_rows, row_tags)
        absorb_count = len(row_absorptions)
        absorb_indicator = f" {C['G_DELTA']}[ABSORB x{absorb_count}]{C['RESET']}" if absorb_count > 0 else ""

        # Multi-candle zones for display
        multi_zones = self.track_multi_candle_absorption(complete_rows, row_tags)
        multi_zones = [z for z in multi_zones if z['hits'] >= MULTI_HIT_THRESHOLD]
        multi_indicator = f" {C['CYAN']}[MULTI-ABSORB x{len(multi_zones)}]{C['RESET']}" if multi_zones else ""

        accel_val = self.get_delta_acceleration()
        voids = self.detect_liquidity_voids(complete_rows)
        accel_color = C['G_DELTA'] if accel_val >= MIN_DELTA_ACCELERATION else C['R_DELTA']

        print(f" 🔥 RVOL: {rvol_color}{rvol_ratio:.2f}x (Z:{rvol_zscore:.1f}){C['RESET']} | Eff: {eff_color}{efficiency:.2f}{C['RESET']}{churn_indicator}{absorb_indicator}{multi_indicator}")
        print(f" 📈 Accel: {accel_color}{accel_val:.0f}{C['RESET']} | Voids: {len(voids)}")

        state_msg = ""
        if self.state_has_light: state_msg = " [STATE: WAITING DG2]"
        elif self.state_highest_dg1: state_msg = " [STATE: WAITING L]"

        # Bearish state message
        bear_state_msg = ""
        if self.bear_state_has_light: bear_state_msg = " [BEAR: WAITING DR2]"
        elif self.bear_state_lowest_dr1: bear_state_msg = " [BEAR: WAITING L]"

        if debug_trap_logs:
            print(f" 🕵️ Analysis:{C['RESET']} {', '.join(debug_trap_logs)}{state_msg}")
        if debug_bear_logs:
            print(f" 🔻 Bear:{C['RESET']} {', '.join(debug_bear_logs)}{bear_state_msg}")

        # 🔥 V5.24: Print signal BEFORE row table so alert is clearly part of this candle
        if alert_msg:
            print(f"\n{C['ALERT_BG_G']} {alert_msg.replace('<b>', '').replace('</b>', '')} {C['RESET']}")
        if bear_alert_msg:
            print(f"\n{C['ALERT_BG_R']} {bear_alert_msg} {C['RESET']}")

        print(f"{'='*80}{C['RESET']}")
        print(f"  {'PRICE':<10} | {'BID':>10}  x  {'ASK':<10}  | {'DELTA':^8} | {'TAG'}")
        print(f"  {'-'*62}")

        for i, row in enumerate(complete_rows):
            price, bid, ask = row['price'], row['sell'], row['buy']
            delta = ask - bid

            # Use pre-computed colors from tagging loop
            rr, rg, rb, render_lu = row_colors[i]
            row_bg = f"\033[48;2;{rr};{rg};{rb}m"
            row_txt = C['W_TEXT'] if render_lu < 140 else C['B_TEXT']
            bid_txt_final = ask_txt_final = row_txt
            if f"{price:.2f}" == poc_price_key: bid_txt_final = ask_txt_final = C['POC_TEXT']

            tag = row_tags[i]
            tag_vis = ""
            if tag in ('DG', 'DR', 'L'):
                tag_vis = f"{row_bg}{C['BOLD']}{row_txt}[{tag}]{C['RESET']}"

            if self.active_trap_price and abs(price - self.active_trap_price) < 0.01:
                if tag in ('DR', 'DG'):
                    if i == new_trap_idx:
                        tag_vis += f" {C['WARN']}<< TRAP{C['RESET']}"
                    else:
                        tag_vis += f" {C['WARN']}<< TRAP (Active){C['RESET']}"

            # 🔻 Bearish ceiling marker
            if self.bear_active_ceiling_price and abs(price - self.bear_active_ceiling_price) < 0.01:
                if tag in ('DR', 'DG'):
                    if i == new_ceil_idx:
                        tag_vis += f" {C['WARN']}<< CEIL{C['RESET']}"
                    else:
                        tag_vis += f" {C['WARN']}<< CEIL (Active){C['RESET']}"

            pattern_marker = ""
            # Bullish pattern markers
            if matched_prices:
                if 'DG1' in matched_prices and abs(price - matched_prices['DG1']) < 0.01:
                    pattern_marker = " ← D1" + (" [HIST]" if matched_prices['DG1'] < fp_min else "")

                if 'L' in matched_prices and abs(price - matched_prices['L']) < 0.01:
                    pattern_marker = " ← L" + (" [HIST]" if matched_prices['L'] < fp_min else "")

                if 'DG2' in matched_prices and abs(price - matched_prices['DG2']) < 0.01:
                    pattern_marker = " ← D2"

            # 🔻 Bearish pattern markers
            if bear_matched_prices:
                if 'DR1' in bear_matched_prices and abs(price - bear_matched_prices['DR1']) < 0.01:
                    pattern_marker += " ← 🔻D1"
                if 'L' in bear_matched_prices and abs(price - bear_matched_prices['L']) < 0.01:
                    pattern_marker += " ← 🔻L"
                if 'DR2' in bear_matched_prices and abs(price - bear_matched_prices['DR2']) < 0.01:
                    pattern_marker += " ← 🔻D2"

            bid_disp = f"{row_bg}{bid_txt_final}{self.format_vol(bid):>10}{C['RESET']}"
            ask_disp = f"{row_bg}{ask_txt_final}{self.format_vol(ask):<10}{C['RESET']}"
            print(f"  {price:<10.2f} | {bid_disp}  x  {ask_disp}  | {self.format_vol(delta):<8} | {tag_vis}{pattern_marker}")

        self.stats['rendered'] += 1

    def on_message(self, ws, message):
        if isinstance(message, str):
            if "Welcome" in message:
                print(f"✅ Footprint (v5.84 NIFTY): Connected for {self.target_ist_date}...")
                # 🔥 NIFTY: Request ONLY current date (matching working script)
                req = {"command": "FOOTPRINT/V2", "request_id": 1, "payload": {"exchange": "NSE", "segment": "FUTURE", "symbol": "NIFTY-I", "interval": "5m", "dates": [self.curr_date], "session": "RTH"}}
                ws.send(json.dumps(req))
            return

        if b'~b' in message:
            try:
                raw = message[message.find(b'~b')+2:]
                resp = footprint_pb2.FootPrintForDateResponse()
                resp.ParseFromString(raw)
                if resp.candles:
                    for c in resp.candles: self.all_candles.append(c)
                    self.dates_fetched += 1
                    print(f"✅ Received Batch {self.dates_fetched}")

                    if self.dates_fetched >= 1:  # Only 1 batch now
                        print(f"🔥 STARTING BACKTEST for {self.target_ist_date}...")

                        # 🔥 DEDUPLICATE: Remove duplicate candles with same timestamp
                        seen_timestamps = set()
                        unique_candles = []
                        for c in self.all_candles:
                            if c.date not in seen_timestamps:
                                seen_timestamps.add(c.date)
                                unique_candles.append(c)

                        print(f"   Received {len(self.all_candles)} candles, {len(unique_candles)} unique")

                        unique_candles.sort(key=lambda c: c.date)
                        count = 0
                        for c in unique_candles:
                            self.render_candle(c)
                            count += 1

                        print(f"\n📊 DIAGNOSTIC REPORT:")
                        print(f"   Total Candles Processed: {self.stats['total']}")
                        print(f"   Skipped (Wrong Date):    {self.stats['skipped_date']}")
                        print(f"   Successfully Rendered:   {self.stats['rendered']}")

                        self.shutting_down = True
                        ws.close()
                        # 🔥 V5.84: Only prompt when running interactively — batch
                        # runners (sys.stdin not a TTY) must not block here.
                        try:
                            if sys.stdin and sys.stdin.isatty():
                                input(f"\n✅ Analysis Complete. Press Enter to exit...")
                            else:
                                print("\n✅ Analysis Complete (non-interactive, exiting).")
                        except Exception:
                            pass
                        sys.exit()
            except Exception as e: print(f"Error: {e}")

    def start(self):
        self.ws = websocket.WebSocketApp(self.ws_url, header=self.headers, on_open=lambda ws: print("Footprint: Connecting..."), on_message=self.on_message)
        self.ws.run_forever()

if __name__ == "__main__":
    token = get_fresh_token()
    if not token:
        print(f"\n{C['ALERT_BG_R']} CRITICAL ERROR: FAILED TO RETRIEVE TOKEN {C['RESET']}")
        sys.exit(1)

    print("Step 1: Fetching Official OHLC...")
    ohlc_thread = threading.Thread(target=lambda: OHLCFetcher(token).start())
    ohlc_thread.daemon = True
    ohlc_thread.start()

    wait_time = 0
    while not ohlc_complete and wait_time < 30:
        time.sleep(1)
        wait_time += 1
        if wait_time % 5 == 0: print(f"   ...waiting for OHLC ({wait_time}s)")

    if ohlc_complete:
        print("Step 2: Starting Footprint Analysis...")
        FootprintRenderer(token).start()
    else:
        print(f"\n{C['ALERT_BG_R']} ERROR: OHLC DOWNLOAD TIMED OUT. Proceeding with internal OHLC... {C['RESET']}")
        ohlc_complete = True
        FootprintRenderer(token).start()