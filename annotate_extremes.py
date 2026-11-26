#!/usr/bin/env python3
"""annotate_extremes.py - Annotate raw OHLCV CSVs with turning-point predictions."""

import argparse
import glob
import os
import re
import sys

import joblib
import numpy as np
import pandas as pd
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import prepareTraining as pt
from train_turning_points import TurningPointMLP, suppress_signal_clusters

try:
    import talib
except Exception as e:
    print("TA-Lib is required:", e, file=sys.stderr)
    sys.exit(1)


def parse_args():
    p = argparse.ArgumentParser(description="Annotate raw CSVs with turning-point extremes.")
    p.add_argument("--model-dir", default="./runs/opt_01", help="Directory with checkpoint & scaler")
    p.add_argument("--input-dir", default=None, help="Folder of raw CSVs")
    p.add_argument("--files", nargs="*", default=None, help="Explicit raw CSV file(s)")
    p.add_argument("--pattern", default="*.csv", help="Glob pattern when using --input-dir")
    p.add_argument("--output-dir", default="./annotated_data", help="Output folder")
    p.add_argument("--min-confidence", type=float, default=None, help="Min max(prob_high,prob_low) to mark")
    p.add_argument("--cooldown-bars", type=int, default=None, help="Override cooldown")
    return p.parse_args()


def collect_files(args):
    files = []
    if args.files:
        files.extend(args.files)
    if args.input_dir:
        cand = sorted(glob.glob(os.path.join(args.input_dir, args.pattern)))
        for pth in cand:
            if os.path.isfile(pth):
                files.append(pth)
    # de-dup
    seen = set()
    out = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def compute_features(df):
    df = pt.sort_and_dedup(df.copy())
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

    # CrossSMA
    use_provided_cross = False
    cross_sma = None
    if "CrossSMA(38,80)" in df.columns:
        try:
            arr = df["CrossSMA(38,80)"].to_numpy(dtype=float)
            if np.isfinite(arr).any():
                use_provided_cross = True
                cross_sma = df["CrossSMA(38,80)"].to_numpy()
        except Exception:
            use_provided_cross = False
    if not use_provided_cross:
        cross_sma = np.zeros(n, dtype=int)
        diff = sma38 - sma80
        prev = np.roll(diff, 1)
        prev[0] = np.nan
        up_cross = (diff > 0) & (prev <= 0) & np.isfinite(diff) & np.isfinite(prev)
        down_cross = (diff < 0) & (prev >= 0) & np.isfinite(diff) & np.isfinite(prev)
        cross_sma[up_cross] = 1
        cross_sma[down_cross] = -1

    atr = talib.ATR(h, l, c, timeperiod=14)
    adx = talib.ADX(h, l, c, timeperiod=14)
    stoch_k, stoch_d = talib.STOCH(h, l, c)
    vol_sma20 = talib.SMA(v, timeperiod=20)

    feat = {}
    feat["feat_body_atr"] = (c - o) / atr
    feat["feat_upper_wick_atr"] = (h - np.maximum(o, c)) / atr
    feat["feat_lower_wick_atr"] = (np.minimum(o, c) - l) / atr
    feat["feat_close_pos_in_candle"] = (c - l) / (h - l + 1e-8)
    feat["feat_dist_sma38_atr"] = (c - sma38) / atr
    feat["feat_dist_sma80_atr"] = (c - sma80) / atr
    feat["feat_diff_sma38_80_atr"] = (sma38 - sma80) / atr
    feat["feat_dist_vwap_atr"] = (c - vw) / atr

    sma38_shifted = np.roll(sma38, 3)
    sma38_shifted[:3] = np.nan
    feat["feat_sma38_slope"] = (sma38 - sma38_shifted) / atr

    feat["feat_rsi21"] = rsi
    rsi_shifted = np.roll(rsi, 1)
    rsi_shifted[0] = np.nan
    feat["feat_rsi21_diff"] = rsi - rsi_shifted

    feat["feat_cross_sma"] = cross_sma
    feat["feat_adx14"] = adx
    feat["feat_stoch_k"] = stoch_k
    feat["feat_stoch_d"] = stoch_d
    feat["feat_rel_volume"] = v / vol_sma20

    for k, val in feat.items():
        df[k] = val
    df = df.replace([np.inf, -np.inf], np.nan)
    return df


