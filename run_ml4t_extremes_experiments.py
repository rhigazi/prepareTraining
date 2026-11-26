#!/usr/bin/env python3
"""run_ml4t_extremes_experiments.py - ML4T-inspired stationary features & label tolerance search."""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import talib
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import ADXIndicator
from ta.volatility import BollingerBands
from ta.volume import MFIIndicator

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.join(HERE, "train_turning_points.py")
EXTREMES = os.path.join(HERE, "extremes_tool.py")
PY = sys.executable
RAW_DIR = os.path.join(HERE, "raw_data")
SEARCH_DIR = os.path.join(HERE, "runs", "ml4t_search")

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import extremes_tool as et


def sma_segment_labels(close, high, low):
    s38 = pd.Series(close).rolling(38, min_periods=38).mean().to_numpy()
    s80 = pd.Series(close).rolling(80, min_periods=80).mean().to_numpy()
    diff = s38 - s80
    crosses = [0]
    for i in range(1, len(close)):
        if not (np.isfinite(diff[i-1]) and np.isfinite(diff[i])):
            continue
        if diff[i-1] == 0:
            continue
        if np.sign(diff[i]) != np.sign(diff[i-1]) and diff[i] != 0:
            crosses.append(i)
    crosses.append(len(close) - 1)
    crosses = sorted(set(crosses))
    labels = np.zeros(len(close), dtype=float)
    for a, b in zip(crosses, crosses[1:]):
        if b - a < 1:
            continue
        mid = (a + b) // 2
        if not np.isfinite(diff[mid]):
            continue
        if diff[mid] > 0:
            pos = int(np.nanargmax(high[a:b+1]) + a)
            labels[pos] = -1.0
        else:
            pos = int(np.nanargmin(low[a:b+1]) + a)
            labels[pos] = 1.0
    return labels


def expand_labels(labels, tol):
    if tol <= 0:
        return labels.copy()
    out = labels.copy()
    n = len(labels)
    for i in range(n):
        if labels[i] != 0:
            for j in range(max(0, i-tol), min(n, i+tol+1)):
                if out[j] == 0:
                    out[j] = labels[i]
    return out


