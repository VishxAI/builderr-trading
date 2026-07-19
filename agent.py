"""Rotor — breadth-aware rotation momentum with a gated convexity sleeve.

Design thesis (July 2026): the field is index-gated momentum. When QQQ breaks
trend, those bots go to cash even while half the universe (financials, health,
quality) is in a clean uptrend. Rotor's regime machine reads market health from
BREADTH as well as index trend, so a rotation is a tradable state, not a
risk-off state. A five-state ladder sets gross; a momentum ranker picks the
strongest names from stocks AND sector sleeves; ATR-scaled trailing stops
replace fixed-percent stops so volatile leaders aren't whipsawed out.

States:
  CRASH  hard brake (fast index drop / vol explosion)          -> 100% cash
  OFF    both indices broken, breadth dead                     -> small defensive sleeve + cash
  SOFT   indices mixed but breadth alive (rotation regime)     -> top names at ~60% gross
  ON     at least one index healthy, breadth OK                -> top names at ~90% gross
  FULL   both indices healthy, breadth strong, vol contained   -> ~76% core + 2x/3x sleeve (~1.4x beta)

Safety: equity-drawdown taper, beta-gross target clamp 1.40x (drift headroom
under the 1.5x rule), per-name cap 25% (drift-trim 27.5%), tight trim bands on
leveraged names, sell-before-buy, buys capped to cash, deterministic, stdlib
only, and decide() can never raise (state snapshot/restore).
"""
from __future__ import annotations

import math
from statistics import pstdev
from typing import Any, Optional

# ---- knobs (tuner-adjustable via module attributes) -------------------------
MOM_L: int = 42          # long momentum lookback
MOM_S: int = 21          # short momentum lookback
MOM_A: int = 10          # acceleration lookback
W_L: float = 0.35
W_S: float = 0.30
W_A: float = 0.15
W_GAP: float = 0.10
VOL_PEN: float = 0.15    # score penalty x annualized vol20 (kills high-vol zombies)
REQ_R21: float = 0.0     # qualifier: 21d momentum must exceed this (kills dead runs)
RECOVERY_R10: float = 0.06  # ...unless 10d thrust exceeds this (V-bottom recovery catch)
STICKY: float = 0.0      # optional incumbent bonus (0 = pure ranks; churn earns its keep)
NAME_SMA: int = 50
IDX_FAST: int = 20
IDX_SLOW: int = 50
RECLAIM_BAND: float = 0.005
EXIT_BAND: float = 0.010
THRUST_RET: float = 0.08      # QQQ 10-day thrust for fast re-entry
BRAKE_QQQ_R3: float = -0.055
BRAKE_SPY_R3: float = -0.045
BRAKE_QQQ_V10: float = 0.55
BRAKE_SPY_V10: float = 0.45
CRASH_COOLDOWN: int = 2
VOL_FULL: float = 0.27        # QQQ vol20 ceiling for FULL
VOL_TQQQ: float = 0.24        # tighter ceiling for the 3x sleeve
VOL_QLD: float = 0.28
BREADTH_FULL: float = 0.55
BREADTH_ON: float = 0.42
BREADTH_SOFT: float = 0.28
BREADTH_TQQQ: float = 0.55
SOFT_SPY_FLOOR: float = 0.965  # SPY must be within 3.5% of SMA50 for SOFT
TOP_K: int = 4
NAME_CAP: float = 0.25
DRIFT_LIMIT: float = 0.275
CORE_FULL: float = 0.76
CORE_ON: float = 0.90
CORE_SOFT: float = 0.60
DEF_BUDGET: float = 0.35       # OFF-state defensive sleeve
CONFIRM_DAYS: int = 2          # index must hold its trend this many days before upgrades
SLEEVE_TQQQ: float = 0.22
SLEEVE_QLD: float = 0.24
MAX_BETA_GROSS: float = 1.40  # target clamp; leaves drift headroom under the 1.5x DQ line
DD_HALF: float = -0.06
DD_LOCK: float = -0.10
TAPER_HALF: float = 0.55
TAPER_LOCK: float = 0.30
STOP_ATR_MULT: float = 3.0
STOP_MIN: float = 0.10
STOP_MAX: float = 0.20
STOP_LEV: float = 0.12
STOP_BLOCK_DAYS: int = 2
REBALANCE_DAYS: int = 1
MIN_TRADE_PCT: float = 0.025
CASH_BUFFER: float = 0.98
MAX_ORDERS: int = 45
MIN_BARS: int = 60

