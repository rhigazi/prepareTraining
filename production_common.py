#!/usr/bin/env python3
"""production_common.py - Shared production helpers for the three bundles.

Responsibilities
----------------
* registry / bundle loading (active model + scaler + model_config.json)
* exact profile-specific feature pipelines used during training
* inference and post-processing (threshold + cooldown NMS)
* validation / OOT / SMA-segment metrics used by the retraining gate
* building updated profile data from raw CSVs for retraining
"""

import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

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
from train_turning_points import (
    TurningPointMLP,
    suppress_signal_clusters,
    turn_metrics,
)

PROD_DIR = os.environ.get("PRODUCTION_MODELS_DIR", os.path.join(HERE, "production_models"))
REGISTRY_PATH = os.path.join(PROD_DIR, "registry.json")
RAW_DIR = os.path.join(HERE, "raw_data")

CLASS_MAP = {0: -1, 1: 0, 2: 1}
SEGMENT_TOLERANCE = 5

DEFAULT_GATE = {
    "val_f1_abs_drop": 0.02,
    "val_f1_rel_drop": 0.10,
    "oot_f1_abs_drop": 0.02,
    "oot_f1_rel_drop": 0.10,
    "hit_avg_abs_drop": 0.05,
    "event_precision_abs_drop": 0.03,
    "extra_rate_abs_increase": 0.05,
    "min_signals": 50,
}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_production_dir():
    os.makedirs(PROD_DIR, exist_ok=True)


# --------------------------------------------------------------------------- #
# Registry / bundle loading
# --------------------------------------------------------------------------- #
def load_registry():
    if not os.path.isfile(REGISTRY_PATH):
        raise FileNotFoundError(
            f"Missing {REGISTRY_PATH}. Run: python3 build_production_bundles.py"
        )
    return read_json(REGISTRY_PATH)


def resolve_profile(profile=None):
    """Return (profile_key, registry_entry, absolute_active_dir).

    Accepts aliases (baseline, sma_auto, ml4t), strand names
    (baseline_opt, sma_auto_opt, ml4t_opt) and bundle names.
    """
    reg = load_registry()
    target = profile or reg["default_active"]
    profiles = reg["profiles"]
    aliases = reg.get("aliases", {})

    if target in profiles:
        key = target
    elif target in aliases:
        key = aliases[target]
    else:
        matches = [k for k, v in profiles.items()
                   if target in (v.get("bundle"), v.get("strand"), v.get("run_id"))]
        if not matches:
            valid = sorted(set(list(profiles) + list(aliases)))
            raise ValueError(f"Unknown model profile '{target}'. Valid: {valid}")
        key = matches[0]

    entry = profiles[key]
    active_dir = os.path.join(PROD_DIR, entry["active_dir"])
    return key, entry, active_dir


def load_bundle(profile=None, model_dir=None):
    """Load config, model and scaler. Returns (cfg, model, scaler, bundle_dir)."""
    if model_dir:
        bundle_dir = os.path.abspath(model_dir)
        cfg = read_json(os.path.join(bundle_dir, "model_config.json"))
    else:
        _, _, bundle_dir = resolve_profile(profile)
        cfg = read_json(os.path.join(bundle_dir, "model_config.json"))

    ckpt_path = os.path.join(bundle_dir, "turning_point_mlp.pt")
    scaler_path = os.path.join(bundle_dir, "feature_scaler.joblib")
    for p in (ckpt_path, scaler_path):
        if not os.path.isfile(p):
            raise FileNotFoundError(f"Missing production artifact: {p}")

    ckpt = torch.load(ckpt_path, map_location="cpu")
    scaler = joblib.load(scaler_path)
    model = TurningPointMLP(
        in_features=len(ckpt["feature_cols"]),
        hidden_dims=ckpt["hidden_dims"],
        dropout=ckpt["dropout"],
        num_classes=3,
    )
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    cfg_features = list(cfg["data"]["feature_list"])
    if cfg_features != list(ckpt["feature_cols"]):
        raise ValueError("model_config feature_list does not match checkpoint feature_cols")
    if int(cfg["architecture"]["input_dim"]) != len(cfg_features):
        raise ValueError("model_config input_dim does not match feature list")
    return cfg, model, scaler, bundle_dir


def postprocessing(cfg):
    pp = cfg["post_processing"]
    return float(pp["threshold"]), int(pp["cooldown_bars"])


