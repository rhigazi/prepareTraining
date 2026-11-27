#!/usr/bin/env python3
"""run_batch_3models.py - One command: raw CSVs in, marked CSVs + PNGs out.

For every raw CSV the script runs, per model profile:
  profile-specific feature engineering -> saved scaler -> MLP -> threshold/cooldown
and writes:
  <output>/<bundle>/<stem>_marked.csv        (all raw columns + signals)
  <output>/<bundle>/charts/<stem>_chart_*.png (400-bar tiles)

Default profiles: ml4t_opt (ml4t_04), baseline_opt (base_05), sma_auto_opt (sma_05).
No manual intermediate CSVs are required; feature preparation happens in memory.
"""

import argparse
import glob
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import talib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import production_common as pc
import extremes_tool as et

DEFAULT_MODELS = ["ml4t", "baseline", "sma_auto"]
SKIP_SUFFIXES = ("_prepared.csv", "_signals.csv", "_marked.csv")
SKIP_NAMES = {"batch_summary.csv", "batch_summary.json"}


class Tee:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8")

    def __call__(self, msg=""):
        line = str(msg)
        print(line)
        self.fh.write(line + "\n")
        self.fh.flush()

    def close(self):
        self.fh.close()


def parse_args():
    ap = argparse.ArgumentParser(
        description="Raw CSV -> marked CSVs and charts for the three production models.")
    ap.add_argument("--input-dir", default="./raw_data", help="Folder with raw CSV files")
    ap.add_argument("--output-dir", default="./batch_output", help="Output root")
    ap.add_argument("--pattern", default="*.csv", help="Glob pattern for input CSVs")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                    help="Profiles: ml4t baseline sma_auto (aliases/bundle names accepted)")
    ap.add_argument("--chart-bars", type=int, default=400, help="Bars per chart tile")
    ap.add_argument("--no-charts", action="store_true", help="Write CSVs only")
    ap.add_argument("--keep-work", action="store_true",
                    help="Keep <output>/_work with per-model processing manifests")
    return ap.parse_args()


def collect_files(input_dir, pattern):
    files = []
    for p in sorted(glob.glob(os.path.join(input_dir, pattern))):
        if not os.path.isfile(p):
            continue
        if os.path.basename(p).endswith(SKIP_SUFFIXES):
            continue
        if os.path.basename(p) in SKIP_NAMES:
            continue
        files.append(p)
    return files


def resolve_models(names):
    resolved, seen = [], set()
    for name in names:
        key, entry, _ = pc.resolve_profile(name)
        bundle = entry["bundle"]
        if bundle not in seen:
            seen.add(bundle)
            resolved.append((key, entry))
    return resolved


def marked_frame(res, raw_cols, cfg, source_name):
    """All original raw columns plus probabilities and extreme markers."""
    df = res["df"]
    keep = [c for c in raw_cols if c in df.columns]
    out = df[keep].copy()
    out["bar_index"] = np.arange(len(out), dtype=int)
    out["prob_-1"] = res["probs"][:, 0].astype(float)
    out["prob_0"] = res["probs"][:, 1].astype(float)
    out["prob_1"] = res["probs"][:, 2].astype(float)
    out["raw_pred"] = res["raw"].astype(int)
    out["filtered_pred"] = res["filt"].astype(int)
    out["extreme_point"] = res["filt"].astype(int)
    out["extreme_label"] = np.select(
        [res["filt"] == -1, res["filt"] == 1],
        ["Extrem-Hoch", "Extrem-Tief"], default="")
    out["valid_features"] = res["valid"].astype(bool)
    out["source_file"] = os.path.basename(source_name)
    out["model_profile"] = cfg.get("profile", "")
    out["threshold"] = float(res["threshold"])
    out["cooldown_bars"] = int(res["cooldown"])
    return out