STOCKS: tuple[str, ...] = (
    "NVDA", "MSFT", "AAPL", "META", "AMZN", "GOOGL", "AVGO", "AMD", "MU", "MRVL",
    "NFLX", "TSLA", "PLTR", "ORCL", "CRM", "JPM", "V", "MA", "COST", "LLY",
)
SECTOR_ETFS: tuple[str, ...] = (
    "XLV", "XLF", "XLI", "XLE", "XLP", "XLU", "XLY", "XLC", "SMH", "IWM", "DIA",
)
CANDIDATES: tuple[str, ...] = tuple(dict.fromkeys(STOCKS + SECTOR_ETFS))
DEFENSIVES: tuple[str, ...] = ("XLP", "XLU", "XLV")
# Correlation clusters: cap picks per cluster so the book is never one trade.
CLUSTERS: dict[str, str] = {
    "NVDA": "semi", "AMD": "semi", "MU": "semi", "MRVL": "semi", "AVGO": "semi",
    "SMH": "semi", "SOXX": "semi",
    "MSFT": "tech", "AAPL": "tech", "META": "tech", "AMZN": "tech",
    "GOOGL": "tech", "NFLX": "tech", "ORCL": "tech", "CRM": "tech",
    "TSLA": "tech", "PLTR": "tech", "XLC": "tech", "XLY": "tech",
    "JPM": "fin", "V": "fin", "MA": "fin", "XLF": "fin",
    "LLY": "health", "XLV": "health",
    "XLP": "def", "XLU": "def",
    "XLI": "cyc", "XLE": "cyc", "IWM": "cyc", "DIA": "cyc", "COST": "cyc",
}
CLUSTER_MAX: int = 2
BETA: dict[str, float] = {
    "QLD": 2.0, "SSO": 2.0, "DDM": 2.0, "ROM": 2.0, "UWM": 2.0, "AGQ": 2.0,
    "TQQQ": 3.0, "SOXL": 3.0, "UPRO": 3.0, "SPXL": 3.0, "TNA": 3.0, "FAS": 3.0,
    "TECL": 3.0, "LABU": 3.0, "CURE": 3.0, "DRN": 3.0, "UDOW": 3.0, "NAIL": 3.0,
}
_STATE_RANK = {"CRASH": 0, "OFF": 1, "SOFT": 2, "ON": 3, "FULL": 4}

# ---- persistent state -------------------------------------------------------
_state: str = "OFF"
_crash_cooldown: int = 0
_up_streak: int = 0
_peak_equity: float = 0.0
_pos_high: dict[str, float] = {}
_stop_block: dict[str, int] = {}
_last_rebalance_date: Optional[str] = None
_last_seen_date: Optional[str] = None
_prev_state: str = "OFF"
_prev_taper: float = 1.0


# ---- pure helpers -----------------------------------------------------------
def _beta(t: str) -> float:
    return BETA.get(t, 1.0)


def _closes(ms: dict, t: str, cache: dict) -> Optional[list[float]]:
    if t in cache:
        return cache[t]
    out = None
    bars = ms.get(t)
    if bars:
        try:
            out = [float(b["close"]) for b in bars]
        except (KeyError, TypeError, ValueError):
            out = None
    cache[t] = out
    return out


def _ok(cs: Optional[list[float]], n: int = MIN_BARS) -> bool:
    return cs is not None and len(cs) >= n and cs[-1] > 0.0


