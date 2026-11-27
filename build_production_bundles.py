#!/usr/bin/env python3
"""build_production_bundles.py - Freeze the three eval winners as production bundles.

Reads runs/eval_3ways/<strand>/best/ plus the stored logs/summaries and writes:
  production_models/<strand>/active/{turning_point_mlp.pt,feature_scaler.joblib,model_config.json}
  production_models/registry.json

The script never changes runs/eval_3ways/. Existing active bundles are only
replaced with --force (archive/promotions are preserved).
"""

import argparse
import ast
import json
import os
import re
import shlex
import shutil
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import production_common as pc

BASE_DIR = os.path.join(HERE, "runs", "eval_3ways")

SPECS = {
    "baseline_opt": {
        "profile": "baseline",
        "run_id": "base_05",
        "description": "Original/Baseline strand: standard feat_* + swing labels (prepared_data)",
        "data_variant": "prepared_data",
        "data_dir": "prepared_data",
        "pipeline": "baseline",
        "prepare_script": "prepareTraining.py",
        "prepare_args": {"window_left": 6, "window_right": 6, "min_move_atr": 1.5,
                         "min_rel_volume": None, "max_gap_minutes": None},
    },
    "sma_auto_opt": {
        "profile": "sma_auto",
        "run_id": "sma_05",
        "description": "SMA(38/80) segment + auto-search strand (sma5_tol2, corrected labels)",
        "data_variant": "sma5_tol2",
        "data_dir": "runs/eval_3ways/_data/sma5_tol2",
        "pipeline": "sma5",
        "prepare_script": "prepare_sma5_data.py + corrected +/-2 label expansion",
        "prepare_args": {"window": 6},
    },
    "ml4t_opt": {
        "profile": "ml4t",
        "run_id": "ml4t_04",
        "description": "Stationary ML4T feature strand (ml4t_tol2) - default active profile",
        "data_variant": "ml4t_tol2",
        "data_dir": "runs/eval_3ways/_data/ml4t_tol2",
        "pipeline": "ml4t",
        "prepare_script": "ml4t_features.compute_features + SMA labels, tol=2",
        "prepare_args": {"sma_fast": 38, "sma_slow": 80, "future_window": 6},
    },
}

PIPELINE_NAMES = {
    "baseline": "annotate_extremes.compute_features (standard feat_*)",
    "sma5": "prepare_sma5_data.compute_features (ta indicator features)",
    "ml4t": "ml4t_features.compute_features (stationary/normalised features)",
}

OUTPUT_COLUMNS = [
    "source_file", "meta_t", "meta_ticker", "meta_timeframe",
    "meta_open", "meta_high", "meta_low", "meta_close",
    "prob_-1", "prob_0", "prob_1", "raw_pred", "filtered_pred",
    "valid_features", "model_profile", "threshold", "cooldown_bars",
]


def parse_command(path):
    if not os.path.isfile(path):
        return {}
    tokens = shlex.split(open(path, encoding="utf-8").read().strip())
    out, i = {}, 0
    while i < len(tokens):
        if tokens[i].startswith("--"):
            key = tokens[i][2:].replace("-", "_")
            vals = []
            i += 1
            while i < len(tokens) and not tokens[i].startswith("--"):
                vals.append(tokens[i])
                i += 1
            out[key] = vals
        else:
            i += 1
    return out


def get_num(cmd, key, default):
    vals = cmd.get(key)
    if not vals:
        return default
    return type(default)(vals[0]) if not isinstance(default, list) else [type(default[0])(v) for v in vals]


def get_list(cmd, key, default):
    vals = cmd.get(key)
    if not vals:
        return default
    return [int(v) for v in vals]


