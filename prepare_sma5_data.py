#!/usr/bin/env python3
"""prepare_sma5_data.py - Prepare data with SMA(38/80)-segment labels and 5 ta indicators."""

import argparse
import glob
import os
import re
import sys

import numpy as np
import pandas as pd
import talib
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import ADXIndicator
from ta.volatility import BollingerBands
from ta.volume import MFIIndicator

# reuse sort/dedup from prepareTraining
import prepareTraining as pt


def parse_args():
    p = argparse.ArgumentParser(description="Prepare SMA-segment-labeled data with 5 ta indicators.")
    p.add_argument("--input-dir", default="./raw_data")
    p.add_argument("--output-dir", default="./prepared_sma5")
    p.add_argument("--pattern", default="*.csv")
    p.add_argument("--window", type=int, default=6, help="Future window for label_max_move_atr")
    return p.parse_args()


def parse_ticker_timeframe(path):
    return pt.parse_ticker_timeframe(path)


def sma_segment_labels(close, high, low):
    s38 = pd.Series(close).rolling(38, min_periods=38).mean().to_numpy()
    s80 = pd.Series(close).rolling(80, min_periods=80).mean().to_numpy()
    diff = s38 - s80
    # crossing positions
    crosses = [0]
    for i in range(1, len(close)):
        if not (np.isfinite(diff[i-1]) and np.isfinite(diff[i])):
            continue
        if diff[i-1] == 0:
            continue
        if np.sign(diff[i]) != np.sign(diff[i-1]) and diff[i] != 0:
            crosses.append(i)
    crosses.append(len(close) - 1)
    crosses = sorted(set(crosses))

    labels = np.zeros(len(close), dtype=float)
    for a, b in zip(crosses, crosses[1:]):
        if b - a < 1:
            continue
        mid = (a + b) // 2
        if not np.isfinite(diff[mid]):
            continue
        if diff[mid] > 0:
            pos = int(np.nanargmax(high[a:b+1]) + a)
            labels[pos] = -1.0
        else:
            pos = int(np.nanargmin(low[a:b+1]) + a)
            labels[pos] = 1.0
    return labels, s38, s80


def compute_features(df):
    """Compute ta-based features and return df with feat_* columns (no labels)."""
    df = pt.sort_and_dedup(df.copy())
    c = df["c"].to_numpy(dtype=float)
    h = df["h"].to_numpy(dtype=float)
    l = df["l"].to_numpy(dtype=float)
    v = df["v"].to_numpy(dtype=float) if "v" in df.columns else np.ones(len(df))
    if "vw" not in df.columns:
        df["vw"] = df["c"]

    rsi = RSIIndicator(pd.Series(c), window=14).rsi().to_numpy(dtype=float)
    stoch = StochasticOscillator(pd.Series(h), pd.Series(l), pd.Series(c), window=14, smooth_window=3)
    stoch_k = stoch.stoch().to_numpy(dtype=float)
    stoch_d = stoch.stoch_signal().to_numpy(dtype=float)
    adx = ADXIndicator(pd.Series(h), pd.Series(l), pd.Series(c), window=14).adx().to_numpy(dtype=float)
    bb = BollingerBands(pd.Series(c), window=20, window_dev=2)
    bb_bandwidth = bb.bollinger_wband().to_numpy(dtype=float)
    bb_pctb = bb.bollinger_pband().to_numpy(dtype=float)
    bb_mid = bb.bollinger_mavg().to_numpy(dtype=float)
    mfi = MFIIndicator(pd.Series(h), pd.Series(l), pd.Series(c), pd.Series(v), window=14).money_flow_index().to_numpy(dtype=float)

    feat = {}
    feat["feat_rsi"] = rsi / 100.0
    feat["feat_rsi_diff"] = (rsi - np.roll(rsi, 1)) / 100.0
    feat["feat_rsi_diff"][0] = np.nan
    feat["feat_stoch_k"] = stoch_k / 100.0
    feat["feat_stoch_d"] = stoch_d / 100.0
    feat["feat_stoch_diff"] = (stoch_k - stoch_d) / 100.0
    feat["feat_adx"] = adx / 100.0
    feat["feat_bb_pct_b"] = bb_pctb
    feat["feat_bb_bandwidth"] = bb_bandwidth
    feat["feat_bb_dist_mid"] = (c - bb_mid) / np.where(np.abs(bb_mid) < 1e-8, 1.0, bb_mid)
    feat["feat_mfi"] = mfi / 100.0
    feat["feat_mfi_diff"] = (mfi - np.roll(mfi, 1)) / 100.0
    feat["feat_mfi_diff"][0] = np.nan

    for k, val in feat.items():
        df[k] = val
    df = df.replace([np.inf, -np.inf], np.nan)
    return df

