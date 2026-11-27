#!/usr/bin/env python3
"""run_eval_3ways.py - Three independent evaluation/search strands.

Strands
-------
1. baseline_opt : standard feat_* features + swing labels (prepareTraining.py),
                  chronologic split, AAPL out-of-ticker holdout.
2. sma_auto_opt : SMA(38/80) segment labels + ta indicator features
                  (prepare_sma5_data.py), optional label-tolerance variants.
3. ml4t_opt     : stationary/normalised ML4T style features + SMA segment labels
                  with tolerance/signal calibration variants.

Every trial is written to runs/eval_3ways/<strand>/<trial>/ including the
trainer's training_run.log.  The winner is copied to <strand>/best/ and gets
PNG/HTML charts under best/charts/.

Existing run folders (runs/opt_01, runs/sma5_best, runs/auto_search, ...) are
never touched by this script.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import talib
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import annotate_extremes as ae
import extremes_tool as et
import ml4t_features as mf
import prepareTraining as pt
import prepare_sma5_data as sma5
from train_turning_points import TurningPointMLP, suppress_signal_clusters

TRAIN = os.path.join(HERE, "train_turning_points.py")
RAW_DIR = os.path.join(HERE, "raw_data")
PREP_ORIG = os.path.join(HERE, "prepared_data")
PREP_SMA5 = os.path.join(HERE, "prepared_sma5")

BASE_DIR = os.path.join(HERE, "runs", "eval_3ways")
DATA_DIR = os.path.join(BASE_DIR, "_data")
STRANDS = ("baseline_opt", "sma_auto_opt", "ml4t_opt")
BUILDERS = {"baseline_opt": "baseline", "sma_auto_opt": "sma5", "ml4t_opt": "ml4t"}

TOLERANCE_BARS = 5
CHART_WINDOW = 400


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
class Tee:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")

    def __call__(self, msg=""):
        line = str(msg)
        print(line)
        self.fh.write(line + "\n")
        self.fh.flush()

    def close(self):
        self.fh.close()


# --------------------------------------------------------------------------- #
# Data preparation
# --------------------------------------------------------------------------- #
def expand_labels(labels, tol):
    if tol <= 0:
        return labels.copy()
    out = labels.copy()
    n = len(labels)
    for i in range(n):
        if labels[i] != 0:
            for j in range(max(0, i - tol), min(n, i + tol + 1)):
                if out[j] == 0:
                    out[j] = labels[i]
    return out


def sma_segment_labels(close, high, low):
    return sma5.sma_segment_labels(close, high, low)[0]


def make_ml4t_prepared(tol, dst, log):
    """Build ML4T stationary-feature CSVs with SMA tolerance labels."""
    if os.path.isdir(dst) and glob.glob(os.path.join(dst, "*_prepared.csv")):
        log(f"  reusing {os.path.relpath(dst, HERE)}")
        return dst
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    n_files = 0
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
        raw = pd.read_csv(path)
        for col in ("t", "o", "h", "l", "c", "v"):
            if col not in raw.columns:
                raise ValueError(f"{path}: missing column {col}")
        if "vw" not in raw.columns:
            raw["vw"] = raw["c"]
        df = pt.sort_and_dedup(raw)
        work = mf.compute_features(df.copy())
        h = df["h"].to_numpy(float)
        l = df["l"].to_numpy(float)
        c = df["c"].to_numpy(float)
        o = df["o"].to_numpy(float)

        labels = expand_labels(sma_segment_labels(c, h, l), tol)
        atr = talib.ATR(h, l, c, timeperiod=14)
        wr = 6
        fut_min_low = pd.Series(l).rolling(wr, min_periods=wr).min().shift(-wr).to_numpy()
        fut_max_high = pd.Series(h).rolling(wr, min_periods=wr).max().shift(-wr).to_numpy()
        valid_future = np.isfinite(fut_min_low) & np.isfinite(fut_max_high)
        drop = h - fut_min_low
        rise = fut_max_high - l
        up_move = (fut_max_high - l) / atr
        down_move = (h - fut_min_low) / atr
        label_move = np.maximum(up_move, down_move)
        hm = labels == -1
        lm = labels == 1
        label_move[hm] = (drop / atr)[hm]
        label_move[lm] = (rise / atr)[lm]
        incomplete = ~valid_future
        labels[incomplete] = np.nan
        label_move[incomplete] = np.nan

        work["meta_t"] = df["t"].values
        work["meta_ticker"] = pt.parse_ticker_timeframe(path)[0]
        work["meta_timeframe"] = pt.parse_ticker_timeframe(path)[1]
        work["meta_open"] = o
        work["meta_high"] = h
        work["meta_low"] = l
        work["meta_close"] = c
        work["label_turn"] = labels
        work["label_max_move_atr"] = label_move

        feat_cols = [col for col in work.columns if col.startswith("feat_")]
        work = work.replace([np.inf, -np.inf], np.nan)
        work = work.dropna(subset=feat_cols + ["label_turn", "label_max_move_atr"]).reset_index(drop=True)
        if work.empty:
            continue
        work["label_turn"] = work["label_turn"].astype(int)
        stem = os.path.splitext(os.path.basename(path))[0]
        work.to_csv(os.path.join(dst, f"{stem}_prepared.csv"), index=False)
        n_files += 1
    log(f"  built {os.path.relpath(dst, HERE)} ({n_files} files, tol={tol})")
    return dst


def make_sma_tol_prepared(tol, dst, log):
    """Copy prepared_sma5 and expand swing labels by +/-tol bars."""
    if tol == 0:
        return PREP_SMA5
    if os.path.isdir(dst) and glob.glob(os.path.join(dst, "*_prepared.csv")):
        log(f"  reusing {os.path.relpath(dst, HERE)}")
        return dst
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(PREP_SMA5, "*_prepared.csv"))):
        df = pd.read_csv(path)
        src = df["label_turn"].to_numpy().copy()
        lt = src.copy()
        lma = df["label_max_move_atr"].to_numpy().copy()
        n = len(df)
        for i in range(n):
            if src[i] != 0:
                for j in range(max(0, i - tol), min(n, i + tol + 1)):
                    if lt[j] == 0:
                        lt[j] = src[i]
                        lma[j] = lma[i]
        df["label_turn"] = lt.astype(int)
        df["label_max_move_atr"] = lma
        df.to_csv(os.path.join(dst, os.path.basename(path)), index=False)
    log(f"  built {os.path.relpath(dst, HERE)} (tol={tol})")
    return dst


def prepare_all(log):
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    if not glob.glob(os.path.join(PREP_ORIG, "*_prepared.csv")):
        log("prepared_data empty -> running prepareTraining.py")
        subprocess.run([sys.executable, os.path.join(HERE, "prepareTraining.py"),
                        "--input-dir", RAW_DIR, "--output-dir", PREP_ORIG], check=True)
    if not glob.glob(os.path.join(PREP_SMA5, "*_prepared.csv")):
        log("prepared_sma5 empty -> running prepare_sma5_data.py")
        subprocess.run([sys.executable, os.path.join(HERE, "prepare_sma5_data.py"),
                        "--input-dir", RAW_DIR, "--output-dir", PREP_SMA5], check=True)
    log("Preparing strand-specific data variants ...")
    sma_tol1 = make_sma_tol_prepared(1, os.path.join(DATA_DIR, "sma5_tol1"), log)
    sma_tol2 = make_sma_tol_prepared(2, os.path.join(DATA_DIR, "sma5_tol2"), log)
    ml_tol0 = make_ml4t_prepared(0, os.path.join(DATA_DIR, "ml4t_tol0"), log)
    ml_tol1 = make_ml4t_prepared(1, os.path.join(DATA_DIR, "ml4t_tol1"), log)
    ml_tol2 = make_ml4t_prepared(2, os.path.join(DATA_DIR, "ml4t_tol2"), log)
    return {
        "orig": PREP_ORIG,
        "sma5": PREP_SMA5,
        "sma5_tol1": sma_tol1,
        "sma5_tol2": sma_tol2,
        "ml4t_tol0": ml_tol0,
        "ml4t_tol1": ml_tol1,
        "ml4t_tol2": ml_tol2,
    }


# --------------------------------------------------------------------------- #
# Trial definitions
# --------------------------------------------------------------------------- #
def trial_configs(data):
    common = ["--out-of-tickers", "AAPL"]
    baseline = [
        ("base_01", data["orig"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.35",
                                   "--class-weight-power", "0.35", "--learning-rate", "5e-4",
                                   "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.60"]),
        ("base_02", data["orig"], ["--epochs", "18", "--hidden-dims", "128", "64", "--dropout", "0.40",
                                   "--class-weight-power", "0.50", "--learning-rate", "1e-3",
                                   "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.55"]),
        ("base_03", data["orig"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.25",
                                   "--class-weight-power", "0.35", "--learning-rate", "5e-4",
                                   "--cooldown-bars", "3", "--threshold-min", "0.35", "--threshold-max", "0.55"]),
        ("base_04", data["orig"], ["--epochs", "18", "--hidden-dims", "64", "32", "16", "--dropout", "0.45",
                                   "--class-weight-power", "0.60", "--learning-rate", "5e-4",
                                   "--cooldown-bars", "8", "--threshold-min", "0.45", "--threshold-max", "0.65"]),
        ("base_05", data["orig"], ["--epochs", "18", "--hidden-dims", "96", "48", "--dropout", "0.30",
                                   "--class-weight-power", "0.50", "--learning-rate", "7e-4",
                                   "--cooldown-bars", "6", "--threshold-min", "0.40", "--threshold-max", "0.60"]),
        ("base_06", data["orig"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.35",
                                   "--class-weight-power", "0.35", "--learning-rate", "5e-4",
                                   "--cooldown-bars", "12", "--threshold-min", "0.50", "--threshold-max", "0.70"]),
        ("base_07", data["orig"], ["--epochs", "18", "--hidden-dims", "128", "64", "--dropout", "0.35",
                                   "--class-weight-power", "0.70", "--learning-rate", "5e-4",
                                   "--cooldown-bars", "5", "--threshold-min", "0.45", "--threshold-max", "0.60"]),
        ("base_08", data["orig"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.35",
                                   "--class-weight-power", "0.35", "--learning-rate", "3e-4",
                                   "--label-smoothing", "0.10", "--cooldown-bars", "5",
                                   "--threshold-min", "0.40", "--threshold-max", "0.55"]),
    ]
    sma_auto = [
        ("sma_01", data["sma5"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.35",
                                  "--class-weight-power", "0.35", "--learning-rate", "5e-4",
                                  "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.55"]),
        ("sma_02", data["sma5_tol1"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.35",
                                       "--class-weight-power", "0.35", "--learning-rate", "5e-4",
                                       "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.55"]),
        ("sma_03", data["sma5_tol2"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.35",
                                       "--class-weight-power", "0.50", "--learning-rate", "5e-4",
                                       "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.55"]),
        ("sma_04", data["sma5_tol1"], ["--epochs", "18", "--hidden-dims", "128", "64", "--dropout", "0.40",
                                       "--class-weight-power", "0.50", "--learning-rate", "1e-3",
                                       "--cooldown-bars", "3", "--threshold-min", "0.35", "--threshold-max", "0.50"]),
        ("sma_05", data["sma5_tol2"], ["--epochs", "18", "--hidden-dims", "96", "48", "--dropout", "0.40",
                                       "--class-weight-power", "0.60", "--learning-rate", "7e-4",
                                       "--cooldown-bars", "8", "--threshold-min", "0.45", "--threshold-max", "0.60"]),
        ("sma_06", data["sma5"], ["--epochs", "18", "--hidden-dims", "64", "32", "16", "--dropout", "0.45",
                                  "--class-weight-power", "0.70", "--learning-rate", "5e-4",
                                  "--cooldown-bars", "3", "--threshold-min", "0.30", "--threshold-max", "0.45"]),
        ("sma_07", data["sma5_tol2"], ["--epochs", "18", "--hidden-dims", "128", "64", "--dropout", "0.30",
                                       "--class-weight-power", "0.50", "--learning-rate", "1e-3",
                                       "--cooldown-bars", "3", "--threshold-min", "0.40", "--threshold-max", "0.55"]),
        ("sma_08", data["sma5_tol1"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.25",
                                       "--class-weight-power", "0.35", "--learning-rate", "5e-4",
                                       "--cooldown-bars", "10", "--threshold-min", "0.50", "--threshold-max", "0.65"]),
    ]
    ml4t = [
        ("ml4t_01", data["ml4t_tol0"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.35",
                                        "--class-weight-power", "0.50", "--learning-rate", "5e-4",
                                        "--cooldown-bars", "5", "--threshold-min", "0.45", "--threshold-max", "0.60"]),
        ("ml4t_02", data["ml4t_tol1"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.35",
                                        "--class-weight-power", "0.50", "--learning-rate", "5e-4",
                                        "--cooldown-bars", "5", "--threshold-min", "0.45", "--threshold-max", "0.60"]),
        ("ml4t_03", data["ml4t_tol2"], ["--epochs", "18", "--hidden-dims", "128", "64", "--dropout", "0.40",
                                        "--class-weight-power", "0.50", "--learning-rate", "1e-3",
                                        "--cooldown-bars", "5", "--threshold-min", "0.45", "--threshold-max", "0.55"]),
        ("ml4t_04", data["ml4t_tol2"], ["--epochs", "18", "--hidden-dims", "96", "48", "--dropout", "0.40",
                                        "--class-weight-power", "0.60", "--learning-rate", "7e-4",
                                        "--cooldown-bars", "8", "--threshold-min", "0.50", "--threshold-max", "0.65"]),
        ("ml4t_05", data["ml4t_tol1"], ["--epochs", "18", "--hidden-dims", "128", "64", "--dropout", "0.45",
                                        "--class-weight-power", "0.70", "--learning-rate", "1e-3",
                                        "--cooldown-bars", "10", "--threshold-min", "0.55", "--threshold-max", "0.70"]),
        ("ml4t_06", data["ml4t_tol0"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.30",
                                        "--class-weight-power", "0.40", "--learning-rate", "5e-4",
                                        "--cooldown-bars", "6", "--threshold-min", "0.50", "--threshold-max", "0.60"]),
        ("ml4t_07", data["ml4t_tol2"], ["--epochs", "18", "--hidden-dims", "64", "32", "--dropout", "0.35",
                                        "--class-weight-power", "0.50", "--learning-rate", "5e-4",
                                        "--cooldown-bars", "8", "--threshold-min", "0.55", "--threshold-max", "0.70"]),
        ("ml4t_08", data["ml4t_tol1"], ["--epochs", "18", "--hidden-dims", "96", "48", "--dropout", "0.40",
                                        "--class-weight-power", "0.60", "--learning-rate", "7e-4",
                                        "--cooldown-bars", "12", "--threshold-min", "0.50", "--threshold-max", "0.65"]),
    ]
    return {"baseline_opt": (baseline, common),
            "sma_auto_opt": (sma_auto, common),
            "ml4t_opt": (ml4t, common)}


# --------------------------------------------------------------------------- #
# Training / log parsing
# --------------------------------------------------------------------------- #
def parse_training_log(log_path):
    val_f1 = threshold = None
    overall = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            m = re.search(r"Val Turn \(filtered\) P/R/F1: [\d.]+/[\d.]+/([\d.]+)", line)
            if m:
                val_f1 = float(m.group(1))
            m = re.search(r"Selected BEST_THRESHOLD: ([\d.]+)", line)
            if m:
                threshold = float(m.group(1))
            m = re.search(r"Overall Turn Precision/Recall/F1: ([\d.]+)/([\d.]+)/([\d.]+)", line)
            if m:
                overall.append(tuple(float(x) for x in m.groups()))
    test_f1 = overall[0][2] if overall else None
    oot_f1 = overall[1][2] if len(overall) >= 2 else (overall[0][2] if overall else None)
    return {"val_f1": val_f1, "test_f1": test_f1, "oot_f1": oot_f1,
            "threshold": threshold}


def run_trial(strand, name, data_dir, extra_args, log):
    out_dir = os.path.join(BASE_DIR, strand, name)
    log_path = os.path.join(out_dir, "training_run.log")
    if os.path.isfile(log_path) and os.path.isfile(os.path.join(out_dir, "turning_point_mlp.pt")):
        log(f"  [{name}] reusing existing run")
        return out_dir
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    cmd = [sys.executable, TRAIN, "--input-dir", data_dir, "--output-dir", out_dir] + extra_args
    with open(os.path.join(out_dir, "command.txt"), "w", encoding="utf-8") as f:
        f.write(" ".join(cmd) + "\n")
    log(f"  [{name}] training ...")
    t0 = time.time()
    with open(os.path.join(out_dir, "console.log"), "w", encoding="utf-8") as console:
        subprocess.run(cmd, stdout=console, stderr=subprocess.STDOUT, check=True)
    log(f"  [{name}] done in {time.time() - t0:.1f}s")
    return out_dir


# --------------------------------------------------------------------------- #
# Model loading / annotation / segment metrics
# --------------------------------------------------------------------------- #
def load_model(model_dir):
    ckpt = torch.load(os.path.join(model_dir, "turning_point_mlp.pt"), map_location="cpu")
    scaler = joblib.load(os.path.join(model_dir, "feature_scaler.joblib"))
    model = TurningPointMLP(in_features=len(ckpt["feature_cols"]),
                            hidden_dims=ckpt["hidden_dims"],
                            dropout=ckpt["dropout"], num_classes=3)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return ckpt, scaler, model


def annotate_raw(raw, ckpt, scaler, model, builder, threshold, cooldown):
    if builder == "baseline":
        df = ae.compute_features(raw.copy())
    elif builder == "sma5":
        df = sma5.compute_features(raw.copy())
    elif builder == "ml4t":
        df = mf.compute_features(raw.copy())
    else:
        raise ValueError(builder)
    cols = ckpt["feature_cols"]
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    X = df[cols].to_numpy(dtype=np.float32)
    valid = np.isfinite(X).all(axis=1)
    X = np.where(np.isfinite(X), X, 0.0)
    Xs = np.nan_to_num(scaler.transform(X), nan=0.0, posinf=0.0, neginf=0.0)
    probs = np.zeros((len(df), 3), dtype=np.float32)
    probs[:, 1] = 1.0
    if valid.any():
        with torch.no_grad():
            logits = model(torch.tensor(Xs[valid], dtype=torch.float32))
            probs[valid] = torch.softmax(logits, dim=-1).numpy()
    raw_idx = suppress_signal_clusters(probs, threshold, cooldown_bars=1)
    filt_idx = suppress_signal_clusters(probs, threshold, cooldown_bars=cooldown)
    raw_idx = np.where(valid, raw_idx, 1)
    filt_idx = np.where(valid, filt_idx, 1)
    idx_to_turn = {0: -1, 1: 0, 2: 1}
    raw_turn = np.array([idx_to_turn[int(i)] for i in raw_idx])
    filt_turn = np.array([idx_to_turn[int(i)] for i in filt_idx])
    close, high, low, _ = et.standardize_ohlc(df)
    out = df.copy()
    out["prob_high"] = probs[:, 0]
    out["prob_neutral"] = probs[:, 1]
    out["prob_low"] = probs[:, 2]
    out["raw_pred_turn"] = raw_turn
    out["extreme_point"] = filt_turn
    return out, probs, filt_turn, valid, close, high, low


def segment_metrics(filt_turn, segs, close, atr, tol=TOLERANCE_BARS):
    """Segment hits plus ATR-normalised distance of matched signals to extremes."""
    hits = {"bull": 0, "bear": 0}
    misses = {"bull": 0, "bear": 0}
    matched = set()
    dists = []
    for seg in segs:
        exp = seg["expected"]
        pos = seg["extremum_pos"]
        lo = max(0, pos - tol)
        hi = min(len(filt_turn) - 1, pos + tol)
        found = [i for i in range(lo, hi + 1) if filt_turn[i] == exp]
        side = "bull" if seg["type"] == "bull" else "bear"
        if found:
            hits[side] += 1
            matched.update(found)
            best = min(found, key=lambda i: abs(i - pos))
            a = atr[pos] if np.isfinite(atr[pos]) and atr[pos] > 0 else np.nan
            if np.isfinite(a):
                dists.append(abs(close[best] - close[pos]) / a)
        else:
            misses[side] += 1
    sig_positions = [i for i in range(len(filt_turn)) if filt_turn[i] != 0]
    extra = [i for i in sig_positions if i not in matched]
    return {
        "hits_bull": hits["bull"], "misses_bull": misses["bull"],
        "hits_bear": hits["bear"], "misses_bear": misses["bear"],
        "extra": len(extra), "extra_high": sum(1 for i in extra if filt_turn[i] == -1),
        "extra_low": sum(1 for i in extra if filt_turn[i] == 1),
        "model_sigs": len(sig_positions),
        "mean_atr_dist": float(np.mean(dists)) if dists else None,
    }


def evaluate_trial(model_dir, builder):
    ckpt, scaler, model = load_model(model_dir)
    threshold = float(ckpt.get("best_threshold", 0.5))
    cooldown = int(ckpt.get("cooldown_bars", 5))
    totals = {"hits_bull": 0, "misses_bull": 0, "hits_bear": 0, "misses_bear": 0,
              "extra": 0, "model_sigs": 0}
    dists = []
    per_file = []
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
        raw = pd.read_csv(path)
        ann, probs, filt, valid, close, high, low = annotate_raw(
            raw, ckpt, scaler, model, builder, threshold, cooldown)
        s38, s80, segs, crosses = et.sma_cross_segments(close, high, low)
        atr = talib.ATR(high, low, close, timeperiod=14)
        m = segment_metrics(filt, segs, close, atr)
        for k in totals:
            totals[k] += m[k]
        if m["mean_atr_dist"] is not None:
            dists.append(m["mean_atr_dist"])
        per_file.append({
            "file": os.path.basename(path),
            "segments_total": len(segs),
            "segments_bull": sum(1 for s in segs if s["type"] == "bull"),
            "segments_bear": sum(1 for s in segs if s["type"] == "bear"),
            **{k: m[k] for k in ("hits_bull", "misses_bull", "hits_bear", "misses_bear",
                                 "extra", "extra_high", "extra_low", "model_sigs")},
            "hit_rate_bull": (m["hits_bull"] / (m["hits_bull"] + m["misses_bull"])
                              if (m["hits_bull"] + m["misses_bull"]) else 0.0),
            "hit_rate_bear": (m["hits_bear"] / (m["hits_bear"] + m["misses_bear"])
                              if (m["hits_bear"] + m["misses_bear"]) else 0.0),
        })
    hb, mb = totals["hits_bull"], totals["misses_bull"]
    hr, mr = totals["hits_bear"], totals["misses_bear"]
    hr_bull = hb / (hb + mb) if (hb + mb) else 0.0
    hr_bear = hr / (hr + mr) if (hr + mr) else 0.0
    mean_dist = float(np.mean(dists)) if dists else None
    totals.update({
        "hit_rate_bull": hr_bull, "hit_rate_bear": hr_bear, "hit_avg": (hr_bull + hr_bear) / 2.0,
        "extra_rate": totals["extra"] / totals["model_sigs"] if totals["model_sigs"] else 1.0,
        "mean_atr_dist": mean_dist,
        "atr_quality": 1.0 / (1.0 + mean_dist) if mean_dist is not None else 0.0,
    })
    return totals, per_file


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def signal_penalty(n, lo, hi):
    p = 0.0
    if n < lo:
        p += (lo - n) / float(lo)
    if n > hi:
        p += (n - hi) / float(hi)
    return p


def composite_score(strand, row):
    val = row.get("val_f1") or 0.0
    oot = row.get("oot_f1") or 0.0
    hit = row.get("hit_avg") or 0.0
    extra = row.get("extra_rate")
    extra = 1.0 if extra is None else min(extra, 1.0)
    atrq = row.get("atr_quality") or 0.0
    n = row.get("model_sigs") or 0
    stability = 1.0 - abs(val - oot)
    if strand == "baseline_opt":
        pen = signal_penalty(n, 300, 9000)
        score = (0.35 * val + 0.25 * oot + 0.20 * hit +
                 0.10 * (1 - extra) + 0.10 * atrq - 0.10 * pen)
    elif strand == "sma_auto_opt":
        pen = signal_penalty(n, 400, 9000)
        score = (0.25 * val + 0.20 * oot + 0.30 * hit +
                 0.15 * (1 - extra) + 0.10 * stability - 0.10 * pen)
    else:  # ml4t_opt
        pen = signal_penalty(n, 300, 7000)
        score = (0.20 * val + 0.15 * oot + 0.45 * hit +
                 0.20 * (1 - extra) - 0.10 * pen)
    return max(0.0, min(1.0, score))


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def _draw_chart(close, high, low, s38, s80, segs, filt_turn, global_metrics,
                file_metrics, start, end, title, out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = np.arange(start, end)
    fig, ax = plt.subplots(figsize=(15, 6.5))
    ax.fill_between(x, high[start:end], low[start:end], color="lightgray", alpha=0.35,
                    label="High-Low")
    ax.plot(x, close[start:end], color="black", linewidth=1.0, label="Close")
    ax.plot(x, s38[start:end], color="orange", linewidth=1.1, label="SMA 38")
    ax.plot(x, s80[start:end], color="royalblue", linewidth=1.1, label="SMA 80")

    diff = s38 - s80
    cross_idx = [i for i in range(max(start, 1), end)
                 if np.isfinite(diff[i - 1]) and np.isfinite(diff[i]) and diff[i - 1] * diff[i] < 0]
    if cross_idx:
        ax.scatter(cross_idx, close[cross_idx], marker="x", color="purple", s=45, zorder=5,
                   label="SMA(38/80)-Cross")

    seg_high = [s["extremum_pos"] for s in segs
                if s["type"] == "bull" and start <= s["extremum_pos"] < end]
    seg_low = [s["extremum_pos"] for s in segs
               if s["type"] == "bear" and start <= s["extremum_pos"] < end]
    if seg_high:
        ax.scatter(seg_high, high[seg_high], marker="v", s=90, facecolors="none",
                   edgecolors="red", linewidths=1.4, zorder=6, label="Seg-Extrem Hoch (Ref)")
    if seg_low:
        ax.scatter(seg_low, low[seg_low], marker="^", s=90, facecolors="none",
                   edgecolors="green", linewidths=1.4, zorder=6, label="Seg-Extrem Tief (Ref)")

    sig_high = [i for i in range(start, end) if filt_turn[i] == -1]
    sig_low = [i for i in range(start, end) if filt_turn[i] == 1]
    if sig_high:
        ax.scatter(sig_high, high[sig_high], marker="v", color="darkred", s=55, zorder=7,
                   label="Modell -1 (Extrem-Hoch)")
    if sig_low:
        ax.scatter(sig_low, low[sig_low], marker="^", color="darkgreen", s=55, zorder=7,
                   label="Modell +1 (Extrem-Tief)")

    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Bar index")
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=7, ncol=2, framealpha=0.85)

    g = global_metrics
    f = file_metrics
    box = (
        f"GLOBAL  sig {g['model_sigs']} | extra {g['extra']} ({g['extra_rate'] * 100:.1f}%)\n"
        f"Hit Bull {g['hits_bull']}/{g['hits_bull'] + g['misses_bull']} ({g['hit_rate_bull']:.2f})"
        f" | Hit Bear {g['hits_bear']}/{g['hits_bear'] + g['misses_bear']} ({g['hit_rate_bear']:.2f})\n"
        f"Val-F1 {g.get('val_f1', float('nan')):.3f} | OOT-F1 {g.get('oot_f1', float('nan')):.3f}"
        f" | ATR-Q {g.get('atr_quality', 0):.2f}\n"
        f"FILE   sig {f['model_sigs']} | extra {f['extra']}"
        f" | Hit Bull {f['hit_rate_bull']:.2f} | Hit Bear {f['hit_rate_bear']:.2f}"
    )
    ax.text(0.995, 0.015, box, transform=ax.transAxes, fontsize=7.5,
            va="bottom", ha="right",
            bbox=dict(boxstyle="round,pad=0.45", facecolor="white", alpha=0.90,
                      edgecolor="#555555"))
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def _write_html(close, high, low, s38, s80, segs, filt_turn, start, end, title, out_html):
    try:
        import plotly.graph_objects as go
    except Exception:
        return
    x = list(range(start, end))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x + x[::-1], y=list(high[start:end]) + list(low[start:end][::-1]),
                             fill="toself", name="High-Low", line=dict(color="lightgray"),
                             opacity=0.25))
    fig.add_trace(go.Scatter(x=x, y=close[start:end], name="Close", line=dict(color="black")))
    fig.add_trace(go.Scatter(x=x, y=s38[start:end], name="SMA 38", line=dict(color="orange")))
    fig.add_trace(go.Scatter(x=x, y=s80[start:end], name="SMA 80", line=dict(color="royalblue")))
    diff = s38 - s80
    cx = [i for i in range(max(start, 1), end)
          if np.isfinite(diff[i - 1]) and np.isfinite(diff[i]) and diff[i - 1] * diff[i] < 0]
    if cx:
        fig.add_trace(go.Scatter(x=cx, y=close[cx], mode="markers", name="Cross",
                                 marker=dict(symbol="x", color="purple", size=8)))
    sh = [s["extremum_pos"] for s in segs if s["type"] == "bull" and start <= s["extremum_pos"] < end]
    sl = [s["extremum_pos"] for s in segs if s["type"] == "bear" and start <= s["extremum_pos"] < end]
    if sh:
        fig.add_trace(go.Scatter(x=sh, y=high[sh], mode="markers", name="Seg-Extrem Hoch",
                                 marker=dict(symbol="triangle-down", color="red", size=11,
                                             line=dict(width=1))))
    if sl:
        fig.add_trace(go.Scatter(x=sl, y=low[sl], mode="markers", name="Seg-Extrem Tief",
                                 marker=dict(symbol="triangle-up", color="green", size=11,
                                             line=dict(width=1))))
    mh = [i for i in range(start, end) if filt_turn[i] == -1]
    ml = [i for i in range(start, end) if filt_turn[i] == 1]
    if mh:
        fig.add_trace(go.Scatter(x=mh, y=high[mh], mode="markers", name="Modell -1",
                                 marker=dict(symbol="triangle-down", color="darkred", size=10)))
    if ml:
        fig.add_trace(go.Scatter(x=ml, y=low[ml], mode="markers", name="Modell +1",
                                 marker=dict(symbol="triangle-up", color="darkgreen", size=10)))
    fig.update_layout(title=title, xaxis_title="Bar index", yaxis_title="Price",
                      template="plotly_white", hovermode="x unified")
    fig.write_html(out_html, include_plotlyjs="cdn")


def generate_charts(best_dir, builder, global_metrics, log):
    chart_dir = os.path.join(best_dir, "charts")
    if os.path.exists(chart_dir):
        shutil.rmtree(chart_dir)
    os.makedirs(chart_dir)
    ckpt, scaler, model = load_model(best_dir)
    threshold = float(ckpt.get("best_threshold", 0.5))
    cooldown = int(ckpt.get("cooldown_bars", 5))
    index_rows = []

    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        raw = pd.read_csv(path)
        ann, probs, filt, valid, close, high, low = annotate_raw(
            raw, ckpt, scaler, model, builder, threshold, cooldown)
        s38, s80, segs, crosses = et.sma_cross_segments(close, high, low)
        atr = talib.ATR(high, low, close, timeperiod=14)
        fm = segment_metrics(filt, segs, close, atr)
        fm["hit_rate_bull"] = (fm["hits_bull"] / (fm["hits_bull"] + fm["misses_bull"])
                              if (fm["hits_bull"] + fm["misses_bull"]) else 0.0)
        fm["hit_rate_bear"] = (fm["hits_bear"] / (fm["hits_bear"] + fm["misses_bear"])
                               if (fm["hits_bear"] + fm["misses_bear"]) else 0.0)
        n = len(close)
        for ci, start in enumerate(range(0, n, CHART_WINDOW)):
            end = min(start + CHART_WINDOW, n)
            png = os.path.join(chart_dir, f"{stem}_chart_{ci + 1:03d}.png")
            title = f"{stem} | bars {start}-{end - 1} | {builder} best model"
            _draw_chart(close, high, low, s38, s80, segs, filt, global_metrics, fm,
                        start, end, title, png)
            index_rows.append({"chart": os.path.basename(png), "file": os.path.basename(path),
                               "start": start, "end": end - 1})

        if stem == "AAPL_1Hour_tool":
            start, end = 1600, min(2000, n)
            png = os.path.join(chart_dir, f"{stem}_bars_{start}-{end - 1}.png")
            html = os.path.join(chart_dir, f"{stem}_bars_{start}-{end - 1}.html")
            title = f"{stem} | bars {start}-{end - 1} (Pflichtausschnitt) | {builder} best model"
            _draw_chart(close, high, low, s38, s80, segs, filt, global_metrics, fm,
                        start, end, title, png)
            _write_html(close, high, low, s38, s80, segs, filt, start, end, title, html)
            index_rows.append({"chart": os.path.basename(png), "file": os.path.basename(path),
                               "start": start, "end": end - 1})
            index_rows.append({"chart": os.path.basename(html), "file": os.path.basename(path),
                               "start": start, "end": end - 1})

    idx = pd.DataFrame(index_rows)
    idx.to_csv(os.path.join(chart_dir, "chart_index.csv"), index=False)
    with open(os.path.join(chart_dir, "chart_index.md"), "w", encoding="utf-8") as f:
        f.write(f"# Charts - {builder} best model\n\n")
        f.write(f"{len(idx)} chart files, {CHART_WINDOW} bars per tile.\n\n")
        f.write("Pflicht: `AAPL_1Hour_tool_bars_1600-1999.png` (+ interaktives `.html`).\n\n")
        f.write(idx.to_markdown(index=False))
        f.write("\n")
    log(f"  charts: {len(idx)} files -> {os.path.relpath(chart_dir, HERE)}")


# --------------------------------------------------------------------------- #
# Summaries
# --------------------------------------------------------------------------- #
def write_summary(strand, df, best_name, log):
    out_dir = os.path.join(BASE_DIR, strand)
    csv_path = os.path.join(out_dir, "experiments_summary.csv")
    df.to_csv(csv_path, index=False)
    cols = ["trial", "data_variant", "val_f1", "test_f1", "oot_f1", "hit_rate_bull",
            "hit_rate_bear", "hit_avg", "model_sigs", "extra", "extra_rate",
            "mean_atr_dist", "atr_quality", "stability", "score"]
    md_path = os.path.join(out_dir, "experiments_summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Evaluation strand: {strand}\n\n")
        f.write(f"Generated: {datetime.now().isoformat(timespec='seconds')}\n\n")
        f.write(f"**Winner:** `{best_name}` (score {df.iloc[0]['score']:.4f})\n\n")
        f.write("## Selection score\n\n")
        if strand == "baseline_opt":
            f.write("`0.35*Val-F1 + 0.25*OOT-F1 + 0.20*HitAvg + 0.10*(1-ExtraRate) "
                    "+ 0.10*ATR-Quality - 0.10*SignalPenalty`\n")
        elif strand == "sma_auto_opt":
            f.write("`0.25*Val-F1 + 0.20*OOT-F1 + 0.30*HitAvg + 0.15*(1-ExtraRate) "
                    "+ 0.10*Stability - 0.10*SignalPenalty`\n")
        else:
            f.write("`0.20*Val-F1 + 0.15*OOT-F1 + 0.45*HitAvg + 0.20*(1-ExtraRate) "
                    "- 0.10*SignalPenalty`\n")
        f.write("\nATR-Quality = `1 / (1 + mean(|Close(signal)-Close(segment extreme)| / ATR14))` "
                "over matched signals. Stability = `1 - |Val-F1 - OOT-F1|`.\n\n")
        f.write("## Runs\n\n")
        f.write(df[cols].to_markdown(index=False, floatfmt=".4f"))
        f.write("\n")
    log(f"  summary: {os.path.relpath(md_path, HERE)}")
    return csv_path, md_path


def copy_best(strand, best_name, log):
    src = os.path.join(BASE_DIR, strand, best_name)
    dst = os.path.join(BASE_DIR, strand, "best")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    log(f"  best -> {os.path.relpath(dst, HERE)}")
    return dst


def write_best_metrics(best_dir, strand, best_name, row, metrics, per_file, log):
    meta = {
        "strand": strand,
        "trial": best_name,
        "score": float(row["score"]),
        "data_variant": row["data_variant"],
        "val_f1": row["val_f1"],
        "test_f1": row["test_f1"],
        "oot_f1": row["oot_f1"],
        "threshold": row["threshold"],
        "global": {k: (float(v) if isinstance(v, (np.floating, float)) else v)
                   for k, v in metrics.items()},
    }
    with open(os.path.join(best_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    rep = os.path.join(best_dir, "reports")
    os.makedirs(rep, exist_ok=True)
    pdf = pd.DataFrame(per_file)
    pdf.to_csv(os.path.join(rep, "sma_validation_summary.csv"), index=False)
    with open(os.path.join(rep, "sma_validation_summary.md"), "w", encoding="utf-8") as f:
        f.write(f"# SMA(38/80) segment validation - {strand} / {best_name}\n\n")
        f.write(pdf.to_markdown(index=False, floatfmt=".4f"))
        f.write("\n")
    g = metrics
    with open(os.path.join(best_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(f"# Best model - {strand}\n\n")
        f.write(f"- Trial: `{best_name}`\n")
        f.write(f"- Score: {row['score']:.4f}\n")
        f.write(f"- Data variant: `{row['data_variant']}`\n")
        f.write(f"- Threshold: {row['threshold']}\n")
        f.write(f"- Val Turn-F1: {row['val_f1']:.3f}\n")
        f.write(f"- Test Turn-F1: {row['test_f1']:.3f}\n")
        f.write(f"- OOT (AAPL) Turn-F1: {row['oot_f1']:.3f}\n\n")
        f.write("## Segment / signal quality (all 27 raw files)\n\n")
        f.write(f"- Signals: {g['model_sigs']}\n- Extra signals: {g['extra']} "
                f"({g['extra_rate'] * 100:.1f}%)\n")
        f.write(f"- Hit Bull: {g['hits_bull']}/{g['hits_bull'] + g['misses_bull']} "
                f"({g['hit_rate_bull']:.2f})\n")
        f.write(f"- Hit Bear: {g['hits_bear']}/{g['hits_bear'] + g['misses_bear']} "
                f"({g['hit_rate_bear']:.2f})\n")
        f.write(f"- Mean ATR distance: {g['mean_atr_dist']}\n")
        f.write(f"- ATR quality: {g['atr_quality']:.3f}\n\n")
        f.write("Charts: `charts/` incl. `AAPL_1Hour_tool_bars_1600-1999.png`.\n")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strands", nargs="*", default=list(STRANDS), choices=list(STRANDS))
    ap.add_argument("--max-trials", type=int, default=None, help="Smoke-test: limit trials per strand")
    ap.add_argument("--skip-charts", action="store_true")
    args = ap.parse_args()

    os.makedirs(BASE_DIR, exist_ok=True)
    log = Tee(os.path.join(BASE_DIR, "search.log"))
    log("=" * 78)
    log(f"eval_3ways started {datetime.now().isoformat(timespec='seconds')}")
    log("=" * 78)

    data = prepare_all(log)
    configs = trial_configs(data)

    for strand in args.strands:
        log("")
        log("#" * 78)
        log(f"# Strand: {strand}")
        log("#" * 78)
        trials, common = configs[strand]
        if args.max_trials:
            trials = trials[:args.max_trials]
        builder = BUILDERS[strand]
        rows = []
        for name, data_dir, extra in trials:
            try:
                out_dir = run_trial(strand, name, data_dir, common + extra, log)
                parsed = parse_training_log(os.path.join(out_dir, "training_run.log"))
                metrics, per_file = evaluate_trial(out_dir, builder)
                row = {
                    "trial": name,
                    "data_variant": os.path.basename(data_dir),
                    "data_dir": data_dir,
                    "val_f1": parsed["val_f1"],
                    "test_f1": parsed["test_f1"],
                    "oot_f1": parsed["oot_f1"],
                    "threshold": parsed["threshold"],
                    **{k: metrics[k] for k in ("hits_bull", "misses_bull", "hits_bear",
                                               "misses_bear", "hit_rate_bull",
                                               "hit_rate_bear", "hit_avg", "extra",
                                               "model_sigs", "extra_rate",
                                               "mean_atr_dist", "atr_quality")},
                    "stability": 1.0 - abs((parsed["val_f1"] or 0.0) - (parsed["oot_f1"] or 0.0)),
                    "params": " ".join(extra),
                }
                row["score"] = composite_score(strand, row)
                rows.append(row)
                log(f"  {name}: val={row['val_f1']} oot={row['oot_f1']} "
                    f"hit_b={row['hit_rate_bull']:.3f} hit_r={row['hit_rate_bear']:.3f} "
                    f"sigs={row['model_sigs']} extra={row['extra']} "
                    f"atrQ={row['atr_quality']:.3f} score={row['score']:.4f}")
            except Exception as e:
                log(f"  {name}: FAILED - {e}")

        if not rows:
            log(f"  no successful trials for {strand}")
            continue
        df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
        best = df.iloc[0]
        best_name = best["trial"]
        write_summary(strand, df, best_name, log)
        best_dir = copy_best(strand, best_name, log)
        metrics, per_file = evaluate_trial(best_dir, builder)
        metrics["val_f1"] = best["val_f1"]
        metrics["oot_f1"] = best["oot_f1"]
        write_best_metrics(best_dir, strand, best_name, best, metrics, per_file, log)
        if not args.skip_charts:
            generate_charts(best_dir, builder, metrics, log)
        log(f"  WINNER {strand}: {best_name} (score {best['score']:.4f})")

    log("")
    log(f"eval_3ways finished {datetime.now().isoformat(timespec='seconds')}")
    log.close()


if __name__ == "__main__":
    main()
