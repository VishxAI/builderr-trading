"""QQQ buy-and-hold — the market benchmark ("the bar to beat").

Buys the Nasdaq-100 ETF (QQQ) with the full account on the first scored day and
holds it, untouched, for the whole round. This is the passive market return: if a
strategy can't beat simply holding the index, it isn't really adding anything.

It is a BENCHMARK LINE, not a prize competitor — shown on the board as the bar to
clear, the same way the RambleFix line works on the speech-to-text board. Scored
by the exact same fill model as every bot (buys at the open + slippage, marks to
the close), so the number is honest, not hand-set.
"""
from __future__ import annotations


def decide(market_state, portfolio_state, cash):
    positions = portfolio_state.get("positions") or []
    # Buy once, then hold forever: if we already hold QQQ, do nothing.
    if any(str(p.get("ticker")) == "QQQ" and float(p.get("quantity") or 0) > 0 for p in positions):
        return []
    px = (portfolio_state.get("last_prices") or {}).get("QQQ")
    try:
        px = float(px)
        cash_avail = float(portfolio_state.get("cash", cash))
    except (TypeError, ValueError):
        return []
    if px <= 0 or cash_avail <= 0:
        return []
    qty = int(cash_avail // px)  # run_bot fills at the open and caps to cash
    if qty <= 0:
        return []
    return [{"ticker": "QQQ", "side": "buy", "quantity": float(qty)}]
