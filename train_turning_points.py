#!/usr/bin/env python3
"""train_turning_points.py - Standalone training/evaluation for turning-point classification."""

import argparse
import glob
import os
import re
import sys
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import classification_report, confusion_matrix, precision_recall_fscore_support
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)
torch.manual_seed(RANDOM_SEED)


def parse_args():
    p = argparse.ArgumentParser(description="Train/evaluate turning-point model on prepared CSVs.")
    p.add_argument("--input-dir", dest="input_dir", default="./prepared_data")
    p.add_argument("--output-dir", dest="output_dir", default="./runs/latest")
    p.add_argument("--out-of-tickers", nargs="*", default=[])
    p.add_argument("--train-frac", type=float, default=0.70)
    p.add_argument("--val-frac", type=float, default=0.15)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--learning-rate", type=float, default=5e-4)
    p.add_argument("--weight-decay", type=float, default=5e-4)
    p.add_argument("--dropout", type=float, default=0.35)
    p.add_argument("--hidden-dims", nargs="*", type=int, default=[64, 32])
    p.add_argument("--patience", type=int, default=10)
    p.add_argument("--class-weight-power", type=float, default=0.35)
    p.add_argument("--label-smoothing", type=float, default=0.05)
    p.add_argument("--cooldown-bars", type=int, default=5)
    p.add_argument("--purge-minutes", type=float, default=0.0,
                   help="Optional purge window (minutes) around split boundaries to reduce label leakage")
    p.add_argument("--use-move-atr-weighting", action="store_true", default=True)
    return p.parse_args()


def set_seed(seed=42):
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def parse_ticker_timeframe_from_name(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.match(r"^([^_]+)_([^_]+)_tool", stem)
    if m:
        return m.group(1), m.group(2)
    return stem, ""


def load_prepared(input_dir):
    files = sorted(glob.glob(os.path.join(input_dir, "*_prepared.csv")))
    if not files:
        files = sorted(glob.glob(os.path.join(input_dir, "*.csv")))
    if not files:
        raise FileNotFoundError(f"No prepared CSV files found in {input_dir}")

    frames = []
    for path in files:
        df = pd.read_csv(path)
        if "meta_ticker" not in df.columns or df["meta_ticker"].isna().all():
            t, tf = parse_ticker_timeframe_from_name(path)
            df["meta_ticker"] = t
        if "meta_timeframe" not in df.columns or df["meta_timeframe"].isna().all():
            t, tf = parse_ticker_timeframe_from_name(path)
            df["meta_timeframe"] = tf
        if "ticker_source" not in df.columns:
            df["ticker_source"] = os.path.splitext(os.path.basename(path))[0]
        # Parse meta_t as UTC datetime
        df["meta_t"] = pd.to_datetime(df["meta_t"], utc=True, errors="coerce")
        if df["meta_t"].isna().all():
            df["meta_t"] = pd.to_datetime(df["meta_t"], errors="coerce")
        frames.append(df)

    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["meta_t"]).reset_index(drop=True)
    return out, files


def summarize_split(name, df):
    if df.empty:
        return f"{name}: 0 rows"
    vc = df["label_turn"].value_counts().to_dict()
    return (f"{name}: rows={len(df)} | time={df['meta_t'].min()} .. {df['meta_t'].max()} | "
            f"label_turn: -1={vc.get(-1, 0)}, 0={vc.get(0, 0)}, 1={vc.get(1, 0)}")


class TurningPointMLP(nn.Module):
    def __init__(self, in_features, hidden_dims, dropout=0.35, num_classes=3):
        super().__init__()
        layers = []
        prev = in_features
        for h in hidden_dims:
            layers.extend([nn.Linear(prev, h), nn.BatchNorm1d(h), nn.SiLU(), nn.Dropout(dropout)])
            prev = h
        layers.append(nn.Linear(prev, num_classes))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