# --------------------------------------------------------------------------- #
# Feature pipelines
# --------------------------------------------------------------------------- #
def compute_profile_features(raw, pipeline):
    if pipeline == "baseline":
        work = raw.copy()
        if "vw" not in work.columns:
            work["vw"] = work["c"]
        return ae.compute_features(work)
    if pipeline == "sma5":
        return sma5.compute_features(raw.copy())
    if pipeline == "ml4t":
        return mf.compute_features(raw.copy())
    raise ValueError(f"Unknown feature pipeline: {pipeline}")


def infer_array(raw, cfg, model, scaler, threshold=None, cooldown=None):
    """Run one raw dataframe through features -> scaler -> MLP -> NMS."""
    pipeline = cfg["data"]["feature_pipeline_key"]
    df = compute_profile_features(raw, pipeline)
    feature_cols = list(cfg["data"]["feature_list"])
    missing = [c for c in feature_cols if c not in df.columns]
    for c in missing:
        df[c] = np.nan

    X = df[feature_cols].to_numpy(dtype=np.float32)
    valid = np.isfinite(X).all(axis=1)
    X = np.where(np.isfinite(X), X, 0.0)
    with np.errstate(all="ignore"):
        Xs = scaler.transform(X)
    Xs = np.nan_to_num(Xs, nan=0.0, posinf=0.0, neginf=0.0)

    probs = np.zeros((len(df), 3), dtype=np.float32)
    probs[:, 1] = 1.0
    if valid.any():
        with torch.no_grad():
            logits = model(torch.tensor(Xs[valid], dtype=torch.float32))
            probs[valid] = torch.softmax(logits, dim=-1).numpy()

    threshold_cfg, cooldown_cfg = postprocessing(cfg)
    threshold = threshold_cfg if threshold is None else threshold
    cooldown = cooldown_cfg if cooldown is None else cooldown
    raw_idx = suppress_signal_clusters(probs, float(threshold), cooldown_bars=1)
    filt_idx = suppress_signal_clusters(probs, float(threshold), cooldown_bars=int(cooldown))
    raw_idx = np.where(valid, raw_idx, 1)
    filt_idx = np.where(valid, filt_idx, 1)

    close, high, low, _ = et.standardize_ohlc(df)
    return {
        "df": df,
        "probs": probs,
        "raw": np.array([CLASS_MAP[int(i)] for i in raw_idx], dtype=int),
        "filt": np.array([CLASS_MAP[int(i)] for i in filt_idx], dtype=int),
        "valid": valid,
        "close": close,
        "high": high,
        "low": low,
        "missing_features": missing,
        "threshold": float(threshold),
        "cooldown": int(cooldown),
    }


def prediction_frame(res, cfg, source_file="", profile_label=""):
    df = res["df"]
    ticker, timeframe = pt.parse_ticker_timeframe(source_file) if source_file else ("", "")
    out = pd.DataFrame({
        "source_file": [os.path.basename(source_file)] * len(df) if source_file else [""] * len(df),
        "meta_t": df["t"].values,
        "meta_ticker": [ticker] * len(df),
        "meta_timeframe": [timeframe] * len(df),
        "meta_open": df["o"].to_numpy(dtype=float) if "o" in df.columns else np.nan,
        "meta_high": df["h"].to_numpy(dtype=float) if "h" in df.columns else np.nan,
        "meta_low": df["l"].to_numpy(dtype=float) if "l" in df.columns else np.nan,
        "meta_close": df["c"].to_numpy(dtype=float) if "c" in df.columns else np.nan,
        "prob_-1": res["probs"][:, 0],
        "prob_0": res["probs"][:, 1],
        "prob_1": res["probs"][:, 2],
        "raw_pred": res["raw"],
        "filtered_pred": res["filt"],
        "valid_features": res["valid"],
        "model_profile": [profile_label or cfg.get("profile", "")] * len(df),
        "threshold": [res["threshold"]] * len(df),
        "cooldown_bars": [res["cooldown"]] * len(df),
    })
    return out


def predict_file(path, cfg, model, scaler, threshold=None, cooldown=None):
    raw = pd.read_csv(path)
    res = infer_array(raw, cfg, model, scaler, threshold, cooldown)
    if res["missing_features"]:
        raise ValueError(f"Feature pipeline missing columns: {res['missing_features']}")
    return prediction_frame(res, cfg, path, cfg.get("profile", ""))


