#!/usr/bin/env python3
"""prepareTraining.py - Feature & Label Generator (PRD)."""

import argparse
import os
import sys

import numpy as np
import pandas as pd

try:
    import talib
except Exception as e:  # pragma: no cover
    print("TA-Lib is required:", e, file=sys.stderr)
    sys.exit(1)


def parse_args():
    p = argparse.ArgumentParser(description="Prepare training CSV from raw 15-min market data.")
    p.add_argument("--inputcsv", required=True, help="Path to input CSV")
    p.add_argument("--outputcsv", required=True, help="Path to output CSV")
    p.add_argument("--window_left", type=int, default=6, help="Left window for swing detection")
    p.add_argument("--window_right", type=int, default=6, help="Right window for swing detection")
    p.add_argument("--min_move_atr", type=float, default=1.5, help="Min counter-move in ATR multiples")
    return p.parse_args()


def sort_and_dedup(df):
    t = df["t"]
    if pd.api.types.is_numeric_dtype(t):
        med = float(t.abs().median()) if len(t) else 0.0
        unit = "ms" if med > 1e11 else "s"
        key = pd.to_datetime(t, unit=unit, utc=True, errors="coerce")
    else:
        key = pd.to_datetime(t, utc=True, errors="coerce")
        if key.isna().all():
            key = t.astype(str)
    df = df.assign(_sort_key=key).sort_values("_sort_key", kind="mergesort").drop(columns="_sort_key")
    df = df.drop_duplicates(subset=["t"], keep="first").reset_index(drop=True)
    return df