def make_prepared(tol):
    dst = os.path.join(SEARCH_DIR, f"prepared_tol{tol}")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
        df = pd.read_csv(path)
        for col in ["t", "o", "h", "l", "c", "v"]:
            if col not in df.columns:
                raise ValueError(f"Missing {col}")
        if "vw" not in df.columns:
            df["vw"] = df["c"]
        df = pd.read_csv(path)
        # sort/dedup like prepareTraining
        import prepareTraining as pt
        df = pt.sort_and_dedup(df)
        o = df["o"].to_numpy(float); h = df["h"].to_numpy(float); l = df["l"].to_numpy(float)
        c = df["c"].to_numpy(float); v = df["v"].to_numpy(float); n = len(df)
        ticker = pt.parse_ticker_timeframe(path)[0]
        timeframe = pt.parse_ticker_timeframe(path)[1]

        # indicators
        rsi = RSIIndicator(pd.Series(c), window=14).rsi().to_numpy(float)
        stoch = StochasticOscillator(pd.Series(h), pd.Series(l), pd.Series(c), window=14, smooth_window=3)
        stoch_k = stoch.stoch().to_numpy(float); stoch_d = stoch.stoch_signal().to_numpy(float)
        adx = ADXIndicator(pd.Series(h), pd.Series(l), pd.Series(c), window=14).adx().to_numpy(float)
        bb = BollingerBands(pd.Series(c), window=20, window_dev=2)
        bb_pctb = bb.bollinger_pband().to_numpy(float)
        bb_bw = bb.bollinger_wband().to_numpy(float)
        bb_mid = bb.bollinger_mavg().to_numpy(float)
        mfi = MFIIndicator(pd.Series(h), pd.Series(l), pd.Series(c), pd.Series(v), window=14).money_flow_index().to_numpy(float)

        # stationary features (ML4T-inspired)
        ret1 = np.concatenate([[np.nan], np.diff(c) / c[:-1]])
        ret5 = pd.Series(c).pct_change(5).to_numpy(float)
        vol20 = pd.Series(ret1).rolling(20, min_periods=20).std().to_numpy(float)
        vol_ratio = v / pd.Series(v).rolling(20, min_periods=20).mean().to_numpy(float)

        feat = {}
        feat["feat_rsi"] = rsi / 100.0
        feat["feat_rsi_diff"] = np.concatenate([[np.nan], np.diff(rsi)]) / 100.0
        feat["feat_stoch_k"] = stoch_k / 100.0
        feat["feat_stoch_d"] = stoch_d / 100.0
        feat["feat_stoch_diff"] = (stoch_k - stoch_d) / 100.0
        feat["feat_stoch_k_diff"] = np.concatenate([[np.nan], np.diff(stoch_k)]) / 100.0
        feat["feat_adx"] = adx / 100.0
        feat["feat_adx_diff"] = np.concatenate([[np.nan], np.diff(adx)]) / 100.0
        feat["feat_bb_pct_b"] = bb_pctb
        feat["feat_bb_bw"] = bb_bw
        feat["feat_bb_bw_diff"] = np.concatenate([[np.nan], np.diff(bb_bw)])
        feat["feat_bb_dist_mid"] = (c - bb_mid) / np.where(np.abs(bb_mid) < 1e-8, 1.0, bb_mid)
        feat["feat_mfi"] = mfi / 100.0
        feat["feat_mfi_diff"] = np.concatenate([[np.nan], np.diff(mfi)]) / 100.0
        feat["feat_ret1"] = ret1
        feat["feat_ret5"] = ret5
        feat["feat_vol20"] = vol20
        feat["feat_vol_ratio"] = vol_ratio

        labels = sma_segment_labels(c, h, l)
        labels = expand_labels(labels, tol)

        # ATR for label_max_move_atr
        atr = talib.ATR(h, l, c, timeperiod=14)
        wr = 6
        fut_min_low = pd.Series(l).rolling(window=wr, min_periods=wr).min().shift(-wr).to_numpy()
        fut_max_high = pd.Series(h).rolling(window=wr, min_periods=wr).max().shift(-wr).to_numpy()
        valid_future = np.isfinite(fut_min_low) & np.isfinite(fut_max_high)
        drop = h - fut_min_low; rise = fut_max_high - l
        up_move = (fut_max_high - l) / atr; down_move = (h - fut_min_low) / atr
        label_max_move = np.maximum(up_move, down_move)
        high_mask = labels == -1; low_mask = labels == 1
        label_max_move[high_mask] = (drop / atr)[high_mask]
        label_max_move[low_mask] = (rise / atr)[low_mask]
        incomplete = ~valid_future
        labels[incomplete] = np.nan
        label_max_move[incomplete] = np.nan

        out = pd.DataFrame({
            "meta_t": df["t"].values,
            "meta_ticker": [ticker] * n,
            "meta_timeframe": [timeframe] * n,
            "meta_open": o, "meta_high": h, "meta_low": l, "meta_close": c,
        })
        for k, val in feat.items():
            out[k] = val
        out["label_turn"] = labels
        out["label_max_move_atr"] = label_max_move
        feat_cols = [col for col in out.columns if col.startswith("feat_")]
        out = out.replace([np.inf, -np.inf], np.nan)
        out = out.dropna(subset=feat_cols + ["label_turn", "label_max_move_atr"]).reset_index(drop=True)
        out["label_turn"] = out["label_turn"].astype(int)
        if out.empty:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        out.to_csv(os.path.join(dst, f"{stem}_prepared.csv"), index=False)
    return dst


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
    val_f1 = None; overall = []
    with open(log_path) as f:
        for line in f:
            m = re.search(r"Val Turn \(filtered\) P/R/F1: [\d.]+/[\d.]+/([\d.]+)", line)
            if m:
                val_f1 = float(m.group(1))
            m2 = re.search(r"Overall Turn Precision/Recall/F1: ([\d.]+)/([\d.]+)/([\d.]+)", line)
            if m2:
                overall.append(float(m2.group(3)))
    oot_f1 = overall[-1] if len(overall) >= 2 else (overall[0] if overall else None)
    return out_dir, val_f1, oot_f1


def validate_trial(model_dir):
    ckpt, scaler, model, threshold, cooldown = et.load_model(model_dir)
    hits_b = misses_b = hits_r = misses_r = 0
    total_extra = total_sigs = 0
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
        raw = pd.read_csv(path)
        annotated, probs, filt_turn, valid = et.annotate_df(raw, ckpt, scaler, model, threshold, cooldown)
        close, high, low, t = et.standardize_ohlc(annotated)
        s38, s80, segs, crosses = et.sma_cross_segments(close, high, low)
        h, m, extra, eb, er, matched = et.validate_segments(filt_turn, segs, tolerance=5)
        hits_b += h["bull"]; misses_b += m["bull"]
        hits_r += h["bear"]; misses_r += m["bear"]
        total_extra += len(extra); total_sigs += int((filt_turn != 0).sum())
    hr_bull = hits_b / (hits_b + misses_b) if (hits_b + misses_b) else 0.0
    hr_bear = hits_r / (hits_r + misses_r) if (hits_r + misses_r) else 0.0
    return {"hits_bull": hits_b, "misses_bull": misses_b, "hit_rate_bull": hr_bull,
            "hits_bear": hits_r, "misses_bear": misses_r, "hit_rate_bear": hr_bear,
            "extra": total_extra, "model_sigs": total_sigs}


