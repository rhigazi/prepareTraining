#!/usr/bin/env python3
"""retrain_production.py - One-configuration retraining with a gate check.

Examples
--------
python3 retrain_production.py --profile ml4t
python3 retrain_production.py --all
python3 retrain_production.py --profile baseline --promote
python3 retrain_production.py --profile sma_auto --dry-run

The script never runs the 3x8 search. It reads the frozen hyperparameters from
production_models/<bundle>/active/model_config.json, rebuilds the profile data
from raw CSVs, trains exactly that configuration, evaluates the candidate and
the active model on the *current* validation/OOT split, and promotes only when
the gate passes (or --promote is given). Rejected candidates stay under
candidates/<timestamp>/ for inspection.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import talib
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import production_common as pc
import extremes_tool as et
from train_turning_points import TurningPointMLP


class MultiLog:
    def __init__(self, paths):
        self.fhs = []
        for p in paths:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            self.fhs.append(open(p, "a", encoding="utf-8"))

    def __call__(self, msg=""):
        line = str(msg)
        print(line)
        for fh in self.fhs:
            fh.write(line + "\n")
            fh.flush()

    def close(self):
        for fh in self.fhs:
            fh.close()


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _bump_version(version):
    try:
        parts = str(version).split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    except Exception:
        return "1.0.1"


def _load_model(path):
    ckpt = torch.load(os.path.join(path, "turning_point_mlp.pt"), map_location="cpu")
    scaler = joblib.load(os.path.join(path, "feature_scaler.joblib"))
    model = TurningPointMLP(in_features=len(ckpt["feature_cols"]),
                            hidden_dims=ckpt["hidden_dims"],
                            dropout=ckpt["dropout"], num_classes=3)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    return model, scaler, ckpt


def parse_log(path):
    text = open(path, encoding="utf-8").read()
    out = {"val_f1": None, "test_f1": None, "oot_f1": None,
           "threshold": None, "epochs_run": None}
    import re
    m = re.search(r"Val Turn \(filtered\) P/R/F1: [\d.]+/[\d.]+/([\d.]+)", text)
    if m:
        out["val_f1"] = float(m.group(1))
    overall = [float(m.group(1)) for m in re.finditer(
        r"Overall Turn Precision/Recall/F1: [\d.]+/[\d.]+/([\d.]+)", text)]
    if overall:
        out["test_f1"] = overall[0]
        out["oot_f1"] = overall[1] if len(overall) > 1 else overall[0]
    m = re.search(r"Selected BEST_THRESHOLD: ([\d.]+)", text)
    if m:
        out["threshold"] = float(m.group(1))
    m = re.search(r"Early stopping in epoch (\d+)", text)
    if m:
        out["epochs_run"] = int(m.group(1))
    else:
        planned = re.findall(r"Epoch \d+/(\d+)", text)
        if planned:
            out["epochs_run"] = int(planned[-1])
    return out


def build_train_cmd(cfg, data_dir, out_dir):
    tr = cfg["training"]
    pp = cfg["post_processing"]
    cmd = [
        sys.executable, os.path.join(HERE, "train_turning_points.py"),
        "--input-dir", data_dir,
        "--output-dir", out_dir,
        "--out-of-tickers", *[str(t) for t in tr.get("out_of_tickers", ["AAPL"])],
        "--epochs", str(tr["epochs"]),
        "--batch-size", str(tr["batch_size"]),
        "--learning-rate", str(tr["learning_rate"]),
        "--weight-decay", str(tr["weight_decay"]),
        "--dropout", str(tr["dropout"]),
        "--hidden-dims", *[str(h) for h in tr["hidden_dims"]],
        "--patience", str(tr["patience"]),
        "--class-weight-power", str(tr["class_weight_power"]),
        "--label-smoothing", str(tr["label_smoothing"]),
        "--cooldown-bars", str(pp["cooldown_bars"]),
        "--train-frac", str(tr["train_frac"]),
        "--val-frac", str(tr["val_frac"]),
        "--purge-minutes", str(tr["purge_minutes"]),
        # Fixed post-processing: no new threshold search.
        "--threshold-min", str(pp["threshold"]),
        "--threshold-max", str(pp["threshold"]),
        "--threshold-step", "0.05",
    ]
    if not tr.get("use_move_atr_weighting", True):
        cmd.append("--disable-move-atr-weighting")
    return cmd


def reference_metrics_from_eval(m):
    s = m["segments_all"]
    return {
        "origin": "retrain_candidate",
        "selection_score": None,
        "val_f1": float(m["val_f1"]),
        "test_f1": float(m["test_f1"]),
        "oot_f1": float(m["oot_f1"]),
        "threshold": float(m["threshold"]),
        "hit_rate_bull": float(s["hit_rate_bull"]),
        "hit_rate_bear": float(s["hit_rate_bear"]),
        "hit_avg": float(s["hit_avg"]),
        "hits_bull": int(s["hits_bull"]), "misses_bull": int(s["misses_bull"]),
        "hits_bear": int(s["hits_bear"]), "misses_bear": int(s["misses_bear"]),
        "signals": int(s["model_sigs"]),
        "extra_signals": int(s["extra"]),
        "extra_rate": float(s["extra_rate"]),
        "event_precision": float(s["event_precision"]),
        "event_recall": float(s["event_recall"]),
        "event_f1": float(s["event_f1"]),
        "atr_quality": float(s["atr_quality"]),
        "mean_atr_dist": s["mean_atr_dist"],
        "oot_only": {
            "signals": int(m["segments_oot"]["model_sigs"]),
            "extra_signals": int(m["segments_oot"]["extra"]),
            "extra_rate": float(m["segments_oot"]["extra_rate"]),
            "hit_avg": float(m["segments_oot"]["hit_avg"]),
            "event_precision": float(m["segments_oot"]["event_precision"]),
            "event_f1": float(m["segments_oot"]["event_f1"]),
        },
    }


def make_candidate_config(active_cfg, run_id, cand_dir, ckpt, m, gate,
                          promoted, forced, dry_run):
    cfg = deepcopy(active_cfg)
    cfg["bundle_version"] = _bump_version(active_cfg.get("bundle_version", "1.0.0"))
    cfg["run_id"] = run_id
    cfg["created_at"] = pc.now_iso()
    cfg["source"]["candidate_dir"] = os.path.relpath(cand_dir, HERE)
    cfg["post_processing"]["threshold"] = float(ckpt.get("best_threshold", active_cfg["post_processing"]["threshold"]))
    cfg["post_processing"]["confidence_filter"] = cfg["post_processing"]["threshold"]
    cfg["post_processing"]["cooldown_bars"] = int(ckpt.get("cooldown_bars", active_cfg["post_processing"]["cooldown_bars"]))
    cfg["training"]["epochs_run"] = None
    cfg["reference_metrics"] = reference_metrics_from_eval(m)
    cfg["gate_last"] = gate
    cfg["lifecycle"] = {
        "state": "active" if promoted else "candidate",
        "promoted_at": pc.now_iso() if promoted else None,
        "parent_version": active_cfg.get("bundle_version"),
        "promotion_reason": (
            "forced via --promote" if forced else
            ("gate passed" if gate["passed"] else "gate rejected; active unchanged")
        ),
        "would_promote": bool(gate["passed"]),
        "dry_run": bool(dry_run),
    }
    cfg["retrain"] = {
        "timestamp": os.path.basename(cand_dir),
        "candidate_dir": os.path.relpath(cand_dir, HERE),
        "promoted": bool(promoted),
        "forced_promotion": bool(forced),
        "dry_run": bool(dry_run),
        "gate": gate,
    }
    cfg["artifacts"]["model_sha256"] = pc.sha256_file(os.path.join(cand_dir, "turning_point_mlp.pt"))
    cfg["artifacts"]["scaler_sha256"] = pc.sha256_file(os.path.join(cand_dir, "feature_scaler.joblib"))
    return cfg


def make_control_charts(cand_dir, cfg, model, scaler, m, log, raw_dir):
    chart_dir = os.path.join(cand_dir, "charts")
    os.makedirs(chart_dir, exist_ok=True)
    candidates = sorted(glob.glob(os.path.join(raw_dir, "AAPL_1Hour*.csv")))
    if not candidates:
        log("WARNING: no AAPL_1Hour raw file found; control chart skipped")
        return []
    path = candidates[0]
    raw = pd.read_csv(path)
    res = pc.infer_array(raw, cfg, model, scaler)
    s38, s80, segs, _ = et.sma_cross_segments(res["close"], res["high"], res["low"])
    atr = talib.ATR(res["high"], res["low"], res["close"], timeperiod=14)
    fm = pc.segment_metrics(res["filt"], segs, res["close"], atr)
    g = dict(m["segments_oot"])
    g["val_f1"] = m["val_f1"]
    g["oot_f1"] = m["oot_f1"]
    n = len(res["close"])
    charts = []
    start, end = 1600, min(2000, n)
    if start < end:
        out = os.path.join(chart_dir, f"AAPL_1Hour_control_{start}-{end - 1}.png")
        pc.plot_control_chart(res, cfg, g, fm, start, end,
                              f"AAPL_1Hour control | bars {start}-{end - 1} | candidate", out)
        charts.append(out)
    if n > 400:
        start, end = n - 400, n
        out = os.path.join(chart_dir, f"AAPL_1Hour_control_last400.png")
        pc.plot_control_chart(res, cfg, g, fm, start, end,
                              "AAPL_1Hour control | last 400 bars | candidate", out)
        charts.append(out)
    for c in charts:
        log(f"control chart: {os.path.relpath(c, HERE)}")
    return charts


def promote(cand_dir, active_dir, strand, archive_stamp, cfg, log):
    archive_root = os.path.join(pc.PROD_DIR, strand, "archive")
    os.makedirs(archive_root, exist_ok=True)
    archive_dir = os.path.join(archive_root, archive_stamp)
    suffix = 1
    while os.path.exists(archive_dir):
        archive_dir = os.path.join(archive_root, f"{archive_stamp}_{suffix}")
        suffix += 1
    shutil.copytree(active_dir, archive_dir)
    log(f"archived previous active -> {os.path.relpath(archive_dir, HERE)}")

    new_dir = active_dir + ".new"
    if os.path.exists(new_dir):
        shutil.rmtree(new_dir)
    os.makedirs(new_dir, exist_ok=True)
    for name in ("turning_point_mlp.pt", "feature_scaler.joblib", "model_config.json",
                 "metrics.json", "retrain.log", "training_run.log"):
        src = os.path.join(cand_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(new_dir, name))
    chart_src = os.path.join(cand_dir, "charts")
    if os.path.isdir(chart_src):
        shutil.copytree(chart_src, os.path.join(new_dir, "charts"))
    shutil.rmtree(active_dir)
    os.replace(new_dir, active_dir)
    log(f"promoted candidate -> {os.path.relpath(active_dir, HERE)} (version {cfg['bundle_version']})")
    return archive_dir


def update_registry(profile_key, entry, cfg, promoted, gate, archive_dir=None, dry_run=False):
    if dry_run:
        return
    reg = pc.load_registry()
    p = reg["profiles"][profile_key]
    p["last_retrain"] = {
        "at": pc.now_iso(),
        "run_id": cfg["run_id"],
        "promoted": bool(promoted),
        "gate_passed": bool(gate["passed"]),
        "candidate": cfg["retrain"]["candidate_dir"],
    }
    if promoted:
        p["run_id"] = cfg["run_id"]
        p["version"] = cfg["bundle_version"]
        p["last_promotion"] = {
            "at": pc.now_iso(),
            "run_id": cfg["run_id"],
            "version": cfg["bundle_version"],
            "archive": os.path.relpath(archive_dir, pc.PROD_DIR) if archive_dir else None,
        }
    reg["updated_at"] = pc.now_iso()
    pc.write_json(pc.REGISTRY_PATH, reg)


def retrain_one(profile, args, global_log):
    key, entry, active_dir = pc.resolve_profile(profile)
    if not os.path.isdir(active_dir):
        raise FileNotFoundError(f"Active bundle not found: {active_dir}")
    active_cfg = pc.read_json(os.path.join(active_dir, "model_config.json"))
    strand = entry["bundle"]
    stamp = _stamp()
    cand_dir = os.path.join(pc.PROD_DIR, strand, "candidates", stamp)
    os.makedirs(cand_dir, exist_ok=True)
    log = MultiLog([os.path.join(pc.PROD_DIR, "retrain.log"),
                    os.path.join(cand_dir, "retrain.log")])
    log("=" * 78)
    log(f"RETRAIN {key} ({strand}) {pc.now_iso()}")
    log(f"active: {os.path.relpath(active_dir, HERE)} version={active_cfg.get('bundle_version')}")
    log(f"candidate: {os.path.relpath(cand_dir, HERE)}")
    log(f"hyperparameters: epochs={active_cfg['training']['epochs']} "
        f"hidden={active_cfg['training']['hidden_dims']} lr={active_cfg['training']['learning_rate']} "
        f"dropout={active_cfg['training']['dropout']} cw_power={active_cfg['training']['class_weight_power']} "
        f"threshold={active_cfg['post_processing']['threshold']} cooldown={active_cfg['post_processing']['cooldown_bars']}")

    tmp_data = None
    try:
        if args.data_dir:
            data_dir = os.path.abspath(args.data_dir)
            log(f"using provided data dir: {data_dir}")
        else:
            os.makedirs(os.path.join(pc.PROD_DIR, "_tmp"), exist_ok=True)
            tmp_data = tempfile.mkdtemp(prefix=f"retrain_{strand}_",
                                        dir=os.path.join(pc.PROD_DIR, "_tmp"))
            data_dir = os.path.join(tmp_data, "prepared")
            log(f"rebuilding profile data from {os.path.relpath(args.raw_dir, HERE)}")
            pc.prepare_profile_data(active_cfg, os.path.abspath(args.raw_dir), data_dir, log)

        cmd = build_train_cmd(active_cfg, data_dir, cand_dir)
        log("training command:")
        log("  " + " ".join(cmd))
        log("training ...")
        proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
        with open(os.path.join(cand_dir, "train_console.log"), "w", encoding="utf-8") as f:
            f.write(proc.stdout)
            if proc.stderr:
                f.write("\n--- stderr ---\n" + proc.stderr)
        if proc.returncode != 0:
            log(proc.stdout[-4000:])
            log(proc.stderr[-4000:])
            raise RuntimeError(f"training failed ({proc.returncode})")
        log_path = os.path.join(cand_dir, "training_run.log")
        parsed = parse_log(log_path)
        log(f"training done: epochs_run={parsed['epochs_run']} val_f1={parsed['val_f1']} "
            f"test_f1={parsed['test_f1']} oot_f1={parsed['oot_f1']} threshold={parsed['threshold']}")

        cand_model, cand_scaler, cand_ckpt = _load_model(cand_dir)
        active_model, active_scaler, _ = _load_model(active_dir)

        # Candidate evaluation config: saved threshold/cooldown, same features.
        cand_cfg = deepcopy(active_cfg)
        cand_cfg["post_processing"]["threshold"] = float(
            cand_ckpt.get("best_threshold", active_cfg["post_processing"]["threshold"]))
        cand_cfg["post_processing"]["confidence_filter"] = cand_cfg["post_processing"]["threshold"]
        cand_cfg["post_processing"]["cooldown_bars"] = int(
            cand_ckpt.get("cooldown_bars", active_cfg["post_processing"]["cooldown_bars"]))

        log("building current split for gate evaluation ...")
        df = pc.load_prepared(data_dir, cand_cfg["data"]["feature_list"])
        frames = pc.split_prepared(df, cand_cfg["training"])
        log(f"current split: train={len(frames['train'])} val={len(frames['val'])} "
            f"test={len(frames['test'])} oot={len(frames['oot'])} | {frames['_cutoffs']}")

        log("evaluating active model on current val/OOT ...")
        active_m = pc.evaluate_bundle(active_cfg, active_model, active_scaler, frames,
                                      os.path.abspath(args.raw_dir))
        log(f"  active:   val_f1={active_m['val_f1']:.4f} oot_f1={active_m['oot_f1']:.4f} "
            f"hit_avg={active_m['segments_oot']['hit_avg']:.4f} "
            f"event_prec={active_m['segments_oot']['event_precision']:.4f} "
            f"extra={active_m['segments_oot']['extra_rate']:.4f}")
        log("evaluating candidate on current val/OOT ...")
        cand_m = pc.evaluate_bundle(cand_cfg, cand_model, cand_scaler, frames,
                                    os.path.abspath(args.raw_dir))
        log(f"  candidate: val_f1={cand_m['val_f1']:.4f} oot_f1={cand_m['oot_f1']:.4f} "
            f"hit_avg={cand_m['segments_oot']['hit_avg']:.4f} "
            f"event_prec={cand_m['segments_oot']['event_precision']:.4f} "
            f"extra={cand_m['segments_oot']['extra_rate']:.4f}")

        gate = pc.gate_check(active_m, cand_m, active_cfg.get("gate"))
        for c in gate["checks"]:
            log(f"  GATE {c['check']}: {'PASS' if c['passed'] else 'FAIL'} "
                f"active={c['active']} candidate={c['candidate']}")
        forced = bool(args.promote)
        promoted = bool(gate["passed"] or forced)
        if args.dry_run:
            promoted = False
        if gate["passed"]:
            log("GATE RESULT: PASS")
        else:
            log("GATE RESULT: FAIL - active model remains in use")
            log("WARNING: no promotion; market shift may require a larger search/reset")
        if forced and not gate["passed"]:
            log("WARNING: gate failed but promotion forced via --promote")
        if args.dry_run and gate["passed"]:
            log("DRY RUN: would have promoted the candidate")

        charts = make_control_charts(cand_dir, cand_cfg, cand_model, cand_scaler,
                                     cand_m, log, os.path.abspath(args.raw_dir))
        run_id = f"retrain_{stamp}"
        new_cfg = make_candidate_config(active_cfg, run_id, cand_dir, cand_ckpt,
                                        cand_m, gate, promoted, forced, args.dry_run)
        new_cfg["training"]["epochs_run"] = parsed["epochs_run"]
        pc.write_json(os.path.join(cand_dir, "model_config.json"), new_cfg)
        pc.write_json(os.path.join(cand_dir, "metrics.json"), {
            "profile": key, "strand": strand, "run_id": run_id,
            "timestamp": pc.now_iso(), "data_dir": data_dir,
            "candidate": cand_m, "active": active_m, "gate": gate,
            "promoted": promoted, "forced_promotion": forced,
            "dry_run": bool(args.dry_run), "control_charts": charts,
        })

        archive_dir = None
        if promoted:
            archive_dir = promote(cand_dir, active_dir, strand, stamp, new_cfg, log)
        else:
            log(f"candidate retained at {os.path.relpath(cand_dir, HERE)}")

        update_registry(key, entry, new_cfg, promoted, gate, archive_dir, args.dry_run)
        return {"profile": key, "promoted": promoted, "gate_passed": gate["passed"],
                "candidate": cand_dir, "run_id": run_id, "metrics": cand_m}
    finally:
        log.close()
        if tmp_data and not args.keep_data:
            shutil.rmtree(tmp_data, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Retrain one production profile with gate check.")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--profile", help="baseline | sma_auto | ml4t (or strand/bundle name)")
    group.add_argument("--all", action="store_true", help="Retrain all registered profiles")
    ap.add_argument("--raw-dir", default=os.path.join(HERE, "raw_data"))
    ap.add_argument("--data-dir", default=None,
                    help="Use an existing prepared data dir instead of rebuilding from raw")
    ap.add_argument("--promote", action="store_true", help="Promote even if the gate fails")
    ap.add_argument("--dry-run", action="store_true", help="Train/evaluate/chart, never promote")
    ap.add_argument("--keep-data", action="store_true", help="Keep the temporary rebuilt dataset")
    args = ap.parse_args()

    if args.all and args.data_dir:
        ap.error("--data-dir cannot be combined with --all (profiles use different pipelines)")

    reg = pc.load_registry()
    targets = list(reg["profiles"].keys()) if args.all else [args.profile]
    errors = []
    results = []
    for target in targets:
        try:
            res = retrain_one(target, args, None)
            results.append(res)
        except Exception as e:
            print(f"ERROR retrain {target}: {e}", file=sys.stderr)
            errors.append((target, str(e)))

    print("\nRetrain summary")
    for r in results:
        print(f"  {r['profile']}: gate={'PASS' if r['gate_passed'] else 'FAIL'} "
              f"promoted={r['promoted']} run={r['run_id']} candidate={r['candidate']}")
    if errors:
        for t, e in errors:
            print(f"  {t}: ERROR {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
