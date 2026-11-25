#!/usr/bin/env python3
"""prepareTraining.py - Batch Feature & Label Generator (PRD)."""

import argparse
import glob
import os
import re
import sys

import numpy as np
import pandas as pd

try:
    import talib
except Exception as e:  # pragma: no cover
    print("TA-Lib is required:", e, file=sys.stderr)
    sys.exit(1)


def parse_args():
    p = argparse.ArgumentParser(description="Prepare training CSVs from raw market data.")
    p.add_argument("--input-dir", dest="input_dir", default="./raw_data",
                   help="Folder containing raw CSV files (default: ./raw_data)")
    p.add_argument("--output-dir", dest="output_dir", default="./prepared_data",
                   help="Folder for prepared CSV files (default: ./prepared_data)")
    p.add_argument("--pattern", default="*.csv",
                   help="Glob pattern for raw CSV files (default: *.csv)")
    p.add_argument("--window_left", type=int, default=6, help="Left window for swing detection")
    p.add_argument("--window_right", type=int, default=6, help="Right window for swing detection")
    p.add_argument("--min_move_atr", type=float, default=1.5, help="Min counter-move in ATR multiples")
    p.add_argument("--min_rel_volume", type=float, default=None,
                   help="Optional: minimum relative volume (feat_rel_volume) for a row to be kept")
    p.add_argument("--max_gap_minutes", type=float, default=None,
                   help="Optional: invalidate label windows crossing a gap larger than this many minutes")
    return p.parse_args()


