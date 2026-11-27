#!/usr/bin/env python3
"""env.py - Self-contained, strictly causal RL trading environment.

The environment is intentionally independent of any backtesting framework.
It consumes the prepared signal datasets of the three turning-point profiles
(``ml4t``, ``baseline``, ``sma_auto``) and builds its own MDP:

    state_t  -> action_t -> position_t -> reward_{t+1}

Causality
---------
At bar ``t`` the agent only sees information up to and including bar ``t``
(signal probabilities, raw/market features, its own position/account state).
The action is executed at ``close_t`` and the reward is realised with the
return from ``close_t`` to ``close_{t+1}``.  No future bar is ever read.

Data
----
* Raw OHLCV series: ``<data_root>/raw_data/*.csv`` (27 ticker/timeframe files)
* Signal models:    ``<data_root>/production_models/<profile>/active``
* Prepared feature CSVs per profile:
    - baseline -> ``prepared_data``
    - ml4t     -> ``runs/eval_3ways/_data/ml4t_tol2``
    - sma_auto -> ``runs/eval_3ways/_data/sma5_tol2``

The prepared CSVs already contain the exact feature columns used by the
corresponding checkpoint, so no TA-Lib dependency is required here.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import gymnasium as gym
from gymnasium import spaces

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_data_root() -> str:
    """Locate the prepareTraining data root whether rl_trader is inside or beside it."""
    env_root = os.environ.get("RL_DATA_ROOT")
    if env_root:
        return os.path.abspath(env_root)
    candidates = [
        HERE,
        os.path.abspath(os.path.join(HERE, "..")),
        os.path.abspath(os.path.join(HERE, "..", "prepareTraining")),
        os.getcwd(),
    ]
    for cand in candidates:
        if (os.path.isdir(os.path.join(cand, "raw_data"))
                and os.path.isdir(os.path.join(cand, "prepared_data"))):
            return cand
    return os.path.abspath(os.path.join(HERE, "..", "prepareTraining"))


DEFAULT_DATA_ROOT = _find_data_root()

# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------
PROFILE_SPECS: Dict[str, Dict[str, str]] = {
    "ml4t": {
        "model_dir": "production_models/ml4t_opt/active",
        "data_dir": "runs/eval_3ways/_data/ml4t_tol2",
    },
    "baseline": {
        "model_dir": "production_models/baseline_opt/active",
        "data_dir": "prepared_data",
    },
    "sma_auto": {
        "model_dir": "production_models/sma_auto_opt/active",
        "data_dir": "runs/eval_3ways/_data/sma5_tol2",
    },
}
PROFILE_CHOICES = ("ml4t", "baseline", "sma_auto")
TIMEFRAME_CHOICES = ("1Hour", "15Min", "5Min")


def _normalize_tf_arg(value) -> List[str]:
    """Accept ``None``, a CSV string or a sequence and return a clean list."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",")]
    else:
        items = [str(v).strip() for v in value]
    return [v for v in items if v]


def resolve_timeframes(include=None, exclude=None) -> Optional[List[str]]:
    """Resolve ``--timeframes`` / ``--exclude-timeframes`` to a canonical list.

    Returns ``None`` when no filter is active (all timeframes).
    """
    inc = _normalize_tf_arg(include)
    exc = set(_normalize_tf_arg(exclude))
    invalid = [tf for tf in inc + list(exc) if tf not in TIMEFRAME_CHOICES]
    if invalid:
        raise ValueError(
            f"Invalid timeframe(s) {sorted(set(invalid))}; choose from {TIMEFRAME_CHOICES}"
        )
    if inc:
        selected = [tf for tf in TIMEFRAME_CHOICES if tf in inc and tf not in exc]
    elif exc:
        selected = [tf for tf in TIMEFRAME_CHOICES if tf not in exc]
    else:
        return None
    if not selected:
        raise ValueError("Timeframe filter removed all timeframes.")
    return selected


# ---------------------------------------------------------------------------
# Model definition (mirrors train_turning_points.TurningPointMLP)
# ---------------------------------------------------------------------------
class TurningPointMLP(nn.Module):
    def __init__(self, in_features: int, hidden_dims: Sequence[int],
                 dropout: float = 0.35, num_classes: int = 3):
        super().__init__()
        layers: List[nn.Module] = []
        prev = in_features
        for h in hidden_dims:
            layers.extend([nn.Linear(prev, h), nn.BatchNorm1d(h), nn.SiLU(), nn.Dropout(dropout)])
            prev = h
        layers.append(nn.Linear(prev, num_classes))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # pragma: no cover - trivial
        return self.net(x)


def suppress_signal_clusters(probs: np.ndarray, threshold: float,
                             cooldown_bars: int = 5) -> np.ndarray:
    """Non-maximum suppression of turning-point signals (class ids 0/1/2)."""
    n = len(probs)
    raw = np.ones(n, dtype=int)
    high_mask = probs[:, 0] >= threshold
    low_mask = probs[:, 2] >= threshold
    both = high_mask & low_mask
    high_mask = high_mask & (~both | (probs[:, 0] >= probs[:, 2]))
    low_mask = low_mask & (~both | (probs[:, 2] > probs[:, 0]))
    raw[high_mask] = 0
    raw[low_mask] = 2

    filtered = raw.copy()
    for cls in (0, 2):
        cand = np.where(raw == cls)[0]
        order = cand[np.argsort(probs[cand, cls])[::-1]]
        kept: List[int] = []
        for idx in order:
            if all(abs(idx - k) >= cooldown_bars for k in kept):
                kept.append(idx)
            else:
                filtered[idx] = 1
    return filtered


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_key(path: str) -> Tuple[str, str]:
    base = os.path.basename(path).replace(".csv", "")
    parts = base.split("_")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse ticker/timeframe from {path}")
    return parts[0], parts[1]


def _to_utc_ns(values) -> np.ndarray:
    t = pd.to_datetime(values, utc=True, errors="coerce")
    return t.values.astype("datetime64[ns]").astype(np.int64)


def _safe_load_torch(path: str, map_location="cpu"):
    try:
        return torch.load(path, map_location=map_location, weights_only=False)
    except TypeError:  # older torch
        return torch.load(path, map_location=map_location)


def _rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(x).rolling(window, min_periods=1).mean().to_numpy(dtype=float)


def _rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    return pd.Series(x).rolling(window, min_periods=2).std().to_numpy(dtype=float)


def _causal_mid(close: np.ndarray, window: int = 20) -> np.ndarray:
    """Causal rolling mean used as the mean-reversion reference."""
    mid = pd.Series(close).rolling(window, min_periods=1).mean().to_numpy(dtype=float)
    return np.where(np.isfinite(mid), mid, close)


def _cross_events(spread: np.ndarray) -> np.ndarray:
    """Sign-change events of a spread series (+1 upcross, -1 downcross)."""
    cross = np.zeros(len(spread), dtype=np.int8)
    for i in range(1, len(spread)):
        a, b = spread[i - 1], spread[i]
        if not (np.isfinite(a) and np.isfinite(b)):
            continue
        if a <= 0.0 < b:
            cross[i] = 1
        elif a >= 0.0 > b:
            cross[i] = -1
    return cross


def _market_features(df: pd.DataFrame) -> np.ndarray:
    """Causal, scale-free market/volatility features (n, 7).

    All features at row i use only rows <= i.
    """
    c = df["c"].to_numpy(dtype=float)
    h = df["h"].to_numpy(dtype=float)
    l = df["l"].to_numpy(dtype=float)
    n = len(c)
    c_prev = np.concatenate([[c[0]], c[:-1]])
    c_prev5 = np.concatenate([np.repeat(c[0], 5), c[:-5]]) if n > 5 else np.repeat(c[0], n)

    ret1 = np.log(np.maximum(c, 1e-12) / np.maximum(c_prev, 1e-12))
    ret5 = np.log(np.maximum(c, 1e-12) / np.maximum(c_prev5, 1e-12))

    tr = np.maximum.reduce([
        h - l,
        np.abs(h - c_prev),
        np.abs(l - c_prev),
    ])
    atr = _rolling_mean(tr, 14)
    atr = np.where(atr <= 0, np.nan, atr)

    sma38 = df["SMA(38)"].to_numpy(dtype=float) if "SMA(38)" in df else _rolling_mean(c, 38)
    sma80 = df["SMA(80)"].to_numpy(dtype=float) if "SMA(80)" in df else _rolling_mean(c, 80)
    sma38 = np.where(np.isfinite(sma38), sma38, _rolling_mean(c, 38))
    sma80 = np.where(np.isfinite(sma80), sma80, _rolling_mean(c, 80))

    range_norm = (h - l) / np.maximum(c, 1e-12)
    atr_norm = atr / np.maximum(c, 1e-12)
    dist38 = (c - sma38) / atr
    dist80 = (c - sma80) / atr
    vol20 = _rolling_std(ret1, 20)

    feats = np.column_stack([
        ret1 * 100.0,
        ret5 * 100.0,
        range_norm * 100.0,
        atr_norm * 100.0,
        dist38,
        dist80,
        vol20 * 100.0,
    ])
    feats = np.nan_to_num(feats, nan=0.0, posinf=0.0, neginf=0.0)
    feats = np.clip(feats, -10.0, 10.0)
    return feats.astype(np.float32)


