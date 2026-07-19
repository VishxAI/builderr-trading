"""Baseline strategy: equal-weight buy-and-hold of 4 broad ETFs, then hold.

This is the simplest thing that actually gets ADMITTED — your 5-minute first
submission. Rename it to agent.py, run `python preview.py`, see it clear the
safety bar, and submit. Then iterate to actually compete.

Why 4 names at 25% each, not 2 at 50%? The concentration cap is <30% per ticker.
Two equal-weight names = 50% each = an instant breach. Four = 25% each = clean.
That single rule is the most common reason a naive bot gets rejected — run
preview.py and you'll watch a 2-name version fail and this one pass.

This buys and holds, so it will score poorly on Calmar in the live test (no
risk-off, no rotation). See https://builderr.ai/start for the strategy families
that actually win — then tweak this into one of them.
"""
from __future__ import annotations

_bought = False
# Four liquid, broad ETFs — 25% each keeps every position under the 30% cap.
_TARGETS = ("SPY", "QQQ", "XLK", "XLV")


def decide(market_state, portfolio_state, cash):
    global _bought
    if _bought:
        return []

    orders = []
    per_ticker_cash = cash / len(_TARGETS)
    for t in _TARGETS:
        bars = market_state.get(t) or []
        if not bars:
            return []  # data not ready yet; try again next tick
        last_close = float(bars[-1]["close"])
        if last_close <= 0:
            return []
        qty = int(per_ticker_cash // last_close)
        if qty > 0:
            orders.append({"ticker": t, "side": "buy", "quantity": qty})

    if orders:
        _bought = True
    return orders
