"""Reference bot — Volatility-Targeted Trend (a different family from rotation).

Built from public best practices (inverse-volatility position sizing + a 50-day
SMA risk-off switch — both heavily documented; see Man Group / Concretum on
vol-targeting, Faber on SMA risk-off).

Rule, rebalanced ~weekly:
  1. Always considers a core risk basket (SPY, QQQ, SMH, XLK, XLV).
  2. Weight each name INVERSELY to its 20-day realized volatility — calmer names
     get more capital (raises risk-adjusted return). Each capped at 28% (< 30%).
  3. RISK-OFF: if SPY < its 50-day SMA, scale total exposure down to ~30%
     (the rest sits in cash) — the single biggest drawdown reducer.
No leverage.
"""
from __future__ import annotations

from statistics import mean, pstdev

_tick = 0
_last_rebalance = -10**9
REBALANCE_EVERY_TICKS = 5    # decide() is called ONCE PER DAY (daily bars) -> 5 = weekly
DRIFT_LIMIT = 0.27
VOL_DAYS = 20
SMA_DAYS = 50
CORE = ("SPY", "QQQ", "SMH", "XLK", "XLV")
MAX_W = 0.28


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


def _targets(ms):
    spy = ms.get("SPY") or []
    closes = _closes(spy)
    sma = _sma(spy, SMA_DAYS)
    risk_on = bool(closes and sma is not None and closes[-1] > sma)
    exposure = 0.95 if risk_on else 0.30   # scale total book by trend

    inv = {}
    for t in CORE:
        v = _vol(ms.get(t) or [], VOL_DAYS)
        if v is not None and ms.get(t):
            inv[t] = 1.0 / v
    if not inv:
        return {}
    total = sum(inv.values())
    weights = {}
    for t, x in inv.items():
        w = min((x / total) * exposure, MAX_W)
        weights[t] = w
    return weights


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
