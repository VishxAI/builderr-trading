"""Strategy-level checks for agent.py (Rotor).

No network, no private engine, no third-party packages. These are not the
official builderr evals; they catch contract, cap, and regime bugs before
submission.

Run:
    python strategy_selftest.py
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import agent


UNIVERSE = (
    "SPY", "QQQ", "DIA", "IWM",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLRE", "XLC", "SMH", "SOXX",
    "NVDA", "MSFT", "AAPL", "META", "AMZN", "GOOGL", "AVGO", "AMD", "MU", "MRVL",
    "NFLX", "TSLA", "PLTR", "ORCL", "CRM", "JPM", "V", "MA", "COST", "LLY",
    "QLD", "SSO", "TQQQ",
)


def bars(start: float, returns: list[float]) -> list[dict]:
    out = []
    px = start
    d = date(2024, 1, 1)
    for r in returns:
        px *= 1.0 + r
        out.append({
            "ts": d.isoformat(),
            "open": px,
            "high": px * 1.01,
            "low": px * 0.99,
            "close": px,
            "volume": 1_000_000,
        })
        d += timedelta(days=1)
    return out


def market(kind: str) -> dict[str, list[dict]]:
    n = 120
    if kind == "risk_off":
        # Everything grinding down; defensives quietly positive.
        base = [-0.004] * n
        defensive = [0.0006] * n
        return {t: bars(100.0, defensive if t in {"XLP", "XLU", "XLV"} else base)
                for t in UNIVERSE}

    if kind == "rotation":
        # QQQ/tech broken, but financials/health/defensives in clean uptrends
        # (breadth alive) — the state machine should stay invested, not hide.
        down = [-0.003] * n
        up = [0.002] * n
        data = {t: bars(100.0, down) for t in UNIVERSE}
        for t in ("JPM", "V", "MA", "LLY", "COST", "XLF", "XLV", "XLP", "XLU",
                  "XLI", "XLE", "DIA", "IWM", "SPY"):
            data[t] = bars(100.0, up)
        data["SPY"] = bars(100.0, [0.0008] * n)   # SPY holding above trend
        return data

    if kind == "high_vol":
        calm_up = [0.002] * n
        chop = [0.035, -0.03] * (n // 2)
        data = {t: bars(100.0, calm_up) for t in UNIVERSE}
        data["QQQ"] = bars(100.0, chop)
        return data

    # calm risk-on with differentiated leaders
    data = {t: bars(100.0, [0.001] * n) for t in UNIVERSE}
    for t in ("SMH", "NVDA", "XLK"):
        data[t] = bars(100.0, [0.004] * n)
    for t in ("QQQ", "AAPL", "META"):
        data[t] = bars(100.0, [0.0025] * n)
    data["SPY"] = bars(100.0, [0.0018] * n)
    data["QLD"] = bars(100.0, [0.0048] * n)
    data["TQQQ"] = bars(100.0, [0.0072] * n)
    return data


def reset_state() -> None:
    agent._state = "OFF"
    agent._crash_cooldown = 0
    agent._up_streak = 5
    agent._peak_equity = 0.0
    agent._pos_high = {}
    agent._stop_block = {}
    agent._last_rebalance_date = None
    agent._last_seen_date = None
    agent._prev_state = "OFF"
    agent._prev_taper = 1.0


def targets_for(kind: str, state: str) -> dict[str, float]:
    return agent._targets(state, 1.0, market(kind), {}, {}, set())


def beta_gross(weights: dict[str, float]) -> float:
    return sum(w * agent.BETA.get(t, 1.0) for t, w in weights.items())


def test_empty_data_returns_no_orders() -> None:
    reset_state()
    assert agent.decide({}, {"cash": 100_000, "positions": [], "last_prices": {}}, 100_000) == []


def test_crash_state_is_flat() -> None:
    assert targets_for("risk_on", "CRASH") == {}


def test_off_state_holds_only_defensives() -> None:
    w = targets_for("risk_off", "OFF")
    assert w, "defensive sleeve should exist when defensives trend up"
    assert set(w).issubset(set(agent.DEFENSIVES))
    assert sum(w.values()) <= agent.DEF_BUDGET + 1e-9


def test_rotation_market_stays_invested() -> None:
    ms = market("rotation")
    cache: dict = {}
    feats = agent._market_features(ms, cache)
    assert feats is not None
    assert feats["breadth"] >= agent.BREADTH_SOFT, feats["breadth"]
    state = agent._next_state(feats, "SOFT")
    assert state in ("SOFT", "ON"), state
    w = agent._targets(state, 1.0, ms, {}, {}, set())
    assert w, "rotation regime should hold the trending half of the market"
    assert all(t not in ("QQQ", "XLK", "SMH", "NVDA") for t in w), w


def test_risk_on_selects_leaders() -> None:
    w = targets_for("risk_on", "FULL")
    assert {"SMH", "NVDA", "XLK"} & set(w), w
    assert len(w) >= 3


def test_full_state_gates_sleeve_by_vol() -> None:
    w_calm = targets_for("risk_on", "FULL")
    assert ("TQQQ" in w_calm) or ("QLD" in w_calm), w_calm
    w_vol = targets_for("high_vol", "FULL")
    assert "TQQQ" not in w_vol and "QLD" not in w_vol, w_vol


def test_cluster_cap_diversifies() -> None:
    w = targets_for("risk_on", "FULL")
    semis = [t for t in w if agent.CLUSTERS.get(t) == "semi"]
    assert len(semis) <= agent.CLUSTER_MAX, w


def test_caps_hold_in_all_states() -> None:
    for kind in ("risk_off", "rotation", "high_vol", "risk_on"):
        for state in ("OFF", "SOFT", "ON", "FULL"):
            w = agent._targets(state, 1.0, market(kind), {}, {}, set())
            assert all(v < agent.NAME_CAP + 1e-6 for v in w.values()), (kind, state, w)
            assert beta_gross(w) <= agent.MAX_BETA_GROSS + 1e-6, (kind, state, w)


def test_orders_are_bounded_fast_and_idempotent() -> None:
    reset_state()
    m = market("risk_on")
    latest = {t: b[-1]["close"] for t, b in m.items()}
    portfolio = {"cash": 100_000.0, "positions": [], "last_prices": latest}
    start = time.perf_counter()
    orders = agent.decide(m, portfolio, 100_000.0)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.25, elapsed
    assert 0 < len(orders) <= agent.MAX_ORDERS, len(orders)
    assert all(o["side"] in {"buy", "sell"} and o["quantity"] > 0 for o in orders)
    # same bar date again -> no second full rebalance
    assert agent.decide(m, portfolio, 100_000.0) == []


def test_decide_never_raises_on_garbage() -> None:
    reset_state()
    garbage = {"SPY": [{"ts": "2024-01-01", "close": "not-a-number"}]}
    assert agent.decide(garbage, {"cash": None, "positions": [{"bad": 1}]}, None) == []


def run() -> None:
    tests = [
        test_empty_data_returns_no_orders,
        test_crash_state_is_flat,
        test_off_state_holds_only_defensives,
        test_rotation_market_stays_invested,
        test_risk_on_selects_leaders,
        test_full_state_gates_sleeve_by_vol,
        test_cluster_cap_diversifies,
        test_caps_hold_in_all_states,
        test_orders_are_bounded_fast_and_idempotent,
        test_decide_never_raises_on_garbage,
    ]
    for test in tests:
        test()
    print(f"OK: {len(tests)} strategy checks passed.")


if __name__ == "__main__":
    run()
