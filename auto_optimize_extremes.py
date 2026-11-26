#!/usr/bin/env python3
"""auto_optimize_extremes.py - Automated search for proximity to SMA segment extremes."""

import argparse
import csv
import glob
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.join(HERE, "train_turning_points.py")
EXTREMES = os.path.join(HERE, "extremes_tool.py")
PY = sys.executable

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import extremes_tool as et

RAW_DIR = os.path.join(HERE, "raw_data")
PREP_ORIG = os.path.join(HERE, "prepared_data")
PREP_SMA5 = os.path.join(HERE, "prepared_sma5")

SEARCH_DIR = os.path.join(HERE, "runs", "auto_search")


def run_train(trial_name, data_dir, extra_args, epochs):
    out_dir = os.path.join(SEARCH_DIR, trial_name)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    cmd = [PY, TRAIN, "--input-dir", data_dir, "--output-dir", out_dir,
           "--out-of-tickers", "AAPL", "--epochs", str(epochs)] + extra_args
    print(f"\n=== {trial_name} ===")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    log_path = os.path.join(out_dir, "training_run.log")
    val_f1 = oot_f1 = None
    with open(log_path) as f:
        for line in f:
            m = re.search(r"Val Turn \(filtered\) P/R/F1: [\d.]+/[\d.]+/([\d.]+)", line)
            if m:
                val_f1 = float(m.group(1))
            m2 = re.search(r"Overall Turn Precision/Recall/F1: ([\d.]+)/([\d.]+)/([\d.]+)", line)
            # last occurrence is OOT (appears after test). We'll capture all and take last.
    # parse OOT f1: find all "Overall Turn Precision/Recall/F1" lines; second is OOT
    overall = []
    with open(log_path) as f:
        for line in f:
            m = re.search(r"Overall Turn Precision/Recall/F1: ([\d.]+)/([\d.]+)/([\d.]+)", line)
            if m:
                overall.append(float(m.group(3)))
    if len(overall) >= 2:
        oot_f1 = overall[-1]
    elif overall:
        oot_f1 = overall[0]
    return out_dir, val_f1, oot_f1


def make_label_tol_data():
    src = PREP_SMA5
    dst = os.path.join(SEARCH_DIR, "prepared_sma5_tol")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    for path in glob.glob(os.path.join(src, "*_prepared.csv")):
        df = pd.read_csv(path)
        lt = df["label_turn"].to_numpy().copy()
        lma = df["label_max_move_atr"].to_numpy().copy()
        n = len(df)
        for i in range(n):
            if lt[i] != 0:
                for j in (i-1, i+1):
                    if 0 <= j < n:
                        if lt[j] == 0:
                            lt[j] = lt[i]
                            lma[j] = lma[i]
        df["label_turn"] = lt
        df["label_max_move_atr"] = lma
        df.to_csv(os.path.join(dst, os.path.basename(path)), index=False)
    return dst


def validate_trial(model_dir):
    ckpt, scaler, model, threshold, cooldown = et.load_model(model_dir)
    feature_cols = ckpt["feature_cols"]
    hits_b = misses_b = hits_r = misses_r = 0
    total_extra = 0
    total_sigs = 0
    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.csv")))
    for path in files:
        raw = pd.read_csv(path)
        annotated, probs, filt_turn, valid = et.annotate_df(raw, ckpt, scaler, model, threshold, cooldown)
        close, high, low, t = et.standardize_ohlc(annotated)
        s38, s80, segs, crosses = et.sma_cross_segments(close, high, low)
        h, m, extra, eb, er, matched = et.validate_segments(filt_turn, segs, tolerance=5)
        hits_b += h["bull"]; misses_b += m["bull"]
        hits_r += h["bear"]; misses_r += m["bear"]
        total_extra += len(extra)
        total_sigs += int((filt_turn != 0).sum())
    hr_bull = hits_b / (hits_b + misses_b) if (hits_b + misses_b) > 0 else 0.0
    hr_bear = hits_r / (hits_r + misses_r) if (hits_r + misses_r) > 0 else 0.0
    return {
        "hits_bull": hits_b, "misses_bull": misses_b, "hit_rate_bull": hr_bull,
        "hits_bear": hits_r, "misses_bear": misses_r, "hit_rate_bear": hr_bear,
        "extra": total_extra, "model_sigs": total_sigs,
    }