def main():
    args = parse_args()
    if not os.path.exists(args.inputcsv):
        print(f"Input file not found: {args.inputcsv}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(args.inputcsv)
    required = ["t", "o", "h", "l", "c", "v", "vw"]
    for col in required:
        if col not in df.columns:
            print(f"Missing required column: {col}", file=sys.stderr)
            sys.exit(1)

    df = sort_and_dedup(df)

    o = df["o"].to_numpy(dtype=float)
    h = df["h"].to_numpy(dtype=float)
    l = df["l"].to_numpy(dtype=float)
    c = df["c"].to_numpy(dtype=float)
    v = df["v"].to_numpy(dtype=float)
    vw = df["vw"].to_numpy(dtype=float)
    n = len(df)

    if "RSI(21)" in df.columns and df["RSI(21)"].notna().any():
        rsi = df["RSI(21)"].to_numpy(dtype=float)
    else:
        rsi = talib.RSI(c, timeperiod=21)

    if "SMA(38)" in df.columns and df["SMA(38)"].notna().any():
        sma38 = df["SMA(38)"].to_numpy(dtype=float)
    else:
        sma38 = talib.SMA(c, timeperiod=38)

    if "SMA(80)" in df.columns and df["SMA(80)"].notna().any():
        sma80 = df["SMA(80)"].to_numpy(dtype=float)
    else:
        sma80 = talib.SMA(c, timeperiod=80)

    if "CrossSMA(38,80)" in df.columns:
        cross_sma = df["CrossSMA(38,80)"].to_numpy()
    else:
        cross_sma = np.zeros(n)

    atr = talib.ATR(h, l, c, timeperiod=14)
    adx = talib.ADX(h, l, c, timeperiod=14)
    stoch_k, stoch_d = talib.STOCH(h, l, c)
    vol_sma20 = talib.SMA(v, timeperiod=20)

    feat_body_atr = (c - o) / atr
    feat_upper_wick_atr = (h - np.maximum(o, c)) / atr
    feat_lower_wick_atr = (np.minimum(o, c) - l) / atr
    feat_close_pos_in_candle = (c - l) / (h - l + 1e-8)

    feat_dist_sma38_atr = (c - sma38) / atr
    feat_dist_sma80_atr = (c - sma80) / atr
    feat_diff_sma38_80_atr = (sma38 - sma80) / atr
    feat_dist_vwap_atr = (c - vw) / atr

    sma38_shifted = np.roll(sma38, 3)
    sma38_shifted[:3] = np.nan
    feat_sma38_slope = (sma38 - sma38_shifted) / atr

    feat_rsi21 = rsi
    rsi_shifted = np.roll(rsi, 1)
    rsi_shifted[0] = np.nan
    feat_rsi21_diff = rsi - rsi_shifted

    feat_cross_sma = cross_sma
    feat_adx14 = adx
    feat_stoch_k = stoch_k
    feat_stoch_d = stoch_d
    feat_rel_volume = v / vol_sma20

    wl = args.window_left
    wr = args.window_right
    min_move = args.min_move_atr

    label_turn = np.zeros(n, dtype=int)
    label_max_move_atr = np.zeros(n, dtype=float)

    window_size = wl + wr + 1
    roll_max_h = pd.Series(h).rolling(window=window_size, center=True, min_periods=window_size).max().to_numpy()
    roll_min_l = pd.Series(l).rolling(window=window_size, center=True, min_periods=window_size).min().to_numpy()
    fut_min_low = pd.Series(l).rolling(window=wr, min_periods=wr).min().shift(-wr).to_numpy()
    fut_max_high = pd.Series(h).rolling(window=wr, min_periods=wr).max().shift(-wr).to_numpy()

    valid = np.isfinite(atr) & (atr != 0)
    valid_future = np.isfinite(fut_min_low) & np.isfinite(fut_max_high)

    drop = h - fut_min_low
    rise = fut_max_high - l

    high_mask = (h == roll_max_h) & (drop >= min_move * atr) & valid & valid_future
    low_mask = (l == roll_min_l) & (rise >= min_move * atr) & valid & valid_future

    label_turn[high_mask] = -1
    label_turn[low_mask] = 1

    label_max_move_atr[high_mask] = (drop / atr)[high_mask]
    label_max_move_atr[low_mask] = (rise / atr)[low_mask]

    neutral_mask = valid & valid_future & ~(high_mask | low_mask)
    up_move = (fut_max_high - l) / atr
    down_move = (h - fut_min_low) / atr
    neu_move = np.maximum(up_move, down_move)
    label_max_move_atr[neutral_mask] = neu_move[neutral_mask]

    out = pd.DataFrame({
        "meta_t": df["t"].values,
        "meta_open": o,
        "meta_high": h,
        "meta_low": l,
        "meta_close": c,
        "feat_body_atr": feat_body_atr,
        "feat_upper_wick_atr": feat_upper_wick_atr,
        "feat_lower_wick_atr": feat_lower_wick_atr,
        "feat_close_pos_in_candle": feat_close_pos_in_candle,
        "feat_dist_sma38_atr": feat_dist_sma38_atr,
        "feat_dist_sma80_atr": feat_dist_sma80_atr,
        "feat_diff_sma38_80_atr": feat_diff_sma38_80_atr,
        "feat_dist_vwap_atr": feat_dist_vwap_atr,
        "feat_sma38_slope": feat_sma38_slope,
        "feat_rsi21": feat_rsi21,
        "feat_rsi21_diff": feat_rsi21_diff,
        "feat_cross_sma": feat_cross_sma,
        "feat_adx14": feat_adx14,
        "feat_stoch_k": feat_stoch_k,
        "feat_stoch_d": feat_stoch_d,
        "feat_rel_volume": feat_rel_volume,
        "label_turn": label_turn,
        "label_max_move_atr": label_max_move_atr,
    })

    out = out.replace([np.inf, -np.inf], np.nan)
    out = out.dropna(axis=0, how="any").reset_index(drop=True)
    out["label_turn"] = out["label_turn"].astype(int)

    os.makedirs(os.path.dirname(os.path.abspath(args.outputcsv)), exist_ok=True)
    out.to_csv(args.outputcsv, index=False)
    print(f"Wrote {len(out)} rows to {args.outputcsv}")


if __name__ == "__main__":
    main()