def file_row(bundle, cfg, source, input_rows, marked, fm):
    hits = fm["hits_bull"] + fm["hits_bear"]
    segs = hits + fm["misses_bull"] + fm["misses_bear"]
    mean_atr_dist = (fm["atr_dist_sum"] / fm["atr_dist_n"]
                     if fm.get("atr_dist_n") else None)
    return {
        "model": bundle,
        "profile": cfg.get("profile"),
        "run_id": cfg.get("run_id"),
        "source_file": os.path.basename(source),
        "input_rows": int(input_rows),
        "output_rows": int(len(marked)),
        "dropped_rows": int(input_rows - len(marked)),
        "valid_rows": int(marked["valid_features"].sum()),
        "signals": int((marked["filtered_pred"] != 0).sum()),
        "high_signals": int((marked["filtered_pred"] == -1).sum()),
        "low_signals": int((marked["filtered_pred"] == 1).sum()),
        "extra_signals": int(fm["extra"]),
        "hits_bull": int(fm["hits_bull"]),
        "misses_bull": int(fm["misses_bull"]),
        "hits_bear": int(fm["hits_bear"]),
        "misses_bear": int(fm["misses_bear"]),
        "hit_rate_bull": (fm["hits_bull"] / (fm["hits_bull"] + fm["misses_bull"])
                          if (fm["hits_bull"] + fm["misses_bull"]) else 0.0),
        "hit_rate_bear": (fm["hits_bear"] / (fm["hits_bear"] + fm["misses_bear"])
                          if (fm["hits_bear"] + fm["misses_bear"]) else 0.0),
        "event_precision": (hits / (hits + fm["extra"]) if (hits + fm["extra"]) else 0.0),
        "event_recall": (hits / segs if segs else 0.0),
        "extra_rate": (fm["extra"] / fm["model_sigs"] if fm["model_sigs"] else 0.0),
        "mean_atr_dist": mean_atr_dist,
        "atr_quality": (1.0 / (1.0 + mean_atr_dist)
                        if mean_atr_dist is not None else 0.0),
        "threshold": float(cfg["post_processing"]["threshold"]),
        "cooldown_bars": int(cfg["post_processing"]["cooldown_bars"]),
    }


def prepare_model_dir(model_dir):
    os.makedirs(model_dir, exist_ok=True)
    charts_dir = os.path.join(model_dir, "charts")
    if os.path.isdir(charts_dir):
        shutil.rmtree(charts_dir)
    for old in glob.glob(os.path.join(model_dir, "*_marked.csv")):
        os.remove(old)
    os.makedirs(charts_dir, exist_ok=True)
    return charts_dir


def process_model(profile, args, log, work_dir):
    key, entry = profile
    cfg, model, scaler, bundle_dir = pc.load_bundle(key)
    bundle = entry["bundle"]
    model_dir = os.path.join(args.output_dir, bundle)
    charts_dir = prepare_model_dir(model_dir)
    files = collect_files(args.input_dir, args.pattern)
    if not files:
        raise FileNotFoundError(f"No raw CSV files found in {args.input_dir} ({args.pattern})")

    log("")
    log(f"### {bundle} | profile={cfg.get('profile')} run={cfg.get('run_id')} "
        f"thr={cfg['post_processing']['threshold']} cd={cfg['post_processing']['cooldown_bars']}")
    log(f"    bundle: {os.path.relpath(bundle_dir, HERE)} | files: {len(files)}")

    rows, payloads, errors = [], [], []
    for path in files:
        try:
            raw = pd.read_csv(path)
            raw_cols = list(raw.columns)
            res = pc.infer_array(raw, cfg, model, scaler)
            marked = marked_frame(res, raw_cols, cfg, path)
            out_csv = os.path.join(model_dir, f"{os.path.splitext(os.path.basename(path))[0]}_marked.csv")
            marked.to_csv(out_csv, index=False)

            s38, s80, segs, crosses = et.sma_cross_segments(res["close"], res["high"], res["low"])
            atr = talib.ATR(res["high"], res["low"], res["close"], timeperiod=14)
            fm = pc.segment_metrics(res["filt"], segs, res["close"], atr)
            row = file_row(bundle, cfg, path, len(raw), marked, fm)
            row["csv"] = os.path.relpath(out_csv, args.output_dir)
            rows.append(row)
            payloads.append({
                "source": path,
                "stem": os.path.splitext(os.path.basename(path))[0],
                "res": {"close": res["close"], "high": res["high"],
                        "low": res["low"], "filt": res["filt"]},
                "file_metrics": fm,
            })
            log(f"    OK {os.path.basename(path)}: rows={len(marked)} "
                f"signals={row['signals']} extra={row['extra_signals']} -> {row['csv']}")
        except Exception as e:
            msg = f"{os.path.basename(path)}: {e}"
            errors.append(msg)
            log(f"    ERROR {msg}")
            log(traceback.format_exc(limit=2))
            rows.append({"model": bundle, "source_file": os.path.basename(path), "error": str(e)})

    aggregate = pc.aggregate_segment_metrics([p["file_metrics"] for p in payloads])
    aggregate.update({
        "model": bundle,
        "profile": cfg.get("profile"),
        "run_id": cfg.get("run_id"),
        "threshold": float(cfg["post_processing"]["threshold"]),
        "cooldown_bars": int(cfg["post_processing"]["cooldown_bars"]),
        "reference_val_f1": cfg.get("reference_metrics", {}).get("val_f1"),
        "reference_test_f1": cfg.get("reference_metrics", {}).get("test_f1"),
        "reference_oot_f1": cfg.get("reference_metrics", {}).get("oot_f1"),
        "files": len(payloads),
        "errors": len(errors),
    })

    chart_count = 0
    charts_by_file = {}
    if not args.no_charts:
        global_m = dict(aggregate)
        global_m["val_f1"] = aggregate.get("reference_val_f1")
        global_m["oot_f1"] = aggregate.get("reference_oot_f1")
        bars = int(args.chart_bars)
        if bars <= 0:
            raise ValueError("--chart-bars must be > 0")
        for p in payloads:
            n = len(p["res"]["close"])
            if n == 0:
                continue
            file_charts = 0
            for ci, start in enumerate(range(0, n, bars)):
                end = min(start + bars, n)
                png = os.path.join(charts_dir, f"{p['stem']}_chart_{ci + 1:03d}.png")
                title = (f"{p['stem']} | bars {start}-{end - 1} | "
                         f"{bundle} / {cfg.get('run_id')}")
                pc.plot_control_chart(p["res"], cfg, global_m, p["file_metrics"],
                                      start, end, title, png, context_label="RUN")
                chart_count += 1
                file_charts += 1
            charts_by_file[os.path.basename(p["source"])] = file_charts
        log(f"    charts: {chart_count} PNG(s) -> {os.path.relpath(charts_dir, args.output_dir)}")

    for row in rows:
        if "error" not in row:
            row["charts"] = charts_by_file.get(row["source_file"], 0) if not args.no_charts else 0
    aggregate["charts"] = chart_count

    if args.keep_work:
        wdir = os.path.join(work_dir, bundle)
        os.makedirs(wdir, exist_ok=True)
        pc.write_json(os.path.join(wdir, "aggregate.json"), aggregate)
        pc.write_json(os.path.join(wdir, "files.json"), rows)
    return rows, aggregate, errors


