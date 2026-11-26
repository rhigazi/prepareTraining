#!/usr/bin/env python3
"""extremes_tool.py - Annotate raw CSVs, validate vs SMA(38/80) cross segments, chart."""

import argparse
import glob
import os
import sys

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import annotate_extremes as ae
try:
    import prepare_sma5_data as sma5
except Exception:
    sma5 = None
try:
    import ml4t_features as ml4t
except Exception:
    ml4t = None
try:
    import fib_features as fib
except Exception:
    fib = None
from train_turning_points import TurningPointMLP, suppress_signal_clusters

try:
    import talib
except Exception as e:
    print("TA-Lib is required:", e, file=sys.stderr)
    sys.exit(1)


def parse_args():
    p = argparse.ArgumentParser(description="Annotate extremes, validate vs SMA cross segments, chart.")
    p.add_argument("--mode", choices=["annotate", "validate-sma", "all"], default="all")
    p.add_argument("--input-dir", default=None)
    p.add_argument("--files", nargs="*", default=None)
    p.add_argument("--pattern", default="*.csv")
    p.add_argument("--model-dir", default="./runs/opt_01")
    p.add_argument("--output-dir", default="./extremes_output")
    p.add_argument("--min-confidence", type=float, default=None)
    p.add_argument("--cooldown-bars", type=int, default=None)
    p.add_argument("--tolerance-bars", type=int, default=5)
    p.add_argument("--window-bars", type=int, default=400)
    p.add_argument("--html", action="store_true", help="Also export interactive HTML charts (plotly)")
    return p.parse_args()


def collect_files(args):
    return ae.collect_files(args)


def load_model(model_dir, cooldown_override=None, min_conf=None):
    ckpt_path = os.path.join(model_dir, "turning_point_mlp.pt")
    scaler_path = os.path.join(model_dir, "feature_scaler.joblib")
    if not os.path.isfile(ckpt_path) or not os.path.isfile(scaler_path):
        raise FileNotFoundError(f"Missing model artifacts in {model_dir}")
    ckpt = torch.load(ckpt_path, map_location="cpu")
    scaler = joblib.load(scaler_path)
    model = TurningPointMLP(in_features=len(ckpt["feature_cols"]), hidden_dims=ckpt["hidden_dims"],
                            dropout=ckpt["dropout"], num_classes=3)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    threshold = float(ckpt.get("best_threshold", 0.5))
    if min_conf is not None:
        threshold = min_conf
    cooldown = int(ckpt.get("cooldown_bars", 5))
    if cooldown_override is not None:
        cooldown = cooldown_override
    return ckpt, scaler, model, threshold, cooldown


def annotate_df(df_raw, ckpt, scaler, model, threshold, cooldown):
    feature_cols = ckpt["feature_cols"]
    if fib is not None and "feat_fib_pos" in feature_cols:
        df = fib.compute_features(df_raw.copy(), lookback=20)
    elif ml4t is not None and "feat_ret1" in feature_cols:
        df = ml4t.compute_features(df_raw.copy())
    elif sma5 is not None and any(c.startswith("feat_rsi") for c in feature_cols):
        df = sma5.compute_features(df_raw.copy())
    else:
        df = ae.compute_features(df_raw.copy())
    feature_cols = ckpt["feature_cols"]
    # ensure all
    for c in feature_cols:
        if c not in df.columns:
            df[c] = np.nan
    X = df[feature_cols].to_numpy(dtype=np.float32)
    X = np.where(np.isfinite(X), X, 0.0)
    valid = np.isfinite(df[feature_cols].to_numpy(dtype=float)).all(axis=1)
    Xs = scaler.transform(X)
    Xs = np.where(np.isfinite(Xs), Xs, 0.0)
    probs = np.zeros((len(df), 3), dtype=np.float32)
    probs[:, 1] = 1.0
    if valid.any():
        with torch.no_grad():
            xb = torch.tensor(Xs[valid], dtype=torch.float32)
            logits = model(xb)
            p = torch.softmax(logits, dim=-1).cpu().numpy()
            probs[valid] = p
    raw_idx = suppress_signal_clusters(probs, threshold, cooldown_bars=1) if len(probs) else np.array([])
    filt_idx = suppress_signal_clusters(probs, threshold, cooldown_bars=cooldown) if len(probs) else np.array([])
    raw_idx = np.where(valid, raw_idx, 1)
    filt_idx = np.where(valid, filt_idx, 1)
    idx_to_turn = {0: -1, 1: 0, 2: 1}
    raw_turn = np.array([idx_to_turn.get(int(i), 0) for i in raw_idx])
    filt_turn = np.array([idx_to_turn.get(int(i), 0) for i in filt_idx])
    out = df.copy()
    feat_cols = [c for c in out.columns if c.startswith("feat_")]
    out = out.drop(columns=feat_cols)
    out["prob_high"] = probs[:, 0]
    out["prob_neutral"] = probs[:, 1]
    out["prob_low"] = probs[:, 2]
    out["raw_pred_turn"] = raw_turn
    out["extreme_point"] = filt_turn
    out["extreme_label"] = [ {-1:"Extrem-Hoch",1:"Extrem-Tief"}.get(v,"") for v in filt_turn ]
    return out, probs, filt_turn, valid