# --------------------------------------------------------------------------- #
# Prepared data / split (identical logic to train_turning_points.py)
# --------------------------------------------------------------------------- #
def load_prepared(input_dir, feature_cols):
    files = sorted(glob.glob(os.path.join(input_dir, "*_prepared.csv")))
    if not files:
        files = sorted(glob.glob(os.path.join(input_dir, "*.csv")))
    if not files:
        raise FileNotFoundError(f"No prepared CSV files in {input_dir}")

    frames = []
    for path in files:
        df = pd.read_csv(path)
        if "meta_ticker" not in df.columns or df["meta_ticker"].isna().all():
            df["meta_ticker"] = pt.parse_ticker_timeframe(path)[0]
        if "meta_timeframe" not in df.columns or df["meta_timeframe"].isna().all():
            df["meta_timeframe"] = pt.parse_ticker_timeframe(path)[1]
        if "ticker_source" not in df.columns:
            df["ticker_source"] = os.path.splitext(os.path.basename(path))[0]
        df["meta_t"] = pd.to_datetime(df["meta_t"], utc=True, errors="coerce")
        if df["meta_t"].isna().all():
            df["meta_t"] = pd.to_datetime(df["meta_t"], errors="coerce")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True).dropna(subset=["meta_t"]).reset_index(drop=True)
    df = df.replace([np.inf, -np.inf], np.nan).dropna(
        subset=list(feature_cols) + ["label_turn", "label_max_move_atr"]
    ).reset_index(drop=True)
    df["target_idx"] = df["label_turn"].astype(int).map({-1: 0, 0: 1, 1: 2})
    return df


def split_prepared(df, training_cfg):
    out_of_tickers = list(training_cfg.get("out_of_tickers", ["AAPL"]))
    oot_mask = df["meta_ticker"].isin(out_of_tickers)
    df_oot = df[oot_mask].copy().reset_index(drop=True)
    df_rest = df[~oot_mask].copy().reset_index(drop=True)
    if df_rest.empty:
        raise ValueError("No in-ticker data after out-of-ticker removal")

    train_frac = float(training_cfg.get("train_frac", 0.70))
    val_frac = float(training_cfg.get("val_frac", 0.15))
    purge = pd.Timedelta(minutes=float(training_cfg.get("purge_minutes", 0.0)))

    unique_times = np.sort(df_rest["meta_t"].unique())
    train_pos = int(len(unique_times) * train_frac)
    val_pos = int(len(unique_times) * (train_frac + val_frac))
    train_cutoff = unique_times[max(train_pos - 1, 0)]
    val_cutoff = unique_times[max(val_pos - 1, 0)]

    frames = {
        "train": df_rest[df_rest["meta_t"] <= (train_cutoff - purge)].copy(),
        "val": df_rest[(df_rest["meta_t"] > (train_cutoff + purge)) &
                       (df_rest["meta_t"] <= (val_cutoff - purge))].copy(),
        "test": df_rest[df_rest["meta_t"] > (val_cutoff + purge)].copy(),
        "oot": df_oot,
    }
    for k in ("train", "val", "test", "oot"):
        frames[k] = frames[k].reset_index(drop=True)
    frames["_cutoffs"] = {"train_cutoff": str(train_cutoff), "val_cutoff": str(val_cutoff)}
    return frames


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def model_probabilities(cfg, model, scaler, frame):
    feature_cols = list(cfg["data"]["feature_list"])
    X = frame[feature_cols].to_numpy(dtype=np.float32)
    Xs = scaler.transform(X)
    Xs = np.nan_to_num(Xs, nan=0.0, posinf=0.0, neginf=0.0)
    if len(Xs) == 0:
        return np.empty((0, 3), dtype=np.float32)
    with torch.no_grad():
        logits = model(torch.tensor(Xs, dtype=torch.float32))
        return torch.softmax(logits, dim=-1).numpy()


def frame_turn_metrics(cfg, model, scaler, frame):
    threshold, cooldown = postprocessing(cfg)
    probs = model_probabilities(cfg, model, scaler, frame)
    if len(probs) == 0:
        return {"f1": 0.0, "precision": 0.0, "recall": 0.0, "signals": 0, "rows": 0}
    pred = suppress_signal_clusters(probs, threshold, cooldown_bars=cooldown)
    p, r, f1 = turn_metrics(frame["target_idx"].to_numpy(), pred)
    return {"f1": float(f1), "precision": float(p), "recall": float(r),
            "signals": int((pred != 1).sum()), "rows": int(len(frame))}


