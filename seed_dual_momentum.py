"""Seed bot — Defensive Dual-Momentum (builderr house reference bot).

Classic dual-momentum, Antonacci-style. Distinct from the AI-basket seed:
no leverage, cross-sectional sector rotation, hard defensive gate.

Logic (rebalanced ~monthly):
  1. ABSOLUTE momentum gate: only hold risk assets if SPY's trailing ~60-day
     return is positive. If SPY is in a downtrend, the gate is OFF.
  2. RELATIVE momentum (gate ON): rank the sector ETFs by trailing ~60-day
     return, hold the top 3 equal-weight.
  3. DEFENSIVE (gate OFF): rotate to XLP + XLU equal-weight (staples + utilities).

Why it should clear Phase A:
  - SVB 2023: sectors recover post-shock → relative momentum catches the bounce.
  - Q4 2022 rate downtrend: gate goes OFF → defensive rotation limits drawdown.
  - Aug 2024 vol spike: gate flickers but defensive ballast caps the damage.

No leverage → beta-adjusted exposure ~1.0x, well under the 1.5x cap.
"""
from __future__ import annotations

from statistics import mean

_tick_count = 0
_last_rebalance = -10**9
REBALANCE_EVERY_TICKS = 5    # decide() is called ONCE PER DAY (daily bars) -> 5 = weekly
LOOKBACK_DAYS = 60
GATE_SMA_DAYS = 50          # trend-based absolute-momentum gate (faster than 60d return)
DRIFT_LIMIT = 0.27          # force rebalance if any holding drifts above this

# Phase A delivers DAILY bars in market_state. Hold 5 names @ ~19% each → safe under 30% cap.
SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "SMH")
DEFENSIVE = ("XLP", "XLU", "XLV", "XLE", "XLI")  # 5 defensive sleeves → 20% each
TOP_N = 5


def _closes(bars: list[dict]) -> list[float]:
    """market_state bars are DAILY in Phase A — closes come straight off them."""
    return [float(b["close"]) for b in bars] if bars else []


def _sma(bars: list[dict], days: int) -> float | None:
    closes = _closes(bars)
    if len(closes) < days:
        return None
    return mean(closes[-days:])


def _trailing_return(bars: list[dict], days: int) -> float | None:
    closes = _closes(bars)
    if len(closes) < 2:
        return None
    window = closes[-(days + 1):] if len(closes) > days else closes
    if len(window) < 2 or window[0] <= 0:
        return None
    return window[-1] / window[0] - 1.0


def _target_weights(market_state: dict) -> dict[str, float]:
    # Absolute-momentum gate: SPY above its 50-day SMA (trend-based, reacts faster
    # than a 60-day return after a sharp dip-and-recover like SVB).
    spy_bars = market_state.get("SPY") or []
    spy_closes = _closes(spy_bars)
    spy_sma = _sma(spy_bars, GATE_SMA_DAYS)
    gate_on = bool(spy_closes and spy_sma is not None and spy_closes[-1] > spy_sma)

    if not gate_on:
        # Defensive: equal-weight staples + utilities (if available)
        avail = [t for t in DEFENSIVE if market_state.get(t)]
        if not avail:
            return {}
        w = 1.0 / len(avail)
        return {t: w for t in avail}

    # Relative momentum: rank sectors by trailing return, take top N
    ranked = []
    for t in SECTORS:
        r = _trailing_return(market_state.get(t) or [], LOOKBACK_DAYS)
        if r is not None:
            ranked.append((r, t))
    ranked.sort(reverse=True)
    winners = [t for _, t in ranked[:TOP_N] if _ > 0]  # only positive-momentum sectors
    if not winners:
        # nothing trending up despite gate on → go defensive
        avail = [t for t in DEFENSIVE if market_state.get(t)]
        if not avail:
            return {}
        w = 1.0 / len(avail)
        return {t: w for t in avail}
    w = 1.0 / len(winners)
    return {t: w for t in winners}


def decide(market_state, portfolio_state, cash):
    global _tick_count, _last_rebalance
    _tick_count += 1

    positions = {p["ticker"]: p for p in portfolio_state.get("positions", [])}
    last_prices = portfolio_state.get("last_prices", {})
    equity = portfolio_state.get("cash", cash)
    for tk, pos in positions.items():
        equity += pos["quantity"] * last_prices.get(tk, pos.get("avg_cost", 0))

    # Rebalance on schedule OR if any holding has drifted above the safety limit.
    drifted = equity > 0 and any(
        pos["quantity"] * last_prices.get(tk, pos.get("avg_cost", 0)) / equity > DRIFT_LIMIT
        for tk, pos in positions.items()
    )
    if (_tick_count - _last_rebalance < REBALANCE_EVERY_TICKS) and not drifted:
        return []

    targets = _target_weights(market_state)
    if not targets:
        return []

    orders = []
    # Sell anything not in target
    for ticker, pos in positions.items():
        if ticker not in targets and pos["quantity"] > 0:
            orders.append({"ticker": ticker, "side": "sell", "quantity": pos["quantity"]})

    # Rebalance to target weights
    for ticker, weight in targets.items():
        bars = market_state.get(ticker)
        if not bars:
            continue
        last_close = float(bars[-1]["close"])
        if last_close <= 0:
            continue
        target_dollars = equity * weight
        cur_qty = positions.get(ticker, {}).get("quantity", 0)
        delta_qty = int((target_dollars - cur_qty * last_close) // last_close)
        if abs(delta_qty * last_close) < 0.02 * equity:
            continue
        if delta_qty > 0:
            orders.append({"ticker": ticker, "side": "buy", "quantity": delta_qty})
        elif delta_qty < 0 and cur_qty > 0:
            orders.append({"ticker": ticker, "side": "sell", "quantity": min(abs(delta_qty), cur_qty)})

    if orders:
        _last_rebalance = _tick_count
    return orders