def standardize_ohlc(df):
    close = df["c"] if "c" in df.columns else df["meta_close"]
    high = df["h"] if "h" in df.columns else df["meta_high"]
    low = df["l"] if "l" in df.columns else df["meta_low"]
    t = df["t"] if "t" in df.columns else df.get("meta_t", pd.Series(range(len(df))))
    return close.astype(float).to_numpy(), high.astype(float).to_numpy(), low.astype(float).to_numpy(), t


def sma_cross_segments(close, high, low):
    s38 = pd.Series(close).rolling(38, min_periods=38).mean().to_numpy()
    s80 = pd.Series(close).rolling(80, min_periods=80).mean().to_numpy()
    # crossing indices where sign of diff changes (finite)
    diff = s38 - s80
    segs = []  # list of dicts: start, end, type, extremum_pos
    # find crossing positions
    crosses = [0]
    for i in range(1, len(close)):
        if not (np.isfinite(diff[i-1]) and np.isfinite(diff[i])):
            continue
        if diff[i-1] == 0:
            continue
        if np.sign(diff[i]) != np.sign(diff[i-1]) and diff[i] != 0:
            crosses.append(i)
    crosses.append(len(close)-1)
    # unique sorted
    crosses = sorted(set(crosses))
    # Build segments between consecutive crosses
    for a, b in zip(crosses, crosses[1:]):
        if b - a < 1:
            continue
        # type by majority sign in segment
        mid = (a + b) // 2
        if not np.isfinite(diff[mid]):
            continue
        bullish = diff[mid] > 0
        if bullish:
            pos = int(np.nanargmax(high[a:b+1]) + a)
            segs.append({"start": a, "end": b, "type": "bull", "extremum_pos": pos, "expected": -1})
        else:
            pos = int(np.nanargmin(low[a:b+1]) + a)
            segs.append({"start": a, "end": b, "type": "bear", "extremum_pos": pos, "expected": +1})
    return s38, s80, segs, crosses


def validate_segments(filt_turn, segs, tolerance):
    hits = {"bull": 0, "bear": 0}
    misses = {"bull": 0, "bear": 0}
    matched_model_idx = set()
    for seg in segs:
        exp = seg["expected"]
        pos = seg["extremum_pos"]
        lo = max(0, pos - tolerance)
        hi = min(len(filt_turn)-1, pos + tolerance)
        window_positions = list(range(lo, hi+1))
        found = [i for i in window_positions if filt_turn[i] == exp]
        if found:
            hits["bull" if seg["type"]=="bull" else "bear"] += 1
            for i in found:
                matched_model_idx.add(i)
        else:
            misses["bull" if seg["type"]=="bull" else "bear"] += 1
    # extra model signals
    model_signal_positions = [i for i in range(len(filt_turn)) if filt_turn[i] != 0]
    extra = [i for i in model_signal_positions if i not in matched_model_idx]
    extra_bull = sum(1 for i in extra if filt_turn[i] == -1)
    extra_bear = sum(1 for i in extra if filt_turn[i] == 1)
    return hits, misses, extra, extra_bull, extra_bear, matched_model_idx