# ---------------------------------------------------------------------------
# Signal generation from the stored production models
# ---------------------------------------------------------------------------
@torch.no_grad()
def _signals_for_profile(data_root: str, profile: str,
                         timeframes: Optional[Sequence[str]] = None) -> Dict[Tuple[str, str], pd.DataFrame]:
    spec = PROFILE_SPECS[profile]
    model_dir = os.path.join(data_root, spec["model_dir"])
    data_dir = os.path.join(data_root, spec["data_dir"])
    ckpt_path = os.path.join(model_dir, "turning_point_mlp.pt")
    scaler_path = os.path.join(model_dir, "feature_scaler.joblib")
    if not (os.path.isfile(ckpt_path) and os.path.isfile(scaler_path)):
        raise FileNotFoundError(f"Missing model artifacts for profile {profile}: {model_dir}")

    ckpt = _safe_load_torch(ckpt_path)
    scaler = joblib.load(scaler_path)
    feature_cols = list(ckpt["feature_cols"])
    model = TurningPointMLP(
        in_features=len(feature_cols),
        hidden_dims=list(ckpt["hidden_dims"]),
        dropout=float(ckpt.get("dropout", 0.0)),
        num_classes=3,
    )
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    threshold = float(ckpt.get("best_threshold", 0.5))
    cooldown = int(ckpt.get("cooldown_bars", 5))

    out: Dict[Tuple[str, str], pd.DataFrame] = {}
    tf_set = set(timeframes) if timeframes else None
    for path in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        _ticker_key, _tf_key = _parse_key(path)
        if tf_set is not None and _tf_key not in tf_set:
            continue
        df = pd.read_csv(path)
        missing = [c for c in feature_cols if c not in df.columns]
        if missing:
            raise ValueError(f"{path}: missing feature columns {missing[:5]}...")
        X = df[feature_cols].to_numpy(dtype=np.float32)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        Xs = scaler.transform(X)
        Xs = np.nan_to_num(Xs, nan=0.0, posinf=0.0, neginf=0.0)
        logits = model(torch.tensor(Xs, dtype=torch.float32))
        probs = torch.softmax(logits, dim=-1).numpy()

        raw_idx = suppress_signal_clusters(probs, threshold, cooldown_bars=1)
        filt_idx = suppress_signal_clusters(probs, threshold, cooldown_bars=cooldown)
        idx_to_turn = {0: -1, 1: 0, 2: 1}
        raw_turn = np.array([idx_to_turn[int(i)] for i in raw_idx], dtype=np.int8)
        filt_turn = np.array([idx_to_turn[int(i)] for i in filt_idx], dtype=np.int8)

        ticker = str(df["meta_ticker"].iloc[0])
        timeframe = str(df["meta_timeframe"].iloc[0])
        res = pd.DataFrame({
            "t_ns": _to_utc_ns(df["meta_t"]),
            "prob_bear": probs[:, 2].astype(np.float32),   # P(extreme high) -> short
            "prob_neutral": probs[:, 1].astype(np.float32),
            "prob_bull": probs[:, 0].astype(np.float32),   # P(extreme low)  -> long
            "raw_pred": raw_turn,
            "filt_pred": filt_turn,
        })
        out[(ticker, timeframe)] = res
    return out


# ---------------------------------------------------------------------------
# Series container
# ---------------------------------------------------------------------------
@dataclass
class SeriesData:
    ticker: str
    timeframe: str
    t_ns: np.ndarray            # (n,) int64 UTC ns
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    market: np.ndarray          # (n, 7) float32
    sma38: np.ndarray           # (n,) causal SMA(38)
    sma80: np.ndarray           # (n,) causal SMA(80)
    mid: np.ndarray             # (n,) rolling mean / mean-reversion reference
    sma_cross: np.ndarray       # (n,) int8: +1 upcross, -1 downcross, 0 none
    signals: Dict[str, np.ndarray] = field(default_factory=dict)  # profile -> (n, 8)
    raw_pred: Dict[str, np.ndarray] = field(default_factory=dict)
    filt_pred: Dict[str, np.ndarray] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.close)


SIGNAL_DIM = 8  # prob_bear, prob_neutral, prob_bull, raw, filt, conf, bars_since, strength
MARKET_DIM = 7
POSITION_DIM = 4