def main():
    args = parse_args()
    args.input_dir = os.path.abspath(args.input_dir)
    args.output_dir = os.path.abspath(args.output_dir)
    if not os.path.isdir(args.input_dir):
        raise SystemExit(f"Input directory not found: {args.input_dir}")
    os.makedirs(args.output_dir, exist_ok=True)

    work_dir = os.path.join(args.output_dir, "_work")
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir)
    os.makedirs(work_dir, exist_ok=True)

    log = Tee(os.path.join(args.output_dir, "batch_run.log"))
    started = datetime.now(timezone.utc)
    log("=" * 78)
    log(f"batch_3models started {started.isoformat(timespec='seconds')}")
    log(f"input:  {args.input_dir}")
    log(f"output: {args.output_dir}")
    log("=" * 78)

    all_rows, model_summaries, all_errors = [], {}, []
    try:
        try:
            profiles = resolve_models(args.models)
        except Exception as e:
            log(f"ERROR resolving models: {e}")
            raise SystemExit(2)
        for profile in profiles:
            bundle = profile[1]["bundle"]
            try:
                rows, aggregate, errors = process_model(profile, args, log, work_dir)
                all_rows.extend(rows)
                model_summaries[bundle] = aggregate
                all_errors.extend(f"{bundle}: {e}" for e in errors)
            except Exception as e:
                msg = f"{bundle}: {e}"
                all_errors.append(msg)
                log(f"MODEL ERROR {msg}")
                log(traceback.format_exc(limit=3))
                model_summaries[bundle] = {"model": bundle, "error": str(e)}

        df = pd.DataFrame(all_rows)
        summary_csv = os.path.join(args.output_dir, "batch_summary.csv")
        df.to_csv(summary_csv, index=False)

        manifest = {
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "input_dir": args.input_dir,
            "output_dir": args.output_dir,
            "chart_bars": int(args.chart_bars),
            "charts_enabled": not args.no_charts,
            "intermediate_data": "in-memory only (no intermediate CSVs required)",
            "models": model_summaries,
            "errors": all_errors,
        }
        pc.write_json(os.path.join(args.output_dir, "batch_summary.json"), manifest)
        if args.keep_work:
            pc.write_json(os.path.join(work_dir, "manifest.json"), manifest)

        log("")
        log("Summary")
        for bundle, m in model_summaries.items():
            if "error" in m:
                log(f"  {bundle}: ERROR {m['error']}")
            else:
                log(f"  {bundle}: files={m['files']} signals={m['model_sigs']} "
                    f"extra={m['extra']} hit_avg={m['hit_avg']:.3f} "
                    f"charts={m['charts']} errors={m['errors']}")
        log(f"  batch_summary.csv: {summary_csv}")
        log(f"  batch_summary.json: {os.path.join(args.output_dir, 'batch_summary.json')}")
        log(f"batch_3models finished {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    finally:
        log.close()
        if not args.keep_work:
            shutil.rmtree(work_dir, ignore_errors=True)

    if all_errors:
        print(f"\nCompleted with {len(all_errors)} error(s). See batch_run.log.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