def parse_ticker_timeframe(path):
    """Extract ticker and timeframe from a raw filename.

    Expected (prefix) form: <TICKER>_<TIMEFRAME>_tool[...].csv
    e.g. AAPL_5Min_tool.csv, AMZN_15Min_tool_202611212329.csv
    Falls back to (stem, "") for anything that does not match.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.match(r"^([^_]+)_([^_]+)_tool", stem)
    if m:
        return m.group(1), m.group(2)
    return stem, ""


def sort_and_dedup(df):
    if "t" not in df.columns:
        raise ValueError("Missing required column: t")
    t = df["t"]
    if pd.api.types.is_numeric_dtype(t):
        med = float(t.abs().median()) if len(t) else 0.0
        unit = "ms" if med > 1e11 else "s"
        key = pd.to_datetime(t, unit=unit, utc=True, errors="coerce")
    else:
        key = pd.to_datetime(t, utc=True, errors="coerce")
        if key.isna().all():
            key = pd.to_datetime(t, errors="coerce")

    valid = ~key.isna()
    if not valid.any():
        raise ValueError("No valid timestamps in column 't'")
    if not valid.all():
        df = df.loc[valid].copy()
        key = key.loc[valid]

    df = df.assign(_sort_key=key).sort_values("_sort_key", kind="mergesort").drop(columns="_sort_key")
    df = df.drop_duplicates(subset=["t"], keep="last").reset_index(drop=True)
    return df


def to_datetime_series(t):
    if pd.api.types.is_numeric_dtype(t):
        med = float(t.abs().median()) if len(t) else 0.0
        unit = "ms" if med > 1e11 else "s"
        return pd.to_datetime(t, unit=unit, utc=True, errors="coerce")
    out = pd.to_datetime(t, utc=True, errors="coerce")
    if out.isna().all():
        out = pd.to_datetime(t, errors="coerce")
    return out


def process_file(input_path, output_dir, args):
    ticker, timeframe = parse_ticker_timeframe(input_path)
    stem = os.path.splitext(os.path.basename(input_path))[0]

    df = pd.read_csv(input_path)
    required = ["t", "o", "h", "l", "c", "v", "vw"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    if df.empty:
        raise ValueError("Input file is empty")

    df = sort_and_dedup(df)

    o = df["o"].to_numpy(dtype=float)
    h = df["h"].to_numpy(dtype=float)
    l = df["l"].to_numpy(dtype=float)
    c = df["c"].to_numpy(dtype=float)
    v = df["v"].to_numpy(dtype=float)
    vw = df["vw"].to_numpy(dtype=float)
    n = len(df)

    if "RSI(21)" in df.columns and df["RSI(21)"].notna().any():
        rsi = df["RSI(21)"].to_numpy(dtype=float)
    else:
        rsi = talib.RSI(c, timeperiod=21)

    if "SMA(38)" in df.columns and df["SMA(38)"].notna().any():
        sma38 = df["SMA(38)"].to_numpy(dtype=float)
    else:
        sma38 = talib.SMA(c, timeperiod=38)

    if "SMA(80)" in df.columns and df["SMA(80)"].notna().any():
        sma80 = df["SMA(80)"].to_numpy(dtype=float)
    else:
        sma80 = talib.SMA(c, timeperiod=80)

    # CrossSMA: use provided column if present and valid, else compute from sma38/sma80
    use_provided_cross = False
    if "CrossSMA(38,80)" in df.columns:
        try:
            arr = df["CrossSMA(38,80)"].to_numpy(dtype=float)
            if np.isfinite(arr).any():
                use_provided_cross = True
                cross_sma = df["CrossSMA(38,80)"].to_numpy()
        except Exception:
            use_provided_cross = False
    if not use_provided_cross:
        cross_sma = np.zeros(n, dtype=int)
        diff = sma38 - sma80
        prev = np.roll(diff, 1)
        prev[0] = np.nan
        up_cross = (diff > 0) & (prev <= 0) & np.isfinite(diff) & np.isfinite(prev)
        down_cross = (diff < 0) & (prev >= 0) & np.isfinite(diff) & np.isfinite(prev)
        cross_sma[up_cross] = 1
        cross_sma[down_cross] = -1

    atr = talib.ATR(h, l, c, timeperiod=14)
    adx = talib.ADX(h, l, c, timeperiod=14)
    stoch_k, stoch_d = talib.STOCH(h, l, c)
    vol_sma20 = talib.SMA(v, timeperiod=20)

    feat_body_atr = (c - o) / atr
    feat_upper_wick_atr = (h - np.maximum(o, c)) / atr
    feat_lower_wick_atr = (np.minimum(o, c) - l) / atr
    feat_close_pos_in_candle = (c - l) / (h - l + 1e-8)

    feat_dist_sma38_atr = (c - sma38) / atr
    feat_dist_sma80_atr = (c - sma80) / atr
    feat_diff_sma38_80_atr = (sma38 - sma80) / atr
    feat_dist_vwap_atr = (c - vw) / atr

    sma38_shifted = np.roll(sma38, 3)
    sma38_shifted[:3] = np.nan
    feat_sma38_slope = (sma38 - sma38_shifted) / atr

    feat_rsi21 = rsi
    rsi_shifted = np.roll(rsi, 1)
    rsi_shifted[0] = np.nan
    feat_rsi21_diff = rsi - rsi_shifted

    feat_cross_sma = cross_sma
    feat_adx14 = adx
    feat_stoch_k = stoch_k
    feat_stoch_d = stoch_d
    feat_rel_volume = v / vol_sma20

    wl = args.window_left
    wr = args.window_right
    min_move = args.min_move_atr

    label_turn = np.zeros(n, dtype=float)
    label_max_move_atr = np.zeros(n, dtype=float)

    window_size = wl + wr + 1
    roll_max_h = pd.Series(h).rolling(window=window_size, center=True, min_periods=window_size).max().to_numpy()
    roll_min_l = pd.Series(l).rolling(window=window_size, center=True, min_periods=window_size).min().to_numpy()
    fut_min_low = pd.Series(l).rolling(window=wr, min_periods=wr).min().shift(-wr).to_numpy()
    fut_max_high = pd.Series(h).rolling(window=wr, min_periods=wr).max().shift(-wr).to_numpy()

    valid = np.isfinite(atr) & (atr != 0)
    valid_future = np.isfinite(fut_min_low) & np.isfinite(fut_max_high)

    # Optional gap filter: invalidate windows crossing a large time gap
    if args.max_gap_minutes is not None:
        t_dt = to_datetime_series(df["t"])
        if not t_dt.isna().all():
            deltas = t_dt.diff().dt.total_seconds().to_numpy() / 60.0
            gap_flag = np.zeros(n, dtype=bool)
            gap_flag[1:] = np.nan_to_num(deltas[1:], nan=0.0) > args.max_gap_minutes
            prefix = np.concatenate([[0], np.cumsum(gap_flag.astype(int))])
            idx = np.arange(n)
            left = idx - wl
            right = idx + wr
            full_window = (left >= 0) & (right < n)
            lc = np.clip(left, 0, n - 1)
            rc = np.clip(right, 0, n - 1)
            gap_in_window = (prefix[rc + 1] - prefix[lc + 1]) > 0
            gap_in_window = gap_in_window | (~full_window)
            valid_future = valid_future & (~gap_in_window)

    # Optional activity filter
    if args.min_rel_volume is not None:
        activity_ok = np.isfinite(feat_rel_volume) & (feat_rel_volume >= args.min_rel_volume)
        valid_future = valid_future & activity_ok

    drop = h - fut_min_low
    rise = fut_max_high - l

    high_mask = (h == roll_max_h) & (drop >= min_move * atr) & valid & valid_future
    low_mask = (l == roll_min_l) & (rise >= min_move * atr) & valid & valid_future

    # Resolve outside-bar conflicts: assign to side with larger counter-move (ATR units).
    conflict_mask = high_mask & low_mask
    high_wins = conflict_mask & ((drop / atr) > (rise / atr))
    low_wins = conflict_mask & ((rise / atr) > (drop / atr))
    high_mask = (high_mask & ~conflict_mask) | high_wins
    low_mask = (low_mask & ~conflict_mask) | low_wins

    label_turn[high_mask] = -1
    label_turn[low_mask] = 1

    label_max_move_atr[high_mask] = (drop / atr)[high_mask]
    label_max_move_atr[low_mask] = (rise / atr)[low_mask]

    neutral_mask = valid & valid_future & ~(high_mask | low_mask)
    up_move = (fut_max_high - l) / atr
    down_move = (h - fut_min_low) / atr
    neu_move = np.maximum(up_move, down_move)
    label_max_move_atr[neutral_mask] = neu_move[neutral_mask]

    # Drop incomplete tail rows (no full future window) by forcing NaN
    incomplete = ~valid_future
    label_turn[incomplete] = np.nan
    label_max_move_atr[incomplete] = np.nan

    out = pd.DataFrame({
        "meta_t": df["t"].values,
        "meta_ticker": [ticker] * n,
        "meta_timeframe": [timeframe] * n,
        "meta_open": o,
        "meta_high": h,
        "meta_low": l,
        "meta_close": c,
        "feat_body_atr": feat_body_atr,
        "feat_upper_wick_atr": feat_upper_wick_atr,
        "feat_lower_wick_atr": feat_lower_wick_atr,
        "feat_close_pos_in_candle": feat_close_pos_in_candle,
        "feat_dist_sma38_atr": feat_dist_sma38_atr,
        "feat_dist_sma80_atr": feat_dist_sma80_atr,
        "feat_diff_sma38_80_atr": feat_diff_sma38_80_atr,
        "feat_dist_vwap_atr": feat_dist_vwap_atr,
        "feat_sma38_slope": feat_sma38_slope,
        "feat_rsi21": feat_rsi21,
        "feat_rsi21_diff": feat_rsi21_diff,
        "feat_cross_sma": feat_cross_sma,
        "feat_adx14": feat_adx14,
        "feat_stoch_k": feat_stoch_k,
        "feat_stoch_d": feat_stoch_d,
        "feat_rel_volume": feat_rel_volume,
        "label_turn": label_turn,
        "label_max_move_atr": label_max_move_atr,
    })

    feat_cols = [c for c in out.columns if c.startswith("feat_")]
    out = out.replace([np.inf, -np.inf], np.nan)
    out = out.dropna(subset=feat_cols + ["label_turn", "label_max_move_atr"]).reset_index(drop=True)
    if out.empty:
        raise ValueError("No rows left after warmup/labeling/NaN cleanup")
    out["label_turn"] = out["label_turn"].astype(int)

    os.makedirs(output_dir, exist_ok=True)
    output_name = f"{stem}_prepared.csv"
    output_path = os.path.join(output_dir, output_name)
    out.to_csv(output_path, index=False)

    return {
        "input": os.path.basename(input_path),
        "output": output_name,
        "ticker": ticker,
        "timeframe": timeframe,
        "rows": len(out),
    }


def main():
    args = parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir

    if not os.path.isdir(input_dir):
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    candidates = sorted(glob.glob(os.path.join(input_dir, args.pattern)))
    files = []
    for p in candidates:
        if not os.path.isfile(p):
            continue
        base = os.path.basename(p)
        # Never re-ingest already prepared outputs.
        if base.endswith("_prepared.csv"):
            continue
        files.append(p)

    if not files:
        print(f"No matching CSV files found in: {input_dir} (pattern: {args.pattern})", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(files)} raw CSV file(s) in {input_dir}")

    processed = []
    skipped = []
    total_rows = 0
    label_counts = {-1: 0, 0: 0, 1: 0}

    for path in files:
        try:
            info = process_file(path, output_dir, args)
        except Exception as e:
            print(f"SKIP {os.path.basename(path)}: {e}", file=sys.stderr)
            skipped.append((os.path.basename(path), str(e)))
            continue

        processed.append(info)
        total_rows += info["rows"]

        # Accumulate label distribution from the written file.
        try:
            out_df = pd.read_csv(os.path.join(output_dir, info["output"]))
            vc = out_df["label_turn"].value_counts().to_dict()
            for k in (-1, 0, 1):
                label_counts[k] += int(vc.get(k, 0))
        except Exception:
            pass

        print(f"OK   {info['input']} -> {info['output']} | ticker={info['ticker']} | timeframe={info['timeframe']} | rows={info['rows']}")

    print()
    print("Batch summary")
    print(f"  Found files:      {len(files)}")
    print(f"  Processed files:  {len(processed)}")
    print(f"  Skipped files:    {len(skipped)}")
    if skipped:
        print("  Skipped details:")
        for name, err in skipped:
            print(f"    - {name}: {err}")
    print(f"  Total rows:       {total_rows}")
    print("  label_turn distribution (all outputs):")
    for k in (-1, 0, 1):
        print(f"    {k}: {label_counts[k]}")
    print("  Per-file rows:")
    for info in processed:
        print(f"    {info['output']} | ticker={info['ticker']} | timeframe={info['timeframe']} | rows={info['rows']}")

    # Batch processing completed; individual file failures were already reported above.


if __name__ == "__main__":
    main()