def suppress_signal_clusters(probs, threshold, cooldown_bars=5):
    n = len(probs)
    raw = np.ones(n, dtype=int)
    high_mask = probs[:, 0] >= threshold
    low_mask = probs[:, 2] >= threshold
    both = high_mask & low_mask
    high_mask = high_mask & (~both | (probs[:, 0] >= probs[:, 2]))
    low_mask = low_mask & (~both | (probs[:, 2] > probs[:, 0]))
    raw[high_mask] = 0
    raw[low_mask] = 2

    filtered = raw.copy()
    for cls in (0, 2):
        cand = np.where(raw == cls)[0]
        order = cand[np.argsort(probs[cand, cls])[::-1]]
        kept = []
        for idx in order:
            if all(abs(idx - k) >= cooldown_bars for k in kept):
                kept.append(idx)
            else:
                filtered[idx] = 1
    return filtered


def turn_metrics(y_true, y_pred):
    prec, rec, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=[0, 2], average="macro", zero_division=0
    )
    return prec, rec, f1


def evaluate_by_timeframe(df, probs, threshold, cooldown):
    results = {}
    for tf, sub in df.groupby("meta_timeframe"):
        idx = sub.index.to_numpy()
        # map back to positional indices in df order
    # We'll handle via positional arrays instead
    return results


