#!/usr/bin/env python3
"""predict_production.py - Inference entrypoint for the production bundles.

Examples
--------
# default model from production_models/registry.json (ml4t_04 / ml4t_opt)
python3 predict_production.py --input new_data/AAPL_1Hour.csv --output out/AAPL_signals.csv

# switch profile
python3 predict_production.py --input new_data/ --output out/ --model-profile baseline

# list profiles / inspect a candidate bundle directly
python3 predict_production.py --list-profiles
python3 predict_production.py --input x.csv --model-dir production_models/ml4t_opt/candidates/...
"""

import argparse
import glob
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import production_common as pc


def _print_summary(df, cfg, bundle_dir):
    sig = df[df["filtered_pred"] != 0]
    print(f"profile={cfg.get('profile')} run={cfg.get('run_id')} bundle={bundle_dir}")
    print(f"threshold={df['threshold'].iloc[0] if len(df) else '-'} "
          f"cooldown={df['cooldown_bars'].iloc[0] if len(df) else '-'}")
    print(f"rows={len(df)} valid_features={int(df['valid_features'].sum()) if len(df) else 0} "
          f"signals={len(sig)} high(-1)={int((sig['filtered_pred'] == -1).sum())} "
          f"low(+1)={int((sig['filtered_pred'] == 1).sum())}")


def main():
    ap = argparse.ArgumentParser(description="Run production inference for one model profile.")
    ap.add_argument("--input", help="Raw CSV file or directory of raw CSVs")
    ap.add_argument("--output", help="Output CSV (file input) or output directory (dir input)")
    ap.add_argument("--model-profile", default=None,
                    help="baseline | sma_auto | ml4t (or bundle name). Default: registry default_active.")
    ap.add_argument("--model-dir", default=None,
                    help="Optional explicit bundle directory (overrides registry profile).")
    ap.add_argument("--pattern", default="*.csv", help="Glob pattern for directory input")
    ap.add_argument("--threshold", type=float, default=None,
                    help="Override saved confidence threshold")
    ap.add_argument("--cooldown-bars", type=int, default=None,
                    help="Override saved cooldown")
    ap.add_argument("--list-profiles", action="store_true", help="Show registry profiles and exit")
    args = ap.parse_args()

    if args.list_profiles:
        reg = pc.load_registry()
        print(f"default_active: {reg['default_active']}")
        for key, e in reg["profiles"].items():
            print(f"  {key:10s} run={e['run_id']:8s} default={e.get('default', False)} "
                  f"dir={e['active_dir']}  {e.get('description', '')}")
        return

    if not args.input:
        ap.error("--input is required (or use --list-profiles)")

    cfg, model, scaler, bundle_dir = pc.load_bundle(args.model_profile, args.model_dir)
    out = args.output

    if os.path.isdir(args.input):
        files = [p for p in sorted(glob.glob(os.path.join(args.input, args.pattern)))
                 if os.path.isfile(p) and not os.path.basename(p).endswith(("_signals.csv", "_prepared.csv"))]
        if not files:
            ap.error(f"No CSV files found in {args.input}")
        combined_only = bool(out and out.lower().endswith(".csv"))
        out_dir = os.path.dirname(out) if combined_only else (out or os.path.join(HERE, "predictions"))
        os.makedirs(out_dir, exist_ok=True)
        frames = []
        for path in files:
            df = pc.predict_file(path, cfg, model, scaler, args.threshold, args.cooldown_bars)
            frames.append(df)
            if not combined_only:
                dst = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(path))[0]}_signals.csv")
                df.to_csv(dst, index=False)
                print(f"OK {os.path.basename(path)} -> {dst} | signals={int((df['filtered_pred'] != 0).sum())}")
        combined = pd.concat(frames, ignore_index=True)
        combined_path = out if combined_only else os.path.join(out_dir, "signals_all.csv")
        combined.to_csv(combined_path, index=False)
        _print_summary(combined, cfg, bundle_dir)
        print(f"Combined: {combined_path}")
        return

    if not os.path.isfile(args.input):
        ap.error(f"Input not found: {args.input}")
    df = pc.predict_file(args.input, cfg, model, scaler, args.threshold, args.cooldown_bars)
    out_path = args.output or os.path.join(
        HERE, "predictions", f"{os.path.splitext(os.path.basename(args.input))[0]}_signals.csv")
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    df.to_csv(out_path, index=False)
    _print_summary(df, cfg, bundle_dir)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
