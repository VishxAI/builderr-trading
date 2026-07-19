"""House reference bot — "Drawdown-First Vol-Managed Momentum" (the bar to beat).

Built for one number: 30-day forward Calmar = annualized return / max drawdown.
Because max drawdown is the *denominator*, protecting it beats chasing return.
So the whole design is: be fully invested only in calm uptrends, and de-risk
hard and fast the instant stress shows up.

What it combines (all standard, deliberately un-fancy so the held-out rerun
can't punish curve-fitting):
  1. Time-series momentum gate (Moskowitz/Ooi/Pedersen) — only take risk when
     SPY and QQQ are above their 100-day trend.
  2. Volatility targeting (Moreira–Muir, "Volatility-Managed Portfolios") —
     scale total exposure inversely to market vol, so a vol spike auto-cuts size.
  3. Cross-sectional momentum (Jegadeesh–Titman) — hold the strongest names.
  4. Risk-parity-lite — size the held names by inverse volatility, not equal $,
     so no single name dominates the drawdown.
  5. A FAST crash brake that overrides the (laggy) trend gate: a sharp multi-day
     drop or a vol explosion flattens us to mostly cash the same day.

Deliberately NO leveraged ETFs. Over a 30-day Calmar window, 2x/3x funds add far
more to the denominator (drawdown, vol decay) than to the numerator. Long-only,
stdlib only, no network, no LLM, no API keys. Every name capped at 18% (well
under the 30% rule); gross never exceeds 1.0x (well under the 1.5x cap).
"""
from __future__ import annotations

from statistics import pstdev

# ---- universe (all inside the v0 list, all 1x) -----------------------------
RISK_ON = (
    "SPY", "QQQ", "SMH",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLC", "XLRE",
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
)
DEFENSIVE = ("XLP", "XLU")            # staples / utilities (added for risk-off breadth)
# When de-risked we still rank the FULL set — in a downtrend the survivors
# (e.g. energy in 2022) are what we want to hold, just at much lower gross.
SELECT = RISK_ON + DEFENSIVE

# ---- knobs (round numbers on purpose; few of them) -------------------------
TREND_SMA = 100          # long-term trend filter
NAME_SMA = 50            # a name must be above its own 50-day trend to qualify
MOM_FAST, MOM_FAST_SKIP = 63, 5      # ~3-month momentum, skip last week
MOM_SLOW = 126           # ~6-month momentum
INDEX_MOM_MIN = -0.02    # index 6-mo momentum must clear this to allow risk-on
                         # — this is what stops us buying bear-market rallies
TREND_BAND = 0.01        # hysteresis: enter on +1% above trend, leave on -1% below
VOL_LOOKBACK = 20        # realized-vol window
VOL_CEILING = 0.28       # risk-on only when QQQ 20d annualized vol < 28%
TARGET_VOL = 0.14        # annualized portfolio vol target for sizing
TOP_N = 6
NAME_CAP = 0.18          # per-name weight cap (< 30% rule, even held 5+ days)
GROSS_MAX = 1.00         # never lever
DEF_GROSS_SOFT = 0.25    # soft risk-off: small defensive sleeve, rest cash
DEF_GROSS_HARD = 0.10    # hard stress: almost entirely cash — protect the denominator
REBALANCE_EVERY = 5      # re-base ~ weekly...
DEAD_BAND = 0.03         # ...ignoring trades < 3% of equity (kills turnover/whipsaw)
COOLDOWN_TICKS = 1       # after a stress day, wait this many ticks before re-risking

# fast crash brake — for genuine PRICE crashes. We deliberately keep the vol
# trigger high (extreme meltdowns only): moderate/elevated vol is handled by
# vol-targeting the gross, not by sitting in cash, so we don't get locked out of
# a snapback whose realized vol stays high while prices are already recovering.
BRAKE_3D, BRAKE_5D = -0.06, -0.08    # 3-/5-day QQQ return triggers
BRAKE_VOL_10D = 0.70                 # 10-day annualized vol trigger (extreme only)

_ANN = 252 ** 0.5
_tick = 0
_last_rebalance = -10**9
_last_regime = None
_cooldown = 0


def _closes(bars):
    return [float(b["close"]) for b in bars] if bars else []


def _sma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def _ret(closes, days, skip=0):
    need = days + skip + 1
    if len(closes) < need:
        return None
    end = closes[-(skip + 1)]
    start = closes[-(days + skip + 1)]
    return end / start - 1.0 if start > 0 else None