def segment_metrics(filt_turn, segs, close, atr, tol=SEGMENT_TOLERANCE):
    hits = {"bull": 0, "bear": 0}
    misses = {"bull": 0, "bear": 0}
    matched = set()
    dist_sum = 0.0
    dist_n = 0
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
                dist_sum += abs(close[best] - close[pos]) / a
                dist_n += 1
        else:
            misses[side] += 1

    sig_positions = [i for i in range(len(filt_turn)) if filt_turn[i] != 0]
    extra = [i for i in sig_positions if i not in matched]
    return {
        "hits_bull": hits["bull"], "misses_bull": misses["bull"],
        "hits_bear": hits["bear"], "misses_bear": misses["bear"],
        "extra": len(extra),
        "extra_high": sum(1 for i in extra if filt_turn[i] == -1),
        "extra_low": sum(1 for i in extra if filt_turn[i] == 1),
        "model_sigs": len(sig_positions),
        "atr_dist_sum": float(dist_sum), "atr_dist_n": int(dist_n),
    }


def aggregate_segment_metrics(items):
    agg = {"hits_bull": 0, "misses_bull": 0, "hits_bear": 0, "misses_bear": 0,
           "extra": 0, "extra_high": 0, "extra_low": 0, "model_sigs": 0,
           "atr_dist_sum": 0.0, "atr_dist_n": 0}
    for m in items:
        for k in agg:
            agg[k] += m[k]
    hb, mb = agg["hits_bull"], agg["misses_bull"]
    hr, mr = agg["hits_bear"], agg["misses_bear"]
    segs = hb + mb + hr + mr
    hits = hb + hr
    agg["hit_rate_bull"] = hb / (hb + mb) if (hb + mb) else 0.0
    agg["hit_rate_bear"] = hr / (hr + mr) if (hr + mr) else 0.0
    agg["hit_avg"] = (agg["hit_rate_bull"] + agg["hit_rate_bear"]) / 2.0
    agg["extra_rate"] = agg["extra"] / agg["model_sigs"] if agg["model_sigs"] else 1.0
    agg["event_precision"] = hits / (hits + agg["extra"]) if (hits + agg["extra"]) else 0.0
    agg["event_recall"] = hits / segs if segs else 0.0
    ep, er = agg["event_precision"], agg["event_recall"]
    agg["event_f1"] = 2 * ep * er / (ep + er) if (ep + er) else 0.0
    agg["mean_atr_dist"] = (agg["atr_dist_sum"] / agg["atr_dist_n"]
                            if agg["atr_dist_n"] else None)
    agg["atr_quality"] = (1.0 / (1.0 + agg["mean_atr_dist"])
                          if agg["mean_atr_dist"] is not None else 0.0)
    agg["segments_total"] = segs
    return agg


def segment_metrics_for_raw(cfg, model, scaler, raw_paths):
    items = []
    details = {}
    for path in raw_paths:
        raw = pd.read_csv(path)
        res = infer_array(raw, cfg, model, scaler)
        s38, s80, segs, crosses = et.sma_cross_segments(res["close"], res["high"], res["low"])
        atr = talib.ATR(res["high"], res["low"], res["close"], timeperiod=14)
        m = segment_metrics(res["filt"], segs, res["close"], atr)
        items.append(m)
        details[os.path.basename(path)] = m
    agg = aggregate_segment_metrics(items) if items else aggregate_segment_metrics([])
    agg["files"] = len(items)
    return agg, details


def evaluate_bundle(cfg, model, scaler, frames, raw_dir=RAW_DIR):
    val = frame_turn_metrics(cfg, model, scaler, frames["val"])
    test = frame_turn_metrics(cfg, model, scaler, frames["test"])
    oot = frame_turn_metrics(cfg, model, scaler, frames["oot"])

    raw_all = sorted(glob.glob(os.path.join(raw_dir, "*.csv")))
    tickers = set(cfg["training"].get("out_of_tickers", ["AAPL"]))
    raw_oot = [p for p in raw_all if pt.parse_ticker_timeframe(p)[0] in tickers]
    seg_all, _ = segment_metrics_for_raw(cfg, model, scaler, raw_all)
    seg_oot, seg_oot_files = segment_metrics_for_raw(cfg, model, scaler, raw_oot)

    return {
        "val_f1": val["f1"], "test_f1": test["f1"], "oot_f1": oot["f1"],
        "val_precision": val["precision"], "val_recall": val["recall"],
        "oot_precision": oot["precision"], "oot_recall": oot["recall"],
        "val_signals": val["signals"], "test_signals": test["signals"],
        "oot_signals": oot["signals"],
        "segments_oot": seg_oot, "segments_all": seg_all,
        "segments_oot_files": seg_oot_files,
        "threshold": postprocessing(cfg)[0], "cooldown_bars": postprocessing(cfg)[1],
    }