def plot_chunks(df, close, high, low, s38, s80, segs, filt_turn, metrics_text, out_dir, stem, window, html=False):
    n = len(df)
    chunk_size = window if window and window > 0 else n
    chunks = list(range(0, n, chunk_size))
    if len(chunks) == 1:
        chunk_indices = [0]
    else:
        chunk_indices = chunks
    for ci, start in enumerate(chunk_indices):
        end = min(start + chunk_size, n)
        fig, ax = plt.subplots(figsize=(14, 6))
        x = np.arange(start, end)
        ax.fill_between(x, high[start:end], low[start:end], color="lightgray", alpha=0.3, label="High-Low")
        ax.plot(x, close[start:end], color="black", linewidth=1, label="Close")
        ax.plot(x, s38[start:end], color="orange", linewidth=1, label="SMA38")
        ax.plot(x, s80[start:end], color="blue", linewidth=1, label="SMA80")
        # cross points in chunk
        for seg in segs:
            # crossing boundaries
            pass
        # segment extremes in chunk
        for seg in segs:
            pos = seg["extremum_pos"]
            if start <= pos < end:
                if seg["type"] == "bull":
                    ax.scatter(pos, high[pos], marker="v", color="red", s=60, zorder=5, label="Seg-Extrem Hoch" if pos==segs[0]["extremum_pos"] else "")
                else:
                    ax.scatter(pos, low[pos], marker="^", color="green", s=60, zorder=5, label="Seg-Extrem Tief" if pos==segs[0]["extremum_pos"] else "")
        # model signals in chunk
        for i in range(start, end):
            if filt_turn[i] == -1:
                ax.scatter(i, high[i], marker="v", color="darkred", s=90, zorder=6)
            elif filt_turn[i] == 1:
                ax.scatter(i, low[i], marker="^", color="darkgreen", s=90, zorder=6)
        # cross points: where sign changes
        diff = s38 - s80
        for i in range(max(start,1), end):
            if np.isfinite(diff[i-1]) and np.isfinite(diff[i]) and diff[i-1]*diff[i] < 0:
                ax.scatter(i, close[i], marker="x", color="purple", s=40, zorder=4)
        ax.set_title(f"{stem} | bars {start}-{end-1}")
        ax.set_xlabel("Bar index")
        ax.set_ylabel("Price")
        ax.grid(True, alpha=0.3)
        # legend dedup
        handles, labels = ax.get_legend_handles_labels()
        seen = set()
        hl = []
        for h, l in zip(handles, labels):
            if l and l not in seen:
                seen.add(l)
                hl.append((h, l))
        if hl:
            ax.legend([h for h,_ in hl], [l for _,l in hl], loc="upper left", fontsize=8)
        # metrics box
        ax.text(0.99, 0.01, metrics_text, transform=ax.transAxes, fontsize=8,
                verticalalignment="bottom", horizontalalignment="right",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))
        suffix = f"_{ci+1:03d}" if len(chunk_indices) > 1 else ""
        png_path = os.path.join(out_dir, f"{stem}_chart{suffix}.png")
        fig.tight_layout()
        fig.savefig(png_path, dpi=120)
        plt.close(fig)
        # html optional
        if html:
            try:
                import plotly.graph_objects as go
                figp = go.Figure()
                xx = list(range(start, end))
                figp.add_trace(go.Scatter(x=xx, y=close[start:end], name="Close", line=dict(color="black")))
                figp.add_trace(go.Scatter(x=xx, y=s38[start:end], name="SMA38", line=dict(color="orange")))
                figp.add_trace(go.Scatter(x=xx, y=s80[start:end], name="SMA80", line=dict(color="blue")))
                # high/low band
                figp.add_trace(go.Scatter(x=xx+xx[::-1], y=list(high[start:end])+list(low[start:end][::-1]),
                                         fill="toself", name="HL", line=dict(color="lightgray"), opacity=0.2))
                model_x = [i for i in range(start,end) if filt_turn[i]!=0]
                model_y = [ (high[i] if filt_turn[i]==-1 else low[i]) for i in model_x]
                model_sym = ["triangle-down" if filt_turn[i]==-1 else "triangle-up" for i in model_x]
                model_col = ["red" if filt_turn[i]==-1 else "green" for i in model_x]
                figp.add_trace(go.Scatter(x=model_x, y=model_y, mode="markers", name="Model",
                                         marker=dict(symbol=model_sym, color=model_col, size=10)))
                html_path = os.path.join(out_dir, f"{stem}_chart{suffix}.html")
                figp.write_html(html_path)
            except Exception as e:
                print(f"HTML export failed: {e}", file=sys.stderr)