def _ann_vol(closes, n):
    if len(closes) < n + 1:
        return None
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(len(closes) - n, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 2:
        return None
    return pstdev(rets) * _ANN


def _market_vol(market_state):
    v = _ann_vol(_closes(market_state.get("QQQ") or []), VOL_LOOKBACK)
    return v if v and v > 0 else 0.20   # sane default if history is short


def _regime(market_state):
    """Return 'hard' (crash/vol stress), 'soft' (trend down, no crash), or 'on'."""
    qqq = _closes(market_state.get("QQQ") or [])
    spy = _closes(market_state.get("SPY") or [])
    if not qqq or not spy:
        return "hard"

    # Fast crash brake — a sharp multi-day drop or vol explosion = hard stress.
    r3, r5, v10 = _ret(qqq, 3), _ret(qqq, 5), _ann_vol(qqq, 10)
    if (r3 is not None and r3 < BRAKE_3D) or (r5 is not None and r5 < BRAKE_5D) or (v10 and v10 > BRAKE_VOL_10D):
        return "hard"

    # On/soft is decided by TREND + index momentum only — both slow, stable
    # signals, so we don't flip-flop. Vol is handled continuously by sizing
    # (vol-targeting the gross), not by a binary ceiling that thrashes in chop.
    spy_sma, qqq_sma = _sma(spy, TREND_SMA), _sma(qqq, TREND_SMA)
    idx_mom = _ret(qqq, MOM_SLOW)
    if spy_sma is None or qqq_sma is None or idx_mom is None:
        return "soft"

    # Hysteresis: turn risk ON only on a clear breakout above trend; once on,
    # tolerate small dips and only turn off on a clear breakdown. This is what
    # stops the daily SMA-cross flip-flop that churns trades in a choppy snapback.
    strong_on = (
        spy[-1] > spy_sma * (1 + TREND_BAND)
        and qqq[-1] > qqq_sma * (1 + TREND_BAND)
        and idx_mom >= INDEX_MOM_MIN
    )
    clearly_off = qqq[-1] < qqq_sma * (1 - TREND_BAND) or idx_mom < INDEX_MOM_MIN
    if _last_regime == "on":
        return "soft" if clearly_off else "on"
    return "on" if strong_on else "soft"


def _inv_vol_weights(names, market_state, gross):
    inv = {}
    for t in names:
        v = _ann_vol(_closes(market_state.get(t) or []), VOL_LOOKBACK)
        if v and v > 0:
            inv[t] = 1.0 / v
    if not inv:
        return {}
    s = sum(inv.values())
    return {t: min(NAME_CAP, gross * w / s) for t, w in inv.items()}


def _rank(market_state, universe):
    """Cross-sectional momentum: positive-score names in their own uptrend, best first."""
    ranked = []
    for t in universe:
        closes = _closes(market_state.get(t) or [])
        sma = _sma(closes, NAME_SMA)
        mf, ms = _ret(closes, MOM_FAST, MOM_FAST_SKIP), _ret(closes, MOM_SLOW)
        if sma is None or mf is None or ms is None or not closes:
            continue
        score = 0.5 * mf + 0.3 * ms + 0.2 * (closes[-1] / sma - 1.0)
        if score > 0 and closes[-1] > sma:
            ranked.append((score, t))
    ranked.sort(reverse=True)
    return [t for _, t in ranked[:TOP_N]]


def _target_weights(market_state, regime):
    # Relative momentum always picks the names; the regime only sets the gross.
    # Hard stress: almost all cash (a tiny low-vol sleeve). In a true crash even
    # "winners" gap down, so we just get out of the way.
    if regime == "hard":
        avail = [t for t in DEFENSIVE if market_state.get(t)]
        return _inv_vol_weights(avail, market_state, DEF_GROSS_HARD) if avail else {}

    if regime == "on":
        gross = min(GROSS_MAX, TARGET_VOL / _market_vol(market_state))
        winners = _rank(market_state, RISK_ON)
        return _inv_vol_weights(winners, market_state, gross) if winners else {}

    # soft: hold whatever is STILL trending up (energy in '22, say), but small.
    winners = _rank(market_state, SELECT)
    return _inv_vol_weights(winners, market_state, DEF_GROSS_SOFT) if winners else {}


def decide(market_state, portfolio_state, cash):
    global _tick, _last_rebalance, _last_regime, _cooldown
    _tick += 1

    positions = {p["ticker"]: p for p in portfolio_state.get("positions", [])}
    last_prices = portfolio_state.get("last_prices", {})
    equity = portfolio_state.get("cash", cash)
    for tk, pos in positions.items():
        equity += pos["quantity"] * last_prices.get(tk, pos.get("avg_cost", 0))
    if equity <= 0:
        return []

    regime = _regime(market_state)
    # Cooldown: after a hard-stress tick, don't jump straight back to full risk
    # into the chop of a snapback — step down to 'soft' for a few ticks.
    if regime == "hard":
        _cooldown = COOLDOWN_TICKS
    elif _cooldown > 0:
        _cooldown -= 1
        if regime == "on":
            regime = "soft"

    # De-risking can't wait for the cadence; re-risking can.
    derisk = _last_regime is not None and regime != _last_regime and (
        regime == "hard" or (regime == "soft" and _last_regime == "on")
    )
    on_cadence = _tick - _last_rebalance >= REBALANCE_EVERY
    _last_regime = regime
    if not on_cadence and not derisk:
        return []

    targets = _target_weights(market_state, regime)

    orders = []
    for ticker, pos in positions.items():       # exit anything not targeted
        if ticker not in targets and pos["quantity"] > 0:
            orders.append({"ticker": ticker, "side": "sell", "quantity": pos["quantity"]})

    for ticker, weight in targets.items():       # move toward target weights
        bars = market_state.get(ticker)
        if not bars:
            continue
        px = float(bars[-1]["close"])
        if px <= 0:
            continue
        cur_qty = positions.get(ticker, {}).get("quantity", 0)
        delta = int((equity * weight - cur_qty * px) // px)
        if abs(delta * px) < DEAD_BAND * equity:
            continue
        if delta > 0:
            orders.append({"ticker": ticker, "side": "buy", "quantity": delta})
        elif delta < 0 and cur_qty > 0:
            orders.append({"ticker": ticker, "side": "sell", "quantity": min(abs(delta), cur_qty)})

    if orders:
        _last_rebalance = _tick
    return orders
