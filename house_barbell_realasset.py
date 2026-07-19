"""House reference bot — Real-Asset Barbell (Soham's portfolio, as a daily rule).

NOT an entrant. Label if ever shown: "house · the bar to beat". This bot is a
translation of Soham's actual fund book into a single decide() function:

  - A permanent CASH FLOOR                 → his ~42% money-market buffer (dry powder).
  - An AI/tech GROWTH CORE when the trend  → Franklin Technology, Allianz Global AI,
    is up, sized by volatility               BGF World Technology (his growth engine).
  - A REAL-ASSET HEDGE sleeve (gold /      → BGF World Gold, World Mining, World Energy
    energy / miners) BOUGHT in risk-off,     (his actual diversifiers) — most losing
    not just a flat run to cash.             board bots only had cash, or nothing.

Why it's a differentiator, not another momentum basket:
  - The existing reference bots (vol-target, dual-momentum, ai-basket) either sit in
    a tech/sector core and scale DOWN to cash in a downtrend, or rotate to
    staples/utilities. None of them BUY a gold+energy hedge when tech rolls over.
  - On the live June board the losers stayed long tech into the correction
    (opu -6%, robert -9%, mohit -8%, siddu -9%). The edge that mirrors Soham's book
    AND survived that window is: hard risk-off switch + a real-asset ballast that can
    rise while tech falls, on top of a standing cash reserve.

The rules it stays inside (auto-enforced by the sandbox):
  - Long only, no leverage (all 1x ETFs → gross ~1.0x, well under the 1.5x cap).
  - Every sleeve capped < 30% per name (barbell of 3-4 names each ≈ 18-24%).
  - Daily decisions, weekly-ish rebalance, <= 50 trades/day, <5s runtime.

Ranking note: the live board sorts by RETURN over each bot's forward window (not
Calmar, despite the older brief copy). Drawdown discipline still matters — it's how
you clear admission and how you avoid giving back the return in the June-style dip —
but the target is "make money without a deep hole", which is exactly the barbell.
"""
from __future__ import annotations

from statistics import mean, pstdev

# ── knobs (deliberately few — fewer params, fewer ways to fool yourself) ──────────
_tick = 0
_last_rebalance = -10**9
# decide() is called ONCE PER DAY in this sim, so cadence is in DAYS, not intraday
# ticks. 5 = weekly — often enough that the risk-off switch actually fires inside a
# correction, rare enough to keep turnover (and slippage) low.
REBALANCE_EVERY_TICKS = 5
DRIFT_LIMIT = 0.27            # force a rebalance if any holding drifts above this
VOL_DAYS = 20                # realized-vol window for sizing the growth core
FAST_SMA = 50                # the primary risk-off switch — reacts fast enough to
SLOW_SMA = 200               # cap a vol-spike drawdown; 200-day is the trend confirm
MAX_W = 0.24                 # hard headroom under the 30% concentration cap
CASH_FLOOR = 0.10            # never fully invested — the money-market instinct
VOL_TARGET = 0.010           # ~1.0%/day SPY vol; above this we cut the growth sleeve
VOL_FLOOR = 0.25             # vol scalar clamp [0.25, 1.0] — a vol spike can cut the
VOL_CAP_MULT = 1.0           # growth sleeve to 1/4 BEFORE the SMA gate even flips

# Soham's book, expressed as ETFs in the challenge universe:
GROWTH = ("SMH", "QQQ", "XLK", "XLV")   # semis + Nasdaq + tech + quality/health ballast
# Risk-off ballast = what actually holds up when tech rolls over: GOLD + a low-vol
# defensive (utilities). NOT energy/miners — in Soham's book those are risk-ON cyclical
# diversifiers that fall WITH the market in a broad spike, so they're a poor crash hedge.
HEDGE = ("GLD", "XLU")

# How much of equity to deploy in each regime (rest is cash). The hedge is sized
# modestly because even gold can wobble — in risk-off, CASH is still the biggest
# position, exactly like the 42% money-market buffer in the fund book.
RISK_ON_EXPOSURE = 0.90     # leaves the 10% cash floor
RISK_OFF_HEDGE = 0.30       # a real-asset ballast, not an all-in bet — rest is cash


