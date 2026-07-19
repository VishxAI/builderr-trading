"""Reference bot — Sector Momentum Rotation (Faber-style).

Built purely from public best practices (Meb Faber sector rotation + SMA risk-off
filter — the most-documented retail systematic strategy). A cold-start builder
could write this from a weekend of reading.

Rule, rebalanced ~weekly:
  1. MARKET FILTER: if SPY is below its 50-day SMA → risk-off (staples + cash).
  2. Otherwise rank the 11 sector ETFs by 60-day total return; hold the top 4
     equal-weight (~24% each, safely under the 30% concentration cap).
No leverage → ~1.0x beta-adjusted exposure.

Public sources this is based on: Faber's "A Quantitative Approach to Tactical
Asset Allocation", StockCharts sector-rotation model, Quantpedia sector momentum.
"""
from __future__ import annotations

from statistics import mean

_tick = 0
_last_rebalance = -10**9
REBALANCE_EVERY_TICKS = 5    # decide() is called ONCE PER DAY (daily bars) -> 5 = weekly
DRIFT_LIMIT = 0.27
MOMENTUM_DAYS = 60
SMA_DAYS = 50

SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "SMH", "XLRE", "XLC")
DEFENSIVE = ("XLP", "XLU", "XLV")   # 3 sleeves @ 25% + 25% cash when risk-off
TOP_N = 4


def _closes(bars):
    return [float(b["close"]) for b in bars] if bars else []


def _ret(bars, days):
    c = _closes(bars)
    if len(c) < 2:
        return None
    w = c[-(days + 1):] if len(c) > days else c
    return (w[-1] / w[0] - 1.0) if w[0] > 0 else None


def _sma(bars, days):
    c = _closes(bars)
    return mean(c[-days:]) if len(c) >= days else None


def _targets(ms):
    spy = ms.get("SPY") or []
    closes = _closes(spy)
    sma = _sma(spy, SMA_DAYS)
    risk_on = bool(closes and sma is not None and closes[-1] > sma)

    if not risk_on:
        avail = [t for t in DEFENSIVE if ms.get(t)]
        return {t: 0.25 for t in avail} if avail else {}

    ranked = sorted(
        ((_ret(ms.get(t) or [], MOMENTUM_DAYS), t)
         for t in SECTORS if _ret(ms.get(t) or [], MOMENTUM_DAYS) is not None),
        reverse=True,
    )
    winners = [t for r, t in ranked[:TOP_N] if r > 0]
    if not winners:
        avail = [t for t in DEFENSIVE if ms.get(t)]
        return {t: 0.25 for t in avail} if avail else {}
    w = 0.96 / len(winners)   # ~24% each, headroom under the 30% cap
    return {t: w for t in winners}


def decide(market_state, portfolio_state, cash):
    global _tick, _last_rebalance
    _tick += 1
    positions = {p["ticker"]: p for p in portfolio_state.get("positions", [])}
    last = portfolio_state.get("last_prices", {})
    equity = portfolio_state.get("cash", cash) + sum(
        p["quantity"] * last.get(t, p.get("avg_cost", 0)) for t, p in positions.items()
    )
    drifted = equity > 0 and any(
        p["quantity"] * last.get(t, p.get("avg_cost", 0)) / equity > DRIFT_LIMIT
        for t, p in positions.items()
    )
    if (_tick - _last_rebalance < REBALANCE_EVERY_TICKS) and not drifted:
        return []

    targets = _targets(market_state)
    if not targets:
        return []

    orders = []
    for t, p in positions.items():
        if t not in targets and p["quantity"] > 0:
            orders.append({"ticker": t, "side": "sell", "quantity": p["quantity"]})
    for t, weight in targets.items():
        bars = market_state.get(t)
        if not bars:
            continue
        px = float(bars[-1]["close"])
        if px <= 0:
            continue
        cur = positions.get(t, {}).get("quantity", 0)
        dq = int((equity * weight - cur * px) // px)
        if abs(dq * px) < 0.02 * equity:
            continue
        if dq > 0:
            orders.append({"ticker": t, "side": "buy", "quantity": dq})
        elif dq < 0 and cur > 0:
            orders.append({"ticker": t, "side": "sell", "quantity": min(abs(dq), cur)})

    if orders:
        _last_rebalance = _tick
    return orders
