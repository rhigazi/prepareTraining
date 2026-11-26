#!/usr/bin/env python3
"""train_sma5_model.py - Train/optimize model on prepared_sma5 data."""

import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.join(HERE, "train_turning_points.py")

def run_exp(name, extra_args):
    out_dir = os.path.join(HERE, "runs", name)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    cmd = [sys.executable, TRAIN, "--input-dir", os.path.join(HERE, "prepared_sma5"),
           "--output-dir", out_dir, "--out-of-tickers", "AAPL"] + extra_args
    print("\n=== Running", name, "===")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    # parse val f1
    log_path = os.path.join(out_dir, "training_run.log")
    val_f1 = None
    with open(log_path) as f:
        for line in f:
            m = re.search(r"Val Turn \(filtered\) P/R/F1: [\d.]+/[\d.]+/([\d.]+)", line)
            if m:
                val_f1 = float(m.group(1))
    print(f"{name}: Val Turn-F1 = {val_f1}")
    return name, out_dir, val_f1

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=40)
    args = parser.parse_args()

    exps = [
        ("sma5_opt_01", ["--epochs", str(args.epochs)]),
        ("sma5_opt_02", ["--epochs", str(args.epochs), "--hidden-dims", "128", "64", "--dropout", "0.4", "--weight-decay", "1e-3"]),
        ("sma5_opt_03", ["--epochs", str(args.epochs), "--class-weight-power", "0.5", "--cooldown-bars", "3", "--threshold-min", "0.30"]),
    ]

    results = []
    for name, extra in exps:
        try:
            r = run_exp(name, extra)
            results.append(r)
        except Exception as e:
            print(f"Experiment {name} failed: {e}", file=sys.stderr)

    if not results:
        print("No successful experiments.", file=sys.stderr)
        sys.exit(1)

    best = max(results, key=lambda x: (x[2] if x[2] is not None else -1))
    print("\nBest experiment:", best[0], "Val F1:", best[2])
    best_dir = best[1]
    target = os.path.join(HERE, "runs", "sma5_best")
    if os.path.exists(target):
        shutil.rmtree(target)
    shutil.copytree(best_dir, target)
    print("Copied best run to", target)

if __name__ == "__main__":
    main()