def _closes(bars):
    return [float(b["close"]) for b in bars] if bars else []


def _sma(bars, days):
    c = _closes(bars)
    return mean(c[-days:]) if len(c) >= days else None


def _vol(bars, days):
    c = _closes(bars)[-(days + 1):]
    if len(c) < 8:
        return None
    rets = [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1] > 0]
    if len(rets) < 5:
        return None
    v = pstdev(rets)
    return v if v > 1e-6 else 1e-6


def _inv_vol_weights(market_state, names, budget):
    """Split `budget` across `names` inversely to 20-day vol; each capped at MAX_W."""
    inv = {}
    for t in names:
        v = _vol(market_state.get(t) or [], VOL_DAYS)
        if v is not None and market_state.get(t):
            inv[t] = 1.0 / v
    if not inv:
        return {}
    total = sum(inv.values())
    return {t: min((x / total) * budget, MAX_W) for t, x in inv.items()}


def _target_weights(market_state):
    """Risk-on: vol-weighted AI/tech growth core. Risk-off: real-asset hedge + cash."""
    spy = market_state.get("SPY") or []
    closes = _closes(spy)
    fast = _sma(spy, FAST_SMA)
    slow = _sma(spy, SLOW_SMA)

    # Trend gate: FAST 50-day is the primary risk-off switch (reacts quickly enough to
    # cap a vol-spike drawdown); the 200-day, when we have it, must also confirm the
    # uptrend. If there's no 50-day yet, stay defensive rather than guess.
    if not (closes and fast is not None):
        risk_on = False
    elif slow is not None:
        risk_on = closes[-1] > fast and closes[-1] > slow
    else:
        risk_on = closes[-1] > fast

    if not risk_on:
        # Risk-off: rotate a modest slice into the real-asset ballast, rest stays cash.
        return _inv_vol_weights(market_state, HEDGE, RISK_OFF_HEDGE)

    # Risk-on: vol-target the growth sleeve — cut exposure as SPY vol rises (Soham's
    # low-vol instinct), so a calm tape gets the full 90% and a jittery one gets less.
    spy_vol = _vol(spy, VOL_DAYS)
    scalar = VOL_CAP_MULT
    if spy_vol:
        scalar = max(VOL_FLOOR, min(VOL_CAP_MULT, VOL_TARGET / spy_vol))
    return _inv_vol_weights(market_state, GROWTH, RISK_ON_EXPOSURE * scalar)


def decide(market_state, portfolio_state, cash):
    global _tick, _last_rebalance
    _tick += 1
    positions = {p["ticker"]: p for p in portfolio_state.get("positions", [])}
    last = portfolio_state.get("last_prices", {})
    equity = portfolio_state.get("cash", cash) + sum(
        p["quantity"] * last.get(t, p.get("avg_cost", 0)) for t, p in positions.items()
    )
    if equity <= 0:
        return []

    drifted = any(
        p["quantity"] * last.get(t, p.get("avg_cost", 0)) / equity > DRIFT_LIMIT
        for t, p in positions.items()
    )
    if (_tick - _last_rebalance < REBALANCE_EVERY_TICKS) and not drifted:
        return []

    targets = _target_weights(market_state)   # may be {} → means "go to cash"

    orders = []
    # 1) Exit anything not in the current target sleeve (this is the risk-off flush).
    for t, p in positions.items():
        if t not in targets and p["quantity"] > 0:
            orders.append({"ticker": t, "side": "sell", "quantity": p["quantity"]})
    # 2) Move each target to its weight.
    for t, weight in targets.items():
        bars = market_state.get(t)
        if not bars:
            continue
        px = float(bars[-1]["close"])
        if px <= 0:
            continue
        cur = positions.get(t, {}).get("quantity", 0)
        dq = int((equity * weight - cur * px) // px)
        if abs(dq * px) < 0.02 * equity:   # ignore dust trades
            continue
        if dq > 0:
            orders.append({"ticker": t, "side": "buy", "quantity": dq})
        elif dq < 0 and cur > 0:
            orders.append({"ticker": t, "side": "sell", "quantity": min(abs(dq), cur)})

    if orders:
        _last_rebalance = _tick
    return orders
