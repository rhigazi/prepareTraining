#!/usr/bin/env python3
"""ml4t_features.py - Stationary ML4T-inspired feature builder."""

import numpy as np
import pandas as pd
import talib
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import ADXIndicator
from ta.volatility import BollingerBands
from ta.volume import MFIIndicator

import prepareTraining as pt


def compute_features(df):
    df = pt.sort_and_dedup(df.copy())
    if "vw" not in df.columns:
        df["vw"] = df["c"]
    o = df["o"].to_numpy(dtype=float)
    h = df["h"].to_numpy(dtype=float)
    l = df["l"].to_numpy(dtype=float)
    c = df["c"].to_numpy(dtype=float)
    v = df["v"].to_numpy(dtype=float)
    n = len(df)

    rsi = RSIIndicator(pd.Series(c), window=14).rsi().to_numpy(dtype=float)
    stoch = StochasticOscillator(pd.Series(h), pd.Series(l), pd.Series(c), window=14, smooth_window=3)
    stoch_k = stoch.stoch().to_numpy(dtype=float)
    stoch_d = stoch.stoch_signal().to_numpy(dtype=float)
    adx = ADXIndicator(pd.Series(h), pd.Series(l), pd.Series(c), window=14).adx().to_numpy(dtype=float)
    bb = BollingerBands(pd.Series(c), window=20, window_dev=2)
    bb_pctb = bb.bollinger_pband().to_numpy(dtype=float)
    bb_bw = bb.bollinger_wband().to_numpy(dtype=float)
    bb_mid = bb.bollinger_mavg().to_numpy(dtype=float)
    mfi = MFIIndicator(pd.Series(h), pd.Series(l), pd.Series(c), pd.Series(v), window=14).money_flow_index().to_numpy(dtype=float)

    ret1 = np.concatenate([[np.nan], np.diff(c) / np.where(c[:-1] == 0, 1.0, c[:-1])])
    ret5 = pd.Series(c).pct_change(5).to_numpy(dtype=float)
    vol20 = pd.Series(ret1).rolling(20, min_periods=20).std().to_numpy(dtype=float)
    vol_ratio = v / np.where(pd.Series(v).rolling(20, min_periods=20).mean().to_numpy() == 0, 1.0, pd.Series(v).rolling(20, min_periods=20).mean().to_numpy())

    feat = {}
    feat["feat_rsi"] = rsi / 100.0
    feat["feat_rsi_diff"] = np.concatenate([[np.nan], np.diff(rsi)]) / 100.0
    feat["feat_stoch_k"] = stoch_k / 100.0
    feat["feat_stoch_d"] = stoch_d / 100.0
    feat["feat_stoch_diff"] = (stoch_k - stoch_d) / 100.0
    feat["feat_stoch_k_diff"] = np.concatenate([[np.nan], np.diff(stoch_k)]) / 100.0
    feat["feat_adx"] = adx / 100.0
    feat["feat_adx_diff"] = np.concatenate([[np.nan], np.diff(adx)]) / 100.0
    feat["feat_bb_pct_b"] = bb_pctb
    feat["feat_bb_bw"] = bb_bw
    feat["feat_bb_bw_diff"] = np.concatenate([[np.nan], np.diff(bb_bw)])
    feat["feat_bb_dist_mid"] = (c - bb_mid) / np.where(np.abs(bb_mid) < 1e-8, 1.0, bb_mid)
    feat["feat_mfi"] = mfi / 100.0
    feat["feat_mfi_diff"] = np.concatenate([[np.nan], np.diff(mfi)]) / 100.0
    feat["feat_ret1"] = ret1
    feat["feat_ret5"] = ret5
    feat["feat_vol20"] = vol20
    feat["feat_vol_ratio"] = vol_ratio

    for k, val in feat.items():
        df[k] = val
    df = df.replace([np.inf, -np.inf], np.nan)
    return df