def main():
    args = parse_args()
    set_seed(RANDOM_SEED)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    os.makedirs(args.output_dir, exist_ok=True)
    log_path = os.path.join(args.output_dir, "training_run.log")
    log_file = open(log_path, "w", encoding="utf-8")

    def log(msg=""):
        print(msg)
        log_file.write(str(msg) + "\n")
        log_file.flush()

    df, files = load_prepared(args.input_dir)
    feature_cols = [c for c in df.columns if c.startswith("feat_")]
    if not feature_cols:
        raise ValueError("No feat_* columns found.")
    required_labels = ["label_turn", "label_max_move_atr"]
    for col in required_labels:
        if col not in df.columns:
            raise ValueError(f"Missing required label column: {col}")

    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=feature_cols + required_labels).reset_index(drop=True)
    df["target_idx"] = df["label_turn"].astype(int).map({-1: 0, 0: 1, 1: 2})

    log(f"Loaded {len(files)} files, {len(df)} rows")
    log(f"Features ({len(feature_cols)}): {feature_cols}")

    # Out-of-ticker split
    oot_mask = df["meta_ticker"].isin(args.out_of_tickers)
    df_oot = df[oot_mask].copy().reset_index(drop=True)
    df_rest = df[~oot_mask].copy().reset_index(drop=True)

    # Time-based split over meta_t for remaining tickers
    if df_rest.empty:
        raise ValueError("No in-ticker data after out-of-ticker removal.")
    unique_times = np.sort(df_rest["meta_t"].unique())
    train_pos = int(len(unique_times) * args.train_frac)
    val_pos = int(len(unique_times) * (args.train_frac + args.val_frac))
    train_cutoff = unique_times[max(train_pos - 1, 0)]
    val_cutoff = unique_times[max(val_pos - 1, 0)]

    purge = pd.Timedelta(minutes=args.purge_minutes)
    train_mask = df_rest["meta_t"] <= (train_cutoff - purge)
    val_mask = (df_rest["meta_t"] > (train_cutoff + purge)) & (df_rest["meta_t"] <= (val_cutoff - purge))
    test_mask = df_rest["meta_t"] > (val_cutoff + purge)

    df_train = df_rest[train_mask].copy().reset_index(drop=True)
    df_val = df_rest[val_mask].copy().reset_index(drop=True)
    df_test = df_rest[test_mask].copy().reset_index(drop=True)

    log("\nSplit summary:")
    log(summarize_split("train", df_train))
    log(summarize_split("val", df_val))
    log(summarize_split("test", df_test))
    log(summarize_split("out_of_ticker", df_oot))

    # Scaling
    scaler = StandardScaler()
    X_train = scaler.fit_transform(df_train[feature_cols].to_numpy(dtype=np.float32))
    X_val = scaler.transform(df_val[feature_cols].to_numpy(dtype=np.float32))
    X_test = scaler.transform(df_test[feature_cols].to_numpy(dtype=np.float32))
    X_oot = scaler.transform(df_oot[feature_cols].to_numpy(dtype=np.float32)) if len(df_oot) else np.empty((0, len(feature_cols)), dtype=np.float32)

    y_train = df_train["target_idx"].to_numpy(dtype=np.int64)
    y_val = df_val["target_idx"].to_numpy(dtype=np.int64)
    y_test = df_test["target_idx"].to_numpy(dtype=np.int64)
    y_oot = df_oot["target_idx"].to_numpy(dtype=np.int64) if len(df_oot) else np.array([], dtype=np.int64)

    # Sample weights
    w_train = np.ones(len(df_train), dtype=np.float32)
    if args.use_move_atr_weighting:
        turn_mask = df_train["label_turn"].to_numpy() != 0
        move_atr = df_train["label_max_move_atr"].to_numpy(dtype=np.float32)
        w_train[turn_mask] = np.clip(move_atr[turn_mask] / 1.5, 1.0, 2.5)

    train_ds = TensorDataset(torch.tensor(X_train), torch.tensor(y_train), torch.tensor(w_train))
    val_ds = TensorDataset(torch.tensor(X_val), torch.tensor(y_val))
    test_ds = TensorDataset(torch.tensor(X_test), torch.tensor(y_test))
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size * 2, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size * 2, shuffle=False)

    # Class weights
    class_counts = np.bincount(y_train, minlength=3)
    raw_weights = len(y_train) / (3.0 * np.maximum(class_counts, 1))
    class_weights = np.power(raw_weights, args.class_weight_power)
    class_weights_tensor = torch.tensor(class_weights, dtype=torch.float32, device=device)

    model = TurningPointMLP(
        in_features=len(feature_cols),
        hidden_dims=args.hidden_dims,
        dropout=args.dropout,
        num_classes=3,
    ).to(device)

    criterion = nn.CrossEntropyLoss(weight=class_weights_tensor, reduction="none", label_smoothing=args.label_smoothing)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=4)

    def predict_proba(loader):
        model.eval()
        all_probs, all_targets = [], []
        with torch.no_grad():
            for batch in loader:
                xb = batch[0].to(device)
                logits = model(xb)
                probs = torch.softmax(logits, dim=-1).cpu().numpy()
                all_probs.append(probs)
                all_targets.append(batch[1].numpy())
        if not all_probs:
            return np.empty((0, 3)), np.array([], dtype=np.int64)
        return np.vstack(all_probs), np.concatenate(all_targets)

    best_val_f1 = -1.0
    best_state = None
    epochs_no_improve = 0
    history = {"train_loss": [], "val_turn_f1": []}

    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0
        total_samples = 0
        for xb, yb, wb in train_loader:
            xb, yb, wb = xb.to(device), yb.to(device), wb.to(device)
            optimizer.zero_grad()
            logits = model(xb)
            per_sample_loss = criterion(logits, yb)
            loss = (per_sample_loss * wb).mean()
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * len(yb)
            total_samples += len(yb)
        train_loss = running_loss / max(total_samples, 1)

        val_probs, val_true = predict_proba(val_loader)
        val_pred = val_probs.argmax(axis=1) if len(val_probs) else np.array([])
        prec, rec, f1 = turn_metrics(val_true, val_pred) if len(val_true) else (0.0, 0.0, 0.0)
        scheduler.step(f1)
        history["train_loss"].append(train_loss)
        history["val_turn_f1"].append(f1)

        if f1 > best_val_f1:
            best_val_f1 = f1
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1

        if epoch % 5 == 0 or epoch == 1:
            log(f"Epoch {epoch:02d}/{args.epochs} | Train Loss: {train_loss:.4f} | Val Turn-F1: {f1:.3f}")

        if epochs_no_improve >= args.patience:
            log(f"Early stopping in epoch {epoch} (best Val Turn-F1: {best_val_f1:.3f})")
            break

    if best_state is not None:
        model.load_state_dict(best_state)

    # Threshold tuning on validation
    val_probs, val_true = predict_proba(val_loader)
    thresholds = np.arange(0.40, 0.81, 0.05)
    results = []
    for thresh in thresholds:
        if len(val_probs) == 0:
            break
        filt_pred = suppress_signal_clusters(val_probs, thresh, cooldown_bars=args.cooldown_bars)
        fp, fr, ff = turn_metrics(val_true, filt_pred)
        results.append((thresh, fp, fr, ff, int((filt_pred != 1).sum())))
    if results:
        best = max(results, key=lambda r: r[3])
        best_threshold = float(best[0])
    else:
        best_threshold = 0.50
    log(f"\nSelected BEST_THRESHOLD: {best_threshold:.2f}")

    # Evaluate test
    test_probs, test_true = predict_proba(test_loader)
    test_pred_idx = suppress_signal_clusters(test_probs, best_threshold, cooldown_bars=args.cooldown_bars) if len(test_probs) else np.array([])
    test_pred_turn = np.where(test_pred_idx == 0, -1, np.where(test_pred_idx == 2, 1, 0))
    log("\n=== Test evaluation (MLP, filtered) ===")
    if len(test_true):
        tp, tr, tf1 = turn_metrics(test_true, test_pred_idx)
        log(f"Overall Turn Precision/Recall/F1: {tp:.3f}/{tr:.3f}/{tf1:.3f}")
        log(classification_report(test_true, test_pred_idx, target_names=["Extrem-Hoch", "Neutral", "Extrem-Tief"], digits=3, zero_division=0))

    # Evaluate by timeframe on test
    log("\nTest metrics by meta_timeframe:")
    for tf, sub in df_test.groupby("meta_timeframe"):
        # positional indices in df_test
        mask = (df_test["meta_timeframe"] == tf).to_numpy()
        if not mask.any():
            continue
        sub_probs = test_probs[mask]
        sub_pred = suppress_signal_clusters(sub_probs, best_threshold, cooldown_bars=args.cooldown_bars) if len(sub_probs) else np.array([])
        sub_true = df_test.loc[mask, "target_idx"].to_numpy()
        p, r, f1 = turn_metrics(sub_true, sub_pred) if len(sub_true) else (0.0, 0.0, 0.0)
        log(f"  {tf}: n={mask.sum()} | Turn P/R/F1 = {p:.3f}/{r:.3f}/{f1:.3f} | signals={(sub_pred != 1).sum()}")

    # OOT
    oot_probs = np.empty((0, 3))
    oot_pred_idx = np.array([])
    if len(df_oot):
        oot_loader = DataLoader(TensorDataset(torch.tensor(X_oot), torch.tensor(y_oot)), batch_size=args.batch_size * 2)
        oot_probs, oot_true = predict_proba(oot_loader)
        oot_pred_idx = suppress_signal_clusters(oot_probs, best_threshold, cooldown_bars=args.cooldown_bars) if len(oot_probs) else np.array([])
        oot_pred_turn = np.where(oot_pred_idx == 0, -1, np.where(oot_pred_idx == 2, 1, 0))
        log("\n=== Out-of-ticker evaluation (MLP, filtered) ===")
        tp, tr, tf1 = turn_metrics(oot_true, oot_pred_idx)
        log(f"Overall Turn Precision/Recall/F1: {tp:.3f}/{tr:.3f}/{tf1:.3f}")
        log("Out-of-ticker metrics by meta_timeframe:")
        for tf, sub in df_oot.groupby("meta_timeframe"):
            mask = (df_oot["meta_timeframe"] == tf).to_numpy()
            sub_probs = oot_probs[mask]
            sub_pred = suppress_signal_clusters(sub_probs, best_threshold, cooldown_bars=args.cooldown_bars) if len(sub_probs) else np.array([])
            sub_true = df_oot.loc[mask, "target_idx"].to_numpy()
            p, r, f1 = turn_metrics(sub_true, sub_pred) if len(sub_true) else (0.0, 0.0, 0.0)
            log(f"  {tf}: n={mask.sum()} | Turn P/R/F1 = {p:.3f}/{r:.3f}/{f1:.3f} | signals={(sub_pred != 1).sum()}")

    # HGB benchmark
    try:
        hgb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, l2_regularization=1.0, random_state=42)
        hgb.fit(X_train, y_train)
        hgb_test_proba = hgb.predict_proba(X_test)
        # pad to 3 columns
        if hgb_test_proba.shape[1] != 3:
            padded = np.zeros((len(hgb_test_proba), 3))
            for i, cls in enumerate(hgb.classes_):
                padded[:, int(cls)] = hgb_test_proba[:, i]
            hgb_test_proba = padded
        hgb_pred = suppress_signal_clusters(hgb_test_proba, best_threshold, cooldown_bars=args.cooldown_bars) if len(hgb_test_proba) else np.array([])
        hp, hr, hf1 = turn_metrics(y_test, hgb_pred) if len(y_test) else (0.0, 0.0, 0.0)
        log(f"\nHGB benchmark Test Turn P/R/F1: {hp:.3f}/{hr:.3f}/{hf1:.3f}")
    except Exception as e:
        log(f"HGB benchmark skipped: {e}")

    # Save predictions
    def build_prediction_frame(df_src, probs, pred_idx):
        # recompute raw with cooldown 1 for raw_pred
        raw = suppress_signal_clusters(probs, best_threshold, cooldown_bars=1) if len(probs) else np.array([])
        filt = pred_idx if len(pred_idx) else np.array([])
        out = pd.DataFrame({
            "ticker_source": df_src["ticker_source"].to_numpy(),
            "meta_t": df_src["meta_t"].to_numpy(),
            "meta_ticker": df_src["meta_ticker"].to_numpy(),
            "meta_timeframe": df_src["meta_timeframe"].to_numpy(),
            "meta_close": df_src["meta_close"].to_numpy(),
            "label_turn": df_src["label_turn"].to_numpy(),
            "label_max_move_atr": df_src["label_max_move_atr"].to_numpy(),
        })
        if len(probs):
            out["prob_high"] = probs[:, 0]
            out["prob_neutral"] = probs[:, 1]
            out["prob_low"] = probs[:, 2]
        else:
            out["prob_high"] = np.nan
            out["prob_neutral"] = np.nan
            out["prob_low"] = np.nan
        idx_to_turn = {0: -1, 1: 0, 2: 1}
        out["raw_pred_turn"] = [idx_to_turn.get(int(i), 0) for i in raw] if len(raw) else [0] * len(out)
        out["filtered_pred_turn"] = [idx_to_turn.get(int(i), 0) for i in filt] if len(filt) else [0] * len(out)
        return out

    test_pred_df = build_prediction_frame(df_test, test_probs, test_pred_idx)
    test_pred_df.to_csv(os.path.join(args.output_dir, "predictions_test.csv"), index=False)
    log(f"Saved predictions_test.csv ({len(test_pred_df)} rows)")

    if len(df_oot):
        oot_pred_df = build_prediction_frame(df_oot, oot_probs, oot_pred_idx)
        oot_pred_df.to_csv(os.path.join(args.output_dir, "predictions_oot.csv"), index=False)
        log(f"Saved predictions_oot.csv ({len(oot_pred_df)} rows)")

    # Save model and scaler
    torch.save({
        "model_state_dict": model.state_dict(),
        "feature_cols": feature_cols,
        "hidden_dims": args.hidden_dims,
        "dropout": args.dropout,
        "best_threshold": best_threshold,
        "cooldown_bars": args.cooldown_bars,
    }, os.path.join(args.output_dir, "turning_point_mlp.pt"))
    joblib.dump(scaler, os.path.join(args.output_dir, "feature_scaler.joblib"))

    log(f"\nArtifacts saved to {args.output_dir}")
    log(f"Run log: {log_path}")
    log_file.close()


if __name__ == "__main__":
    main()