def gate_check(active, candidate, gate=None):
    gate = {**DEFAULT_GATE, **(gate or {})}
    checks = []

    def add(name, passed, active_val, cand_val, rule):
        checks.append({"check": name, "passed": bool(passed),
                       "active": active_val, "candidate": cand_val, "rule": rule})

    def allowed_drop(active_val, abs_key, rel_key):
        return max(float(gate[abs_key]), float(gate[rel_key]) * abs(float(active_val)))

    for key, abs_key, rel_key, label in (
        ("val_f1", "val_f1_abs_drop", "val_f1_rel_drop", "Val-F1"),
        ("oot_f1", "oot_f1_abs_drop", "oot_f1_rel_drop", "OOT-F1"),
    ):
        a, c = float(active[key]), float(candidate[key])
        lim = allowed_drop(a, abs_key, rel_key)
        add(f"{key}_no_significant_drop", c >= a - lim, a, c,
            f"candidate >= active - max({gate[abs_key]}, {gate[rel_key]}*active) = {a - lim:.4f}")

    a = active["segments_oot"]["hit_avg"]
    c = candidate["segments_oot"]["hit_avg"]
    add("segment_hit_avg_no_drop", c >= a - gate["hit_avg_abs_drop"], a, c,
        f"candidate >= active - {gate['hit_avg_abs_drop']}")

    a = active["segments_oot"]["event_precision"]
    c = candidate["segments_oot"]["event_precision"]
    add("event_precision_no_drop", c >= a - gate["event_precision_abs_drop"], a, c,
        f"candidate >= active - {gate['event_precision_abs_drop']}")

    a = active["segments_oot"]["extra_rate"]
    c = candidate["segments_oot"]["extra_rate"]
    add("extra_rate_no_increase", c <= a + gate["extra_rate_abs_increase"], a, c,
        f"candidate <= active + {gate['extra_rate_abs_increase']}")

    a = active["segments_oot"]["model_sigs"]
    c = candidate["segments_oot"]["model_sigs"]
    add("minimum_signal_count", c >= gate["min_signals"], a, c,
        f"candidate >= {gate['min_signals']}")

    return {"passed": all(x["passed"] for x in checks), "checks": checks,
            "thresholds": gate}


# --------------------------------------------------------------------------- #
# Updated data preparation (for retraining)
# --------------------------------------------------------------------------- #
def _run(cmd, log, cwd=HERE):
    log(f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.stdout.strip():
        log(proc.stdout.strip()[-6000:])
    if proc.returncode != 0:
        if proc.stderr.strip():
            log(proc.stderr.strip()[-6000:])
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def expand_sma_labels(src_dir, dst_dir, tol):
    """Expand SMA segment labels by +/-tol without cascading (source snapshot)."""
    os.makedirs(dst_dir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(src_dir, "*_prepared.csv"))):
        df = pd.read_csv(path)
        src = df["label_turn"].to_numpy().copy()
        lt = src.copy()
        lma = df["label_max_move_atr"].to_numpy().copy()
        lma_src = lma.copy()
        n = len(df)
        for i in range(n):
            if src[i] != 0:
                for j in range(max(0, i - tol), min(n, i + tol + 1)):
                    if lt[j] == 0:
                        lt[j] = src[i]
                        lma[j] = lma_src[i]
        df["label_turn"] = lt.astype(int)
        df["label_max_move_atr"] = lma
        df.to_csv(os.path.join(dst_dir, os.path.basename(path)), index=False)