def process_file(input_path, output_dir, args):
    ticker, timeframe = parse_ticker_timeframe(input_path)
    stem = os.path.splitext(os.path.basename(input_path))[0]
    df = pd.read_csv(input_path)
    for col in ["t", "o", "h", "l", "c", "v"]:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    if "vw" not in df.columns:
        df["vw"] = df["c"]
    if df.empty:
        raise ValueError("Input file is empty")

    df = pt.sort_and_dedup(df)
    o = df["o"].to_numpy(dtype=float)
    h = df["h"].to_numpy(dtype=float)
    l = df["l"].to_numpy(dtype=float)
    c = df["c"].to_numpy(dtype=float)
    v = df["v"].to_numpy(dtype=float)
    n = len(df)

    # indicators (ta)
    rsi = RSIIndicator(pd.Series(c), window=14).rsi().to_numpy(dtype=float)
    stoch = StochasticOscillator(pd.Series(h), pd.Series(l), pd.Series(c), window=14, smooth_window=3)
    stoch_k = stoch.stoch().to_numpy(dtype=float)
    stoch_d = stoch.stoch_signal().to_numpy(dtype=float)
    adx = ADXIndicator(pd.Series(h), pd.Series(l), pd.Series(c), window=14).adx().to_numpy(dtype=float)
    bb = BollingerBands(pd.Series(c), window=20, window_dev=2)
    bb_high = bb.bollinger_hband().to_numpy(dtype=float)
    bb_low = bb.bollinger_lband().to_numpy(dtype=float)
    bb_mid = bb.bollinger_mavg().to_numpy(dtype=float)
    bb_bandwidth = bb.bollinger_wband().to_numpy(dtype=float)
    bb_pctb = bb.bollinger_pband().to_numpy(dtype=float)
    mfi = MFIIndicator(pd.Series(h), pd.Series(l), pd.Series(c), pd.Series(v), window=14).money_flow_index().to_numpy(dtype=float)

    # scale-stable features
    feat = {}
    feat["feat_rsi"] = rsi / 100.0
    feat["feat_rsi_diff"] = (rsi - np.roll(rsi, 1)) / 100.0
    feat["feat_rsi_diff"][0] = np.nan
    feat["feat_stoch_k"] = stoch_k / 100.0
    feat["feat_stoch_d"] = stoch_d / 100.0
    feat["feat_stoch_diff"] = (stoch_k - stoch_d) / 100.0
    feat["feat_adx"] = adx / 100.0
    feat["feat_bb_pct_b"] = bb_pctb
    feat["feat_bb_bandwidth"] = bb_bandwidth
    feat["feat_bb_dist_mid"] = (c - bb_mid) / np.where(np.abs(bb_mid) < 1e-8, 1.0, bb_mid)
    feat["feat_mfi"] = mfi / 100.0
    feat["feat_mfi_diff"] = (mfi - np.roll(mfi, 1)) / 100.0
    feat["feat_mfi_diff"][0] = np.nan

    # labels from SMA segments
    labels, s38, s80 = sma_segment_labels(c, h, l)

    # ATR for label_max_move_atr
    atr = talib.ATR(h, l, c, timeperiod=14)
    wr = args.window
    fut_min_low = pd.Series(l).rolling(window=wr, min_periods=wr).min().shift(-wr).to_numpy()
    fut_max_high = pd.Series(h).rolling(window=wr, min_periods=wr).max().shift(-wr).to_numpy()
    valid_future = np.isfinite(fut_min_low) & np.isfinite(fut_max_high)
    drop = h - fut_min_low
    rise = fut_max_high - l
    up_move = (fut_max_high - l) / atr
    down_move = (h - fut_min_low) / atr

    label_max_move = np.zeros(n, dtype=float)
    # neutral default
    neu_move = np.maximum(up_move, down_move)
    label_max_move[:] = neu_move[:]
    # extremes
    high_mask = labels == -1
    low_mask = labels == 1
    label_max_move[high_mask] = (drop / atr)[high_mask]
    label_max_move[low_mask] = (rise / atr)[low_mask]

    # drop incomplete future rows
    incomplete = ~valid_future
    labels[incomplete] = np.nan
    label_max_move[incomplete] = np.nan

    # assemble output
    out = pd.DataFrame({
        "meta_t": df["t"].values,
        "meta_ticker": [ticker] * n,
        "meta_timeframe": [timeframe] * n,
        "meta_open": o,
        "meta_high": h,
        "meta_low": l,
        "meta_close": c,
    })
    for k, val in feat.items():
        out[k] = val
    out["label_turn"] = labels
    out["label_max_move_atr"] = label_max_move

    feat_cols = [col for col in out.columns if col.startswith("feat_")]
    out = out.replace([np.inf, -np.inf], np.nan)
    out = out.dropna(subset=feat_cols + ["label_turn", "label_max_move_atr"]).reset_index(drop=True)
    out["label_turn"] = out["label_turn"].astype(int)

    if out.empty:
        raise ValueError("No rows left after cleanup")

    os.makedirs(output_dir, exist_ok=True)
    output_name = f"{stem}_prepared.csv"
    output_path = os.path.join(output_dir, output_name)
    out.to_csv(output_path, index=False)
    return {"input": os.path.basename(input_path), "output": output_name, "rows": len(out),
            "ticker": ticker, "timeframe": timeframe}


def main():
    args = parse_args()
    if not os.path.isdir(args.input_dir):
        print(f"Input directory not found: {args.input_dir}", file=sys.stderr)
        sys.exit(1)
    os.makedirs(args.output_dir, exist_ok=True)
    candidates = sorted(glob.glob(os.path.join(args.input_dir, args.pattern)))
    files = [p for p in candidates if os.path.isfile(p) and not os.path.basename(p).endswith("_prepared.csv")]
    if not files:
        print("No files found", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(files)} raw CSV(s)")
    total = 0
    for path in files:
        try:
            info = process_file(path, args.output_dir, args)
            total += info["rows"]
            print(f"OK {info['input']} -> {info['output']} | rows={info['rows']}")
        except Exception as e:
            print(f"SKIP {os.path.basename(path)}: {e}", file=sys.stderr)
    print(f"Total rows: {total}")


if __name__ == "__main__":
    main()
