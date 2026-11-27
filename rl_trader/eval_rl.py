#!/usr/bin/env python3
"""eval_rl.py - Evaluate a trained PPO agent against simple baselines.

Baselines
---------
1. ``blind``    : trade every ``filtered_pred`` signal (long on +1, short on -1)
2. ``high_conf``: same, but only signals with confidence >= --high-conf
3. ``flat``     : never trade (capital preservation reference)

Splits
------
* ``val``  : last 15% of each non-AAPL series (chronological)
* ``test`` : final 15% of each non-AAPL series
* ``oot``  : all AAPL series (out-of-ticker holdout, never seen in training)

Artifacts are written to ``rl_trader/runs/<run-name>/eval/``:
    eval_metrics.json, eval_report.md, per_series_metrics.csv,
    trades_<split>_<method>.csv, equity_<split>.png, drawdown_<split>.png
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time
from typing import Callable, Dict, List, Sequence

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from env import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    KOTradingEnv,
    TradingEnv,
    build_pools,
    build_series,
    resolve_timeframes,
)
from train_rl import PPOAgent, PPOConfig  # noqa: E402

RUNS_DIR = os.path.join(HERE, "runs")


# ---------------------------------------------------------------------------
# Checkpoint loading
# ---------------------------------------------------------------------------
def _safe_load_torch(path: str):
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:  # older torch
        return torch.load(path, map_location="cpu")


def load_agent(run_dir: str, device: str = "cpu") -> PPOAgent:
    ckpt = _safe_load_torch(os.path.join(run_dir, "checkpoint.pt"))
    agent = PPOAgent(ckpt["obs_dim"], ckpt.get("n_actions", 4),
                     cfg=PPOConfig(), device=device, seed=0)
    agent.model.load_state_dict(ckpt["model_state_dict"])
    agent.model.eval()
    return agent, ckpt


def latest_run() -> str:
    runs = sorted(glob.glob(os.path.join(RUNS_DIR, "*", "checkpoint.pt")),
                  key=os.path.getmtime)
    if not runs:
        raise FileNotFoundError("No checkpoint found under rl_trader/runs/")
    return os.path.dirname(runs[-1])


# ---------------------------------------------------------------------------
# Episode execution
# ---------------------------------------------------------------------------
def run_episode(env: TradingEnv, action_fn: Callable) -> dict:
    obs, _ = env.reset()
    done = False
    while not done:
        action = int(action_fn(env, obs))
        obs, _reward, done, _trunc, _info = env.step(action)
    return env_result(env)


def env_result(env: TradingEnv) -> dict:
    eq = np.asarray(env.equity_curve, dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = 1.0 - eq / np.maximum(peak, 1e-12)
    step_ret = np.diff(eq) / np.maximum(eq[:-1], 1e-12)
    trades = env.trade_log
    trade_rets = np.array([t["net_return"] for t in trades], dtype=float)
    holding = np.array([t["holding_bars"] for t in trades], dtype=float)
    return {
        "ticker": env.series.ticker,
        "timeframe": env.series.timeframe,
        "total_return": float(eq[-1] - 1.0),
        "max_drawdown": float(dd.max()) if len(dd) else 0.0,
        "sharpe": float(step_ret.mean() / (step_ret.std() + 1e-12) * np.sqrt(len(step_ret)))
        if len(step_ret) > 1 else 0.0,
        "trade_count": int(len(trades)),
        "win_rate": float((trade_rets > 0).mean()) if len(trade_rets) else 0.0,
        "avg_holding_bars": float(holding.mean()) if len(holding) else 0.0,
        "avg_trade_return": float(trade_rets.mean()) if len(trade_rets) else 0.0,
        "signals_total": int(env.total_signals),
        "signals_used": int(env.signals_used),
        "signals_ignored": int(env.signals_ignored),
        "standalone_trades": int(env.standalone_trades),
        "equity_curve": eq,
        "drawdown_curve": dd,
        "trades": trades,
    }


# ---------------------------------------------------------------------------
# KO episode execution / metrics
# ---------------------------------------------------------------------------
def run_ko_episode(env: KOTradingEnv, action_fn: Callable) -> dict:
    obs, _ = env.reset()
    done = False
    while not done:
        action = int(action_fn(env, obs))
        obs, _reward, done, _trunc, _info = env.step(action)
    return ko_env_result(env)


def ko_env_result(env: KOTradingEnv) -> dict:
    eq = np.asarray(env.equity_curve, dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = 1.0 - eq / np.maximum(peak, 1e-9)
    step_ret = np.diff(eq) / np.maximum(eq[:-1], 1e-9)
    trades = env.trade_log
    net = np.array([t["net_pnl_usd"] for t in trades], dtype=float)
    gross = np.array([t["gross_pnl_usd"] for t in trades], dtype=float)
    fees = np.array([t["fees_usd"] for t in trades], dtype=float)
    holding = np.array([t["holding_bars"] for t in trades], dtype=float)
    stakes = np.array([t["stake_usd"] for t in trades], dtype=float)
    ko_trades = [t for t in trades if t["knockout"]]
    partials = [t for t in trades if t.get("partial_done", False)]
    total_gross = float(gross.sum()) if len(gross) else 0.0
    total_fees = float(fees.sum()) if len(fees) else 0.0
    total_net = float(net.sum()) if len(net) else 0.0
    fee_to_gross = (total_fees / abs(total_gross)) if abs(total_gross) > 1e-9 else (
        0.0 if total_fees == 0 else float("inf")
    )
    reason_counts: Dict[str, int] = {}
    reason_holds: Dict[str, List[int]] = {}
    for t in trades:
        r = t["exit_reason"]
        reason_counts[r] = reason_counts.get(r, 0) + 1
        reason_holds.setdefault(r, []).append(int(t["holding_bars"]))
    avg_hold_by_reason = {r: float(np.mean(v)) for r, v in reason_holds.items()}
    close_count = reason_counts.get("close", 0)
    eod_count = reason_counts.get("eod", 0)
    target_reasons = ("mean_revert", "sma_cross", "max_hold")
    target_count = sum(reason_counts.get(r, 0) for r in target_reasons)
    close_holds = [h for r in ("close", "eod") for h in reason_holds.get(r, [])]
    target_holds = [h for r in target_reasons for h in reason_holds.get(r, [])]
    ko_holds = reason_holds.get("knockout", [])
    cert_stats = []
    for i, lev in enumerate(env.cert_leverages):
        ts = [t for t in trades if t["cert_idx"] == i]
        if not ts:
            cert_stats.append({"cert_idx": i, "leverage": float(lev), "trades": 0,
                               "wins": 0, "kos": 0, "win_rate": 0.0,
                               "avg_net_usd": 0.0, "avg_holding_bars": 0.0,
                               "fees_usd": 0.0, "share": 0.0})
            continue
        nets = np.array([t["net_pnl_usd"] for t in ts], dtype=float)
        cert_stats.append({
            "cert_idx": i,
            "leverage": float(lev),
            "trades": len(ts),
            "wins": int((nets > 0).sum()),
            "kos": int(sum(1 for t in ts if t["knockout"])),
            "win_rate": float((nets > 0).mean()),
            "avg_net_usd": float(nets.mean()),
            "avg_holding_bars": float(np.mean([t["holding_bars"] for t in ts])),
            "fees_usd": float(sum(t["fees_usd"] for t in ts)),
            "share": float(len(ts) / max(1, len(trades))),
        })
    mr_ratios = np.array([t.get("entry_mr_ratio", 0.0) for t in trades], dtype=float) \
        if trades else np.array([])
    return {
        "ticker": env.series.ticker,
        "timeframe": env.series.timeframe,
        "total_return": float(eq[-1] / max(env.initial_cash, 1e-9) - 1.0),
        "max_drawdown": float(dd.max()) if len(dd) else 0.0,
        "sharpe": float(step_ret.mean() / (step_ret.std() + 1e-12) * np.sqrt(len(step_ret)))
        if len(step_ret) > 1 else 0.0,
        "trade_count": int(len(trades)),
        "win_rate": float((net > 0).mean()) if len(net) else 0.0,
        "avg_holding_bars": float(holding.mean()) if len(holding) else 0.0,
        "avg_trade_usd": float(net.mean()) if len(net) else 0.0,
        "gross_pnl_usd": total_gross,
        "fees_usd": total_fees,
        "net_pnl_usd": total_net,
        "fee_to_gross": float(fee_to_gross),
        "ko_count": int(len(ko_trades)),
        "ko_rate": float(len(ko_trades) / len(trades)) if trades else 0.0,
        "ko_loss_usd": float(-sum(t["gross_pnl_usd"] for t in ko_trades)),
        "partial_count": int(len(partials)),
        "partial_rate": float(len(partials) / len(trades)) if trades else 0.0,
        "avg_partial_holding_bars": float(np.mean([t.get("partial_holding_bars", 0)
                                                   for t in partials])) if partials else 0.0,
        "avg_mr_ko_ratio": float(mr_ratios.mean()) if len(mr_ratios) else 0.0,
        "median_mr_ko_ratio": float(np.median(mr_ratios)) if len(mr_ratios) else 0.0,
        "min_mr_ko_ratio": float(mr_ratios.min()) if len(mr_ratios) else 0.0,
        "max_mr_ko_ratio": float(mr_ratios.max()) if len(mr_ratios) else 0.0,
        "close_count": int(close_count),
        "eod_count": int(eod_count),
        "target_exit_count": int(target_count),
        "sma_cross_count": int(reason_counts.get("sma_cross", 0)),
        "mean_revert_count": int(reason_counts.get("mean_revert", 0)),
        "max_hold_count": int(reason_counts.get("max_hold", 0)),
        "exit_reason_counts": reason_counts,
        "avg_holding_by_exit": avg_hold_by_reason,
        "avg_holding_close": float(np.mean(close_holds)) if close_holds else 0.0,
        "avg_holding_ko": float(np.mean(ko_holds)) if ko_holds else 0.0,
        "avg_holding_target": float(np.mean(target_holds)) if target_holds else 0.0,
        "cert_stats": cert_stats,
        "cert_counts": list(env.cert_entry_counts),
        "size_counts": list(env.size_entry_counts),
        "avg_stake_usd": float(stakes.mean()) if len(stakes) else 0.0,
        "filtered_entries": int(env.filtered_entries),
        "regime_filtered": int(env.regime_filtered),
        "signals_total": int(env.total_signals),
        "signals_used": int(env.signals_used),
        "signals_ignored": int(env.signals_ignored),
        "standalone_trades": int(env.standalone_trades),
        "equity_curve": eq,
        "equity_curve_norm": eq / max(env.initial_cash, 1e-9),
        "drawdown_curve": dd,
        "trades": trades,
    }


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------
def make_signal_policy(high_conf: float = 0.0) -> Callable:
    def policy(env: TradingEnv, _obs):
        sig = env.current_signal()
        if sig == 0:
            return 0  # hold current position
        if high_conf > 0 and env.current_signal_conf() < high_conf:
            return 0
        return 1 if sig > 0 else 2  # long on +1 (bottom), short on -1 (top)
    return policy


def make_ko_signal_policy(high_conf: float = 0.0, cert_idx: int = 1,
                          size_idx: int = 0) -> Callable:
    def policy(env: KOTradingEnv, _obs):
        sig = env.current_signal()
        if sig == 0:
            return 0
        if high_conf > 0 and env.current_signal_conf() < high_conf:
            return 0
        return env.action_for_direction(sig, cert_idx=cert_idx, size_idx=size_idx)
    return policy


def flat_policy(_env, _obs):
    return 0


def make_agent_policy(agent: PPOAgent) -> Callable:
    def policy(_env, obs):
        x = torch.as_tensor(obs[None, :], dtype=torch.float32, device=agent.device)
        with torch.no_grad():
            logits, _ = agent.model(x)
        return int(torch.argmax(logits, dim=-1).item())
    return policy


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def aggregate(results: Sequence[dict]) -> dict:
    if not results:
        return {}
    rets = np.array([r["total_return"] for r in results])
    dds = np.array([r["max_drawdown"] for r in results])
    sharpes = np.array([r["sharpe"] for r in results])
    trades = [t for r in results for t in r["trades"]]
    trade_rets = np.array([t["net_return"] for t in trades]) if trades else np.array([])
    holding = np.array([t["holding_bars"] for t in trades]) if trades else np.array([])
    return {
        "series_count": len(results),
        "mean_return": float(rets.mean()),
        "median_return": float(np.median(rets)),
        "worst_return": float(rets.min()),
        "best_return": float(rets.max()),
        "mean_max_drawdown": float(dds.mean()),
        "worst_max_drawdown": float(dds.max()),
        "mean_sharpe": float(sharpes.mean()),
        "trade_count": int(len(trades)),
        "win_rate": float((trade_rets > 0).mean()) if len(trade_rets) else 0.0,
        "avg_holding_bars": float(holding.mean()) if len(holding) else 0.0,
        "avg_trade_return": float(trade_rets.mean()) if len(trade_rets) else 0.0,
        "signals_total": int(sum(r["signals_total"] for r in results)),
        "signals_used": int(sum(r["signals_used"] for r in results)),
        "signals_ignored": int(sum(r["signals_ignored"] for r in results)),
        "standalone_trades": int(sum(r["standalone_trades"] for r in results)),
        "profitable_series": int((rets > 0).sum()),
    }


def signal_usage_rate(agg: dict) -> float:
    total = agg.get("signals_total", 0)
    return agg.get("signals_used", 0) / total if total else 0.0


def aggregate_by_timeframe(results: Sequence[dict]) -> Dict[str, dict]:
    groups: Dict[str, List[dict]] = {}
    for r in results:
        groups.setdefault(r["timeframe"], []).append(r)
    return {tf: aggregate(rs) for tf, rs in sorted(groups.items())}


def aggregate_by_ticker(results: Sequence[dict]) -> Dict[str, dict]:
    groups: Dict[str, List[dict]] = {}
    for r in results:
        groups.setdefault(r["ticker"], []).append(r)
    return {tk: aggregate(rs) for tk, rs in sorted(groups.items())}


def ko_aggregate(results: Sequence[dict]) -> dict:
    if not results:
        return {}
    rets = np.array([r["total_return"] for r in results])
    dds = np.array([r["max_drawdown"] for r in results])
    sharpes = np.array([r["sharpe"] for r in results])
    trades = [t for r in results for t in r["trades"]]
    net = np.array([t["net_pnl_usd"] for t in trades], dtype=float) if trades else np.array([])
    holding = np.array([t["holding_bars"] for t in trades], dtype=float) if trades else np.array([])
    stakes = np.array([t["stake_usd"] for t in trades], dtype=float) if trades else np.array([])
    mr_ratios = np.array([t.get("entry_mr_ratio", 0.0) for t in trades], dtype=float) \
        if trades else np.array([])
    total_gross = float(sum(r["gross_pnl_usd"] for r in results))
    total_fees = float(sum(r["fees_usd"] for r in results))
    total_net = float(sum(r["net_pnl_usd"] for r in results))
    ko_count = int(sum(r["ko_count"] for r in results))
    fee_to_gross = (total_fees / abs(total_gross)) if abs(total_gross) > 1e-9 else (
        0.0 if total_fees == 0 else float("inf")
    )
    cert_counts = np.sum([np.asarray(r["cert_counts"], dtype=int) for r in results],
                         axis=0).astype(int).tolist() if results else []
    size_counts = np.sum([np.asarray(r["size_counts"], dtype=int) for r in results],
                         axis=0).astype(int).tolist() if results else []

    exit_counts: Dict[str, int] = {}
    for r in results:
        for reason, cnt in r.get("exit_reason_counts", {}).items():
            exit_counts[reason] = exit_counts.get(reason, 0) + int(cnt)
    close_count = int(sum(r.get("close_count", 0) for r in results))
    eod_count = int(sum(r.get("eod_count", 0) for r in results))
    target_count = int(sum(r.get("target_exit_count", 0) for r in results))
    sma_cross_count = int(sum(r.get("sma_cross_count", 0) for r in results))
    mean_revert_count = int(sum(r.get("mean_revert_count", 0) for r in results))
    max_hold_count = int(sum(r.get("max_hold_count", 0) for r in results))

    def _weighted_hold(attr: str, weight_attr: str) -> float:
        num = sum(r.get(attr, 0.0) * r.get(weight_attr, 0) for r in results)
        den = sum(r.get(weight_attr, 0) for r in results)
        return float(num / den) if den else 0.0

    avg_holding_close = _weighted_hold("avg_holding_close", "close_count") if close_count else 0.0
    avg_holding_ko = _weighted_hold("avg_holding_ko", "ko_count") if ko_count else 0.0
    avg_holding_target = _weighted_hold("avg_holding_target", "target_exit_count") if target_count else 0.0
    avg_hold_by_reason: Dict[str, float] = {}
    for reason, cnt in exit_counts.items():
        num = sum(r.get("avg_holding_by_exit", {}).get(reason, 0.0) *
                  r.get("exit_reason_counts", {}).get(reason, 0) for r in results)
        avg_hold_by_reason[reason] = float(num / cnt) if cnt else 0.0

    cert_map: Dict[int, dict] = {}
    for r in results:
        for cs in r.get("cert_stats", []):
            key = int(cs["cert_idx"])
            agg = cert_map.setdefault(key, {
                "cert_idx": key, "leverage": cs["leverage"], "trades": 0, "wins": 0,
                "kos": 0, "net_sum": 0.0, "hold_sum": 0.0, "fees_usd": 0.0,
            })
            agg["trades"] += int(cs["trades"])
            agg["wins"] += int(cs["wins"])
            agg["kos"] += int(cs["kos"])
            agg["net_sum"] += float(cs["avg_net_usd"]) * int(cs["trades"])
            agg["hold_sum"] += float(cs["avg_holding_bars"]) * int(cs["trades"])
            agg["fees_usd"] += float(cs["fees_usd"])
    cert_stats = []
    for key in sorted(cert_map):
        agg = cert_map[key]
        n = max(1, agg["trades"])
        cert_stats.append({
            "cert_idx": key,
            "leverage": agg["leverage"],
            "trades": agg["trades"],
            "wins": agg["wins"],
            "kos": agg["kos"],
            "win_rate": float(agg["wins"] / n) if agg["trades"] else 0.0,
            "avg_net_usd": float(agg["net_sum"] / n) if agg["trades"] else 0.0,
            "avg_holding_bars": float(agg["hold_sum"] / n) if agg["trades"] else 0.0,
            "fees_usd": agg["fees_usd"],
            "share": float(agg["trades"] / len(trades)) if trades else 0.0,
        })

    return {
        "series_count": len(results),
        "mean_return": float(rets.mean()),
        "median_return": float(np.median(rets)),
        "worst_return": float(rets.min()),
        "best_return": float(rets.max()),
        "mean_max_drawdown": float(dds.mean()),
        "worst_max_drawdown": float(dds.max()),
        "mean_sharpe": float(sharpes.mean()),
        "trade_count": int(len(trades)),
        "win_rate": float((net > 0).mean()) if len(net) else 0.0,
        "avg_holding_bars": float(holding.mean()) if len(holding) else 0.0,
        "avg_trade_usd": float(net.mean()) if len(net) else 0.0,
        "avg_stake_usd": float(stakes.mean()) if len(stakes) else 0.0,
        "gross_pnl_usd": total_gross,
        "fees_usd": total_fees,
        "net_pnl_usd": total_net,
        "fee_to_gross": float(fee_to_gross),
        "ko_count": ko_count,
        "ko_rate": float(ko_count / len(trades)) if trades else 0.0,
        "partial_count": int(sum(r.get("partial_count", 0) for r in results)),
        "partial_rate": float(sum(r.get("partial_count", 0) for r in results)
                              / len(trades)) if trades else 0.0,
        "avg_mr_ko_ratio": float(mr_ratios.mean()) if len(mr_ratios) else 0.0,
        "median_mr_ko_ratio": float(np.median(mr_ratios)) if len(mr_ratios) else 0.0,
        "min_mr_ko_ratio": float(mr_ratios.min()) if len(mr_ratios) else 0.0,
        "max_mr_ko_ratio": float(mr_ratios.max()) if len(mr_ratios) else 0.0,
        "close_count": close_count,
        "eod_count": eod_count,
        "target_exit_count": target_count,
        "sma_cross_count": sma_cross_count,
        "mean_revert_count": mean_revert_count,
        "max_hold_count": max_hold_count,
        "exit_reason_counts": exit_counts,
        "avg_holding_by_exit": avg_hold_by_reason,
        "avg_holding_close": avg_holding_close,
        "avg_holding_ko": avg_holding_ko,
        "avg_holding_target": avg_holding_target,
        "cert_stats": cert_stats,
        "cert_counts": cert_counts,
        "size_counts": size_counts,
        "filtered_entries": int(sum(r.get("filtered_entries", 0) for r in results)),
        "regime_filtered": int(sum(r.get("regime_filtered", 0) for r in results)),
        "signals_total": int(sum(r["signals_total"] for r in results)),
        "signals_used": int(sum(r["signals_used"] for r in results)),
        "signals_ignored": int(sum(r["signals_ignored"] for r in results)),
        "standalone_trades": int(sum(r["standalone_trades"] for r in results)),
        "profitable_series": int((rets > 0).sum()),
    }


def ko_aggregate_by_timeframe(results: Sequence[dict]) -> Dict[str, dict]:
    groups: Dict[str, List[dict]] = {}
    for r in results:
        groups.setdefault(r["timeframe"], []).append(r)
    return {tf: ko_aggregate(rs) for tf, rs in sorted(groups.items())}


def ko_aggregate_by_ticker(results: Sequence[dict]) -> Dict[str, dict]:
    groups: Dict[str, List[dict]] = {}
    for r in results:
        groups.setdefault(r["ticker"], []).append(r)
    return {tk: ko_aggregate(rs) for tk, rs in sorted(groups.items())}


def _cert_pref(counts: Sequence[int], leverages: Sequence[float]) -> str:
    if not counts:
        return "-"
    names = []
    for i, c in enumerate(counts):
        lev = leverages[i] if i < len(leverages) else 0.0
        names.append(f"{lev:.0f}x:{c}")
    return "/".join(names)


def _size_pref(counts: Sequence[int], fractions: Sequence[float]) -> str:
    if not counts:
        return "-"
    return "/".join(f"{f*100:.0f}%:{c}" for f, c in zip(fractions, counts))


def write_by_timeframe_csv(path: str, split: str,
                           by_tf: Dict[str, Dict[str, dict]]):
    fields = ["split", "method", "timeframe", "series_count", "mean_return",
              "median_return", "worst_return", "mean_max_drawdown", "mean_sharpe",
              "trade_count", "win_rate", "avg_holding_bars", "avg_trade_return",
              "signals_total", "signals_used", "signals_ignored", "standalone_trades"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for method, tf_map in by_tf.items():
            for tf, agg in tf_map.items():
                row = {k: agg.get(k) for k in fields if k not in ("split", "method", "timeframe")}
                row.update(split=split, method=method, timeframe=tf)
                w.writerow(row)


def write_ko_by_timeframe_csv(path: str, split: str,
                              by_tf: Dict[str, Dict[str, dict]]):
    fields = ["split", "method", "timeframe", "series_count", "mean_return",
              "median_return", "worst_return", "mean_max_drawdown", "mean_sharpe",
              "trade_count", "win_rate", "avg_holding_bars", "avg_trade_usd",
              "avg_stake_usd", "gross_pnl_usd", "fees_usd", "net_pnl_usd",
              "fee_to_gross", "ko_count", "ko_rate", "signals_total", "signals_used",
              "signals_ignored", "standalone_trades", "regime_filtered"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for method, tf_map in by_tf.items():
            for tf, agg in tf_map.items():
                row = {k: agg.get(k) for k in fields if k not in ("split", "method", "timeframe")}
                row.update(split=split, method=method, timeframe=tf)
                w.writerow(row)


def write_by_ticker_csv(path: str, split: str,
                        by_tk: Dict[str, Dict[str, dict]]):
    fields = ["split", "method", "ticker", "series_count", "mean_return",
              "median_return", "worst_return", "mean_max_drawdown", "mean_sharpe",
              "trade_count", "win_rate", "avg_holding_bars", "avg_trade_return",
              "signals_total", "signals_used", "signals_ignored", "standalone_trades"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for method, tk_map in by_tk.items():
            for tk, agg in tk_map.items():
                row = {k: agg.get(k) for k in fields if k not in ("split", "method", "ticker")}
                row.update(split=split, method=method, ticker=tk)
                w.writerow(row)


def write_ko_by_ticker_csv(path: str, split: str,
                           by_tk: Dict[str, Dict[str, dict]]):
    fields = ["split", "method", "ticker", "series_count", "mean_return",
              "median_return", "worst_return", "mean_max_drawdown", "mean_sharpe",
              "trade_count", "win_rate", "avg_holding_bars", "avg_trade_usd",
              "avg_stake_usd", "gross_pnl_usd", "fees_usd", "net_pnl_usd",
              "fee_to_gross", "ko_count", "ko_rate", "close_count", "sma_cross_count",
              "mean_revert_count", "max_hold_count", "avg_holding_close",
              "avg_holding_ko", "avg_holding_target", "signals_total", "signals_used",
              "signals_ignored", "standalone_trades", "regime_filtered"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for method, tk_map in by_tk.items():
            for tk, agg in tk_map.items():
                row = {k: agg.get(k) for k in fields if k not in ("split", "method", "ticker")}
                row.update(split=split, method=method, ticker=tk)
                w.writerow(row)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def write_per_series_csv(path: str, split: str, method: str, results: Sequence[dict]):
    fields = ["split", "method", "ticker", "timeframe", "total_return", "max_drawdown",
              "sharpe", "trade_count", "win_rate", "avg_holding_bars", "avg_trade_return",
              "signals_total", "signals_used", "signals_ignored", "standalone_trades"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            row = {k: r.get(k) for k in fields if k not in ("split", "method")}
            row["split"] = split
            row["method"] = method
            w.writerow(row)


def write_trades_csv(path: str, results: Sequence[dict]):
    fields = ["ticker", "timeframe", "entry_idx", "exit_idx", "entry_t", "exit_t",
              "direction", "entry_price", "exit_price", "gross_return", "net_return",
              "holding_bars", "entry_signal", "entry_had_signal"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            for t in r["trades"]:
                row = dict(t)
                row["ticker"] = r["ticker"]
                row["timeframe"] = r["timeframe"]
                w.writerow({k: row.get(k) for k in fields})


def write_ko_per_series_csv(path: str, split: str, method: str, results: Sequence[dict]):
    fields = ["split", "method", "ticker", "timeframe", "total_return", "max_drawdown",
              "sharpe", "trade_count", "win_rate", "avg_holding_bars", "avg_trade_usd",
              "avg_stake_usd", "gross_pnl_usd", "fees_usd", "net_pnl_usd", "fee_to_gross",
              "ko_count", "ko_rate", "ko_loss_usd", "partial_count", "partial_rate",
              "avg_partial_holding_bars", "avg_mr_ko_ratio",
              "median_mr_ko_ratio", "min_mr_ko_ratio", "max_mr_ko_ratio",
              "close_count", "eod_count",
              "sma_cross_count", "mean_revert_count", "max_hold_count",
              "target_exit_count", "avg_holding_close", "avg_holding_ko",
              "avg_holding_target", "cert_count_0", "cert_count_1", "cert_count_2",
              "cert_count_3", "signals_total", "signals_used",
              "signals_ignored", "standalone_trades", "regime_filtered"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            row = {k: r.get(k) for k in fields if k not in ("split", "method")}
            row["split"] = split
            row["method"] = method
            counts = list(r.get("cert_counts", []))
            for i in range(4):
                row[f"cert_count_{i}"] = counts[i] if i < len(counts) else 0
            w.writerow(row)


def write_ko_trades_csv(path: str, results: Sequence[dict]):
    fields = ["ticker", "timeframe", "entry_idx", "exit_idx", "entry_t", "exit_t",
              "direction", "cert_idx", "leverage", "size_idx", "size_fraction",
              "stake_usd", "remaining_stake_usd", "entry_price", "exit_price",
              "ko_level", "gross_pnl_usd", "fees_usd", "net_pnl_usd",
              "holding_bars", "knockout", "exit_reason",
              "partial_done", "partial_stake_usd", "partial_gross_usd",
              "partial_fees_usd", "partial_exit_idx", "partial_exit_price",
              "partial_holding_bars",
              "entry_signal", "entry_had_signal", "entry_mid", "mid_target_active",
              "entry_mr_ratio", "entry_expected_net_fees",
              "entry_atr_pct", "entry_partial_multiple",
              "max_proximity", "min_ko_dist_atr"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            for t in r["trades"]:
                row = dict(t)
                row["ticker"] = r["ticker"]
                row["timeframe"] = r["timeframe"]
                w.writerow({k: row.get(k) for k in fields})


def _grid_curve(curves: Sequence[np.ndarray], points: int = 200) -> np.ndarray:
    grid = np.linspace(0.0, 1.0, points)
    vals = []
    for c in curves:
        if len(c) < 2:
            continue
        x = np.linspace(0.0, 1.0, len(c))
        vals.append(np.interp(grid, x, c))
    if not vals:
        return np.ones(points)
    return np.mean(np.vstack(vals), axis=0)


def plot_split(out_dir: str, split: str, all_results: Dict[str, List[dict]]):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover
        print(f"matplotlib unavailable: {e}")
        return

    colors = {"rl_agent": "#1f77b4", "blind": "#ff7f0e",
              "high_conf": "#2ca02c", "flat": "#7f7f7f"}
    labels = {"rl_agent": "RL agent", "blind": "blind signals",
              "high_conf": "high-confidence signals", "flat": "flat"}

    fig, ax = plt.subplots(figsize=(10, 5))
    for method, results in all_results.items():
        if not results:
            continue
        eq = _grid_curve([r.get("equity_curve_norm", r["equity_curve"]) for r in results])
        ax.plot(np.linspace(0, 100, len(eq)), eq, lw=2 if method == "rl_agent" else 1.4,
                color=colors.get(method), label=labels.get(method, method))
        if method == "rl_agent":
            for r in results:
                c = r.get("equity_curve_norm", r["equity_curve"])
                if len(c) > 1:
                    x = np.linspace(0, 100, len(c))
                    ax.plot(x, c, color=colors[method], alpha=0.12, lw=0.7)
    ax.axhline(1.0, color="black", lw=0.8)
    ax.set_xlabel("episode progress (%)")
    ax.set_ylabel("normalised equity")
    ax.set_title(f"Equity - {split} (mean across series)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, f"equity_{split}.png"), dpi=130)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    for method, results in all_results.items():
        if not results:
            continue
        dd = _grid_curve([r["drawdown_curve"] for r in results])
        ax.plot(np.linspace(0, 100, len(dd)), dd, lw=2 if method == "rl_agent" else 1.4,
                color=colors.get(method), label=labels.get(method, method))
    ax.set_xlabel("episode progress (%)")
    ax.set_ylabel("drawdown")
    ax.set_title(f"Drawdown - {split} (mean across series)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, f"drawdown_{split}.png"), dpi=130)
    plt.close(fig)


def format_table(split: str, aggs: Dict[str, dict], high_conf: float) -> str:
    lines = [f"\n=== {split.upper()} ==="]
    header = (f"{'method':<16} {'meanRet':>9} {'medRet':>9} {'worst':>9} "
              f"{'maxDD':>8} {'trades':>7} {'win%':>6} {'hold':>7} "
              f"{'sigUse%':>8} {'standalone':>10}")
    lines.append(header)
    for method, a in aggs.items():
        name = method if method != "high_conf" else f"high_conf>={high_conf:.2f}"
        lines.append(
            f"{name:<16} {a['mean_return']*100:>8.2f}% {a['median_return']*100:>8.2f}% "
            f"{a['worst_return']*100:>8.2f}% {a['mean_max_drawdown']*100:>7.2f}% "
            f"{a['trade_count']:>7d} {a['win_rate']*100:>5.1f}% "
            f"{a['avg_holding_bars']:>6.1f} {signal_usage_rate(a)*100:>7.1f}% "
            f"{a['standalone_trades']:>10d}"
        )
    return "\n".join(lines)


def format_timeframe_table(split: str, by_tf: Dict[str, Dict[str, dict]],
                           high_conf: float) -> str:
    lines = [f"\n--- {split.upper()} by timeframe ---"]
    header = (f"{'tf':<7} {'method':<16} {'meanRet':>9} {'maxDD':>8} "
              f"{'trades':>7} {'win%':>6} {'hold':>7} {'sigUse%':>8} {'standalone':>10}")
    lines.append(header)
    for tf, method_map in by_tf.items():
        for method, a in method_map.items():
            name = method if method != "high_conf" else f"high_conf>={high_conf:.2f}"
            lines.append(
                f"{tf:<7} {name:<16} {a['mean_return']*100:>8.2f}% "
                f"{a['mean_max_drawdown']*100:>7.2f}% {a['trade_count']:>7d} "
                f"{a['win_rate']*100:>5.1f}% {a['avg_holding_bars']:>6.1f} "
                f"{signal_usage_rate(a)*100:>7.1f}% {a['standalone_trades']:>10d}"
            )
    return "\n".join(lines)


def format_ko_table(split: str, aggs: Dict[str, dict], high_conf: float,
                    cert_leverages: Sequence[float],
                    size_fractions: Sequence[float]) -> str:
    lines = [f"\n=== {split.upper()} (KO certificates) ==="]
    header = (f"{'method':<16} {'meanRet':>9} {'maxDD':>8} {'trades':>7} "
              f"{'win%':>6} {'hold':>7} {'KOs':>5} {'KO%':>6} {'part':>5} {'filt':>5} {'rfilt':>6} {'MR/KO':>7} "
              f"{'fees$':>9} {'gross$':>10} {'net$':>10} {'fee/gross':>9} "
              f"{'sigUse%':>8} {'certPref':>18} {'sizePref':>12}")
    lines.append(header)
    for method, a in aggs.items():
        name = method if method != "high_conf" else f"high_conf>={high_conf:.2f}"
        fg = a["fee_to_gross"]
        fg_s = "inf" if not np.isfinite(fg) else f"{fg:.2f}"
        lines.append(
            f"{name:<16} {a['mean_return']*100:>8.2f}% {a['mean_max_drawdown']*100:>7.2f}% "
            f"{a['trade_count']:>7d} {a['win_rate']*100:>5.1f}% {a['avg_holding_bars']:>6.1f} "
            f"{a['ko_count']:>5d} {a['ko_rate']*100:>5.1f}% "
            f"{a.get('partial_count', 0):>5d} {a.get('filtered_entries', 0):>5d} "
            f"{a.get('regime_filtered', 0):>6d} {a.get('avg_mr_ko_ratio', 0.0):>7.2f} "
            f"{a['fees_usd']:>9.0f} {a['gross_pnl_usd']:>10.0f} {a['net_pnl_usd']:>10.0f} "
            f"{fg_s:>9} {signal_usage_rate(a)*100:>7.1f}% "
            f"{_cert_pref(a['cert_counts'], cert_leverages):>18} "
            f"{_size_pref(a['size_counts'], size_fractions):>12}"
        )
    return "\n".join(lines)


def format_ko_timeframe_table(split: str, by_tf: Dict[str, Dict[str, dict]],
                              high_conf: float, cert_leverages: Sequence[float],
                              size_fractions: Sequence[float]) -> str:
    lines = [f"\n--- {split.upper()} by timeframe (KO) ---"]
    header = (f"{'tf':<7} {'method':<16} {'meanRet':>9} {'maxDD':>8} {'trades':>7} "
              f"{'win%':>6} {'hold':>7} {'KOs':>5} {'KO%':>6} "
              f"{'fees$':>9} {'net$':>10} {'sigUse%':>8}")
    lines.append(header)
    for tf, method_map in by_tf.items():
        for method, a in method_map.items():
            name = method if method != "high_conf" else f"high_conf>={high_conf:.2f}"
            lines.append(
                f"{tf:<7} {name:<16} {a['mean_return']*100:>8.2f}% "
                f"{a['mean_max_drawdown']*100:>7.2f}% {a['trade_count']:>7d} "
                f"{a['win_rate']*100:>5.1f}% {a['avg_holding_bars']:>6.1f} "
                f"{a['ko_count']:>5d} {a['ko_rate']*100:>5.1f}% "
                f"{a['fees_usd']:>9.0f} {a['net_pnl_usd']:>10.0f} "
                f"{signal_usage_rate(a)*100:>7.1f}%"
            )
    return "\n".join(lines)


def format_ko_exit_table(split: str, aggs: Dict[str, dict]) -> str:
    lines = [f"\n--- {split.upper()} exit diagnostics (KO) ---"]
    header = (f"{'method':<16} {'close':>7} {'eod':>5} {'KO':>5} {'smaX':>6} "
              f"{'meanRev':>7} {'maxHold':>7} {'holdClose':>9} {'holdKO':>7} "
              f"{'holdTarget':>10}")
    lines.append(header)
    for method, a in aggs.items():
        lines.append(
            f"{method:<16} {a.get('close_count', 0):>7d} {a.get('eod_count', 0):>5d} "
            f"{a.get('ko_count', 0):>5d} {a.get('sma_cross_count', 0):>6d} "
            f"{a.get('mean_revert_count', 0):>7d} {a.get('max_hold_count', 0):>7d} "
            f"{a.get('avg_holding_close', 0.0):>9.1f} {a.get('avg_holding_ko', 0.0):>7.1f} "
            f"{a.get('avg_holding_target', 0.0):>10.1f}"
        )
    return "\n".join(lines)


def format_ko_cert_table(split: str, aggs: Dict[str, dict]) -> str:
    lines = [f"\n--- {split.upper()} by certificate (KO) ---"]
    header = (f"{'method':<16} {'lev':>5} {'trades':>7} {'share':>7} {'win%':>6} "
              f"{'KOs':>5} {'avgNet$':>9} {'avgHold':>8} {'fees$':>8}")
    lines.append(header)
    for method, a in aggs.items():
        for cs in a.get("cert_stats", []):
            lines.append(
                f"{method:<16} {cs['leverage']:>4.0f}x {cs['trades']:>7d} "
                f"{cs['share']*100:>6.1f}% {cs['win_rate']*100:>5.1f}% "
                f"{cs['kos']:>5d} {cs['avg_net_usd']:>9.0f} "
                f"{cs['avg_holding_bars']:>8.1f} {cs['fees_usd']:>8.0f}"
            )
    return "\n".join(lines)


def format_ticker_table(split: str, by_tk: Dict[str, Dict[str, dict]],
                        high_conf: float) -> str:
    lines = [f"\n--- {split.upper()} by ticker ---"]
    header = (f"{'ticker':<7} {'method':<16} {'meanRet':>9} {'maxDD':>8} {'trades':>7} "
              f"{'win%':>6} {'hold':>7} {'sigUse%':>8}")
    lines.append(header)
    for tk, method_map in by_tk.items():
        for method, a in method_map.items():
            name = method if method != "high_conf" else f"high_conf>={high_conf:.2f}"
            lines.append(
                f"{tk:<7} {name:<16} {a['mean_return']*100:>8.2f}% "
                f"{a['mean_max_drawdown']*100:>7.2f}% {a['trade_count']:>7d} "
                f"{a['win_rate']*100:>5.1f}% {a['avg_holding_bars']:>6.1f} "
                f"{signal_usage_rate(a)*100:>7.1f}%"
            )
    return "\n".join(lines)


def format_ko_ticker_table(split: str, by_tk: Dict[str, Dict[str, dict]],
                           high_conf: float) -> str:
    lines = [f"\n--- {split.upper()} by ticker (KO) ---"]
    header = (f"{'ticker':<7} {'method':<16} {'meanRet':>9} {'maxDD':>8} {'trades':>7} "
              f"{'win%':>6} {'hold':>7} {'KOs':>5} {'KO%':>6} "
              f"{'fees$':>8} {'net$':>9} {'sigUse%':>8}")
    lines.append(header)
    for tk, method_map in by_tk.items():
        for method, a in method_map.items():
            name = method if method != "high_conf" else f"high_conf>={high_conf:.2f}"
            lines.append(
                f"{tk:<7} {name:<16} {a['mean_return']*100:>8.2f}% "
                f"{a['mean_max_drawdown']*100:>7.2f}% {a['trade_count']:>7d} "
                f"{a['win_rate']*100:>5.1f}% {a['avg_holding_bars']:>6.1f} "
                f"{a['ko_count']:>5d} {a['ko_rate']*100:>5.1f}% "
                f"{a['fees_usd']:>8.0f} {a['net_pnl_usd']:>9.0f} "
                f"{signal_usage_rate(a)*100:>7.1f}%"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Evaluate a PPO trading agent vs baselines.")
    p.add_argument("--run-name", default=None, help="Run folder under rl_trader/runs/ (default: latest).")
    p.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    p.add_argument("--env", choices=["auto", "classic", "ko"], default="auto",
                   help="Environment type; auto uses the checkpoint metadata.")
    p.add_argument("--timeframes", default=None,
                   help="Override timeframe whitelist (default: checkpoint).")
    p.add_argument("--exclude-timeframes", default=None,
                   help="Exclude timeframes (default: checkpoint).")
    p.add_argument("--oot-tickers", default=None,
                   help="Override OOT tickers, comma separated (default: checkpoint).")
    p.add_argument("--splits", default="val,test,oot",
                   help="Comma separated subset of val,test,oot.")
    p.add_argument("--high-conf", type=float, default=0.60)
    p.add_argument("--cost-bps", type=float, default=None,
                   help="Override transaction cost; default from checkpoint.")
    p.add_argument("--slippage-bps", type=float, default=None)
    p.add_argument("--trade-fee", type=float, default=None,
                   help="KO environment: override USD fee per order.")
    p.add_argument("--position-size", type=float, default=None,
                   help="KO environment: override full stake in USD.")
    p.add_argument("--initial-cash", type=float, default=None,
                   help="KO environment: override initial account cash in USD.")
    p.add_argument("--cert-leverages", default=None,
                   help="KO environment: comma separated leverages, e.g. 22,30,38.")
    p.add_argument("--size-fractions", default=None,
                   help="KO environment: comma separated size tiers, e.g. 1.0,0.5.")
    p.add_argument("--ko-buffer", type=float, default=None)
    p.add_argument("--ko-penalty", type=float, default=None)
    p.add_argument("--ko-event-penalty", type=float, default=None)
    p.add_argument("--reward-scale-usd", type=float, default=None)
    p.add_argument("--fee-basis", type=float, default=None,
                   help="Override fee multiplier for ratio features (2=round trip).")
    p.add_argument("--legacy-obs", action="store_true",
                   help="Use the legacy KO observation layout (for v2 checkpoints).")
    p.add_argument("--regime-filter", action="store_true",
                   help="Enable the lean causal regime/entry filter.")
    p.add_argument("--min-atr-pct", type=float, default=0.0)
    p.add_argument("--max-atr-pct", type=float, default=1.0)
    p.add_argument("--min-mr-room-atr", type=float, default=-99.0,
                   help="Minimum directional room to the mean in ATR.")
    p.add_argument("--max-short-d80", type=float, default=99.0,
                   help="Block shorts when (close-SMA80)/ATR is above this.")
    p.add_argument("--min-long-d80", type=float, default=-99.0,
                   help="Block longs when (close-SMA80)/ATR is below this.")
    p.add_argument("--min-conf", type=float, default=0.0)
    p.add_argument("--device", default="cpu")
    p.add_argument("--out-dir", default=None)
    return p.parse_args()


def _parse_float_list(value, default):
    if value is None:
        value = default
    if isinstance(value, str):
        return tuple(float(v) for v in value.split(",") if v.strip())
    return tuple(float(v) for v in value)


def main():
    args = parse_args()
    run_dir = os.path.join(RUNS_DIR, args.run_name) if args.run_name else latest_run()
    if not os.path.isfile(os.path.join(run_dir, "checkpoint.pt")):
        raise FileNotFoundError(f"No checkpoint in {run_dir}")
    out_dir = args.out_dir or os.path.join(run_dir, "eval")
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "eval_run.log")
    log_file = open(log_path, "w")

    def log(msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    agent, ckpt = load_agent(run_dir, device=args.device)
    cfg = ckpt.get("config", {})
    profiles = ckpt["profiles"]
    cost_bps = args.cost_bps if args.cost_bps is not None else cfg.get("cost_bps", 5.0)
    slippage_bps = args.slippage_bps if args.slippage_bps is not None else cfg.get("slippage_bps", 1.0)
    reward_scale = cfg.get("reward_scale", 100.0)
    dd_penalty = cfg.get("dd_penalty", 0.10)
    trade_penalty = cfg.get("trade_penalty", 0.01)
    signal_bonus = cfg.get("signal_bonus", 0.0)
    signal_conf_min = cfg.get("signal_conf_min", 0.55)
    env_type = args.env if args.env != "auto" else ckpt.get("env_type", "classic")
    trade_fee = args.trade_fee if args.trade_fee is not None else cfg.get("trade_fee", 10.0)
    position_size = (args.position_size if args.position_size is not None
                     else cfg.get("position_size", 200.0))
    initial_cash = (args.initial_cash if args.initial_cash is not None
                    else cfg.get("initial_cash", 10_000.0))
    cert_leverages = _parse_float_list(
        args.cert_leverages, cfg.get("cert_leverages", (22.0, 30.0, 60.0, 80.0)))
    size_fractions = _parse_float_list(
        args.size_fractions, cfg.get("size_fractions", (1.0, 0.5)))
    ko_buffer = args.ko_buffer if args.ko_buffer is not None else cfg.get("ko_buffer", 0.005)
    ko_penalty = args.ko_penalty if args.ko_penalty is not None else cfg.get("ko_penalty", 0.05)
    ko_event_penalty = (args.ko_event_penalty if args.ko_event_penalty is not None
                        else cfg.get("ko_event_penalty", 0.5))
    reward_scale_usd = (args.reward_scale_usd if args.reward_scale_usd is not None
                        else cfg.get("reward_scale_usd", 100.0))
    exit_on_sma_cross = cfg.get("exit_on_sma_cross", False)
    mean_revert_target = cfg.get("mean_revert_target", False)
    max_hold_bars = int(cfg.get("max_hold_bars", 0))
    target_bonus = float(cfg.get("target_bonus", 0.2))
    avoid_ko_bonus = float(cfg.get("avoid_ko_bonus", 0.1))
    high_lev_threshold = float(cfg.get("high_lev_threshold", 60.0))
    high_lev_ko_penalty = float(cfg.get("high_lev_ko_penalty", 0.05))
    fee_basis = float(cfg.get("fee_basis", 2.0))
    min_edge_ratio = float(cfg.get("min_edge_ratio", 0.0))
    min_ko_buffer_atr = float(cfg.get("min_ko_buffer_atr", 0.0))
    mr_only = bool(cfg.get("mr_only", False))
    min_mr_ko_ratio = float(cfg.get("min_mr_ko_ratio", 0.0))
    mr_ko_ratios = cfg.get("mr_ko_ratios")
    if isinstance(mr_ko_ratios, str):
        mr_ko_ratios = tuple(float(v) for v in mr_ko_ratios.split(",") if v.strip())
    elif mr_ko_ratios is not None:
        mr_ko_ratios = tuple(float(v) for v in mr_ko_ratios)
    mr_ratio_vol_scaling = float(cfg.get("mr_ratio_vol_scaling", 0.0))
    mr_ratio_bonus = float(cfg.get("mr_ratio_bonus", 0.25))
    partial_target = bool(cfg.get("partial_target", False))
    partial_fraction = float(cfg.get("partial_fraction", 0.5))
    partial_ko_multiple = float(cfg.get("partial_ko_multiple", 1.0))
    partial_atr = bool(cfg.get("partial_atr", False))
    partial_multiple_low = float(cfg.get("partial_multiple_low", 1.0))
    partial_multiple_high = float(cfg.get("partial_multiple_high", 0.75))
    partial_atr_percentile = float(cfg.get("partial_atr_percentile", 0.7))
    partial_atr_window = int(cfg.get("partial_atr_window", 100))
    partial_min_net_usd = float(cfg.get("partial_min_net_usd", 0.0))
    legacy_obs = bool(args.legacy_obs) or bool(cfg.get("legacy_obs_layout", False))
    if args.fee_basis is not None:
        fee_basis = float(args.fee_basis)
    regime_filter = bool(args.regime_filter) or bool(cfg.get("regime_filter", False))
    min_atr_pct = float(cfg.get("min_atr_pct", 0.0) if args.min_atr_pct == 0.0 else args.min_atr_pct)
    max_atr_pct = float(cfg.get("max_atr_pct", 1.0) if args.max_atr_pct == 1.0 else args.max_atr_pct)
    min_mr_room_atr = (float(cfg.get("min_mr_room_atr", -99.0))
                       if args.min_mr_room_atr == -99.0 else args.min_mr_room_atr)
    max_short_d80 = (float(cfg.get("max_short_d80", 99.0))
                     if args.max_short_d80 == 99.0 else args.max_short_d80)
    min_long_d80 = (float(cfg.get("min_long_d80", -99.0))
                    if args.min_long_d80 == -99.0 else args.min_long_d80)
    min_conf = float(cfg.get("min_conf", 0.0) if args.min_conf == 0.0 else args.min_conf)
    if args.timeframes is not None or args.exclude_timeframes is not None:
        timeframes = resolve_timeframes(args.timeframes, args.exclude_timeframes)
    else:
        timeframes = ckpt.get("timeframes")
    if args.oot_tickers is not None:
        oot_tickers = tuple(v.strip() for v in args.oot_tickers.split(",") if v.strip())
    else:
        oot_tickers = tuple(ckpt.get("oot_tickers", ["AAPL"]))

    log(f"run_dir={run_dir}")
    log(f"env={env_type} profiles={profiles} "
        f"timeframes={timeframes if timeframes is not None else 'all'} "
        f"oot_tickers={oot_tickers} high_conf={args.high_conf}")
    if env_type == "ko":
        log(f"KO: fee=${trade_fee:.2f}/order stake=${position_size:.0f} "
            f"cash=${initial_cash:.0f} certs={list(cert_leverages)} "
            f"sizes={list(size_fractions)} buffer={ko_buffer:.3f} "
            f"mr_only={mr_only} min_mr_ko={min_mr_ko_ratio:.2f} "
            f"min_edge={min_edge_ratio:.2f} min_ko_atr={min_ko_buffer_atr:.2f}")
    else:
        log(f"costs={cost_bps}bps + {slippage_bps}bps slippage")

    t0 = time.time()
    series = build_series(args.data_root, profiles=profiles, timeframes=timeframes)
    log(f"Loaded {len(series)} series ({time.time()-t0:.1f}s)")
    pools = build_pools(series, timeframes=timeframes, oot_tickers=oot_tickers)
    split_map = {"val": pools.val, "test": pools.test, "oot": pools.oot}
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    for s in splits:
        if s not in split_map:
            raise ValueError(f"Unknown split {s!r}")

    if env_type == "ko":
        env_cls = KOTradingEnv
        env_kwargs = dict(
            episode_len=None, random_start=False,
            position_size=position_size, trade_fee=trade_fee,
            initial_cash=initial_cash, cert_leverages=cert_leverages,
            size_fractions=size_fractions, ko_buffer=ko_buffer,
            reward_scale_usd=reward_scale_usd, dd_penalty=dd_penalty,
            ko_penalty=ko_penalty, ko_event_penalty=ko_event_penalty,
            exit_on_sma_cross=exit_on_sma_cross,
            mean_revert_target=mean_revert_target,
            max_hold_bars=max_hold_bars,
            target_bonus=target_bonus,
            avoid_ko_bonus=avoid_ko_bonus,
            high_lev_threshold=high_lev_threshold,
            high_lev_ko_penalty=high_lev_ko_penalty,
            fee_basis=fee_basis,
            min_edge_ratio=min_edge_ratio,
            min_ko_buffer_atr=min_ko_buffer_atr,
            mr_only=mr_only,
            min_mr_ko_ratio=min_mr_ko_ratio,
            mr_ko_ratios=mr_ko_ratios,
            mr_ratio_vol_scaling=mr_ratio_vol_scaling,
            mr_ratio_bonus=mr_ratio_bonus,
            partial_target=partial_target,
            partial_fraction=partial_fraction,
            partial_ko_multiple=partial_ko_multiple,
            partial_atr=partial_atr,
            partial_multiple_low=partial_multiple_low,
            partial_multiple_high=partial_multiple_high,
            partial_atr_percentile=partial_atr_percentile,
            partial_atr_window=partial_atr_window,
            partial_min_net_usd=partial_min_net_usd,
            regime_filter=regime_filter,
            min_atr_pct=min_atr_pct,
            max_atr_pct=max_atr_pct,
            min_mr_room_atr=min_mr_room_atr,
            max_short_d80=max_short_d80,
            min_long_d80=min_long_d80,
            min_conf=min_conf,
            legacy_obs_layout=legacy_obs,
            signal_bonus=signal_bonus, signal_conf_min=signal_conf_min,
        )
        methods = {
            "rl_agent": make_agent_policy(agent),
            "blind": make_ko_signal_policy(0.0),
            "high_conf": make_ko_signal_policy(args.high_conf),
            "flat": flat_policy,
        }
        run_fn = run_ko_episode
        agg_fn = ko_aggregate
        agg_tf_fn = ko_aggregate_by_timeframe
        agg_tk_fn = ko_aggregate_by_ticker
        write_ps = write_ko_per_series_csv
        write_tr = write_ko_trades_csv
        write_tf = write_ko_by_timeframe_csv
        write_tk = write_ko_by_ticker_csv
        format_fn = lambda split, aggs: format_ko_table(  # noqa: E731
            split, aggs, args.high_conf, cert_leverages, size_fractions)
        format_tf_fn = lambda split, by_tf: format_ko_timeframe_table(  # noqa: E731
            split, by_tf, args.high_conf, cert_leverages, size_fractions)
        format_tk_fn = lambda split, by_tk: format_ko_ticker_table(  # noqa: E731
            split, by_tk, args.high_conf)
    else:
        env_cls = TradingEnv
        env_kwargs = dict(episode_len=None, random_start=False, cost_bps=cost_bps,
                          slippage_bps=slippage_bps, reward_scale=reward_scale,
                          dd_penalty=dd_penalty, trade_penalty=trade_penalty,
                          signal_bonus=signal_bonus, signal_conf_min=signal_conf_min)
        methods = {
            "rl_agent": make_agent_policy(agent),
            "blind": make_signal_policy(0.0),
            "high_conf": make_signal_policy(args.high_conf),
            "flat": flat_policy,
        }
        run_fn = run_episode
        agg_fn = aggregate
        agg_tf_fn = aggregate_by_timeframe
        agg_tk_fn = aggregate_by_ticker
        write_ps = write_per_series_csv
        write_tr = write_trades_csv
        write_tf = write_by_timeframe_csv
        write_tk = write_by_ticker_csv
        format_fn = lambda split, aggs: format_table(split, aggs, args.high_conf)  # noqa: E731
        format_tf_fn = lambda split, by_tf: format_timeframe_table(  # noqa: E731
            split, by_tf, args.high_conf)
        format_tk_fn = lambda split, by_tk: format_ticker_table(  # noqa: E731
            split, by_tk, args.high_conf)

    # Guard against evaluating a legacy checkpoint with a changed state layout.
    first_pool = next((split_map[s] for s in splits if split_map.get(s)), None)
    if first_pool:
        probe = env_cls([first_pool[0]], profiles=profiles, seed=0, **env_kwargs)
        if probe.obs_dim != int(ckpt["obs_dim"]):
            raise SystemExit(
                f"Checkpoint obs_dim={ckpt['obs_dim']} does not match env obs_dim={probe.obs_dim}. "
                "This checkpoint was trained with a different state layout (e.g. the legacy "
                "3-cert KO state). Train a new run with the current env or evaluate it with "
                "the matching legacy version."
            )

    all_split_results: Dict[str, Dict[str, List[dict]]] = {}
    report = {
        "run_name": os.path.basename(run_dir),
        "env_type": env_type,
        "profiles": profiles,
        "timeframes": timeframes,
        "oot_tickers": list(oot_tickers),
        "high_conf": args.high_conf,
        "splits": {},
    }
    if env_type == "ko":
        report.update({
            "position_size": position_size,
            "trade_fee": trade_fee,
            "initial_cash": initial_cash,
            "cert_leverages": list(cert_leverages),
            "size_fractions": list(size_fractions),
            "ko_buffer": ko_buffer,
            "ko_penalty": ko_penalty,
            "ko_event_penalty": ko_event_penalty,
            "reward_scale_usd": reward_scale_usd,
            "exit_on_sma_cross": exit_on_sma_cross,
            "mean_revert_target": mean_revert_target,
            "max_hold_bars": max_hold_bars,
            "target_bonus": target_bonus,
            "avoid_ko_bonus": avoid_ko_bonus,
            "high_lev_threshold": high_lev_threshold,
            "high_lev_ko_penalty": high_lev_ko_penalty,
            "fee_basis": fee_basis,
            "min_edge_ratio": min_edge_ratio,
            "min_ko_buffer_atr": min_ko_buffer_atr,
            "mr_only": mr_only,
            "min_mr_ko_ratio": min_mr_ko_ratio,
            "mr_ko_ratios": list(mr_ko_ratios) if mr_ko_ratios else None,
            "mr_ratio_vol_scaling": mr_ratio_vol_scaling,
            "mr_ratio_bonus": mr_ratio_bonus,
            "partial_target": partial_target,
            "partial_fraction": partial_fraction,
            "partial_ko_multiple": partial_ko_multiple,
            "partial_atr": partial_atr,
            "partial_multiple_low": partial_multiple_low,
            "partial_multiple_high": partial_multiple_high,
            "partial_atr_percentile": partial_atr_percentile,
            "partial_atr_window": partial_atr_window,
            "partial_min_net_usd": partial_min_net_usd,
            "regime_filter": regime_filter,
            "min_atr_pct": min_atr_pct,
            "max_atr_pct": max_atr_pct,
            "min_mr_room_atr": min_mr_room_atr,
            "max_short_d80": max_short_d80,
            "min_long_d80": min_long_d80,
            "min_conf": min_conf,
            "legacy_obs_layout": legacy_obs,
        })
    else:
        report.update({
            "cost_bps": cost_bps,
            "slippage_bps": slippage_bps,
            "reward_scale": reward_scale,
        })

    for split in splits:
        pool = split_map[split]
        if not pool:
            log(f"split {split}: no series, skipping")
            continue
        split_results: Dict[str, List[dict]] = {}
        for method, policy in methods.items():
            results = []
            for item in pool:
                env = env_cls([item], profiles=profiles, seed=0, **env_kwargs)
                results.append(run_fn(env, policy))
            split_results[method] = results
            write_ps(
                os.path.join(out_dir, f"per_series_{split}_{method}.csv"),
                split, method, results,
            )
            write_tr(os.path.join(out_dir, f"trades_{split}_{method}.csv"), results)

        aggs = {m: agg_fn(r) for m, r in split_results.items()}
        by_tf = {m: agg_tf_fn(r) for m, r in split_results.items()}
        by_tk = {m: agg_tk_fn(r) for m, r in split_results.items()}
        report["splits"][split] = {
            "aggregate": aggs,
            "by_timeframe": by_tf,
            "by_ticker": by_tk,
            "series_count": len(pool),
        }
        write_tf(os.path.join(out_dir, f"by_timeframe_{split}.csv"), split, by_tf)
        write_tk(os.path.join(out_dir, f"by_ticker_{split}.csv"), split, by_tk)
        log(format_fn(split, aggs))
        log(format_tf_fn(split, by_tf))
        if split == "oot" or len(by_tk) > 1:
            log(format_tk_fn(split, by_tk))
        if env_type == "ko":
            log(format_ko_exit_table(split, aggs))
            log(format_ko_cert_table(split, aggs))
        plot_split(out_dir, split, split_results)
        all_split_results[split] = split_results

    with open(os.path.join(out_dir, "eval_metrics.json"), "w") as f:
        json.dump(report, f, indent=2)

    # Markdown summary
    md = [f"# RL evaluation - {os.path.basename(run_dir)}", ""]
    md.append(f"- Environment: `{env_type}`")
    md.append(f"- Profiles: `{', '.join(profiles)}`")
    md.append(f"- Timeframes: `{timeframes if timeframes is not None else 'all'}`")
    md.append(f"- OOT tickers: `{', '.join(oot_tickers)}`")
    if env_type == "ko":
        md.append(f"- KO: fee ${trade_fee:.2f}/order, stake ${position_size:.0f}, "
                  f"cash ${initial_cash:.0f}, certs {list(cert_leverages)}, "
                  f"sizes {list(size_fractions)}")
    else:
        md.append(f"- Costs: {cost_bps:.1f} bps + {slippage_bps:.1f} bps slippage")
    md.append(f"- High-confidence threshold: {args.high_conf:.2f}")
    md.append("")
    for split in all_split_results:
        md.append(f"## {split}")
        md.append("```")
        md.append(format_fn(split, report["splits"][split]["aggregate"]))
        md.append("```")
        md.append("")
        md.append("```")
        md.append(format_tf_fn(split, report["splits"][split]["by_timeframe"]))
        md.append("```")
        md.append("")
        if split == "oot" or len(report["splits"][split]["by_ticker"]) > 1:
            md.append("```")
            md.append(format_tk_fn(split, report["splits"][split]["by_ticker"]))
            md.append("```")
            md.append("")
        if env_type == "ko":
            aggs = report["splits"][split]["aggregate"]
            md.append("```")
            md.append(format_ko_exit_table(split, aggs))
            md.append("```")
            md.append("")
            md.append("```")
            md.append(format_ko_cert_table(split, aggs))
            md.append("```")
            md.append("")
        md.append(f"![equity](equity_{split}.png)")
        md.append(f"![drawdown](drawdown_{split}.png)")
        md.append("")
    with open(os.path.join(out_dir, "eval_report.md"), "w") as f:
        f.write("\n".join(md))

    log(f"Artifacts written to {out_dir}")
    log(f"Done in {time.time()-t0:.1f}s")
    log_file.close()


if __name__ == "__main__":
    main()