def build_ml4t_data(raw_dir, out_dir, tol):
    os.makedirs(out_dir, exist_ok=True)
    n_files = 0
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.csv"))):
        raw = pd.read_csv(path)
        if "vw" not in raw.columns:
            raw["vw"] = raw["c"]
        df = pt.sort_and_dedup(raw)
        work = mf.compute_features(df.copy())
        o = df["o"].to_numpy(float)
        h = df["h"].to_numpy(float)
        l = df["l"].to_numpy(float)
        c = df["c"].to_numpy(float)

        base = sma5.sma_segment_labels(c, h, l)[0]
        labels = base.copy()
        if tol > 0:
            out = base.copy()
            for i in range(len(base)):
                if base[i] != 0:
                    for j in range(max(0, i - tol), min(len(base), i + tol + 1)):
                        if out[j] == 0:
                            out[j] = base[i]
            labels = out

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
        work.to_csv(os.path.join(out_dir, f"{stem}_prepared.csv"), index=False)
        n_files += 1
    if n_files == 0:
        raise RuntimeError("ML4T data preparation produced no files")
    return n_files


def prepare_profile_data(cfg, raw_dir, out_dir, log):
    """Rebuild the exact profile dataset from raw CSVs into out_dir."""
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    pipeline = cfg["data"]["feature_pipeline_key"]
    args = cfg["data"].get("prepare_args", {})

    if pipeline == "baseline":
        cmd = [sys.executable, os.path.join(HERE, "prepareTraining.py"),
               "--input-dir", raw_dir, "--output-dir", out_dir,
               "--window_left", str(args.get("window_left", 6)),
               "--window_right", str(args.get("window_right", 6)),
               "--min_move_atr", str(args.get("min_move_atr", 1.5))]
        if args.get("min_rel_volume") is not None:
            cmd += ["--min_rel_volume", str(args["min_rel_volume"])]
        if args.get("max_gap_minutes") is not None:
            cmd += ["--max_gap_minutes", str(args["max_gap_minutes"])]
        _run(cmd, log)

    elif pipeline == "sma5":
        pre_dir = out_dir + "_pre"
        cmd = [sys.executable, os.path.join(HERE, "prepare_sma5_data.py"),
               "--input-dir", raw_dir, "--output-dir", pre_dir,
               "--window", str(args.get("window", 6))]
        _run(cmd, log)
        expand_sma_labels(pre_dir, out_dir, int(cfg["data"]["label_rule"]["tolerance_bars"]))
        shutil.rmtree(pre_dir, ignore_errors=True)

    elif pipeline == "ml4t":
        build_ml4t_data(raw_dir, out_dir, int(cfg["data"]["label_rule"]["tolerance_bars"]))

    else:
        raise ValueError(f"Unknown pipeline: {pipeline}")

    files = glob.glob(os.path.join(out_dir, "*_prepared.csv"))
    if not files:
        raise RuntimeError(f"Prepared data is empty: {out_dir}")
    log(f"Prepared {len(files)} files for pipeline '{pipeline}' in {out_dir}")
    return out_dir


# --------------------------------------------------------------------------- #
# Control chart
# --------------------------------------------------------------------------- #
def plot_control_chart(res, cfg, global_metrics, file_metrics, start, end, title, out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    close, high, low = res["close"], res["high"], res["low"]
    s38, s80, segs, _ = et.sma_cross_segments(close, high, low)
    filt = res["filt"]
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
    sig_high = [i for i in range(start, end) if filt[i] == -1]
    sig_low = [i for i in range(start, end) if filt[i] == 1]
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

    g, f = global_metrics, file_metrics
    box = (
        f"OOT  sig {g['model_sigs']} | extra {g['extra']} ({g['extra_rate'] * 100:.1f}%)\n"
        f"Hit Bull {g['hits_bull']}/{g['hits_bull'] + g['misses_bull']} ({g['hit_rate_bull']:.2f})"
        f" | Hit Bear {g['hits_bear']}/{g['hits_bear'] + g['misses_bear']} ({g['hit_rate_bear']:.2f})\n"
        f"Val-F1 {g.get('val_f1', float('nan')):.3f} | OOT-F1 {g.get('oot_f1', float('nan')):.3f}"
        f" | ATR-Q {g.get('atr_quality', 0):.2f}\n"
        f"FILE sig {f['model_sigs']} | extra {f['extra']}"
        f" | Hit Bull {f['hits_bull'] / max(f['hits_bull'] + f['misses_bull'], 1):.2f}"
        f" | Hit Bear {f['hits_bear'] / max(f['hits_bear'] + f['misses_bear'], 1):.2f}"
    )
    ax.text(0.995, 0.015, box, transform=ax.transAxes, fontsize=7.5,
            va="bottom", ha="right",
            bbox=dict(boxstyle="round,pad=0.45", facecolor="white", alpha=0.90,
                      edgecolor="#555555"))
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)
