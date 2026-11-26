#!/usr/bin/env python3
"""compare_sma5_tool.py - Annotate/validate sma5 model and compare to opt_01."""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXTREMES = os.path.join(HERE, "extremes_tool.py")
PY = sys.executable

def run_extremes(model_dir, out_dir, min_conf, tol, window):
    if os.path.exists(os.path.join(out_dir, "reports", "sma_validation_summary.csv")):
        print(f"Using existing report: {out_dir}")
        return
    cmd = [PY, EXTREMES, "--mode", "all", "--input-dir", os.path.join(HERE, "raw_data"),
           "--output-dir", out_dir, "--model-dir", model_dir,
           "--min-confidence", str(min_conf), "--tolerance-bars", str(tol),
           "--window-bars", str(window)]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--opt01-dir", default=os.path.join(HERE, "extremes_output"))
    parser.add_argument("--sma5-dir", default=os.path.join(HERE, "extremes_output_sma5"))
    parser.add_argument("--opt01-model", default=os.path.join(HERE, "runs", "opt_01"))
    parser.add_argument("--sma5-model", default=os.path.join(HERE, "runs", "sma5_best"))
    parser.add_argument("--min-confidence", type=float, default=0.60)
    parser.add_argument("--tolerance-bars", type=int, default=5)
    parser.add_argument("--window-bars", type=int, default=400)
    args = parser.parse_args()

    run_extremes(args.opt01_model, args.opt01_dir, args.min_confidence, args.tolerance_bars, args.window_bars)
    run_extremes(args.sma5_model, args.sma5_dir, args.min_confidence, args.tolerance_bars, args.window_bars)

    import pandas as pd
    d0 = pd.read_csv(os.path.join(args.opt01_dir, "reports", "sma_validation_summary.csv"))
    d5 = pd.read_csv(os.path.join(args.sma5_dir, "reports", "sma_validation_summary.csv"))

    # aggregate by timeframe
    def agg(df):
        df = df.copy()
        df['tf'] = df['file'].str.extract(r'_([0-9]+(?:Min|Hour))_')
        g = df.groupby('tf').agg(
            files=('file','count'),
            segs=('segments_total','sum'),
            bull=('segments_bull','sum'),
            bear=('segments_bear','sum'),
            hits_bull=('hits_bull','sum'),
            misses_bull=('misses_bull','sum'),
            hits_bear=('hits_bear','sum'),
            misses_bear=('misses_bear','sum'),
            extra=('extra_signals','sum'),
            model_sigs=('model_signals','sum'),
        ).reset_index()
        g['hr_bull'] = g['hits_bull']/(g['hits_bull']+g['misses_bull'])
        g['hr_bear'] = g['hits_bear']/(g['hits_bear']+g['misses_bear'])
        return g

    a0 = agg(d0); a5 = agg(d5)

    lines = []
    lines.append("# Vergleich: sma5_best vs. opt_01 (SMA 38/80 Cross-Segment)\n")
    lines.append(f"Konfidenz >= {args.min_confidence}, Toleranz {args.tolerance_bars} Bars, Fenster {args.window_bars} Bars.\n")

    lines.append("## Gesamtübersicht nach Timeframe\n")
    lines.append("| Timeframe | Modell | Segmente (Bull/Bear) | Hit Bull (Rate) | Hit Bear (Rate) | Extra-Signale | Modell-Signale |")
    lines.append("|---|---|---|---|---|---|---|")
    for tf in ["5Min","15Min","1Hour"]:
        r0 = a0[a0['tf']==tf].iloc[0]
        r5 = a5[a5['tf']==tf].iloc[0]
        lines.append(f"| {tf} | opt_01 | {int(r0['segs'])} ({int(r0['bull'])}/{int(r0['bear'])}) | {int(r0['hits_bull'])}/{int(r0['hits_bull'])+int(r0['misses_bull'])} ({r0['hr_bull']:.2f}) | {int(r0['hits_bear'])}/{int(r0['hits_bear'])+int(r0['misses_bear'])} ({r0['hr_bear']:.2f}) | {int(r0['extra'])} | {int(r0['model_sigs'])} |")
        lines.append(f"| {tf} | sma5_best | {int(r5['segs'])} ({int(r5['bull'])}/{int(r5['bear'])}) | {int(r5['hits_bull'])}/{int(r5['hits_bull'])+int(r5['misses_bull'])} ({r5['hr_bull']:.2f}) | {int(r5['hits_bear'])}/{int(r5['hits_bear'])+int(r5['misses_bear'])} ({r5['hr_bear']:.2f}) | {int(r5['extra'])} | {int(r5['model_sigs'])} |")

    # overall
    def overall(df):
        return df['segments_total'].sum(), df['segments_bull'].sum(), df['segments_bear'].sum(), df['hits_bull'].sum(), df['misses_bull'].sum(), df['hits_bear'].sum(), df['misses_bear'].sum(), df['extra_signals'].sum(), df['model_signals'].sum()
    o0 = overall(d0); o5 = overall(d5)
    hr0_bull = o0[3]/(o0[3]+o0[4]); hr0_bear = o0[5]/(o0[5]+o0[6])
    hr5_bull = o5[3]/(o5[3]+o5[4]); hr5_bear = o5[5]/(o5[5]+o5[6])
    lines.append(f"| ALL | opt_01 | {o0[0]} ({o0[1]}/{o0[2]}) | {o0[3]}/{o0[3]+o0[4]} ({hr0_bull:.2f}) | {o0[5]}/{o0[5]+o0[6]} ({hr0_bear:.2f}) | {o0[7]} | {o0[8]} |")
    lines.append(f"| ALL | sma5_best | {o5[0]} ({o5[1]}/{o5[2]}) | {o5[3]}/{o5[3]+o5[4]} ({hr5_bull:.2f}) | {o5[5]}/{o5[5]+o5[6]} ({hr5_bear:.2f}) | {o5[7]} | {o5[8]} |")

    lines.append("\n## AAPL 1Hour – Bars 1600–1999\n")
    lines.append("Relevante Chart-Kacheln (Fenster 400):")
    lines.append(f"- opt_01: `{args.opt01_dir}/charts/AAPL_1Hour_tool_chart_005.png`")
    lines.append(f"- sma5_best: `{args.sma5_dir}/charts/AAPL_1Hour_tool_chart_005.png`\n")
    # per-file row for AAPL 1Hour
    row0 = d0[d0['file'].str.contains('AAPL_1Hour')].iloc[0]
    row5 = d5[d5['file'].str.contains('AAPL_1Hour')].iloc[0]
    lines.append("| Metrik | opt_01 | sma5_best |")
    lines.append("|---|---|---|")
    lines.append(f"| Segmente (Bull/Bear) | {int(row0['segments_total'])} ({int(row0['segments_bull'])}/{int(row0['segments_bear'])}) | {int(row5['segments_total'])} ({int(row5['segments_bull'])}/{int(row5['segments_bear'])}) |")
    lines.append(f"| Hit Bull | {int(row0['hits_bull'])}/{int(row0['hits_bull'])+int(row0['misses_bull'])} ({row0['hit_rate_bull']:.2f}) | {int(row5['hits_bull'])}/{int(row5['hits_bull'])+int(row5['misses_bull'])} ({row5['hit_rate_bull']:.2f}) |")
    lines.append(f"| Hit Bear | {int(row0['hits_bear'])}/{int(row0['hits_bear'])+int(row0['misses_bear'])} ({row0['hit_rate_bear']:.2f}) | {int(row5['hits_bear'])}/{int(row5['hits_bear'])+int(row5['misses_bear'])} ({row5['hit_rate_bear']:.2f}) |")
    lines.append(f"| Extra-Signale | {int(row0['extra_signals'])} | {int(row5['extra_signals'])} |")
    lines.append(f"| Modell-Signale | {int(row0['model_signals'])} | {int(row5['model_signals'])} |")

    lines.append("\n## Kurzfazit\n")
    lines.append("- opt_01 (Originalmodell) erzeugt mehr Signale und höhere Segment-Trefferquoten (besonders Bear).")
    lines.append("- sma5_best (5 ta-Indikatoren) ist deutlich sparsamer bei Signalen und hat niedrigere Trefferquoten auf SMA-Segment-Extreme; die Labels stammen aus denselben SMA-Cross-Segmenten, aber die Features sind indikatorbasiert und weniger direkt an Preisextrema gekoppelt.")
    lines.append("- Die Charts (Bars 1600–1999) zeigen für opt_01 mehr Modell-Dreiecke nahe Segment-Extrema; sma5_best markiert weniger Punkte mit größerem Versatz.")

    out_path = os.path.join(args.sma5_dir, "comparison_vs_opt01.md")
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Comparison report saved: {out_path}")

if __name__ == "__main__":
    main()