def main():
    args = parse_args()
    files = collect_files(args)
    if not files:
        print("No input files found.", file=sys.stderr)
        sys.exit(1)

    model_dir = args.model_dir
    ckpt_path = os.path.join(model_dir, "turning_point_mlp.pt")
    scaler_path = os.path.join(model_dir, "feature_scaler.joblib")
    if not os.path.isfile(ckpt_path) or not os.path.isfile(scaler_path):
        print(f"Missing model artifacts in {model_dir}", file=sys.stderr)
        sys.exit(1)

    ckpt = torch.load(ckpt_path, map_location="cpu")
    feature_cols = ckpt["feature_cols"]
    hidden_dims = ckpt["hidden_dims"]
    dropout = ckpt["dropout"]
    best_threshold = float(ckpt.get("best_threshold", 0.5))
    cooldown = int(ckpt.get("cooldown_bars", 5))
    if args.cooldown_bars is not None:
        cooldown = args.cooldown_bars
    threshold = args.min_confidence if args.min_confidence is not None else best_threshold

    scaler = joblib.load(scaler_path)
    model = TurningPointMLP(in_features=len(feature_cols), hidden_dims=hidden_dims, dropout=dropout, num_classes=3)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    os.makedirs(args.output_dir, exist_ok=True)

    idx_to_turn = {0: -1, 1: 0, 2: 1}

    for path in files:
        try:
            raw = pd.read_csv(path)
        except Exception as e:
            print(f"SKIP {path}: {e}", file=sys.stderr)
            continue
        if "t" not in raw.columns:
            print(f"SKIP {path}: missing 't'", file=sys.stderr)
            continue
        # keep original order copy for output? We'll work on sorted.
        work = raw.copy()
        # ensure required columns
        for col in ["o", "h", "l", "c", "v", "vw"]:
            if col not in work.columns:
                print(f"SKIP {path}: missing column {col}", file=sys.stderr)
                break
        else:
            pass
        if any(col not in work.columns for col in ["o", "h", "l", "c", "v", "vw"]):
            continue

        df = compute_features(work)

        # Feature matrix
        X = df[feature_cols].to_numpy(dtype=np.float32) if all(c in df.columns for c in feature_cols) else None
        if X is None:
            print(f"SKIP {path}: missing feature columns", file=sys.stderr)
            continue
        X = np.where(np.isfinite(X), X, 0.0)
        # valid mask: all original features finite
        valid = np.isfinite(df[feature_cols].to_numpy(dtype=float)).all(axis=1)

        # Scale
        Xs = scaler.transform(X)
        Xs = np.where(np.isfinite(Xs), Xs, 0.0)

        probs = np.zeros((len(df), 3), dtype=np.float32)
        probs[:, 1] = 1.0  # neutral default for invalid rows
        if valid.any():
            with torch.no_grad():
                xb = torch.tensor(Xs[valid], dtype=torch.float32)
                logits = model(xb)
                p = torch.softmax(logits, dim=-1).cpu().numpy()
                probs[valid] = p

        # raw & filtered with suppress
        raw_idx = suppress_signal_clusters(probs, threshold, cooldown_bars=1) if len(probs) else np.array([])
        filt_idx = suppress_signal_clusters(probs, threshold, cooldown_bars=cooldown) if len(probs) else np.array([])
        # For invalid rows force neutral
        raw_idx = np.where(valid, raw_idx, 1)
        filt_idx = np.where(valid, filt_idx, 1)

        raw_turn = np.array([idx_to_turn.get(int(i), 0) for i in raw_idx])
        filt_turn = np.array([idx_to_turn.get(int(i), 0) for i in filt_idx])

        # Build output preserving sorted df's original columns
        out = df.copy()
        # Keep only original (non-engineered) columns in the output.
        feat_cols = [c for c in out.columns if c.startswith("feat_")]
        out = out.drop(columns=feat_cols)
        out["prob_high"] = probs[:, 0]
        out["prob_neutral"] = probs[:, 1]
        out["prob_low"] = probs[:, 2]
        out["raw_pred_turn"] = raw_turn
        out["extreme_point"] = filt_turn
        def label_of(v):
            if v == -1:
                return "Extrem-Hoch"
            if v == 1:
                return "Extrem-Tief"
            return ""
        out["extreme_label"] = [label_of(v) for v in filt_turn]

        stem = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(args.output_dir, f"{stem}_extremes.csv")
        out.to_csv(out_path, index=False)

        n_high = int((filt_turn == -1).sum())
        n_low = int((filt_turn == 1).sum())
        msg = f"{os.path.basename(path)}: rows={len(out)}, Extrem-Hoch(-1)={n_high}, Extrem-Tief(+1)={n_low}, threshold={threshold:.2f}, cooldown={cooldown}"
        if "label_turn" in raw.columns:
            # map back? raw sorted; out sorted same. compute hit among marked
            marked = out[out["extreme_point"] != 0]
            if len(marked):
                hits = (marked["extreme_point"] == marked["label_turn"]).sum()
                hr = hits / len(marked)
                msg += f", marked_hit_rate={hr:.3f} ({hits}/{len(marked)})"
        print(msg)

    print(f"\nDone. Output dir: {args.output_dir}")


if __name__ == "__main__":
    main()