def main():
    args = parse_args()
    files = collect_files(args)
    if not files:
        print("No input files found.", file=sys.stderr)
        sys.exit(1)

    out_dir = args.output_dir
    ann_dir = os.path.join(out_dir, "annotated")
    chart_dir = os.path.join(out_dir, "charts")
    report_dir = os.path.join(out_dir, "reports")
    for d in (out_dir, ann_dir, chart_dir, report_dir):
        os.makedirs(d, exist_ok=True)

    ckpt, scaler, model, threshold, cooldown = load_model(args.model_dir, args.cooldown_bars, args.min_confidence)

    report_rows = []

    for path in files:
        try:
            raw = pd.read_csv(path)
        except Exception as e:
            print(f"SKIP {path}: {e}", file=sys.stderr)
            continue
        stem = os.path.splitext(os.path.basename(path))[0]

        # annotate
        annotated, probs, filt_turn, valid = annotate_df(raw, ckpt, scaler, model, threshold, cooldown)

        if args.mode in ("annotate", "all"):
            out_path = os.path.join(ann_dir, f"{stem}_extremes.csv")
            annotated.to_csv(out_path, index=False)

        if args.mode == "annotate":
            n_high = int((filt_turn == -1).sum())
            n_low = int((filt_turn == 1).sum())
            print(f"{os.path.basename(path)}: rows={len(annotated)}, Extrem-Hoch(-1)={n_high}, Extrem-Tief(+1)={n_low}")
            continue

        close, high, low, t = standardize_ohlc(annotated)
        # annotated has original columns (maybe sorted). Use annotated for ohlc to align with filt_turn.
        # recompute ohlc from annotated (sorted)
        close, high, low, t = standardize_ohlc(annotated)

        s38, s80, segs, crosses = sma_cross_segments(close, high, low)
        hits, misses, extra, extra_bull, extra_bear, matched = validate_segments(filt_turn, segs, args.tolerance_bars)

        n_bull = sum(1 for s in segs if s["type"] == "bull")
        n_bear = sum(1 for s in segs if s["type"] == "bear")
        hit_bull = hits["bull"]; miss_bull = misses["bull"]
        hit_bear = hits["bear"]; miss_bear = misses["bear"]
        hr_bull = hit_bull / (hit_bull + miss_bull) if (hit_bull + miss_bull) > 0 else 0.0
        hr_bear = hit_bear / (hit_bear + miss_bear) if (hit_bear + miss_bear) > 0 else 0.0
        total_signals = int((filt_turn != 0).sum())
        metrics_text = (f"Segs: {len(segs)} (bull {n_bull}, bear {n_bear})\n"
                        f"Hit bull: {hit_bull}/{hit_bull+miss_bull} ({hr_bull:.2f})\n"
                        f"Hit bear: {hit_bear}/{hit_bear+miss_bear} ({hr_bear:.2f})\n"
                        f"Extra sigs: {len(extra)} (H {extra_bull}, T {extra_bear})\n"
                        f"Model sigs: {total_signals}")

        # report row
        report_rows.append({
            "file": os.path.basename(path),
            "segments_total": len(segs),
            "segments_bull": n_bull,
            "segments_bear": n_bear,
            "hits_bull": hit_bull,
            "misses_bull": miss_bull,
            "hit_rate_bull": round(hr_bull, 4),
            "hits_bear": hit_bear,
            "misses_bear": miss_bear,
            "hit_rate_bear": round(hr_bear, 4),
            "extra_signals": len(extra),
            "extra_high": extra_bull,
            "extra_low": extra_bear,
            "model_signals": total_signals,
            "tolerance_bars": args.tolerance_bars,
        })

        print(f"{os.path.basename(path)}: segs={len(segs)} (bull {n_bull}, bear {n_bear}) | "
              f"bull hit {hit_bull}/{hit_bull+miss_bull} ({hr_bull:.2f}) | "
              f"bear hit {hit_bear}/{hit_bear+miss_bear} ({hr_bear:.2f}) | "
              f"extra {len(extra)} | model_sigs {total_signals}")

        if args.mode in ("validate-sma", "all"):
            plot_chunks(annotated, close, high, low, s38, s80, segs, filt_turn, metrics_text,
                        chart_dir, stem, args.window_bars, html=args.html)

    # Save report
    if report_rows:
        rdf = pd.DataFrame(report_rows)
        csv_path = os.path.join(report_dir, "sma_validation_summary.csv")
        rdf.to_csv(csv_path, index=False)
        # markdown
        md_path = os.path.join(report_dir, "sma_validation_summary.md")
        with open(md_path, "w") as f:
            f.write("# SMA(38/80) Cross-Segment Validation\n\n")
            f.write(rdf.to_markdown(index=False))
            f.write("\n")
        print(f"\nReport saved: {csv_path} and {md_path}")

    print(f"Done. Output: {out_dir}")


if __name__ == "__main__":
    main()