def composite_score(val_f1, oot_f1, v):
    val_f1 = val_f1 or 0.0
    oot_f1 = oot_f1 or 0.0
    hr_avg = (v["hit_rate_bull"] + v["hit_rate_bear"]) / 2.0
    extra_rate = (v["extra"] / v["model_sigs"]) if v["model_sigs"] > 0 else 1.0
    extra_rate = min(extra_rate, 1.0)
    penalty = 0.0
    if v["model_sigs"] < 50:
        penalty += (50 - v["model_sigs"]) / 50.0
    if v["model_sigs"] > 4000:
        penalty += (v["model_sigs"] - 4000) / 4000.0
    score = 0.30 * val_f1 + 0.20 * oot_f1 + 0.30 * hr_avg + 0.20 * (1 - extra_rate) - 0.10 * penalty
    return max(0.0, min(1.0, score))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--trials", type=int, default=10)
    args = parser.parse_args()

    os.makedirs(SEARCH_DIR, exist_ok=True)
    tol_data = make_label_tol_data()

    # trial configs
    configs = [
        ("trial_01", PREP_ORIG, ["--hidden-dims", "64", "32", "--dropout", "0.35", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.45"]),
        ("trial_02", PREP_ORIG, ["--hidden-dims", "128", "64", "--dropout", "0.4", "--class-weight-power", "0.5", "--learning-rate", "1e-3", "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.50"]),
        ("trial_03", PREP_SMA5, ["--hidden-dims", "64", "32", "--dropout", "0.35", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.50"]),
        ("trial_04", PREP_SMA5, ["--hidden-dims", "128", "64", "--dropout", "0.4", "--class-weight-power", "0.5", "--learning-rate", "1e-3", "--cooldown-bars", "3", "--threshold-min", "0.35", "--threshold-max", "0.45"]),
        ("trial_05", tol_data, ["--hidden-dims", "64", "32", "--dropout", "0.35", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.50"]),
        ("trial_06", PREP_SMA5, ["--hidden-dims", "64", "32", "16", "--dropout", "0.45", "--class-weight-power", "0.7", "--learning-rate", "5e-4", "--cooldown-bars", "3", "--threshold-min", "0.30", "--threshold-max", "0.40"]),
        ("trial_07", PREP_SMA5, ["--hidden-dims", "128", "64", "--dropout", "0.3", "--class-weight-power", "0.5", "--learning-rate", "1e-3", "--cooldown-bars", "5", "--threshold-min", "0.45", "--threshold-max", "0.55"]),
        ("trial_08", PREP_SMA5, ["--hidden-dims", "64", "32", "--dropout", "0.25", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.50", "--threshold-max", "0.60"]),
        ("trial_09", PREP_ORIG, ["--hidden-dims", "64", "32", "--dropout", "0.35", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.60", "--threshold-max", "0.65"]),
        ("trial_10", PREP_SMA5, ["--hidden-dims", "96", "48", "--dropout", "0.35", "--class-weight-power", "0.5", "--learning-rate", "7e-4", "--cooldown-bars", "4", "--threshold-min", "0.40", "--threshold-max", "0.50"]),
    ]
    configs = configs[:args.trials]

    rows = []
    for name, data_dir, extra in configs:
        try:
            out_dir, val_f1, oot_f1 = run_train(name, data_dir, extra, args.epochs)
            v = validate_trial(out_dir)
            score = composite_score(val_f1, oot_f1, v)
            data_variant = "orig" if data_dir == PREP_ORIG else ("sma5_tol" if data_dir == tol_data else "sma5")
            row = {
                "trial": name,
                "data_variant": data_variant,
                "data_dir": data_dir,
                "val_f1": val_f1,
                "oot_f1": oot_f1,
                "hit_rate_bull": v["hit_rate_bull"],
                "hit_rate_bear": v["hit_rate_bear"],
                "extra": v["extra"],
                "model_sigs": v["model_sigs"],
                "score": score,
                "params": " ".join(extra),
            }
            rows.append(row)
            print(f"{name}: val={val_f1} oot={oot_f1} hr_bull={v['hit_rate_bull']:.3f} hr_bear={v['hit_rate_bear']:.3f} sigs={v['model_sigs']} extra={v['extra']} score={score:.4f}")
        except Exception as e:
            print(f"Trial {name} failed: {e}", file=sys.stderr)

    # save summary
    summary_path = os.path.join(SEARCH_DIR, "experiments_summary.csv")
    if rows:
        df = pd.DataFrame(rows).sort_values("score", ascending=False)
        df.to_csv(summary_path, index=False)
        print(f"\nSummary saved: {summary_path}")

        # best
        best_name = df.iloc[0]["trial"]
        best_dir = os.path.join(SEARCH_DIR, best_name)
        best_target = os.path.join(SEARCH_DIR, "best")
        if os.path.exists(best_target):
            shutil.rmtree(best_target)
        shutil.copytree(best_dir, best_target)
        print("Best trial:", best_name, "score:", df.iloc[0]["score"])

        # validation + charts for best
        best_val_dir = best_target
        cmd = [PY, EXTREMES, "--mode", "all", "--input-dir", RAW_DIR,
               "--output-dir", best_val_dir, "--model-dir", best_target,
               "--tolerance-bars", "5", "--window-bars", "400"]
        print("Running validation/charts for best:", " ".join(cmd))
        subprocess.run(cmd, check=True)

        # top-5 + comparison report
        top5 = df.head(5)
        # load opt01 and sma5 summaries if available
        def load_summary(d):
            p = os.path.join(d, "reports", "sma_validation_summary.csv")
            if os.path.exists(p):
                return pd.read_csv(p)
            return None
        opt01 = load_summary(os.path.join(HERE, "extremes_output"))
        sma5 = load_summary(os.path.join(HERE, "extremes_output_sma5"))

        report_path = os.path.join(SEARCH_DIR, "summary_report.md")
        with open(report_path, "w") as f:
            f.write("# Auto-Optimize Extremes – Ergebnisse\n\n")
            f.write("## Top-5 Experimente\n\n")
            f.write(top5[["trial", "data_variant", "val_f1", "oot_f1", "hit_rate_bull", "hit_rate_bear", "model_sigs", "extra", "score"]].to_markdown(index=False))
            f.write("\n\n## Bester Lauf\n\n")
            f.write(f"- Trial: {best_name}\n- Score: {df.iloc[0]['score']:.4f}\n- Dir: {best_target}\n")
            f.write(f"- Validierung/Charts: {best_val_dir}/charts/ (inkl. AAPL_1Hour Bars 1600–1999)\n\n")
            if opt01 is not None:
                o = opt01
                o_tot = o["model_signals"].sum()
                o_extra = o["extra_signals"].sum()
                o_hb = o["hits_bull"].sum(); o_mb = o["misses_bull"].sum()
                o_hr = o["hits_bear"].sum(); o_mr = o["misses_bear"].sum()
                f.write("## Vergleich vs. opt_01\n\n")
                f.write(f"- opt_01: Signale {o_tot}, Extra {o_extra}, Hit Bull {o_hb}/{o_hb+o_mb} ({o_hb/(o_hb+o_mb):.2f}), Hit Bear {o_hr}/{o_hr+o_mr} ({o_hr/(o_hr+o_mr):.2f})\n")
            if sma5 is not None:
                s = sma5
                s_tot = s["model_signals"].sum()
                s_extra = s["extra_signals"].sum()
                s_hb = s["hits_bull"].sum(); s_mb = s["misses_bull"].sum()
                s_hr = s["hits_bear"].sum(); s_mr = s["misses_bear"].sum()
                f.write("## Vergleich vs. sma5_best\n\n")
                f.write(f"- sma5_best: Signale {s_tot}, Extra {s_extra}, Hit Bull {s_hb}/{s_hb+s_mb} ({(s_hb/(s_hb+s_mb) if s_hb+s_mb else 0):.2f}), Hit Bear {s_hr}/{s_hr+s_mr} ({(s_hr/(s_hr+s_mr) if s_hr+s_mr else 0):.2f})\n")
            f.write("\n## Bester Lauf vs. opt_01/sma5_best (Signale)\n\n")
            best_v = validate_trial(best_target)
            f.write(f"- best: Signale {best_v['model_sigs']}, Extra {best_v['extra']}, Hit Bull {best_v['hits_bull']}/{best_v['hits_bull']+best_v['misses_bull']} ({best_v['hit_rate_bull']:.2f}), Hit Bear {best_v['hits_bear']}/{best_v['hits_bear']+best_v['misses_bear']} ({best_v['hit_rate_bear']:.2f})\n")
        print(f"Report saved: {report_path}")
        print("\nTop-5:")
        print(top5[["trial", "score", "val_f1", "oot_f1", "hit_rate_bull", "hit_rate_bear", "model_sigs", "extra"]].to_string(index=False))


if __name__ == "__main__":
    main()