def _align_profile_signals(series: SeriesData, sig: pd.DataFrame,
                           master_t_ns: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Align a profile's per-bar signals onto the raw master timeline.

    Bars without a model signal (feature warm-up / dropped rows) are neutral.
    """
    n = len(master_t_ns)
    pos = {int(v): i for i, v in enumerate(sig["t_ns"].to_numpy())}
    src = np.array([pos.get(int(v), -1) for v in master_t_ns], dtype=np.int64)
    valid = src >= 0

    prob_bear = np.zeros(n, dtype=np.float32)
    prob_neutral = np.ones(n, dtype=np.float32)
    prob_bull = np.zeros(n, dtype=np.float32)
    raw = np.zeros(n, dtype=np.int8)
    filt = np.zeros(n, dtype=np.int8)
    if valid.any():
        prob_bear[valid] = sig["prob_bear"].to_numpy()[src[valid]]
        prob_neutral[valid] = sig["prob_neutral"].to_numpy()[src[valid]]
        prob_bull[valid] = sig["prob_bull"].to_numpy()[src[valid]]
        raw[valid] = sig["raw_pred"].to_numpy()[src[valid]]
        filt[valid] = sig["filt_pred"].to_numpy()[src[valid]]

    conf = np.maximum(prob_bear, prob_bull)
    strength = np.abs(prob_bull - prob_bear)
    bars_since = np.full(n, 100.0, dtype=np.float32)
    last = -1000
    for i in range(n):
        if filt[i] != 0:
            last = i
        bars_since[i] = min(i - last, 100)
    bars_norm = np.clip(bars_since / 20.0, 0.0, 1.0)

    feats = np.column_stack([
        prob_bear, prob_neutral, prob_bull,
        raw.astype(np.float32), filt.astype(np.float32),
        conf, bars_norm, strength,
    ]).astype(np.float32)
    return feats, raw, filt


def build_series(data_root: str = DEFAULT_DATA_ROOT,
                 profiles: Sequence[str] = ("ml4t",),
                 timeframes: Optional[Sequence[str]] = None,
                 mean_window: int = 20) -> Dict[Tuple[str, str], SeriesData]:
    """Build raw series annotated with the signals of ``profiles``.

    ``timeframes`` optionally restricts the build to e.g. ``["1Hour", "15Min"]``.
    ``mean_window`` controls the causal mean-reversion reference in ``SeriesData.mid``.
    """
    for p in profiles:
        if p not in PROFILE_SPECS:
            raise ValueError(f"Unknown profile {p!r}; choose from {PROFILE_CHOICES}")
    tf_set = set(timeframes) if timeframes else None
    if tf_set is not None:
        invalid = [tf for tf in tf_set if tf not in TIMEFRAME_CHOICES]
        if invalid:
            raise ValueError(f"Invalid timeframe(s) {sorted(invalid)}")

    raw_dir = os.path.join(data_root, "raw_data")
    if not os.path.isdir(raw_dir):
        raise FileNotFoundError(f"raw_data not found under {data_root}")

    signal_cache = {p: _signals_for_profile(data_root, p, timeframes=timeframes)
                    for p in profiles}

    series: Dict[Tuple[str, str], SeriesData] = {}
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.csv"))):
        ticker, timeframe = _parse_key(path)
        if tf_set is not None and timeframe not in tf_set:
            continue
        df = pd.read_csv(path)
        df = df.copy()
        df["_t"] = pd.to_datetime(df["t"], utc=True, errors="coerce")
        df = df[df["_t"].notna()].sort_values("_t", kind="mergesort")
        df = df.drop_duplicates(subset=["_t"], keep="last").reset_index(drop=True)
        t_ns = _to_utc_ns(df["_t"])
        close = df["c"].to_numpy(dtype=float)
        sma38 = (df["SMA(38)"].to_numpy(dtype=float)
                 if "SMA(38)" in df.columns else _rolling_mean(close, 38))
        sma80 = (df["SMA(80)"].to_numpy(dtype=float)
                 if "SMA(80)" in df.columns else _rolling_mean(close, 80))
        sma38 = np.where(np.isfinite(sma38), sma38, _rolling_mean(close, 38))
        sma80 = np.where(np.isfinite(sma80), sma80, _rolling_mean(close, 80))
        mid = _causal_mid(close, mean_window)
        sma_cross = _cross_events(sma38 - sma80)

        s = SeriesData(
            ticker=ticker,
            timeframe=timeframe,
            t_ns=t_ns,
            open=df["o"].to_numpy(dtype=float),
            high=df["h"].to_numpy(dtype=float),
            low=df["l"].to_numpy(dtype=float),
            close=close,
            volume=df["v"].to_numpy(dtype=float),
            market=_market_features(df),
            sma38=sma38.astype(np.float32),
            sma80=sma80.astype(np.float32),
            mid=mid.astype(np.float32),
            sma_cross=sma_cross,
        )
        for p in profiles:
            sig = signal_cache[p].get((ticker, timeframe))
            if sig is None:
                n = len(s)
                feats = np.zeros((n, SIGNAL_DIM), dtype=np.float32)
                feats[:, 1] = 1.0
                feats[:, 6] = 1.0
                raw = np.zeros(n, dtype=np.int8)
                filt = np.zeros(n, dtype=np.int8)
            else:
                feats, raw, filt = _align_profile_signals(s, sig, t_ns)
            s.signals[p] = feats
            s.raw_pred[p] = raw
            s.filt_pred[p] = filt
        series[(ticker, timeframe)] = s
    return series


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------
@dataclass
class SplitPools:
    train: List[Tuple[SeriesData, int, int]]
    val: List[Tuple[SeriesData, int, int]]
    test: List[Tuple[SeriesData, int, int]]
    oot: List[Tuple[SeriesData, int, int]]


def build_pools(series: Dict[Tuple[str, str], SeriesData],
                train_frac: float = 0.70, val_frac: float = 0.15,
                min_idx: int = 100,
                timeframes: Optional[Sequence[str]] = None,
                exclude_timeframes: Optional[Sequence[str]] = None,
                oot_tickers: Sequence[str] = ("AAPL",)) -> SplitPools:
    """Per-file chronological split; ``oot_tickers`` are fully held out.

    Optional timeframe filters make the split self-contained even if the caller
    passes an unfiltered ``series`` dict.
    """
    tf_set = set(timeframes) if timeframes else None
    exc_set = set(exclude_timeframes) if exclude_timeframes else set()
    oot_set = set(oot_tickers) if oot_tickers else {"AAPL"}
    pools = SplitPools(train=[], val=[], test=[], oot=[])
    for (ticker, _tf), s in series.items():
        if tf_set is not None and _tf not in tf_set:
            continue
        if _tf in exc_set:
            continue
        n = len(s)
        if n <= min_idx + 20:
            continue
        train_end = max(min_idx + 10, int(n * train_frac))
        val_end = max(train_end + 10, int(n * (train_frac + val_frac)))
        val_end = min(val_end, n - 1)
        train_end = min(train_end, val_end - 1)
        if ticker in oot_set:
            pools.oot.append((s, min_idx, n - 1))
        else:
            pools.train.append((s, min_idx, train_end))
            pools.val.append((s, train_end, val_end))
            pools.test.append((s, val_end, n - 1))
    return pools


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
class TradingEnv(gym.Env):
    """Causal discrete-action trading MDP.

    Observation
    -----------
    Per profile (8 values each):
        prob_bear, prob_neutral, prob_bull, raw_pred, filtered_pred,
        confidence, bars_since_signal (normalised), signal strength
    Market (7):
        ret1, ret5, normalised range, normalised ATR, dist SMA38, dist SMA80,
        rolling volatility
    Account (4):
        position (-1/0/+1), unrealised PnL, holding bars (normalised),
        current drawdown

    Actions
    -------
    0 = hold, 1 = long/target +1, 2 = short/target -1, 3 = close/target 0

    Reward
    ------
    ``scale * (position * next_return - costs)`` minus a drawdown-increase
    penalty and a small trade-friction penalty.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        series_pool: Sequence[Tuple[SeriesData, int, int]],
        profiles: Sequence[str] = ("ml4t",),
        episode_len: Optional[int] = 256,
        random_start: bool = True,
        cost_bps: float = 5.0,
        slippage_bps: float = 1.0,
        reward_scale: float = 100.0,
        dd_penalty: float = 0.10,
        trade_penalty: float = 0.01,
        signal_bonus: float = 0.0,
        signal_conf_min: float = 0.55,
        seed: int = 0,
    ):
        super().__init__()
        if not series_pool:
            raise ValueError("series_pool must not be empty")
        self.series_pool = list(series_pool)
        self.profiles = tuple(profiles)
        self.episode_len = episode_len
        self.random_start = random_start
        self.cost_rate = float(cost_bps + slippage_bps) / 10_000.0
        self.reward_scale = float(reward_scale)
        self.dd_penalty = float(dd_penalty)
        self.trade_penalty = float(trade_penalty)
        self.signal_bonus = float(signal_bonus)
        self.signal_conf_min = float(signal_conf_min)
        self.rng = np.random.default_rng(seed)

        self.obs_dim = SIGNAL_DIM * len(self.profiles) + MARKET_DIM + POSITION_DIM
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(self.obs_dim,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(4)

        self.series: Optional[SeriesData] = None
        self.start = 0
        self.end = 0
        self.idx = 0
        self.position = 0
        self.equity = 1.0
        self.peak = 1.0
        self.entry_price: Optional[float] = None
        self.holding = 0
        self.prev_dd = 0.0
        self.open_trade: Optional[dict] = None
        self.trade_log: List[dict] = []
        self.equity_curve: List[float] = []
        self.price_curve: List[float] = []
        self.position_curve: List[int] = []
        self.total_signals = 0
        self.signals_used = 0
        self.signals_ignored = 0
        self.standalone_trades = 0

    # ------------------------------------------------------------------
    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        series, start, end = self.series_pool[int(self.rng.integers(len(self.series_pool)))]
        end = min(end, len(series) - 1)
        if self.episode_len is not None:
            if self.random_start and end - start > self.episode_len:
                start = int(self.rng.integers(start, end - self.episode_len + 1))
                end = start + self.episode_len
            else:
                end = min(start + self.episode_len, end)
        if end <= start:
            end = min(start + 2, len(series) - 1)

        self.series = series
        self.start, self.end = int(start), int(end)
        self.idx = self.start
        self.position = 0
        self.equity = 1.0
        self.peak = 1.0
        self.entry_price = None
        self.holding = 0
        self.prev_dd = 0.0
        self.open_trade = None
        self.trade_log = []
        self.equity_curve = [1.0]
        self.price_curve = [float(series.close[self.idx])]
        self.position_curve = [0]
        self.total_signals = 0
        self.signals_used = 0
        self.signals_ignored = 0
        self.standalone_trades = 0
        return self._observation(), {}

    # ------------------------------------------------------------------
    def _observation(self) -> np.ndarray:
        s = self.series
        assert s is not None
        idx = self.idx
        parts: List[np.ndarray] = []
        for p in self.profiles:
            parts.append(s.signals[p][idx])
        market = s.market[idx]

        close = float(s.close[idx])
        if self.position != 0 and self.entry_price:
            unreal = self.position * (close / self.entry_price - 1.0)
        else:
            unreal = 0.0
        unreal = float(np.clip(unreal * 10.0, -1.0, 1.0))
        holding_norm = float(np.clip(self.holding / 50.0, 0.0, 1.0))
        dd = float(np.clip(1.0 - self.equity / max(self.peak, 1e-9), 0.0, 1.0))
        account = np.array([self.position, unreal, holding_norm, dd], dtype=np.float32)
        return np.concatenate(parts + [market, account]).astype(np.float32)

    # ------------------------------------------------------------------
    def current_signal(self) -> int:
        """Combined discrete signal at the current bar (-1/0/+1)."""
        s = self.series
        assert s is not None
        votes = 0
        for p in self.profiles:
            votes += int(s.filt_pred[p][self.idx])
        if votes > 0:
            return 1
        if votes < 0:
            return -1
        return 0

    def current_signal_conf(self) -> float:
        s = self.series
        assert s is not None
        if not self.profiles:
            return 0.0
        # signal feature column 5 is confidence
        return float(max(s.signals[p][self.idx, 5] for p in self.profiles))

    def action_for_direction(self, direction: int, cert_idx: Optional[int] = None,
                             size_idx: int = 0) -> int:
        """Classic env: 1=long, 2=short, 3=close."""
        if direction > 0:
            return 1
        if direction < 0:
            return 2
        return 3

    # ------------------------------------------------------------------
    def _open_trade(self, idx: int, direction: int, price: float) -> None:
        sig = self.current_signal()
        self.open_trade = {
            "entry_idx": int(idx),
            "entry_t": int(self.series.t_ns[idx]),
            "direction": int(direction),
            "entry_price": float(price),
            "entry_signal": int(sig),
            "entry_had_signal": bool(sig != 0),
        }

    def _close_trade(self, idx: int, price: float) -> None:
        if self.open_trade is None:
            return
        tr = self.open_trade
        direction = tr["direction"]
        gross = direction * (price / tr["entry_price"] - 1.0)
        net = gross - 2.0 * self.cost_rate
        self.trade_log.append({
            "entry_idx": tr["entry_idx"],
            "exit_idx": int(idx),
            "entry_t": tr["entry_t"],
            "exit_t": int(self.series.t_ns[idx]),
            "direction": direction,
            "entry_price": float(tr["entry_price"]),
            "exit_price": float(price),
            "gross_return": float(gross),
            "net_return": float(net),
            "holding_bars": int(idx - tr["entry_idx"]),
            "entry_signal": tr["entry_signal"],
            "entry_had_signal": tr["entry_had_signal"],
        })
        self.open_trade = None

    # ------------------------------------------------------------------
    def step(self, action: int):
        s = self.series
        assert s is not None
        idx = self.idx
        action = int(action)

        if action == 0:
            target = self.position
        elif action == 1:
            target = 1
        elif action == 2:
            target = -1
        else:
            target = 0

        close_t = float(s.close[idx])
        signal = self.current_signal()

        # signal usage diagnostics (evaluated against the intended position)
        if signal != 0:
            self.total_signals += 1
            if target == signal:
                self.signals_used += 1
            else:
                self.signals_ignored += 1

        delta = target - self.position
        if delta != 0 and target != 0 and signal == 0:
            self.standalone_trades += 1

        # execute position change at close_t
        if delta != 0:
            if self.position != 0:
                self._close_trade(idx, close_t)
            if target != 0:
                self._open_trade(idx, target, close_t)
            self.position = target
            self.entry_price = close_t if target != 0 else None

        trade_cost = self.cost_rate * abs(delta)

        nxt = min(idx + 1, self.end)
        ret = 0.0
        if nxt > idx:
            ret = float(s.close[nxt] / s.close[idx] - 1.0)
        gross = self.position * ret
        net = gross - trade_cost

        done = nxt >= self.end
        close_cost = 0.0
        if done and self.position != 0:
            close_cost = self.cost_rate * abs(self.position)
            net -= close_cost
            self._close_trade(nxt, float(s.close[nxt]))
            self.position = 0
            self.entry_price = None

        self.equity *= (1.0 + net)
        self.peak = max(self.peak, self.equity)
        dd = 1.0 - self.equity / max(self.peak, 1e-9)
        shaping = 0.0
        if self.signal_bonus > 0.0 and signal != 0 and target == signal:
            conf = self.current_signal_conf()
            if conf >= self.signal_conf_min:
                excess = (conf - self.signal_conf_min) / max(1e-9, 1.0 - self.signal_conf_min)
                shaping = self.signal_bonus * float(np.clip(excess, 0.0, 1.0))
        reward = (
            self.reward_scale * net
            - self.dd_penalty * self.reward_scale * max(0.0, dd - self.prev_dd)
            - self.trade_penalty * abs(delta)
            + shaping
        )
        self.prev_dd = dd

        if self.position != 0:
            self.holding += 1
        else:
            self.holding = 0

        self.idx = nxt
        self.equity_curve.append(float(self.equity))
        self.price_curve.append(float(s.close[self.idx]))
        self.position_curve.append(int(self.position))

        info = {
            "equity": float(self.equity),
            "drawdown": float(dd),
            "position": int(self.position),
            "trade_count": len(self.trade_log),
            "ticker": s.ticker,
            "timeframe": s.timeframe,
            "t_ns": int(s.t_ns[self.idx]),
            "close": float(s.close[self.idx]),
        }
        return self._observation(), float(reward), bool(done), False, info

    # ------------------------------------------------------------------
    def run(self, action_fn):
        """Run one full episode with a callable ``action_fn(env) -> int``."""
        obs, _ = self.reset()
        done = False
        while not done:
            action = int(action_fn(self))
            obs, _reward, done, _trunc, info = self.step(action)
        return info


KO_OBS_DIM = 45  # account + partial/ATR + mid/SMA + fee ratios + 4-slot certificate palette (5 values/cert)
MAX_CERTS_STATE = 4


class KOTradingEnv(gym.Env):
    """USD knock-out certificate trading environment.

    Differences to :class:`TradingEnv`
    -----------------------------------
    * Accounting is in **USD** with a fixed stake per position
      (``position_size``, default 200 $) and a configurable size tier.
    * The agent trades simulated **knock-out certificates** with leverages
      (default 22x / 30x / 60x / 80x).  A long certificate is knocked out when
      the low of a subsequent bar touches the KO level; a short when the high
      touches it.  A knock-out is a total loss of the stake.
    * Every order costs ``trade_fee`` USD (default 10 $); this is charged on
      entry, exit and flip.
    * Optional protective exits can close positions at a mean-reversion
      reference, on an SMA(38/80) cross, or after ``max_hold_bars``.
    * The action space lets the agent choose direction, certificate and size::

          0 = hold / no entry
          1 = close
          2 .. 2+C*S-1 : long  (cert x size)
          2+C*S .. 2+2*C*S-1 : short (cert x size)

      with ``C = len(cert_leverages)`` and ``S = len(size_fractions)``
      (default 4 x 2 -> 18 actions).
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        series_pool: Sequence[Tuple[SeriesData, int, int]],
        profiles: Sequence[str] = ("ml4t",),
        episode_len: Optional[int] = 256,
        random_start: bool = True,
        position_size: float = 200.0,
        trade_fee: float = 10.0,
        initial_cash: float = 10_000.0,
        cert_leverages: Sequence[float] = (22.0, 30.0, 60.0, 80.0),
        size_fractions: Sequence[float] = (1.0, 0.5),
        ko_buffer: float = 0.005,
        reward_scale_usd: float = 100.0,
        dd_penalty: float = 0.10,
        ko_penalty: float = 0.05,
        ko_event_penalty: float = 0.5,
        exit_on_sma_cross: bool = False,
        mean_revert_target: bool = False,
        max_hold_bars: int = 0,
        target_bonus: float = 0.2,
        avoid_ko_bonus: float = 0.1,
        high_lev_threshold: float = 60.0,
        high_lev_ko_penalty: float = 0.05,
        fee_basis: float = 2.0,
        min_edge_ratio: float = 0.0,
        min_ko_buffer_atr: float = 0.0,
        mr_only: bool = False,
        min_mr_ko_ratio: float = 0.0,
        mr_ko_ratios: Optional[Sequence[float]] = None,
        mr_ratio_vol_scaling: float = 0.0,
        mr_ratio_bonus: float = 0.25,
        partial_target: bool = False,
        partial_fraction: float = 0.5,
        partial_ko_multiple: float = 1.0,
        partial_atr: bool = False,
        partial_multiple_low: float = 1.0,
        partial_multiple_high: float = 0.75,
        partial_atr_percentile: float = 0.7,
        partial_atr_window: int = 100,
        partial_min_net_usd: float = 0.0,
        regime_filter: bool = False,
        min_atr_pct: float = 0.0,
        max_atr_pct: float = 1.0,
        min_mr_room_atr: float = -99.0,
        max_short_d80: float = 99.0,
        min_long_d80: float = -99.0,
        min_conf: float = 0.0,
        legacy_obs_layout: bool = False,
        signal_bonus: float = 0.0,
        signal_conf_min: float = 0.55,
        seed: int = 0,
    ):
        super().__init__()
        if not series_pool:
            raise ValueError("series_pool must not be empty")
        self.series_pool = list(series_pool)
        self.profiles = tuple(profiles)
        self.episode_len = episode_len
        self.random_start = random_start
        self.position_size = float(position_size)
        self.trade_fee = float(trade_fee)
        self.initial_cash = float(initial_cash)
        self.cert_leverages = tuple(float(v) for v in cert_leverages)
        self.size_fractions = tuple(float(v) for v in size_fractions)
        self.ko_buffer = float(ko_buffer)
        self.reward_scale_usd = float(reward_scale_usd)
        self.dd_penalty = float(dd_penalty)
        self.ko_penalty = float(ko_penalty)
        self.ko_event_penalty = float(ko_event_penalty)
        self.signal_bonus = float(signal_bonus)
        self.signal_conf_min = float(signal_conf_min)
        self.exit_on_sma_cross = bool(exit_on_sma_cross)
        self.mean_revert_target = bool(mean_revert_target)
        self.max_hold_bars = int(max_hold_bars)
        self.target_bonus = float(target_bonus)
        self.avoid_ko_bonus = float(avoid_ko_bonus)
        self.high_lev_threshold = float(high_lev_threshold)
        self.high_lev_ko_penalty = float(high_lev_ko_penalty)
        self.fee_basis = float(fee_basis)
        self.min_edge_ratio = float(min_edge_ratio)
        self.min_ko_buffer_atr = float(min_ko_buffer_atr)
        self.mr_only = bool(mr_only)
        self.min_mr_ko_ratio = float(min_mr_ko_ratio)
        self.mr_ko_ratios = (tuple(float(v) for v in mr_ko_ratios)
                             if mr_ko_ratios else None)
        self.mr_ratio_vol_scaling = float(mr_ratio_vol_scaling)
        self.mr_ratio_bonus = float(mr_ratio_bonus)
        self.partial_target = bool(partial_target)
        self.partial_fraction = float(partial_fraction)
        self.partial_ko_multiple = float(partial_ko_multiple)
        self.partial_atr = bool(partial_atr)
        self.partial_multiple_low = float(partial_multiple_low)
        self.partial_multiple_high = float(partial_multiple_high)
        self.partial_atr_percentile = float(partial_atr_percentile)
        self.partial_atr_window = int(partial_atr_window)
        self.partial_min_net_usd = float(partial_min_net_usd)
        self.regime_filter = bool(regime_filter)
        self.min_atr_pct = float(min_atr_pct)
        self.max_atr_pct = float(max_atr_pct)
        self.min_mr_room_atr = float(min_mr_room_atr)
        self.max_short_d80 = float(max_short_d80)
        self.min_long_d80 = float(min_long_d80)
        self.min_conf = float(min_conf)
        self.legacy_obs_layout = bool(legacy_obs_layout)
        if self.mr_only:
            self.exit_on_sma_cross = False
        self.rng = np.random.default_rng(seed)

        self.n_certs = len(self.cert_leverages)
        self.n_sizes = len(self.size_fractions)
        self.n_entry_actions = 2 * self.n_certs * self.n_sizes
        self.n_actions = 2 + self.n_entry_actions
        self.obs_dim = (SIGNAL_DIM * len(self.profiles) + MARKET_DIM
                        + (34 if self.legacy_obs_layout else KO_OBS_DIM))
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(self.obs_dim,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(self.n_actions)

        self.series: Optional[SeriesData] = None
        self.start = 0
        self.end = 0
        self.idx = 0
        self.cash = self.initial_cash
        self.equity = self.initial_cash
        self.peak = self.initial_cash
        self.prev_dd = 0.0
        self.position = 0
        self.position_value = 0.0
        self.stake = 0.0
        self.remaining_stake = 0.0
        self.partial_done = False
        self.partial_gross = 0.0
        self.partial_fees = 0.0
        self.partial_exit_idx = 0
        self.partial_exit_price = 0.0
        self.partial_stake = 0.0
        self.partial_target_price = 0.0
        self.size_frac = 0.0
        self.size_idx = 0
        self.cert_idx = 0
        self.leverage = 0.0
        self.ko_level = 0.0
        self.initial_ko_dist = 0.0
        self.initial_ko_dist_atr = 1.0
        self.entry_price = 0.0
        self.entry_idx = 0
        self.entry_t = 0
        self.entry_fee = 0.0
        self.entry_signal = 0
        self.entry_mid = 0.0
        self.entry_mr_ratio = 0.0
        self.entry_expected_net_fees = 0.0
        self.entry_atr_pct = 0.0
        self.entry_partial_multiple = 0.0
        self.mid_target_active = False
        self.holding = 0
        self.max_proximity = 0.0
        self.min_ko_dist_atr = 999.0
        self.trade_log: List[dict] = []
        self.equity_curve: List[float] = [self.initial_cash]
        self.price_curve: List[float] = []
        self.position_curve: List[int] = []
        self.total_signals = 0
        self.signals_used = 0
        self.signals_ignored = 0
        self.standalone_trades = 0
        self.filtered_entries = 0
        self.regime_filtered = 0
        self.total_fees = 0.0
        self.gross_pnl = 0.0
        self.net_pnl = 0.0
        self.ko_count = 0
        self.cert_entry_counts = [0] * self.n_certs
        self.size_entry_counts = [0] * self.n_sizes

    # ------------------------------------------------------------------
    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        series, start, end = self.series_pool[int(self.rng.integers(len(self.series_pool)))]
        end = min(end, len(series) - 1)
        if self.episode_len is not None:
            if self.random_start and end - start > self.episode_len:
                start = int(self.rng.integers(start, end - self.episode_len + 1))
                end = start + self.episode_len
            else:
                end = min(start + self.episode_len, end)
        if end <= start:
            end = min(start + 2, len(series) - 1)

        self.series = series
        self.start, self.end = int(start), int(end)
        self.idx = self.start
        self.cash = self.initial_cash
        self.equity = self.initial_cash
        self.peak = self.initial_cash
        self.prev_dd = 0.0
        self.position = 0
        self.position_value = 0.0
        self.stake = 0.0
        self.remaining_stake = 0.0
        self.partial_done = False
        self.partial_gross = 0.0
        self.partial_fees = 0.0
        self.partial_exit_idx = 0
        self.partial_exit_price = 0.0
        self.partial_stake = 0.0
        self.partial_target_price = 0.0
        self.size_frac = 0.0
        self.size_idx = 0
        self.cert_idx = 0
        self.leverage = 0.0
        self.ko_level = 0.0
        self.initial_ko_dist = 0.0
        self.initial_ko_dist_atr = 1.0
        self.entry_price = 0.0
        self.entry_idx = 0
        self.entry_t = 0
        self.entry_fee = 0.0
        self.entry_signal = 0
        self.entry_mid = 0.0
        self.entry_mr_ratio = 0.0
        self.entry_expected_net_fees = 0.0
        self.entry_atr_pct = 0.0
        self.entry_partial_multiple = 0.0
        self.mid_target_active = False
        self.holding = 0
        self.max_proximity = 0.0
        self.min_ko_dist_atr = 999.0
        self.trade_log = []
        self.equity_curve = [self.initial_cash]
        self.price_curve = [float(series.close[self.idx])]
        self.position_curve = [0]
        self.total_signals = 0
        self.signals_used = 0
        self.signals_ignored = 0
        self.standalone_trades = 0
        self.filtered_entries = 0
        self.regime_filtered = 0
        self.total_fees = 0.0
        self.gross_pnl = 0.0
        self.net_pnl = 0.0
        self.ko_count = 0
        self.cert_entry_counts = [0] * self.n_certs
        self.size_entry_counts = [0] * self.n_sizes
        return self._observation(), {}

    # ------------------------------------------------------------------
    def current_signal(self) -> int:
        s = self.series
        assert s is not None
        votes = 0
        for p in self.profiles:
            votes += int(s.filt_pred[p][self.idx])
        return 1 if votes > 0 else (-1 if votes < 0 else 0)

    def current_signal_conf(self) -> float:
        s = self.series
        assert s is not None
        if not self.profiles:
            return 0.0
        return float(max(s.signals[p][self.idx, 5] for p in self.profiles))

    def action_for_direction(self, direction: int, cert_idx: Optional[int] = None,
                             size_idx: int = 0) -> int:
        """Map a directional rule signal to an entry action (default standard cert)."""
        if direction == 0:
            return 0
        if cert_idx is None:
            cert_idx = min(1, self.n_certs - 1)
        size_idx = int(np.clip(size_idx, 0, self.n_sizes - 1))
        base = 2
        if direction < 0:
            base += self.n_certs * self.n_sizes
        return base + int(cert_idx) * self.n_sizes + size_idx

    def bc_action(self, signal: int, conf: float, conf_min: float) -> int:
        """Risk-aware rule used for the optional BC warm start.

        * close before the KO buffer gets too small,
        * otherwise enter only when flat or when the signal flips,
        * use the conservative certificate in high-volatility bars.
        """
        s = self.series
        assert s is not None
        if self.position != 0:
            price = float(s.close[self.idx])
            dist = self._ko_distance(price)
            prox = 1.0 - float(np.clip(dist / max(self.initial_ko_dist, 1e-9), 0.0, 1.0))
            if prox >= 0.75:
                return 1  # close
        if signal != 0 and conf >= conf_min and signal != self.position:
            if not self.regime_entry_ok(self.idx, signal):
                return 0
            if self.mr_only:
                for cert_idx in range(self.n_certs - 1, -1, -1):
                    sizes = [1, 0] if cert_idx == self.n_certs - 1 else [0, 1]
                    for size_idx in sizes:
                        if size_idx < self.n_sizes and self.entry_edge_ok(
                                self.idx, cert_idx, size_idx):
                            return self.action_for_direction(
                                signal, cert_idx=cert_idx, size_idx=size_idx)
                return 0

            atr_norm = abs(float(s.market[self.idx, 3])) / 100.0
            if atr_norm >= 0.01:
                cert_idx, size_idx = 0, 0          # 22x, full
            elif atr_norm >= 0.005:
                cert_idx, size_idx = min(1, self.n_certs - 1), 0  # 30x, full
            elif conf >= 0.70 and self.n_certs >= 4:
                cert_idx, size_idx = 3, 1          # 80x, half stake
            elif self.n_certs >= 3:
                cert_idx, size_idx = 2, 0          # 60x, full stake
            else:
                cert_idx, size_idx = min(1, self.n_certs - 1), 0
            if not self.entry_edge_ok(self.idx, cert_idx, size_idx):
                return 0
            return self.action_for_direction(signal, cert_idx=cert_idx, size_idx=size_idx)
        return 0

    def _decode_action(self, action: int):
        if action == 0:
            return "hold", 0, 0, 0
        if action == 1:
            return "close", 0, 0, 0
        k = int(action) - 2
        if k < 0 or k >= self.n_entry_actions:
            return "hold", 0, 0, 0
        direction = 1 if k < self.n_certs * self.n_sizes else -1
        rem = k % (self.n_certs * self.n_sizes)
        cert_idx = rem // self.n_sizes
        size_idx = rem % self.n_sizes
        return "entry", direction, cert_idx, size_idx

    # ------------------------------------------------------------------
    def _atr_at(self, idx: int) -> float:
        s = self.series
        assert s is not None
        atr_norm = float(s.market[idx, 3]) / 100.0
        return max(float(s.close[idx]) * abs(atr_norm), 1e-9)

    def _atr_percentile(self, idx: int) -> float:
        s = self.series
        assert s is not None
        atr_series = np.abs(s.market[:, 3].astype(float)) / 100.0
        lo = max(0, idx - max(1, self.partial_atr_window) + 1)
        window = atr_series[lo:idx + 1]
        if len(window) == 0:
            return 0.5
        return float((window <= atr_series[idx]).mean())

    def _partial_multiple(self, idx: int) -> float:
        if not self.partial_atr:
            return self.partial_ko_multiple
        pct = self._atr_percentile(idx)
        return (self.partial_multiple_high
                if pct >= self.partial_atr_percentile else self.partial_multiple_low)

    def _ko_distance(self, price: float) -> float:
        """Current distance to KO in price fraction (>=0)."""
        if self.position == 0 or self.ko_level <= 0:
            return 0.0
        if self.position > 0:
            return max((price - self.ko_level) / max(price, 1e-9), 0.0)
        return max((self.ko_level - price) / max(price, 1e-9), 0.0)

    def _entry_edge(self, idx: int, cert_idx: int, size_idx: int):
        """Return (edge_fees, ko_atr, mr_ko_ratio, expected_net_fees)."""
        s = self.series
        assert s is not None
        price = float(s.close[idx])
        atr = self._atr_at(idx)
        stake = self.position_size * self.size_fractions[size_idx]
        lev = self.cert_leverages[cert_idx]
        mid = float(s.mid[idx])
        mid_dist_price = abs(price - mid)
        spread = abs(float(s.sma38[idx] - s.sma80[idx]))
        mid_room = mid_dist_price * lev * stake / max(price, 1e-9)
        sma_room = spread * lev * stake / max(price, 1e-9)
        roundtrip_fee = max(self.trade_fee * self.fee_basis, 1e-9)
        target_room = mid_room if self.mr_only else max(mid_room, sma_room)
        edge_fees = target_room / roundtrip_fee
        ko_dist = 1.0 / max(lev, 1e-9) + self.ko_buffer
        ko_dist_price = price * ko_dist
        ko_atr = ko_dist_price / max(atr, 1e-9)
        mr_ko_ratio = mid_dist_price / max(ko_dist_price, 1e-9)
        expected_net = mid_room - roundtrip_fee
        expected_net_fees = expected_net / roundtrip_fee
        return (float(edge_fees), float(ko_atr), float(mr_ko_ratio),
                float(expected_net_fees))

    def _min_mr_ratio(self, idx: int, cert_idx: int) -> float:
        if self.mr_ko_ratios and cert_idx < len(self.mr_ko_ratios):
            base = float(self.mr_ko_ratios[cert_idx])
        else:
            base = float(self.min_mr_ko_ratio)
        if base <= 0.0:
            return 0.0
        if self.mr_ratio_vol_scaling > 0.0:
            s = self.series
            assert s is not None
            atr_norm = abs(float(s.market[idx, 3])) / 100.0
            base *= 1.0 + self.mr_ratio_vol_scaling * max(0.0, atr_norm - 0.005) / 0.005
        return base

    def entry_edge_ok(self, idx: int, cert_idx: int, size_idx: int) -> bool:
        """Strict cost/KO/mean-reversion filter for new entries."""
        min_ratio = self._min_mr_ratio(idx, cert_idx)
        if (self.min_edge_ratio <= 0.0 and self.min_ko_buffer_atr <= 0.0
                and min_ratio <= 0.0):
            return True
        edge_fees, ko_atr, mr_ko_ratio, _ = self._entry_edge(idx, cert_idx, size_idx)
        return (edge_fees >= self.min_edge_ratio
                and ko_atr >= self.min_ko_buffer_atr
                and mr_ko_ratio >= min_ratio)

    def regime_entry_ok(self, idx: int, direction: int) -> bool:
        """Lean causal regime gate layered on top of the v2 policy."""
        if not self.regime_filter:
            return True
        s = self.series
        assert s is not None
        atr_pct = self._atr_percentile(idx)
        if atr_pct < self.min_atr_pct or atr_pct > self.max_atr_pct:
            return False
        atr = self._atr_at(idx)
        price = float(s.close[idx])
        mid = float(s.mid[idx])
        mr_room = -direction * (price - mid) / max(atr, 1e-9)
        if mr_room < self.min_mr_room_atr:
            return False
        d80 = float(s.market[idx, 5])
        if direction < 0 and d80 > self.max_short_d80:
            return False
        if direction > 0 and d80 < self.min_long_d80:
            return False
        if self.current_signal_conf() < self.min_conf:
            return False
        return True

    def _unrealized(self, price: float) -> float:
        if self.position == 0 or self.entry_price <= 0:
            return 0.0
        stake = self.remaining_stake if self.remaining_stake > 0 else self.stake
        pnl = self.position * stake * self.leverage * (price / self.entry_price - 1.0)
        return max(pnl, -stake)

    def _mark_position(self, price: float) -> None:
        if self.position == 0:
            self.position_value = 0.0
            return
        stake = self.remaining_stake
        pnl = self.position * stake * self.leverage * (
            price / max(self.entry_price, 1e-9) - 1.0)
        self.position_value = max(0.0, stake + pnl)

    def _maybe_partial_exit(self, idx: int) -> None:
        """Take partial profit at the configured KO-multiple target (causal high/low)."""
        if (not self.partial_target or self.position == 0 or self.partial_done
                or self.remaining_stake <= 0):
            return
        s = self.series
        assert s is not None
        target = self.partial_target_price
        if self.position > 0:
            hit = float(s.high[idx]) >= target
        else:
            hit = float(s.low[idx]) <= target
        if not hit:
            return
        close_stake = self.remaining_stake * self.partial_fraction
        if close_stake <= 0:
            return
        fill = target
        gross = self.position * close_stake * self.leverage * (
            fill / max(self.entry_price, 1e-9) - 1.0)
        fee = self.trade_fee
        if gross - fee < self.partial_min_net_usd:
            return
        self.cash += close_stake + gross - fee
        self.remaining_stake -= close_stake
        self.partial_gross += gross
        self.partial_fees += fee
        self.total_fees += fee
        self.partial_done = True
        self.partial_exit_idx = int(idx)
        self.partial_exit_price = float(fill)
        self.partial_stake = float(close_stake)
        self.partial_target_price = 0.0

    def _observation(self) -> np.ndarray:
        s = self.series
        assert s is not None
        idx = self.idx
        parts: List[np.ndarray] = []
        for p in self.profiles:
            parts.append(s.signals[p][idx])
        market = s.market[idx]
        price = float(s.close[idx])
        dd = 1.0 - self.equity / max(self.peak, 1e-9)
        equity_ret = self.equity / max(self.initial_cash, 1e-9) - 1.0

        if self.position != 0:
            dist = self._ko_distance(price)
            dist_norm = float(np.clip(dist / max(self.initial_ko_dist, 1e-9), 0.0, 1.0))
            dist_atr = dist * price / max(self._atr_at(idx), 1e-9)
            dist_atr_norm = float(np.clip(dist_atr / 10.0, 0.0, 2.0))
            proximity = 1.0 - dist_norm
            unreal = float(np.clip(self._unrealized(price)
                                   / max(self.remaining_stake, 1e-9), -1.0, 1.0))
            stake_norm = self.remaining_stake / max(self.position_size, 1e-9)
            lev_norm = self.leverage / 100.0
            holding_norm = float(np.clip(self.holding / 100.0, 0.0, 1.0))
        else:
            dist_norm, dist_atr_norm, proximity, unreal = 1.0, 1.0, 0.0, 0.0
            stake_norm, lev_norm, holding_norm = 0.0, 0.0, 0.0

        atr = self._atr_at(idx)
        prev_idx = max(idx - 1, 0)
        mid = float(s.mid[idx])
        prev_mid = float(s.mid[prev_idx])
        prev_price = float(s.close[prev_idx])
        mid_dist = (price - mid) / max(atr, 1e-9)
        mid_dist_norm = float(np.clip(mid_dist / 10.0, -2.0, 2.0))
        mid_side = float(np.sign(price - mid))
        mid_approach = float(np.sign(abs(price - mid) - abs(prev_price - prev_mid)))
        spread = float(s.sma38[idx] - s.sma80[idx])
        prev_spread = float(s.sma38[prev_idx] - s.sma80[prev_idx])
        spread_norm = float(np.clip(spread / max(atr, 1e-9) / 10.0, -2.0, 2.0))
        spread_change = float(np.sign(spread - prev_spread))
        sma_cross = float(s.sma_cross[idx])
        if self.mr_only:
            spread_norm = 0.0
            spread_change = 0.0
            sma_cross = 0.0

        if self.position != 0:
            ratio_stake = self.stake
            ratio_lev = self.leverage
            unreal_usd = self._unrealized(price)
        else:
            ratio_stake = self.position_size
            ratio_lev = self.cert_leverages[min(1, self.n_certs - 1)]
            unreal_usd = 0.0
        fee = max(self.trade_fee * self.fee_basis, 1e-9)
        atr_value_usd = ratio_stake * ratio_lev * (atr / max(price, 1e-9))
        atr_value_fees = float(np.clip(atr_value_usd / fee, 0.0, 10.0))
        mid_room_usd = abs(price - mid) * ratio_lev * ratio_stake / max(price, 1e-9)
        mid_room_fees = float(np.clip(mid_room_usd / fee, 0.0, 20.0))
        sma_room_usd = abs(spread) * ratio_lev * ratio_stake / max(price, 1e-9)
        sma_room_fees = float(np.clip(sma_room_usd / fee, 0.0, 20.0))
        if self.mr_only:
            sma_room_fees = 0.0
        pnl_to_fee = float(np.clip(unreal_usd / fee, -10.0, 10.0))
        fee_burden = float(np.clip(self.total_fees / max(self.initial_cash, 1e-9), 0.0, 1.0))
        trade_count_norm = float(np.clip(len(self.trade_log) / 50.0, 0.0, 1.0))

        cert_block = np.zeros(MAX_CERTS_STATE * 5, dtype=np.float32)
        cert_block_old = np.zeros(MAX_CERTS_STATE * 3, dtype=np.float32)
        for i, lev in enumerate(self.cert_leverages[:MAX_CERTS_STATE]):
            dist_pct = 1.0 / max(lev, 1e-9) + self.ko_buffer
            dist_atr = price * dist_pct / max(atr, 1e-9)
            ko_dist_price = price * dist_pct
            mid_dist_price = abs(price - mid)
            ratio = mid_dist_price / max(ko_dist_price, 1e-9)
            expected_net = (mid_dist_price * lev * self.position_size
                            / max(price, 1e-9) - fee)
            cert_block[5 * i] = np.clip(lev / 100.0, 0.0, 1.5)
            cert_block[5 * i + 1] = np.clip(dist_pct * 10.0, 0.0, 2.0)
            cert_block[5 * i + 2] = np.clip(dist_atr / 10.0, 0.0, 2.0)
            cert_block[5 * i + 3] = np.clip(ratio / 5.0, 0.0, 3.0)
            cert_block[5 * i + 4] = np.clip(expected_net / fee / 10.0, -1.0, 3.0)
            cert_block_old[3 * i] = cert_block[5 * i]
            cert_block_old[3 * i + 1] = cert_block[5 * i + 1]
            cert_block_old[3 * i + 2] = cert_block[5 * i + 2]

        atr_pct = self._atr_percentile(idx)
        partial_mult_active = self._partial_multiple(idx) if self.partial_target else 0.0

        if self.legacy_obs_layout:
            ko_block = np.array([
                float(self.position),
                float(np.clip(stake_norm, 0.0, 1.0)),
                float(np.clip(lev_norm, 0.0, 1.0)),
                float(np.clip(dist_norm, 0.0, 1.0)),
                float(np.clip(dist_atr_norm, 0.0, 2.0)),
                float(np.clip(proximity, 0.0, 1.0)),
                float(unreal),
                float(holding_norm),
                float(np.clip(dd, 0.0, 1.0)),
                float(np.clip(equity_ret, -1.0, 1.0)),
                mid_dist_norm,
                mid_side,
                mid_approach,
                spread_norm,
                spread_change,
                sma_cross,
                fee_burden,
                trade_count_norm,
                pnl_to_fee,
                atr_value_fees,
                mid_room_fees,
                sma_room_fees,
                *cert_block_old.tolist(),
            ], dtype=np.float32)
        else:
            ko_block = np.array([
                float(self.position),
                float(self.partial_done),
                float(np.clip(stake_norm, 0.0, 1.0)),
                float(np.clip(lev_norm, 0.0, 1.0)),
                float(np.clip(dist_norm, 0.0, 1.0)),
                float(np.clip(dist_atr_norm, 0.0, 2.0)),
                float(np.clip(proximity, 0.0, 1.0)),
                float(unreal),
                float(holding_norm),
                float(np.clip(dd, 0.0, 1.0)),
                float(np.clip(equity_ret, -1.0, 1.0)),
                float(np.clip(atr_pct, 0.0, 1.0)),
                float(np.clip(partial_mult_active, 0.0, 2.0)),
                mid_dist_norm,
                mid_side,
                mid_approach,
                spread_norm,
                spread_change,
                sma_cross,
                fee_burden,
                trade_count_norm,
                pnl_to_fee,
                atr_value_fees,
                mid_room_fees,
                sma_room_fees,
                *cert_block.tolist(),
            ], dtype=np.float32)
        return np.concatenate(parts + [market, ko_block]).astype(np.float32)

    # ------------------------------------------------------------------
    def _open_position(self, idx: int, direction: int, cert_idx: int, size_idx: int) -> bool:
        s = self.series
        assert s is not None
        stake = self.position_size * self.size_fractions[size_idx]
        if self.cash < stake + self.trade_fee:
            return False
        entry = float(s.close[idx])
        leverage = self.cert_leverages[cert_idx]
        ko_dist = 1.0 / max(leverage, 1e-9) + self.ko_buffer
        self.cash -= stake + self.trade_fee
        self.total_fees += self.trade_fee
        self.position = direction
        self.stake = stake
        self.position_value = stake
        self.remaining_stake = stake
        self.partial_done = False
        self.partial_gross = 0.0
        self.partial_fees = 0.0
        self.partial_exit_idx = 0
        self.partial_exit_price = 0.0
        self.partial_stake = 0.0
        self.size_frac = self.size_fractions[size_idx]
        self.size_idx = int(size_idx)
        self.cert_idx = int(cert_idx)
        self.leverage = leverage
        self.initial_ko_dist = ko_dist
        self.ko_level = entry * (1.0 - direction * ko_dist)
        partial_mult = self._partial_multiple(idx)
        self.entry_atr_pct = self._atr_percentile(idx)
        self.entry_partial_multiple = partial_mult if self.partial_target else 0.0
        self.partial_target_price = (
            entry * (1.0 + direction * partial_mult * ko_dist)
            if self.partial_target else 0.0
        )
        atr = self._atr_at(idx)
        self.initial_ko_dist_atr = (entry * ko_dist) / max(atr, 1e-9)
        self.entry_price = entry
        self.entry_idx = int(idx)
        self.entry_t = int(s.t_ns[idx])
        self.entry_fee = self.trade_fee
        self.entry_signal = int(self.current_signal())
        entry_mid = float(s.mid[idx])
        atr_entry = self._atr_at(idx)
        self.entry_mid = entry_mid
        self.mid_target_active = False
        if abs(entry - entry_mid) / max(atr_entry, 1e-9) > 0.2:
            if direction > 0:
                self.mid_target_active = entry < entry_mid
            else:
                self.mid_target_active = entry > entry_mid
        _, _, self.entry_mr_ratio, self.entry_expected_net_fees = self._entry_edge(
            idx, cert_idx, size_idx)
        self.holding = 0
        self.max_proximity = 0.0
        self.min_ko_dist_atr = self.initial_ko_dist_atr
        self.cert_entry_counts[int(cert_idx)] += 1
        self.size_entry_counts[int(size_idx)] += 1
        return True

    def _record_trade(self, exit_idx: int, exit_price: float, exit_reason: str,
                      knockout: bool) -> None:
        s = self.series
        assert s is not None
        if self.position == 0:
            return
        remaining = self.remaining_stake
        partial_gross = self.partial_gross
        partial_fees = self.partial_fees
        if knockout:
            gross_final = -remaining
            fees = self.entry_fee + partial_fees  # no exit order on a KO
        else:
            gross_final = self.position * remaining * self.leverage * (
                exit_price / max(self.entry_price, 1e-9) - 1.0
            )
            fees = self.entry_fee + partial_fees + self.trade_fee
        gross = partial_gross + gross_final
        net = gross - fees
        self.gross_pnl += gross
        self.net_pnl += net
        self.total_fees += (fees - self.entry_fee - partial_fees)
        stake = self.stake
        self.trade_log.append({
            "entry_idx": int(self.entry_idx),
            "exit_idx": int(exit_idx),
            "entry_t": int(self.entry_t),
            "exit_t": int(s.t_ns[exit_idx]),
            "direction": int(self.position),
            "cert_idx": int(self.cert_idx),
            "leverage": float(self.leverage),
            "size_idx": int(self.size_idx),
            "size_fraction": float(self.size_frac),
            "stake_usd": float(self.stake),
            "remaining_stake_usd": float(remaining),
            "entry_price": float(self.entry_price),
            "exit_price": float(exit_price),
            "ko_level": float(self.ko_level),
            "gross_pnl_usd": float(gross),
            "fees_usd": float(fees),
            "net_pnl_usd": float(net),
            "holding_bars": int(exit_idx - self.entry_idx),
            "knockout": bool(knockout),
            "exit_reason": exit_reason,
            "partial_done": bool(self.partial_done),
            "partial_stake_usd": float(self.partial_stake),
            "partial_gross_usd": float(partial_gross),
            "partial_fees_usd": float(partial_fees),
            "partial_exit_idx": int(self.partial_exit_idx),
            "partial_exit_price": float(self.partial_exit_price),
            "partial_holding_bars": int(self.partial_exit_idx - self.entry_idx)
            if self.partial_done else 0,
            "entry_signal": int(self.entry_signal),
            "entry_had_signal": bool(self.entry_signal != 0),
            "entry_mid": float(self.entry_mid),
            "mid_target_active": bool(self.mid_target_active),
            "entry_mr_ratio": float(self.entry_mr_ratio),
            "entry_expected_net_fees": float(self.entry_expected_net_fees),
            "entry_atr_pct": float(self.entry_atr_pct),
            "entry_partial_multiple": float(self.entry_partial_multiple),
            "max_proximity": float(self.max_proximity),
            "min_ko_dist_atr": float(self.min_ko_dist_atr),
        })
        if knockout:
            self.ko_count += 1
            self.cash += 0.0  # remaining stake was paid on entry and is now lost
        else:
            self.cash += remaining + gross_final - self.trade_fee
        self.position = 0
        self.position_value = 0.0
        self.stake = 0.0
        self.remaining_stake = 0.0
        self.partial_done = False
        self.partial_gross = 0.0
        self.partial_fees = 0.0
        self.partial_exit_idx = 0
        self.partial_exit_price = 0.0
        self.partial_stake = 0.0
        self.partial_target_price = 0.0
        self.size_frac = 0.0
        self.leverage = 0.0
        self.ko_level = 0.0
        self.entry_price = 0.0
        self.holding = 0

    def _close_position(self, idx: int, reason: str = "close") -> None:
        s = self.series
        assert s is not None
        if self.position == 0:
            return
        price = float(s.close[idx])
        self._record_trade(idx, price, reason, knockout=False)

    # ------------------------------------------------------------------
    def step(self, action: int):
        s = self.series
        assert s is not None
        idx = self.idx
        action = int(action)
        kind, direction, cert_idx, size_idx = self._decode_action(action)
        signal = self.current_signal()
        conf = self.current_signal_conf()

        # equity before the step (position marked at close_t)
        price_t = float(s.close[idx])
        self._maybe_partial_exit(idx)
        self._mark_position(price_t)
        equity_before = self.cash + self.position_value
        dd_before = 1.0 - equity_before / max(self.peak, 1e-9)

        # optional protective exits evaluated at close_t (causal)
        trades_before = len(self.trade_log)
        triggered = False
        trigger_reason = None
        if self.position != 0:
            if self.exit_on_sma_cross and int(s.sma_cross[idx]) != 0:
                trigger_reason = "sma_cross"
            elif self.mean_revert_target and self.mid_target_active:
                mid_now = float(s.mid[idx])
                if (self.position > 0 and price_t >= mid_now) or (
                        self.position < 0 and price_t <= mid_now):
                    trigger_reason = "mean_revert"
            elif self.max_hold_bars > 0 and self.holding >= self.max_hold_bars:
                trigger_reason = "max_hold"
        if trigger_reason is not None:
            self._close_position(idx, reason=trigger_reason)
            triggered = True

        # signal diagnostics
        if triggered:
            intended = 0
        elif kind == "entry":
            intended = direction
        elif kind == "close":
            intended = 0
        else:
            intended = self.position
        if signal != 0:
            self.total_signals += 1
            if intended == signal:
                self.signals_used += 1
            else:
                self.signals_ignored += 1
        if not triggered and kind == "entry" and signal == 0:
            self.standalone_trades += 1

        # execute the action at close_t
        if not triggered:
            if kind == "close":
                if self.position != 0:
                    self._close_position(idx, reason="close")
            elif kind == "entry":
                if not self.regime_entry_ok(idx, direction):
                    self.regime_filtered += 1
                elif not self.entry_edge_ok(idx, cert_idx, size_idx):
                    self.filtered_entries += 1
                else:
                    same = (self.position == direction and self.cert_idx == cert_idx
                            and self.size_idx == size_idx)
                    if not same:
                        if self.position != 0:
                            self._close_position(idx, reason="close")
                        self._open_position(idx, direction, cert_idx, size_idx)
            # "hold" does nothing

        # advance to t+1 and mark to market / check KO
        nxt = min(idx + 1, self.end)
        done = nxt >= self.end
        knockout = False
        proximity = 0.0
        if self.position != 0:
            high = float(s.high[nxt])
            low = float(s.low[nxt])
            if self.position > 0 and low <= self.ko_level:
                knockout = True
            elif self.position < 0 and high >= self.ko_level:
                knockout = True

            if knockout:
                self._record_trade(nxt, self.ko_level, "knockout", knockout=True)
            else:
                price_n = float(s.close[nxt])
                pnl = self.position * self.remaining_stake * self.leverage * (
                    price_n / max(self.entry_price, 1e-9) - 1.0
                )
                self.position_value = max(0.0, self.remaining_stake + pnl)
                dist = self._ko_distance(price_n)
                dist_norm = float(np.clip(dist / max(self.initial_ko_dist, 1e-9), 0.0, 1.0))
                proximity = 1.0 - dist_norm
                self.max_proximity = max(self.max_proximity, proximity)
                atr = self._atr_at(nxt)
                dist_atr = dist * price_n / max(atr, 1e-9)
                self.min_ko_dist_atr = min(self.min_ko_dist_atr, dist_atr)
                self.holding += 1

                if done:
                    self._close_position(nxt, reason="eod")
        # if flat, position_value is 0

        # reward for clean exits at mean-reversion / SMA-cross targets
        exit_bonus = 0.0
        if len(self.trade_log) > trades_before:
            tr = self.trade_log[-1]
            reason = tr["exit_reason"]
            net_usd = float(tr["net_pnl_usd"])
            fee_rt = max(self.trade_fee * self.fee_basis, 1e-9)
            target_ok = (reason == "mean_revert") or (
                reason == "sma_cross" and not self.mr_only)
            if target_ok and net_usd > fee_rt:
                ratio_boost = 1.0
                if self.min_mr_ko_ratio > 0.0:
                    ratio_boost += self.mr_ratio_bonus * max(
                        0.0, float(tr.get("entry_mr_ratio", 0.0)) - self.min_mr_ko_ratio)
                exit_bonus += self.target_bonus * min(1.0, net_usd / fee_rt) * ratio_boost
            if (reason in ("close", "mean_revert", "sma_cross", "max_hold", "eod")
                    and net_usd >= 0 and tr["max_proximity"] >= 0.6):
                exit_bonus += self.avoid_ko_bonus

        self.idx = nxt
        self.equity = self.cash + self.position_value
        self.peak = max(self.peak, self.equity)
        dd = 1.0 - self.equity / max(self.peak, 1e-9)
        delta = self.equity - equity_before
        reward = delta / max(self.reward_scale_usd, 1e-9)
        reward -= self.dd_penalty * max(0.0, dd - dd_before) * (
            self.initial_cash / max(self.reward_scale_usd, 1e-9)
        )
        reward -= self.ko_penalty * proximity
        if (self.position != 0 and proximity > 0.0
                and self.leverage >= self.high_lev_threshold):
            reward -= self.high_lev_ko_penalty * proximity * (
                self.leverage / max(self.high_lev_threshold, 1e-9))
        if knockout:
            reward -= self.ko_event_penalty
        reward += exit_bonus
        if (self.signal_bonus > 0.0 and self.position != 0 and signal == self.position
                and conf >= self.signal_conf_min):
            excess = (conf - self.signal_conf_min) / max(1e-9, 1.0 - self.signal_conf_min)
            reward += self.signal_bonus * float(np.clip(excess, 0.0, 1.0))

        self.prev_dd = dd
        self.equity_curve.append(float(self.equity))
        self.price_curve.append(float(s.close[self.idx]))
        self.position_curve.append(int(self.position))

        info = {
            "equity": float(self.equity),
            "drawdown": float(dd),
            "position": int(self.position),
            "trade_count": len(self.trade_log),
            "knockout_count": int(self.ko_count),
            "knockout": bool(knockout),
            "fees_usd": float(self.total_fees),
            "gross_pnl_usd": float(self.gross_pnl),
            "net_pnl_usd": float(self.net_pnl),
            "ticker": s.ticker,
            "timeframe": s.timeframe,
            "t_ns": int(s.t_ns[self.idx]),
            "close": float(s.close[self.idx]),
        }
        return self._observation(), float(reward), bool(done), False, info

    def run(self, action_fn):
        obs, _ = self.reset()
        done = False
        while not done:
            action = int(action_fn(self))
            obs, _reward, done, _trunc, info = self.step(action)
        return info


def make_env(series_pool: Sequence[Tuple[SeriesData, int, int]],
             profiles: Sequence[str], **kwargs) -> TradingEnv:
    return TradingEnv(series_pool=series_pool, profiles=profiles, **kwargs)


def make_ko_env(series_pool: Sequence[Tuple[SeriesData, int, int]],
                profiles: Sequence[str], **kwargs) -> KOTradingEnv:
    return KOTradingEnv(series_pool=series_pool, profiles=profiles, **kwargs)