def composite_score(val_f1, oot_f1, v):
    val_f1 = val_f1 or 0.0; oot_f1 = oot_f1 or 0.0
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
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--trials", type=int, default=9)
    args = parser.parse_args()

    os.makedirs(SEARCH_DIR, exist_ok=True)
    # methodology doc
    with open(os.path.join(SEARCH_DIR, "methodology.md"), "w") as f:
        f.write("# ML4T-inspired Experiment Strand\n\n")
        f.write("Übernommen aus machine-learning-for-trading:\n")
        f.write("- Stationäre/normierte Features (Differenzen, Momentum-Änderungen, Ratios, normierte Abstände) statt roher nicht-stationärer Werte.\n")
        f.write("- Zeitlich saubere Splits (train/val/test + OOT-Ticker) wie in train_turning_points.py.\n")
        f.write("- Precision/Recall/F1 und Event-Treffer (Hit-Rate auf Bull/Bear-Segment-Extreme) als Bewertung.\n")
        f.write("- Schwellen-/Signal-Kalibrierung über Threshold-Tuning und Cooldown (NMS).\n")
        f.write("- Klassen-Gewichtung zur Behandlung des Ungleichgewichts.\n")
        f.write("Keine SMA(38/80)-Leaks in Features; Labels aus SMA-Cross-Segmenten (mit optionalem Toleranzfenster).\n")

    # prepared datasets
    print("Preparing tolerance datasets...")
    data_tol0 = make_prepared(0)
    data_tol1 = make_prepared(1)
    data_tol2 = make_prepared(2)

    configs = [
        ("ml4t_01", data_tol0, ["--hidden-dims", "64", "32", "--dropout", "0.35", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.50"]),
        ("ml4t_02", data_tol1, ["--hidden-dims", "64", "32", "--dropout", "0.35", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.50"]),
        ("ml4t_03", data_tol2, ["--hidden-dims", "64", "32", "--dropout", "0.35", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.40", "--threshold-max", "0.50"]),
        ("ml4t_04", data_tol1, ["--hidden-dims", "128", "64", "--dropout", "0.4", "--class-weight-power", "0.5", "--learning-rate", "1e-3", "--cooldown-bars", "3", "--threshold-min", "0.35", "--threshold-max", "0.45"]),
        ("ml4t_05", data_tol1, ["--hidden-dims", "64", "32", "16", "--dropout", "0.45", "--class-weight-power", "0.7", "--learning-rate", "5e-4", "--cooldown-bars", "3", "--threshold-min", "0.30", "--threshold-max", "0.40"]),
        ("ml4t_06", data_tol0, ["--hidden-dims", "96", "48", "--dropout", "0.3", "--class-weight-power", "0.5", "--learning-rate", "7e-4", "--cooldown-bars", "4", "--threshold-min", "0.40", "--threshold-max", "0.50"]),
        ("ml4t_07", data_tol2, ["--hidden-dims", "128", "64", "--dropout", "0.4", "--class-weight-power", "0.5", "--learning-rate", "1e-3", "--cooldown-bars", "5", "--threshold-min", "0.45", "--threshold-max", "0.55"]),
        ("ml4t_08", data_tol1, ["--hidden-dims", "64", "32", "--dropout", "0.25", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.50", "--threshold-max", "0.60"]),
        ("ml4t_09", data_tol0, ["--hidden-dims", "64", "32", "--dropout", "0.35", "--class-weight-power", "0.35", "--learning-rate", "5e-4", "--cooldown-bars", "5", "--threshold-min", "0.60", "--threshold-max", "0.65"]),
    ]
    configs = configs[:args.trials]

    rows = []
    for name, data_dir, extra in configs:
        try:
            out_dir, val_f1, oot_f1 = run_train(name, data_dir, extra, args.epochs)
            v = validate_trial(out_dir)
            score = composite_score(val_f1, oot_f1, v)
            tol = os.path.basename(data_dir).replace("prepared_tol", "")
            row = {"trial": name, "label_tol": tol, "data_dir": data_dir, "val_f1": val_f1, "oot_f1": oot_f1,
                   "hit_rate_bull": v["hit_rate_bull"], "hit_rate_bear": v["hit_rate_bear"],
                   "extra": v["extra"], "model_sigs": v["model_sigs"], "score": score, "params": " ".join(extra)}
            rows.append(row)
            print(f"{name}: val={val_f1} oot={oot_f1} hr_bull={v['hit_rate_bull']:.3f} hr_bear={v['hit_rate_bear']:.3f} sigs={v['model_sigs']} extra={v['extra']} score={score:.4f}")
        except Exception as e:
            print(f"Trial {name} failed: {e}", file=sys.stderr)

    summary_path = os.path.join(SEARCH_DIR, "experiments_summary.csv")
    if rows:
        df = pd.DataFrame(rows).sort_values("score", ascending=False)
        df.to_csv(summary_path, index=False)
        best_name = df.iloc[0]["trial"]
        best_dir = os.path.join(SEARCH_DIR, best_name)
        best_target = os.path.join(SEARCH_DIR, "best")
        if os.path.exists(best_target):
            shutil.rmtree(best_target)
        shutil.copytree(best_dir, best_target)
        print("Best trial:", best_name, "score:", df.iloc[0]["score"])

        # validation + charts for best
        cmd = [PY, EXTREMES, "--mode", "all", "--input-dir", RAW_DIR,
               "--output-dir", best_target, "--model-dir", best_target,
               "--tolerance-bars", "5", "--window-bars", "400"]
        subprocess.run(cmd, check=True)

        # comparison report
        def load_summary(d):
            p = os.path.join(d, "reports", "sma_validation_summary.csv")
            return pd.read_csv(p) if os.path.exists(p) else None
        opt01 = load_summary(os.path.join(HERE, "extremes_output"))
        sma5 = load_summary(os.path.join(HERE, "extremes_output_sma5"))
        best_v = validate_trial(best_target)

        report_path = os.path.join(SEARCH_DIR, "comparison_report.md")
        with open(report_path, "w") as f:
            f.write("# ML4T Experiment Strand – Vergleich\n\n")
            f.write("## Top-5 Experimente\n\n")
            f.write(df.head(5)[["trial", "label_tol", "val_f1", "oot_f1", "hit_rate_bull", "hit_rate_bear", "model_sigs", "extra", "score"]].to_markdown(index=False))
            f.write("\n\n## Bester Lauf\n\n")
            f.write(f"- Trial: {best_name}\n- Score: {df.iloc[0]['score']:.4f}\n- Dir: {best_target}\n")
            f.write(f"- Validierung/Charts: {best_target}/charts/ (inkl. AAPL_1Hour Bars 1600–1999)\n\n")
            if opt01 is not None:
                o = opt01
                o_tot = o["model_signals"].sum(); o_extra = o["extra_signals"].sum()
                o_hb = o["hits_bull"].sum(); o_mb = o["misses_bull"].sum()
                o_hr = o["hits_bear"].sum(); o_mr = o["misses_bear"].sum()
                f.write("## Vergleich vs. opt_01\n\n")
                f.write(f"- opt_01: Signale {o_tot}, Extra {o_extra}, Hit Bull {o_hb}/{o_hb+o_mb} ({o_hb/(o_hb+o_mb):.2f}), Hit Bear {o_hr}/{o_hr+o_mr} ({o_hr/(o_hr+o_mr):.2f})\n")
            if sma5 is not None:
                s = sma5
                s_tot = s["model_signals"].sum(); s_extra = s["extra_signals"].sum()
                s_hb = s["hits_bull"].sum(); s_mb = s["misses_bull"].sum()
                s_hr = s["hits_bear"].sum(); s_mr = s["misses_bear"].sum()
                f.write("## Vergleich vs. sma5_best\n\n")
                f.write(f"- sma5_best: Signale {s_tot}, Extra {s_extra}, Hit Bull {s_hb}/{s_hb+s_mb} ({(s_hb/(s_hb+s_mb) if s_hb+s_mb else 0):.2f}), Hit Bear {s_hr}/{s_hr+s_mr} ({(s_hr/(s_hr+s_mr) if s_hr+s_mr else 0):.2f})\n")
            f.write("## Bester ML4T-Lauf\n\n")
            f.write(f"- Signale {best_v['model_sigs']}, Extra {best_v['extra']}, Hit Bull {best_v['hits_bull']}/{best_v['hits_bull']+best_v['misses_bull']} ({best_v['hit_rate_bull']:.2f}), Hit Bear {best_v['hits_bear']}/{best_v['hits_bear']+best_v['misses_bear']} ({best_v['hit_rate_bear']:.2f})\n")
        print(f"Report saved: {report_path}")
        print("\nTop-5:")
        print(df.head(5)[["trial", "score", "val_f1", "oot_f1", "hit_rate_bull", "hit_rate_bear", "model_sigs", "extra"]].to_string(index=False))


if __name__ == "__main__":
    main()
