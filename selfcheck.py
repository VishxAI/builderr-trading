"""Local self-check — runs WITHOUT the builderr engine, no network, no keys.

This is NOT the real eval (we run that centrally on hidden market data so it's
identical for everyone). It's a smoke test so you're not flying blind: it loads
your agent, feeds it synthetic daily bars, and checks that decide() returns
well-formed orders and doesn't crash. Catch the dumb bugs before you submit.

    python selfcheck.py                       # checks agent.py
    python selfcheck.py example_sector_rotation.py
"""
from __future__ import annotations

import importlib.util
import random
import re
import sys
from pathlib import Path

UNIVERSE = [
    "SPY", "QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP",
    "XLU", "XLRE", "XLC", "KRE", "JPM", "TQQQ", "SOXL", "NVDA", "MSFT", "AAPL", "META",
]

# Your repo is likely public — a committed key leaks to everyone. We scan for the
# obvious ones before you push. High-confidence patterns FAIL; loose ones only warn.
_HIGH = [
    ("OpenAI/Anthropic-style key", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
_LOOSE = re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{16,}['\"]")
_SKIP_DIRS = {".git", "venv", ".venv", "node_modules", "__pycache__", ".idea", ".vscode"}
_SCAN_EXT = {".py", ".env", ".txt", ".json", ".cfg", ".ini", ".yml", ".yaml", ".toml", ".sh", ".md"}


def _scan_secrets(root: Path, self_name: str):
    high, warn = [], []
    for p in root.rglob("*"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file() or p.name == self_name:
            continue
        if p.name in (".env", ".env.local") or (p.suffix in _SCAN_EXT and p.stat().st_size < 1_000_000):
            try:
                text = p.read_text(errors="ignore")
            except OSError:
                continue
            if p.name in (".env", ".env.local"):
                warn.append((p.name, 0, "committed .env file — keep keys out of the repo"))
            for i, line in enumerate(text.splitlines(), 1):
                for label, rx in _HIGH:
                    if rx.search(line):
                        high.append((p.name, i, label))
                if _LOOSE.search(line):
                    warn.append((p.name, i, "looks like a hardcoded secret"))
    return high, warn


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("agent", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "decide"), "your file must define decide(market_state, portfolio_state, cash)"
    return mod.decide


def _synth_bars(days: int = 240, start: float = 100.0):
    bars, px = [], start * random.uniform(0.5, 3.0)
    for i in range(days):
        px *= 1 + random.uniform(-0.02, 0.02)
        bars.append({
            "ts": f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": 1_000_000,
        })
    return bars


def main() -> int:
    agent_file = sys.argv[1] if len(sys.argv) > 1 else "agent.py"
    decide = _load(Path(__file__).parent / agent_file)

    market = {t: _synth_bars() for t in UNIVERSE}
    portfolio = {
        "cash": 100_000.0,
        "positions": [],
        "last_prices": {t: market[t][-1]["close"] for t in UNIVERSE},
    }

    steps, total_orders = 0, 0
    for _ in range(12):
        out = decide(market, portfolio, portfolio["cash"])
        assert isinstance(out, list), f"decide() must return a list, got {type(out).__name__}"
        for o in out:
            assert isinstance(o, dict), f"each order must be a dict, got {o!r}"
            assert {"ticker", "side", "quantity"} <= set(o), f"order missing keys: {o!r}"
            assert o["side"] in ("buy", "sell"), f"side must be 'buy' or 'sell': {o!r}"
            assert float(o["quantity"]) > 0, f"quantity must be > 0: {o!r}"
            assert o["ticker"] in UNIVERSE, f"ticker not in the universe: {o['ticker']!r}"
        total_orders += len(out)
        steps += 1

    print(f"✓ {agent_file} loaded and ran {steps} steps cleanly.")
    print(f"  {total_orders} well-formed orders emitted across the run.")
    print("  Smoke test only — real admission runs centrally on hidden market data.")

    high, warn = _scan_secrets(Path(__file__).parent, Path(__file__).name)
    for f, ln, why in warn:
        loc = f"{f}:{ln}" if ln else f
        print(f"  ⚠ possible secret in {loc} — {why}")
    if high:
        print("\n✗ SECRET DETECTED — do NOT push this repo until you remove it:")
        for f, ln, label in high:
            print(f"    {f}:{ln}  ({label})")
        print("  Your repo is public-readable; a committed key leaks to everyone.")
        print("  Use endpoint mode or a capped throwaway key, and never commit secrets.")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"✗ FAILED: {e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"✗ CRASHED: {e!r}")
        sys.exit(1)