def _sma(cs: list[float], n: int) -> Optional[float]:
    if len(cs) < n:
        return None
    return sum(cs[-n:]) / n


def _ret(cs: list[float], k: int) -> Optional[float]:
    if len(cs) < k + 1 or cs[-(k + 1)] <= 0.0:
        return None
    return cs[-1] / cs[-(k + 1)] - 1.0


def _vol(cs: list[float], n: int) -> Optional[float]:
    if len(cs) < n + 1:
        return None
    w = cs[-(n + 1):]
    rets = []
    for i in range(1, len(w)):
        if w[i - 1] <= 0.0:
            return None
        rets.append(w[i] / w[i - 1] - 1.0)
    if len(rets) < 2:
        return None
    return pstdev(rets) * math.sqrt(252.0)


def _atr_pct(ms: dict, t: str, n: int = 14) -> Optional[float]:
    bars = ms.get(t)
    if not bars or len(bars) < n + 1:
        return None
    trs = []
    try:
        for i in range(len(bars) - n, len(bars)):
            h = float(bars[i]["high"])
            lo = float(bars[i]["low"])
            pc = float(bars[i - 1]["close"])
            trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
        px = float(bars[-1]["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if px <= 0.0 or len(trs) < n:
        return None
    return (sum(trs) / len(trs)) / px


def _score(cs: list[float]) -> Optional[float]:
    rl, rs, ra = _ret(cs, MOM_L), _ret(cs, MOM_S), _ret(cs, MOM_A)
    sma = _sma(cs, NAME_SMA)
    v = _vol(cs, 20)
    if rl is None or rs is None or ra is None or sma is None or sma <= 0.0 or v is None:
        return None
    if rs <= REQ_R21 and ra <= RECOVERY_R10:
        # a red last month is a dying run — unless a fresh 10d thrust says V-recovery
        return None
    gap = cs[-1] / sma - 1.0
    return W_L * rl + W_S * rs + W_A * ra + W_GAP * gap - VOL_PEN * v


# ---- portfolio helpers ------------------------------------------------------
def _resolve_cash(ps: dict, cash: float) -> float:
    try:
        return float(ps.get("cash", cash))
    except (TypeError, ValueError):
        try:
            return float(cash)
        except (TypeError, ValueError):
            return 0.0


def _positions(ps: dict) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for raw in ps.get("positions", []) or []:
        try:
            t = str(raw["ticker"]).upper()
            q = float(raw.get("quantity", 0.0))
            ac = float(raw.get("avg_cost", 0.0))
        except (KeyError, TypeError, ValueError):
            continue
        if q <= 0.0:
            continue
        if t in out:
            tot = out[t]["quantity"] + q
            out[t]["avg_cost"] = (
                (out[t]["avg_cost"] * out[t]["quantity"] + ac * q) / tot if tot > 0 else ac
            )
            out[t]["quantity"] = tot
        else:
            out[t] = {"quantity": q, "avg_cost": ac}
    return out


def _price(t: str, ms: dict, cache: dict, last: dict) -> Optional[float]:
    cs = _closes(ms, t, cache)
    if cs and cs[-1] > 0.0:
        return cs[-1]
    lp = last.get(t)
    try:
        if lp is not None and float(lp) > 0.0:
            return float(lp)
    except (TypeError, ValueError):
        pass
    return None


def _equity(pos: dict, ms: dict, cache: dict, last: dict, cash_v: float) -> float:
    tot = cash_v
    for t in sorted(pos):
        p = _price(t, ms, cache, last)
        if p is None:
            p = pos[t]["avg_cost"] if pos[t]["avg_cost"] > 0 else 0.0
        tot += pos[t]["quantity"] * max(p, 0.0)
    return max(tot, 0.0)


# ---- regime -----------------------------------------------------------------
def _market_features(ms: dict, cache: dict) -> Optional[dict]:
    spy = _closes(ms, "SPY", cache)
    qqq = _closes(ms, "QQQ", cache)
    if not _ok(spy) or not _ok(qqq):
        return None
    n_comp = n_up = 0
    for t in CANDIDATES:
        cs = _closes(ms, t, cache)
        if not _ok(cs):
            continue
        sma = _sma(cs, NAME_SMA)
        if sma is None:
            continue
        n_comp += 1
        if cs[-1] > sma:
            n_up += 1
    return {
        "spy": spy, "qqq": qqq,
        "spy_sma_f": _sma(spy, IDX_FAST), "spy_sma_s": _sma(spy, IDX_SLOW),
        "qqq_sma_f": _sma(qqq, IDX_FAST), "qqq_sma_s": _sma(qqq, IDX_SLOW),
        "qqq_r3": _ret(qqq, 3), "spy_r3": _ret(spy, 3),
        "qqq_r10": _ret(qqq, 10),
        "qqq_v10": _vol(qqq, 10), "spy_v10": _vol(spy, 10),
        "qqq_v20": _vol(qqq, 20),
        "breadth": (n_up / n_comp) if n_comp else 0.0,
    }


def _next_state(f: dict, prev: str) -> str:
    brake = (
        (f["qqq_r3"] is not None and f["qqq_r3"] < BRAKE_QQQ_R3)
        or (f["spy_r3"] is not None and f["spy_r3"] < BRAKE_SPY_R3)
        or (f["qqq_v10"] is not None and f["qqq_v10"] > BRAKE_QQQ_V10)
        or (f["spy_v10"] is not None and f["spy_v10"] > BRAKE_SPY_V10)
    )
    if brake:
        return "CRASH"

    spy_c, qqq_c = f["spy"][-1], f["qqq"][-1]
    b = f["breadth"]

    def above(px: float, sma: Optional[float], band: float) -> bool:
        return sma is not None and px > sma * (1.0 + band)

    spy_up = above(spy_c, f["spy_sma_s"], RECLAIM_BAND)
    qqq_up = above(qqq_c, f["qqq_sma_s"], RECLAIM_BAND)
    spy_fast_up = above(spy_c, f["spy_sma_f"], 0.0)
    qqq_fast_up = above(qqq_c, f["qqq_sma_f"], 0.0)
    spy_hold = f["spy_sma_s"] is not None and spy_c > f["spy_sma_s"] * SOFT_SPY_FLOOR
    vol_ok = f["qqq_v20"] is not None and f["qqq_v20"] < VOL_FULL

    # Fast re-entry: a genuine V-thrust re-opens risk without waiting for SMA50.
    thrust = (
        f["qqq_r10"] is not None and f["qqq_r10"] > THRUST_RET
        and f["qqq_sma_f"] is not None and qqq_c > f["qqq_sma_f"]
        and len(f["qqq"]) >= 2 and qqq_c > f["qqq"][-2]
    )

    if spy_up and qqq_up and spy_fast_up and qqq_fast_up and b >= BREADTH_FULL and vol_ok:
        target = "FULL"
    elif (spy_up or qqq_up) and b >= BREADTH_ON:
        target = "ON"
    elif b >= BREADTH_SOFT and spy_hold:
        target = "SOFT"
    else:
        target = "OFF"

    # Confirmation: upgrades to ON/FULL need the index trend held CONFIRM_DAYS in
    # a row (a one-day bear-rally poke over the SMA can't drag us to 90% gross).
    # A genuine thrust bypasses the wait. Downgrades are never delayed.
    if (
        _STATE_RANK[target] >= _STATE_RANK["ON"]
        and _STATE_RANK[target] > _STATE_RANK[prev]
        and _up_streak < CONFIRM_DAYS
        and not thrust
    ):
        target = "SOFT" if _STATE_RANK[prev] <= _STATE_RANK["SOFT"] else prev

    # Hysteresis: coming out of OFF/CRASH, cap at SOFT unless a reclaim or thrust.
    if prev in ("OFF", "CRASH") and _STATE_RANK[target] >= _STATE_RANK["ON"]:
        if not (spy_up and qqq_up) and not thrust:
            target = "SOFT"
    return target


# ---- targets ----------------------------------------------------------------
def _rank(ms: dict, cache: dict, block: dict, held: set[str]) -> list[tuple[float, str]]:
    out = []
    for t in CANDIDATES:
        if t in block:
            continue
        cs = _closes(ms, t, cache)
        if not _ok(cs):
            continue
        sc = _score(cs)
        sma = _sma(cs, NAME_SMA)
        if sc is None or sma is None:
            continue
        if t in held:
            sc += STICKY  # incumbents keep their seat unless clearly outscored
        if sc > 0.0 and cs[-1] > sma:
            out.append((sc, t))
    out.sort(key=lambda p: (-p[0], p[1]))
    return out


def _targets(state: str, taper: float, ms: dict, cache: dict, block: dict,
             held: set[str]) -> dict[str, float]:
    w: dict[str, float] = {}
    if state == "CRASH":
        return w

    if state == "OFF":
        # Defensive sleeve: best two defensives above their own trend, small.
        scored = []
        for t in DEFENSIVES:
            cs = _closes(ms, t, cache)
            if not _ok(cs) or t in block:
                continue
            r = _ret(cs, MOM_S)
            sma = _sma(cs, NAME_SMA)
            if r is not None and sma is not None and cs[-1] > sma:
                scored.append((r, t))
        scored.sort(key=lambda p: (-p[0], p[1]))
        per = (DEF_BUDGET * taper) / 2.0
        for _, t in scored[:2]:
            w[t] = per
        return w

    core = {"SOFT": CORE_SOFT, "ON": CORE_ON, "FULL": CORE_FULL}[state] * taper
    ranked = _rank(ms, cache, block, held)
    picks: list[tuple[float, str]] = []
    cluster_count: dict[str, int] = {}
    for sc, t in ranked:  # greedy top-K under the per-cluster cap
        c = CLUSTERS.get(t, t)
        if cluster_count.get(c, 0) >= CLUSTER_MAX:
            continue
        picks.append((sc, t))
        cluster_count[c] = cluster_count.get(c, 0) + 1
        if len(picks) >= TOP_K:
            break
    if not picks:
        return w
    per = min(core / len(picks), NAME_CAP)
    for _, t in picks:
        w[t] = per

    if state == "FULL":
        f_qqq = _closes(ms, "QQQ", cache)
        v20 = _vol(f_qqq, 20) if f_qqq else None
        sma_f = _sma(f_qqq, IDX_FAST) if f_qqq else None
        sma_s = _sma(f_qqq, IDX_SLOW) if f_qqq else None
        n_comp = n_up = 0
        for t in CANDIDATES:
            cs = _closes(ms, t, cache)
            if not _ok(cs):
                continue
            sma = _sma(cs, NAME_SMA)
            if sma is None:
                continue
            n_comp += 1
            if cs[-1] > sma:
                n_up += 1
        breadth = (n_up / n_comp) if n_comp else 0.0
        strong = (
            v20 is not None and sma_f is not None and sma_s is not None
            and sma_f > sma_s and breadth >= BREADTH_TQQQ
        )
        if strong and v20 < VOL_TQQQ and "TQQQ" not in block and _ok(_closes(ms, "TQQQ", cache), 30):
            w["TQQQ"] = min(SLEEVE_TQQQ * taper, NAME_CAP)
        elif v20 is not None and v20 < VOL_QLD and "QLD" not in block and _ok(_closes(ms, "QLD", cache), 30):
            w["QLD"] = min(SLEEVE_QLD * taper, NAME_CAP)

    gross = sum(v * _beta(t) for t, v in w.items())
    if gross > MAX_BETA_GROSS:
        scale = MAX_BETA_GROSS / gross
        w = {t: v * scale for t, v in w.items()}
    return {t: v for t, v in w.items() if v > 0.001}


# ---- orders -----------------------------------------------------------------
def _orders(do_reb: bool, w: dict, pos: dict, stops: list, equity: float,
            ms: dict, cache: dict, last: dict, cash_v: float) -> list[dict]:
    orders: list[dict] = []
    sold: set[str] = set()
    proceeds = 0.0
    min_trade = MIN_TRADE_PCT * equity

    for t, q in stops:
        if q > 0.0:
            orders.append({"ticker": t, "side": "sell", "quantity": q})
            sold.add(t)
            p = _price(t, ms, cache, last)
            if p:
                proceeds += q * p

    if do_reb:
        for t in sorted(pos):
            if t in sold:
                continue
            held = pos[t]["quantity"]
            if held <= 0.0:
                continue
            tw = w.get(t, 0.0)
            p = _price(t, ms, cache, last)
            if tw == 0.0:
                orders.append({"ticker": t, "side": "sell", "quantity": held})
                sold.add(t)
                if p and p > 0:
                    proceeds += held * p
                continue
            if p is None or p <= 0.0:
                continue
            tgt = math.floor(tw * equity / p)
            delta = tgt - held
            # Leveraged names trim on a much tighter band: sleeve drift is what
            # pushes realized beta-gross toward the 1.5x line.
            trim_band = min_trade * (0.3 if _beta(t) > 1.0 else 1.0)
            if delta < 0 and (-delta) * p >= trim_band:
                q = float(int(min(-delta, held)))
                if q > 0.0:
                    orders.append({"ticker": t, "side": "sell", "quantity": q})
                    sold.add(t)
                    proceeds += q * p

        spend = cash_v + CASH_BUFFER * proceeds
        for t in sorted(w, key=lambda k: (-w[k], k)):
            p = _price(t, ms, cache, last)
            if p is None or p <= 0.0:
                continue
            held = pos[t]["quantity"] if t in pos else 0.0
            tgt = math.floor(w[t] * equity / p)
            deficit = tgt - held
            if deficit > 0 and deficit * p >= min_trade:
                afford = math.floor(min(deficit * p, spend) / p)
                if afford > 0:
                    orders.append({"ticker": t, "side": "buy", "quantity": float(afford)})
                    spend -= afford * p

    if len(orders) > MAX_ORDERS:
        sells = [o for o in orders if o["side"] == "sell"]
        buys = [o for o in orders if o["side"] == "buy"]
        orders = (sells + buys)[:MAX_ORDERS]
    return [o for o in orders if o["quantity"] > 0.0]


# ---- decide -----------------------------------------------------------------
def decide(market_state: dict, portfolio_state: dict, cash: float) -> list[dict]:
    """Return long-only buy/sell orders; guaranteed never to raise."""
    global _state, _crash_cooldown, _peak_equity, _pos_high, _stop_block
    global _last_rebalance_date, _last_seen_date, _prev_state, _prev_taper, _up_streak

    snap = (_state, _crash_cooldown, _peak_equity, dict(_pos_high),
            dict(_stop_block), _last_rebalance_date, _last_seen_date,
            _prev_state, _prev_taper, _up_streak)
    try:
        return _run(market_state or {}, portfolio_state or {}, cash)
    except Exception:  # noqa: BLE001
        (_state, _crash_cooldown, _peak_equity, _pos_high, _stop_block,
         _last_rebalance_date, _last_seen_date, _prev_state, _prev_taper,
         _up_streak) = snap
        return []


def _run(ms: dict, ps: dict, cash: float) -> list[dict]:
    global _state, _crash_cooldown, _peak_equity, _pos_high, _stop_block
    global _last_rebalance_date, _last_seen_date, _prev_state, _prev_taper, _up_streak

    if not ms:
        return []
    cache: dict = {}
    last = {str(k).upper(): v for k, v in (ps.get("last_prices", {}) or {}).items()}
    cash_v = _resolve_cash(ps, cash)

    spy_bars = ms.get("SPY") or []
    cur_date = None
    if spy_bars:
        ts = spy_bars[-1].get("ts")
        cur_date = str(ts)[:10] if ts is not None else str(len(spy_bars))

    feats = _market_features(ms, cache)
    pos = _positions(ps)

    if feats is None:  # data guard: liquidate what we can, stay consistent
        orders = []
        for t in sorted(pos):
            if ms.get(t) and pos[t]["quantity"] > 0.0:
                orders.append({"ticker": t, "side": "sell", "quantity": pos[t]["quantity"]})
        _prev_state, _prev_taper = _state, 1.0
        if cur_date is not None:
            _last_seen_date = cur_date
        return orders

    new_day = cur_date != _last_seen_date
    if new_day:
        if _crash_cooldown > 0:
            _crash_cooldown -= 1
        if _stop_block:
            _stop_block = {t: d - 1 for t, d in _stop_block.items() if d - 1 > 0}
        idx_up = (
            feats["spy_sma_s"] is not None
            and feats["spy"][-1] > feats["spy_sma_s"] * (1.0 + RECLAIM_BAND)
        ) or (
            feats["qqq_sma_s"] is not None
            and feats["qqq"][-1] > feats["qqq_sma_s"] * (1.0 + RECLAIM_BAND)
        )
        _up_streak = _up_streak + 1 if idx_up else 0

    equity = _equity(pos, ms, cache, last, cash_v)
    if equity <= 0.0:
        _prev_state, _prev_taper, _last_seen_date = _state, 1.0, cur_date
        return []
    _peak_equity = max(_peak_equity, equity)
    dd = equity / _peak_equity - 1.0 if _peak_equity > 0 else 0.0
    taper = TAPER_LOCK if dd <= DD_LOCK else (TAPER_HALF if dd <= DD_HALF else 1.0)

    nxt = _next_state(feats, _state)
    if nxt == "CRASH":
        _crash_cooldown = CRASH_COOLDOWN
    elif _crash_cooldown > 0 and _STATE_RANK[nxt] > _STATE_RANK["SOFT"]:
        nxt = "SOFT"  # post-crash: re-risk through SOFT first
    _state = nxt

    # trailing stops (ATR-scaled; fixed for leveraged names)
    for t in list(_pos_high):
        if t not in pos:
            del _pos_high[t]
    forced: list[tuple[str, float]] = []
    for t in sorted(pos):
        p = _price(t, ms, cache, last)
        if p is None:
            continue
        hi = max(_pos_high.get(t, p), p)
        _pos_high[t] = hi
        if _beta(t) > 1.0:
            trail = STOP_LEV
        else:
            a = _atr_pct(ms, t)
            trail = min(max(STOP_ATR_MULT * a, STOP_MIN), STOP_MAX) if a else STOP_MIN
        if hi > 0.0 and p < hi * (1.0 - trail):
            forced.append((t, pos[t]["quantity"]))
            _stop_block[t] = STOP_BLOCK_DAYS
            _pos_high.pop(t, None)

    # rebalance gate
    if _last_rebalance_date is None:
        do_reb = True
    else:
        elapsed = {str(b.get("ts", ""))[:10] for b in spy_bars
                   if str(b.get("ts", ""))[:10] > _last_rebalance_date}
        derisk = _STATE_RANK[_state] < _STATE_RANK[_prev_state] or taper < _prev_taper
        drift = False
        for t, pdata in pos.items():
            p = _price(t, ms, cache, last)
            if p is not None and equity > 0 and (pdata["quantity"] * p / equity) > DRIFT_LIMIT:
                drift = True
                break
        do_reb = len(elapsed) >= REBALANCE_DAYS or derisk or drift
    if _last_rebalance_date == cur_date:
        do_reb = False

    w = _targets(_state, taper, ms, cache, _stop_block, set(pos)) if do_reb else {}
    orders = _orders(do_reb, w, pos, forced, equity, ms, cache, last, cash_v)
    if do_reb and orders:
        _last_rebalance_date = cur_date

    _prev_state, _prev_taper, _last_seen_date = _state, taper, cur_date
    return orders