def parse_training_log(path):
    text = open(path, encoding="utf-8").read()
    info = {"features": None, "splits": {}, "val_f1": None, "test_f1": None,
            "oot_f1": None, "threshold": None, "epochs_run": None}
    m = re.search(r"Features \((\d+)\): (\[.*?\])", text)
    if m:
        info["feature_count"] = int(m.group(1))
        info["features"] = ast.literal_eval(m.group(2))
    split_re = re.compile(
        r"^(train|val|test|out_of_ticker): rows=(\d+) \| time=(.*?) \.\. (.*?) \| "
        r"label_turn: -1=(\d+), 0=(\d+), 1=(\d+)", re.MULTILINE)
    for m in split_re.finditer(text):
        name = "oot" if m.group(1) == "out_of_ticker" else m.group(1)
        info["splits"][name] = {
            "rows": int(m.group(2)), "start": m.group(3), "end": m.group(4),
            "labels": {"-1": int(m.group(5)), "0": int(m.group(6)), "1": int(m.group(7))},
        }
    m = re.search(r"Val Turn \(filtered\) P/R/F1: [\d.]+/[\d.]+/([\d.]+)", text)
    if m:
        info["val_f1"] = float(m.group(1))
    overall = [float(m.group(1)) for m in re.finditer(
        r"Overall Turn Precision/Recall/F1: [\d.]+/[\d.]+/([\d.]+)", text)]
    if overall:
        info["test_f1"] = overall[0]
        info["oot_f1"] = overall[1] if len(overall) > 1 else overall[0]
    m = re.search(r"Selected BEST_THRESHOLD: ([\d.]+)", text)
    if m:
        info["threshold"] = float(m.group(1))
    m = re.search(r"Early stopping in epoch (\d+)", text)
    if m:
        info["epochs_run"] = int(m.group(1))
    else:
        planned = re.findall(r"Epoch \d+/(\d+)", text)
        if planned:
            info["epochs_run"] = int(planned[-1])
    return info


def label_rule(spec):
    if spec["pipeline"] == "baseline":
        return {
            "type": "swing_high_low",
            "window_left": 6, "window_right": 6, "min_move_atr": 1.5,
            "future_horizon_bars": 6,
            "conflict_resolution": "larger ATR counter-move wins; tie -> neutral",
            "tolerance_bars": 0,
            "notes": "Standard prepareTraining.py swing labels (prepared_data).",
        }
    base = {
        "type": "sma_cross_segment_extreme",
        "sma_fast": 38, "sma_slow": 80,
        "segment_definition": (
            "Contiguous segments between sign changes of (SMA38-SMA80). "
            "Bull segment -> argmax(high) labeled -1; bear segment -> argmin(low) labeled +1."
        ),
        "future_horizon_bars": 6,
        "label_max_move_atr": "ATR(14)-normalized move to the segment extreme / future window",
        "tolerance_bars": 2,
        "tolerance_expansion": (
            "Original segment labels expanded into neutral bars within +/-2 bars. "
            "Expansion uses a snapshot of the original labels, so no forward cascade."
        ),
    }
    if spec["pipeline"] == "sma5":
        base["notes"] = "Corrected SMA(38/80) segment logic (sma5_tol2)."
    else:
        base["notes"] = "ML4T stationary features with SMA(38/80) segment labels (ml4t_tol2)."
    return base


def class_weights_from_split(train_labels, power):
    counts = np.array([train_labels["-1"], train_labels["0"], train_labels["1"]], dtype=float)
    n = counts.sum()
    raw = n / (3.0 * np.maximum(counts, 1.0))
    return (raw ** float(power)).tolist(), counts.tolist()


