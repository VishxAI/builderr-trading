"""builderr fairness tests — PUBLISHED FOR AUDIT.

These run on our private scoring engine (so you cannot execute them from this
repo), but here is the actual source so you can see exactly what \"fair\" means:
same code + same data => identical result, and the same order => the same fill
regardless of which agent sent it. If these ever failed, the leaderboard would
be untrustworthy. This is the real file from our test suite, unedited below.
"""

"""Fairness / determinism evals — the platform's #1 credibility property.

These exist to answer one question publicly: "is the leaderboard rigged?"
They prove two guarantees:

1. SAME code + SAME data  =>  SAME result   (determinism: re-running can't change your score)
2. SAME order, regardless of WHICH agent sent it  =>  SAME fill   (no agent gets special treatment)

If either ever breaks, the leaderboard is not trustworthy and these tests fail loudly.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from builderr.harness import AgentProcess, AgentSession, Tick
from builderr.risk.exposure import ExposureTracker
from builderr.risk.portfolio import PortfolioState
from builderr.sim.fills import Fill, FillSimulator, Order

AGENT_DIR = Path(__file__).parent / "_agents"


def _ts(i: int = 0) -> datetime:
    return datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc) + timedelta(minutes=i)


def _bar(open_=550.0, high=551.0, low=549.0, close=550.5, volume=10_000_000):
    s = pd.Series({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
    s.name = _ts(0)
    return s


def _tick(i: int, universe=("SPY",)):
    return Tick(
        timestamp=_ts(i),
        bars={t: pd.DataFrame() for t in universe},
        portfolio=PortfolioState(cash=100_000, timestamp=_ts(i)),
        universe=list(universe),
    )


def _run(agent_file: str):
    proc = AgentProcess(AGENT_DIR / agent_file, python_executable=sys.executable)
    sim = FillSimulator()
    tracker = ExposureTracker()
    next_bars = {"SPY": _bar(open_=550.0)}

    def lookup(ticker, _ts_arg):
        return next_bars.get(ticker)

    session = AgentSession(
        process=proc, simulator=sim, tracker=tracker,
        next_bar_lookup=lookup, starting_cash=100_000,
    )
    return session.run([_tick(i) for i in range(4)])


# --- Guarantee 1: same code + same data => same result ----------------------


def test_same_agent_same_result_is_deterministic():
    """Re-running identical code on identical data must produce an identical score.

    If this fails, a builder's leaderboard position could change on a re-run —
    which would make the whole competition meaningless.
    """
    r1 = _run("buy_spy_once_agent.py")
    r2 = _run("buy_spy_once_agent.py")

    assert r1.total_fills == r2.total_fills
    assert r1.final_portfolio.cash == r2.final_portfolio.cash
    assert r1.final_portfolio.positions.keys() == r2.final_portfolio.positions.keys()
    for tkr in r1.final_portfolio.positions:
        assert (
            r1.final_portfolio.positions[tkr].quantity
            == r2.final_portfolio.positions[tkr].quantity
        )
        assert (
            r1.final_portfolio.positions[tkr].avg_cost
            == r2.final_portfolio.positions[tkr].avg_cost
        )


def test_noop_agent_is_a_clean_zero():
    """A no-trade agent always ends exactly where it started — no hidden drift."""
    r = _run("noop_agent.py")
    assert r.total_fills == 0
    assert r.final_portfolio.cash == 100_000
    assert r.final_portfolio.positions == {}


# --- Guarantee 2: identical order => identical fill, regardless of agent -----


def test_identical_orders_get_identical_fills():
    """Two different agents submitting the same order get byte-identical fills.

    The fill engine never looks at *who* sent the order — only the order + the
    market bar. No agent can get a better price than another for the same action.
    """
    sim = FillSimulator()
    bar = _bar(open_=550.0)

    order_from_agent_a = Order("SPY", "buy", 100, _ts(0), client_order_id="agent-A")
    order_from_agent_b = Order("SPY", "buy", 100, _ts(0), client_order_id="agent-B")

    fill_a = sim.fill(order_from_agent_a, bar)
    fill_b = sim.fill(order_from_agent_b, bar)

    assert isinstance(fill_a, Fill) and isinstance(fill_b, Fill)
    assert fill_a.price == fill_b.price
    assert fill_a.quantity == fill_b.quantity
    assert fill_a.slippage_bps == fill_b.slippage_bps
    # only the client_order_id (identity tag) differs
    assert fill_a.client_order_id != fill_b.client_order_id


def test_same_ticker_same_slippage_for_everyone():
    """Slippage is a function of the instrument, not the agent. TQQQ always 10bps,
    SPY always 5bps — for every submission."""
    sim = FillSimulator()
    bar = _bar(open_=80.0)
    spy = sim.fill(Order("SPY", "buy", 10, _ts(0)), bar)
    tqqq = sim.fill(Order("TQQQ", "buy", 10, _ts(0)), bar)
    assert spy.slippage_bps == 5.0      # plain equity
    assert tqqq.slippage_bps == 10.0    # leveraged ETF — same rule for all agents
