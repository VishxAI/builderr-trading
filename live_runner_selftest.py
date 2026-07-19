"""Focused checks for live_runner.py.

Run:
    python live_runner_selftest.py
"""
from __future__ import annotations

import live_runner


def _bar(ts: str, open_: float, close: float) -> dict:
    return {
        "ts": ts,
        "open": open_,
        "high": max(open_, close),
        "low": min(open_, close),
        "close": close,
        "volume": 1_000_000,
    }


def _buy_one_qqq(_market_state: dict, portfolio_state: dict, _cash: float) -> list[dict]:
    if portfolio_state.get("positions"):
        return []
    return [{"ticker": "QQQ", "side": "buy", "quantity": 1}]


def test_same_day_entry_scores_opening_session() -> None:
    bars = {
        "QQQ": [
            _bar("2026-07-06", 100.0, 100.0),
            _bar("2026-07-07", 100.0, 110.0),
        ],
    }

    result = live_runner.run_bot(_buy_one_qqq, bars, "2026-07-07")

    assert result["days"] == 1, result
    assert result["trades"] == 1, result
    assert result["equity"] > live_runner.START_CASH, result


def test_future_entry_does_not_backfill() -> None:
    bars = {
        "QQQ": [
            _bar("2026-07-06", 100.0, 100.0),
            _bar("2026-07-07", 100.0, 110.0),
        ],
    }

    result = live_runner.run_bot(_buy_one_qqq, bars, "2026-07-08")

    assert result["days"] == 0, result
    assert result["trades"] == 0, result
    assert result["equity"] == live_runner.START_CASH, result


def run() -> None:
    test_same_day_entry_scores_opening_session()
    test_future_entry_does_not_backfill()
    print("live_runner_selftest: PASS")


if __name__ == "__main__":
    run()