def bundle_config(strand, spec, force=False):
    src = os.path.join(BASE_DIR, strand, "best")
    run_dir = os.path.join(BASE_DIR, strand, spec["run_id"])
    metrics = pc.read_json(os.path.join(src, "metrics.json"))
    summary = pd.read_csv(os.path.join(BASE_DIR, strand, "experiments_summary.csv"))
    row = summary[summary["trial"] == spec["run_id"]].iloc[0]
    report = pd.read_csv(os.path.join(src, "reports", "sma_validation_summary.csv"))
    log_info = parse_training_log(os.path.join(run_dir, "training_run.log"))
    cmd = parse_command(os.path.join(run_dir, "command.txt"))
    ckpt = torch.load(os.path.join(src, "turning_point_mlp.pt"), map_location="cpu")

    hits = int(report["hits_bull"].sum() + report["hits_bear"].sum())
    segs = int(report["segments_total"].sum())
    extra = int(report["extra"].sum())
    sigs = int(report["model_sigs"].sum())
    event_precision = hits / (hits + extra) if (hits + extra) else 0.0
    event_recall = hits / segs if segs else 0.0
    event_f1 = (2 * event_precision * event_recall / (event_precision + event_recall)
                if (event_precision + event_recall) else 0.0)

    power = get_num(cmd, "class_weight_power", 0.35)
    train_labels = log_info["splits"].get("train", {}).get("labels", {"-1": 0, "0": 1, "1": 0})
    weights, counts = class_weights_from_split(train_labels, power)

    hidden_dims = get_list(cmd, "hidden_dims", list(ckpt["hidden_dims"]))
    threshold = float(ckpt.get("best_threshold", row["threshold"]))
    cooldown = int(ckpt.get("cooldown_bars", cmd.get("cooldown_bars", [5])[0]))
    th_min = get_num(cmd, "threshold_min", threshold)
    th_max = get_num(cmd, "threshold_max", threshold)
    th_step = get_num(cmd, "threshold_step", 0.05)

    cfg = {
        "schema_version": "1.0",
        "bundle_version": "1.0.0",
        "profile": spec["profile"],
        "strand": strand,
        "run_id": spec["run_id"],
        "display_name": f"{strand} / {spec['run_id']}",
        "description": spec["description"],
        "created_at": pc.now_iso(),
        "source": {
            "eval_dir": os.path.relpath(src, HERE),
            "run_dir": os.path.relpath(run_dir, HERE),
            "training_run_log": os.path.relpath(os.path.join(run_dir, "training_run.log"), HERE),
            "experiments_summary": os.path.relpath(
                os.path.join(BASE_DIR, strand, "experiments_summary.csv"), HERE),
            "command_file": os.path.relpath(os.path.join(run_dir, "command.txt"), HERE),
            "source_model_mtime": datetime.fromtimestamp(
                os.path.getmtime(os.path.join(src, "turning_point_mlp.pt")),
                tz=timezone.utc).isoformat(timespec="seconds"),
        },
        "data": {
            "variant": spec["data_variant"],
            "input_dir": spec["data_dir"],
            "feature_pipeline_key": spec["pipeline"],
            "feature_pipeline": PIPELINE_NAMES[spec["pipeline"]],
            "feature_list": list(ckpt["feature_cols"]),
            "feature_count": len(ckpt["feature_cols"]),
            "prepare_script": spec["prepare_script"],
            "prepare_args": spec["prepare_args"],
            "label_rule": label_rule(spec),
        },
        "architecture": {
            "type": "TurningPointMLP",
            "input_dim": len(ckpt["feature_cols"]),
            "hidden_dims": hidden_dims,
            "dropout": float(ckpt["dropout"]),
            "num_classes": 3,
            "activation": "SiLU",
            "normalization": "BatchNorm1d",
            "output": "softmax over [Extrem-Hoch(-1), Neutral(0), Extrem-Tief(+1)]",
        },
        "training": {
            "seed": 42,
            "epochs": int(get_num(cmd, "epochs", 60)),
            "epochs_run": log_info.get("epochs_run"),
            "batch_size": int(get_num(cmd, "batch_size", 64)),
            "learning_rate": float(get_num(cmd, "learning_rate", 5e-4)),
            "weight_decay": float(get_num(cmd, "weight_decay", 5e-4)),
            "dropout": float(get_num(cmd, "dropout", float(ckpt["dropout"]))),
            "hidden_dims": hidden_dims,
            "patience": int(get_num(cmd, "patience", 10)),
            "class_weight_power": float(power),
            "class_weights": weights,
            "class_counts_train": counts,
            "label_smoothing": float(get_num(cmd, "label_smoothing", 0.05)),
            "use_move_atr_weighting": "disable_move_atr_weighting" not in cmd,
            "train_frac": float(get_num(cmd, "train_frac", 0.70)),
            "val_frac": float(get_num(cmd, "val_frac", 0.15)),
            "purge_minutes": float(get_num(cmd, "purge_minutes", 0.0)),
            "out_of_tickers": cmd.get("out_of_tickers", ["AAPL"]),
        },
        "post_processing": {
            "threshold": threshold,
            "confidence_filter": threshold,
            "cooldown_bars": cooldown,
            "nms": "suppress_signal_clusters: keep strongest signal per class, enforce cooldown bars",
            "threshold_search_range": [th_min, th_max, th_step],
        },
        "class_mapping": {"0": -1, "1": 0, "2": 1},
        "reference_metrics": {
            "selection_score": float(row["score"]),
            "val_f1": float(row["val_f1"]),
            "test_f1": float(row["test_f1"]),
            "oot_f1": float(row["oot_f1"]),
            "threshold": threshold,
            "hit_rate_bull": float(row["hit_rate_bull"]),
            "hit_rate_bear": float(row["hit_rate_bear"]),
            "hit_avg": float(row["hit_avg"]),
            "hits_bull": int(row["hits_bull"]), "misses_bull": int(row["misses_bull"]),
            "hits_bear": int(row["hits_bear"]), "misses_bear": int(row["misses_bear"]),
            "signals": int(row["model_sigs"]),
            "extra_signals": int(row["extra"]),
            "extra_rate": float(row["extra_rate"]),
            "event_precision": float(event_precision),
            "event_recall": float(event_recall),
            "event_f1": float(event_f1),
            "atr_quality": float(row["atr_quality"]),
            "mean_atr_dist": float(row["mean_atr_dist"]),
        },
        "gate": dict(pc.DEFAULT_GATE),
        "training_data": {
            "prepared_rows": int(log_info["splits"].get("train", {}).get("rows", 0)
                                 + log_info["splits"].get("val", {}).get("rows", 0)
                                 + log_info["splits"].get("test", {}).get("rows", 0)
                                 + log_info["splits"].get("oot", {}).get("rows", 0)),
            "splits": log_info["splits"],
            "features_seen_in_log": log_info.get("features"),
        },
        "inference": {
            "entrypoint": "predict_production.py",
            "output_columns": OUTPUT_COLUMNS,
            "raw_pred": "threshold applied with cooldown_bars=1",
            "filtered_pred": "threshold + configured cooldown (NMS)",
        },
        "lifecycle": {
            "state": "active",
            "promoted_at": pc.now_iso(),
            "parent_version": None,
            "promotion_reason": "initial production freeze from eval winner",
        },
    }
    cfg["artifacts"] = {
        "model_file": "turning_point_mlp.pt",
        "scaler_file": "feature_scaler.joblib",
        "model_sha256": pc.sha256_file(os.path.join(src, "turning_point_mlp.pt")),
        "scaler_sha256": pc.sha256_file(os.path.join(src, "feature_scaler.joblib")),
        "model_bytes": os.path.getsize(os.path.join(src, "turning_point_mlp.pt")),
        "scaler_bytes": os.path.getsize(os.path.join(src, "feature_scaler.joblib")),
    }
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="Replace existing active bundles (archive is preserved).")
    args = ap.parse_args()

    pc.ensure_production_dir()
    os.makedirs(os.path.join(pc.PROD_DIR, "archive"), exist_ok=True)

    registry = {
        "schema_version": "1.0",
        "updated_at": pc.now_iso(),
        "default_active": "ml4t_opt",
        "profiles": {},
        "aliases": {},
    }
    if os.path.isfile(pc.REGISTRY_PATH):
        old = pc.read_json(pc.REGISTRY_PATH)
        registry["profiles"] = old.get("profiles", {})
        registry["aliases"] = old.get("aliases", {})

    for strand, spec in SPECS.items():
        dst = os.path.join(pc.PROD_DIR, strand, "active")
        cfg_path = os.path.join(dst, "model_config.json")
        if os.path.isfile(cfg_path) and not args.force:
            print(f"SKIP {strand}/active (exists; use --force to rebuild)")
        else:
            if os.path.isdir(dst):
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                arch = os.path.join(pc.PROD_DIR, strand, "archive", f"{stamp}_prebuild")
                os.makedirs(os.path.dirname(arch), exist_ok=True)
                shutil.copytree(dst, arch)
                shutil.rmtree(dst)
            os.makedirs(dst, exist_ok=True)
            src = os.path.join(BASE_DIR, strand, "best")
            shutil.copy2(os.path.join(src, "turning_point_mlp.pt"),
                         os.path.join(dst, "turning_point_mlp.pt"))
            shutil.copy2(os.path.join(src, "feature_scaler.joblib"),
                         os.path.join(dst, "feature_scaler.joblib"))
            cfg = bundle_config(strand, spec)
            pc.write_json(os.path.join(dst, "model_config.json"), cfg)
            print(f"OK   {strand}/active  run={spec['run_id']}  features={cfg['data']['feature_count']}")

        entry = {
            "bundle": strand,
            "strand": strand,
            "run_id": spec["run_id"],
            "profile": spec["profile"],
            "active_dir": os.path.relpath(dst, pc.PROD_DIR),
            "config": os.path.relpath(os.path.join(dst, "model_config.json"), pc.PROD_DIR),
            "description": spec["description"],
            "default": strand == "ml4t_opt",
        }
        registry["profiles"][spec["profile"]] = entry
        registry["aliases"][strand] = spec["profile"]

    # Keep the documented order: default first, then baseline, then SMA.
    order = ["ml4t", "baseline", "sma_auto"]
    registry["profiles"] = {k: registry["profiles"][k]
                            for k in order if k in registry["profiles"]}
    pc.write_json(pc.REGISTRY_PATH, registry)
    print(f"Registry: {os.path.relpath(pc.REGISTRY_PATH, HERE)}")
    print(f"Default active: {registry['default_active']}")


if __name__ == "__main__":
    main()
