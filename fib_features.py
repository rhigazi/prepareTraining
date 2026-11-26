#!/usr/bin/env python3
"""fib_features.py - Fibonacci-based feature builder (no lookahead)."""

import numpy as np
import pandas as pd
import talib

import prepareTraining as pt


def compute_features(df, lookback=20):
    df = pt.sort_and_dedup(df.copy())
    if "vw" not in df.columns:
        df["vw"] = df["c"]
    o = df["o"].to_numpy(dtype=float); h = df["h"].to_numpy(dtype=float)
    l = df["l"].to_numpy(dtype=float); c = df["c"].to_numpy(dtype=float)
    v = df["v"].to_numpy(dtype=float); n = len(df)

    sh = pd.Series(h).rolling(lookback, min_periods=lookback).max().to_numpy()
    sl = pd.Series(l).rolling(lookback, min_periods=lookback).min().to_numpy()
    rng = sh - sl
    atr = talib.ATR(h, l, c, timeperiod=14)
    valid_swing = np.isfinite(rng) & (rng > 0) & np.isfinite(atr) & (atr > 0) & (rng / atr >= 1.0)

    fib_pos = (c - sl) / np.where(rng == 0, 1.0, rng)
    levels = [0.382, 0.5, 0.618, 0.786]
    feat = {}
    feat["feat_fib_pos"] = fib_pos
    for lev in levels:
        lvl_price = sl + lev * rng
        feat[f"feat_fib_dist_{int(lev*1000)}"] = (c - lvl_price) / np.where(rng == 0, 1.0, rng)
    feat["feat_swing_range_atr"] = rng / np.where(atr == 0, 1.0, atr)
    feat["feat_dist_swing_high_atr"] = (sh - c) / np.where(atr == 0, 1.0, atr)
    feat["feat_dist_swing_low_atr"] = (c - sl) / np.where(atr == 0, 1.0, atr)

    ret1 = np.concatenate([[np.nan], np.diff(c) / np.where(c[:-1] == 0, 1.0, c[:-1])])
    vol_ratio = v / np.where(pd.Series(v).rolling(20, min_periods=20).mean().to_numpy() == 0, 1.0, pd.Series(v).rolling(20, min_periods=20).mean().to_numpy())
    feat["feat_ret1"] = ret1
    feat["feat_vol_ratio"] = vol_ratio

    for k in feat:
        feat[k] = np.where(valid_swing, feat[k], np.nan)
    for k, val in feat.items():
        df[k] = val
    df = df.replace([np.inf, -np.inf], np.nan)
    return df
