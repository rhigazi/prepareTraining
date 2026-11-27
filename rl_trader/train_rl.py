#!/usr/bin/env python3
"""train_rl.py - PPO training for the causal trading environment.

Examples
--------
    python rl_trader/train_rl.py --profile ml4t --run-name ml4t_smoke --iterations 40
    python rl_trader/train_rl.py --profile all_3 --run-name all3_ppo --iterations 80

Artifacts are written to ``rl_trader/runs/<run-name>/``:
    checkpoint.pt, training_run.log, learning_curve.png, learning_curve.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Sequence

import numpy as np
import torch
import torch.nn as nn
from torch.distributions import Categorical

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from env import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    KOTradingEnv,
    PROFILE_CHOICES,
    TradingEnv,
    build_pools,
    build_series,
    resolve_timeframes,
)

RUNS_DIR = os.path.join(HERE, "runs")


# ---------------------------------------------------------------------------
# Network / PPO
# ---------------------------------------------------------------------------
class ActorCritic(nn.Module):
    def __init__(self, obs_dim: int, n_actions: int = 4, hidden: int = 128):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.Tanh(),
            nn.Linear(hidden, hidden), nn.Tanh(),
        )
        self.actor = nn.Linear(hidden, n_actions)
        self.critic = nn.Linear(hidden, 1)
        for m in (self.actor, self.critic):
            nn.init.orthogonal_(m.weight, gain=0.01 if m is self.actor else 1.0)
            nn.init.zeros_(m.bias)

    def forward(self, x: torch.Tensor):
        h = self.trunk(x)
        return self.actor(h), self.critic(h).squeeze(-1)


@dataclass
class PPOConfig:
    lr: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    ppo_epochs: int = 4
    batch_size: int = 256
    target_kl: float = 0.03


class PPOAgent:
    def __init__(self, obs_dim: int, n_actions: int = 4, cfg: PPOConfig = PPOConfig(),
                 device: str = "cpu", seed: int = 0):
        torch.manual_seed(seed)
        self.cfg = cfg
        self.device = torch.device(device)
        self.model = ActorCritic(obs_dim, n_actions).to(self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=cfg.lr, eps=1e-5)

    def act(self, obs: np.ndarray):
        x = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
        with torch.no_grad():
            logits, value = self.model(x)
            dist = Categorical(logits=logits)
            action = dist.sample()
            logp = dist.log_prob(action)
        return action.cpu().numpy(), logp.cpu().numpy(), value.cpu().numpy()

    def value_only(self, obs: np.ndarray) -> np.ndarray:
        x = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
        with torch.no_grad():
            _, value = self.model(x)
        return value.cpu().numpy()

    def update(self, obs, actions, old_logp, rewards, dones, values,
               bc_obs=None, bc_actions=None, bc_coef: float = 0.0) -> Dict[str, float]:
        cfg = self.cfg
        T, N = rewards.shape
        adv = np.zeros((T, N), dtype=np.float32)
        last = np.zeros(N, dtype=np.float32)
        for t in reversed(range(T)):
            next_val = values[t + 1]
            nonterminal = 1.0 - dones[t]
            delta = rewards[t] + cfg.gamma * next_val * nonterminal - values[t]
            last = delta + cfg.gamma * cfg.gae_lambda * nonterminal * last
            adv[t] = last
        returns = adv + values[:-1]

        b_obs = torch.as_tensor(obs.reshape(T * N, -1), dtype=torch.float32, device=self.device)
        b_actions = torch.as_tensor(actions.reshape(-1), dtype=torch.long, device=self.device)
        b_old_logp = torch.as_tensor(old_logp.reshape(-1), dtype=torch.float32, device=self.device)
        b_adv = torch.as_tensor(adv.reshape(-1), dtype=torch.float32, device=self.device)
        b_returns = torch.as_tensor(returns.reshape(-1), dtype=torch.float32, device=self.device)
        b_adv = (b_adv - b_adv.mean()) / (b_adv.std() + 1e-8)

        n = b_obs.shape[0]
        idx = np.arange(n)
        stats = {"policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0,
                 "approx_kl": 0.0, "bc_loss": 0.0, "updates": 0}
        if bc_obs is not None and bc_actions is not None and bc_coef > 0:
            if not torch.is_tensor(bc_obs):
                bc_obs = torch.as_tensor(bc_obs, dtype=torch.float32, device=self.device)
            if not torch.is_tensor(bc_actions):
                bc_actions = torch.as_tensor(bc_actions, dtype=torch.long, device=self.device)
        else:
            bc_obs, bc_actions = None, None
        stop = False
        for _ in range(cfg.ppo_epochs):
            np.random.shuffle(idx)
            for start in range(0, n, cfg.batch_size):
                mb = idx[start:start + cfg.batch_size]
                logits, value = self.model(b_obs[mb])
                dist = Categorical(logits=logits)
                logp = dist.log_prob(b_actions[mb])
                entropy = dist.entropy().mean()
                ratio = torch.exp(logp - b_old_logp[mb])
                adv_mb = b_adv[mb]
                p_loss1 = -adv_mb * ratio
                p_loss2 = -adv_mb * torch.clamp(ratio, 1 - cfg.clip, 1 + cfg.clip)
                policy_loss = torch.max(p_loss1, p_loss2).mean()
                value_loss = 0.5 * ((value - b_returns[mb]) ** 2).mean()
                loss = policy_loss + cfg.vf_coef * value_loss - cfg.ent_coef * entropy
                bc_loss = torch.zeros((), device=self.device)
                if bc_obs is not None:
                    bidx = torch.randint(0, bc_obs.shape[0], (len(mb),), device=self.device)
                    logits_bc, _ = self.model(bc_obs[bidx])
                    bc_loss = nn.functional.cross_entropy(logits_bc, bc_actions[bidx])
                    loss = loss + bc_coef * bc_loss

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), cfg.max_grad_norm)
                self.optimizer.step()

                with torch.no_grad():
                    approx_kl = ((ratio - 1.0) - (logp - b_old_logp[mb])).mean().item()
                stats["policy_loss"] += float(policy_loss.item())
                stats["value_loss"] += float(value_loss.item())
                stats["entropy"] += float(entropy.item())
                stats["approx_kl"] += approx_kl
                stats["bc_loss"] += float(bc_loss.item())
                stats["updates"] += 1
                if cfg.target_kl and approx_kl > 1.5 * cfg.target_kl:
                    stop = True
                    break
            if stop:
                break
        for k in ("policy_loss", "value_loss", "entropy", "approx_kl", "bc_loss"):
            stats[k] /= max(stats["updates"], 1)
        return stats


# ---------------------------------------------------------------------------
# Rollout
# ---------------------------------------------------------------------------
def collect_rollout(envs, agent: PPOAgent, rollout: int, obs: np.ndarray):
    N = len(envs)
    obs_list: List[np.ndarray] = []
    act_list: List[np.ndarray] = []
    logp_list: List[np.ndarray] = []
    rew_list: List[np.ndarray] = []
    done_list: List[np.ndarray] = []
    val_list: List[np.ndarray] = []

    episode_returns: List[float] = []
    episode_trades: List[int] = []
    episode_dd: List[float] = []

    for _ in range(rollout):
        actions, logp, values = agent.act(obs)
        next_obs = np.zeros_like(obs)
        rewards = np.zeros(N, dtype=np.float32)
        dones = np.zeros(N, dtype=np.float32)
        for i, env in enumerate(envs):
            o, r, d, _trunc, info = env.step(int(actions[i]))
            rewards[i] = r
            dones[i] = float(d)
            if d:
                base = getattr(env, "initial_cash", 1.0)
                episode_returns.append(float(info["equity"] / max(base, 1e-9) - 1.0))
                episode_trades.append(int(info.get("trade_count", 0)))
                episode_dd.append(float(info.get("drawdown", 0.0)))
                o, _ = env.reset()
            next_obs[i] = o
        obs_list.append(obs)
        act_list.append(actions)
        logp_list.append(logp)
        rew_list.append(rewards)
        done_list.append(dones)
        val_list.append(values)
        obs = next_obs

    last_values = agent.value_only(obs)
    vals = np.stack(val_list + [last_values], axis=0)  # (T+1, N)
    rollout_data = {
        "obs": np.stack(obs_list),
        "actions": np.stack(act_list),
        "logp": np.stack(logp_list),
        "rewards": np.stack(rew_list),
        "dones": np.stack(done_list),
        "values": vals,
    }
    episodes = {
        "returns": episode_returns,
        "trades": episode_trades,
        "max_dd": episode_dd,
        "mean_step_reward": float(np.mean(np.stack(rew_list))),
    }
    return rollout_data, episodes, obs


# ---------------------------------------------------------------------------
# Optional behaviour-cloning warm start
# ---------------------------------------------------------------------------
def collect_bc_dataset(envs, n_samples: int, conf_min: float):
    """Collect (observation, action) pairs from a confident-signal rule policy."""
    obs_list: List[np.ndarray] = []
    act_list: List[int] = []
    rule_returns: List[float] = []
    obs = np.stack([env.reset()[0] for env in envs]).astype(np.float32)
    steps = 0
    while steps < n_samples:
        actions = np.zeros(len(envs), dtype=np.int64)
        for i, env in enumerate(envs):
            sig = env.current_signal()
            conf = env.current_signal_conf()
            if hasattr(env, "bc_action"):
                actions[i] = env.bc_action(sig, conf, conf_min)
                continue
            if sig != 0 and conf >= conf_min:
                target = sig
            else:
                target = env.position
            if target == env.position:
                actions[i] = 0
            elif hasattr(env, "action_for_direction"):
                actions[i] = env.action_for_direction(target, cert_idx=1, size_idx=0)
            elif target == 1:
                actions[i] = 1
            elif target == -1:
                actions[i] = 2
            else:
                actions[i] = 3
        next_obs = np.zeros_like(obs)
        for i, env in enumerate(envs):
            o, _r, d, _trunc, info = env.step(int(actions[i]))
            if d:
                base = getattr(env, "initial_cash", 1.0)
                rule_returns.append(float(info["equity"] / max(base, 1e-9) - 1.0))
                o, _ = env.reset()
            next_obs[i] = o
        obs_list.append(obs)
        act_list.append(actions)
        obs = next_obs
        steps += len(envs)
    return (np.concatenate(obs_list, axis=0), np.concatenate(act_list, axis=0),
            float(np.mean(rule_returns)) if rule_returns else 0.0)


def behaviour_clone(agent: PPOAgent, obs: np.ndarray, actions: np.ndarray,
                    epochs: int, lr: float, batch_size: int = 256,
                    log=print) -> float:
    X = torch.as_tensor(obs, dtype=torch.float32, device=agent.device)
    y = torch.as_tensor(actions, dtype=torch.long, device=agent.device)
    opt = torch.optim.Adam(agent.model.parameters(), lr=lr)
    n = X.shape[0]
    acc = 0.0
    for epoch in range(1, epochs + 1):
        perm = torch.randperm(n, device=agent.device)
        total_loss, correct = 0.0, 0
        for start in range(0, n, batch_size):
            idx = perm[start:start + batch_size]
            logits, _ = agent.model(X[idx])
            loss = nn.functional.cross_entropy(logits, y[idx])
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(agent.model.parameters(), 0.5)
            opt.step()
            total_loss += float(loss.item()) * len(idx)
            correct += int((logits.argmax(-1) == y[idx]).sum().item())
        acc = correct / n
        log(f"BC epoch {epoch:02d}/{epochs} | loss {total_loss/n:.4f} | acc {acc:.3f}")
    return acc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="PPO training on the causal RL trading env.")
    p.add_argument("--profile", choices=list(PROFILE_CHOICES) + ["all_3"], default="ml4t")
    p.add_argument("--run-name", default=None)
    p.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    p.add_argument("--env", choices=["classic", "ko"], default="classic",
                   help="classic = bps-cost spot-like env; ko = USD knock-out certificate env.")
    p.add_argument("--timeframes", default=None,
                   help="Comma separated timeframe whitelist, e.g. 1Hour,15Min.")
    p.add_argument("--oot-tickers", default="AAPL",
                   help="Comma separated tickers fully held out for OOT, e.g. AAPL,NVDA.")
    p.add_argument("--exclude-timeframes", default=None,
                   help="Comma separated timeframe blacklist, e.g. 5Min.")
    p.add_argument("--iterations", type=int, default=60)
    p.add_argument("--n-envs", type=int, default=8)
    p.add_argument("--rollout", type=int, default=128,
                   help="Steps per environment per PPO iteration.")
    p.add_argument("--episode-len", type=int, default=256)
    p.add_argument("--train-frac", type=float, default=0.70)
    p.add_argument("--val-frac", type=float, default=0.15)
    p.add_argument("--min-idx", type=int, default=100)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--gae-lambda", type=float, default=0.95)
    p.add_argument("--clip", type=float, default=0.2)
    p.add_argument("--ent-coef", type=float, default=0.01)
    p.add_argument("--vf-coef", type=float, default=0.5)
    p.add_argument("--ppo-epochs", type=int, default=4)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--cost-bps", type=float, default=5.0)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    # Knock-out environment parameters (used when --env ko)
    p.add_argument("--position-size", type=float, default=200.0,
                   help="KO: full stake per position in USD.")
    p.add_argument("--trade-fee", type=float, default=10.0,
                   help="KO: USD fee per order (entry, exit, flip).")
    p.add_argument("--initial-cash", type=float, default=10_000.0,
                   help="KO: initial account cash in USD.")
    p.add_argument("--target-leverage", type=float, default=30.0,
                   help="KO: reference leverage (standard certificate).")
    p.add_argument("--cert-leverages", default="22,30,60,80",
                   help="KO: comma separated certificate leverages.")
    p.add_argument("--size-fractions", default="1.0,0.5",
                   help="KO: comma separated stake fractions (full, reduced, ...).")
    p.add_argument("--ko-buffer", type=float, default=0.005,
                   help="KO: extra distance beyond 1/leverage (fraction).")
    p.add_argument("--ko-penalty", type=float, default=0.05,
                   help="KO: per-step reward penalty proportional to KO proximity.")
    p.add_argument("--ko-event-penalty", type=float, default=0.5,
                   help="KO: extra reward penalty on a knock-out event.")
    p.add_argument("--reward-scale-usd", type=float, default=100.0,
                   help="KO: divide USD reward changes by this value.")
    p.add_argument("--exit-on-sma-cross", action="store_true",
                   help="KO: close automatically when SMA38/SMA80 cross.")
    p.add_argument("--mean-revert-target", action="store_true",
                   help="KO: close automatically when price reaches the rolling mean.")
    p.add_argument("--max-hold-bars", type=int, default=0,
                   help="KO: close automatically after N bars (0 disables).")
    p.add_argument("--target-bonus", type=float, default=0.2,
                   help="KO: reward bonus for profitable mean-reversion/SMA-cross exits.")
    p.add_argument("--avoid-ko-bonus", type=float, default=0.1,
                   help="KO: reward bonus for closing profitably near the KO level.")
    p.add_argument("--high-lev-threshold", type=float, default=60.0,
                   help="KO: leverage above which the KO-proximity penalty is scaled.")
    p.add_argument("--high-lev-ko-penalty", type=float, default=0.05,
                   help="KO: extra per-bar penalty for high leverage in the KO zone.")
    p.add_argument("--fee-basis", type=float, default=2.0,
                   help="KO: fee multiplier for cost/edge ratios (2 = round trip).")
    p.add_argument("--min-edge-ratio", type=float, default=0.0,
                   help="KO: block entries whose target move is below this multiple "
                        "of the round-trip fee (0 disables).")
    p.add_argument("--min-ko-buffer-atr", type=float, default=0.0,
                   help="KO: block entries whose initial KO distance is below this ATR value.")
    p.add_argument("--mr-only", action="store_true",
                   help="KO: disable SMA-cross targets; trade mean-reversion only.")
    p.add_argument("--min-mr-ko-ratio", type=float, default=0.0,
                   help="KO: global minimum mid-distance / KO-distance ratio for entries.")
    p.add_argument("--mr-ko-ratios", default=None,
                   help="KO: per-certificate ratio thresholds, e.g. 0.8,1.0,1.5,2.0.")
    p.add_argument("--mr-ratio-vol-scaling", type=float, default=0.0,
                   help="KO: increase the per-cert ratio threshold with ATR (0 disables).")
    p.add_argument("--mr-ratio-bonus", type=float, default=0.25,
                   help="KO: extra reward scale for higher mid/KO ratios on mean-reversion exits.")
    p.add_argument("--partial-target", action="store_true",
                   help="KO: take partial profit at a multiple of the initial KO distance.")
    p.add_argument("--partial-fraction", type=float, default=0.5,
                   help="KO: fraction of the position closed at the partial target.")
    p.add_argument("--partial-ko-multiple", type=float, default=1.0,
                   help="KO: partial target distance as a multiple of the initial KO distance.")
    p.add_argument("--partial-atr", action="store_true",
                   help="KO: make the partial target multiple ATR/volatility dependent.")
    p.add_argument("--partial-multiple-low", type=float, default=1.0,
                   help="KO: partial multiple in low-volatility regimes.")
    p.add_argument("--partial-multiple-high", type=float, default=0.75,
                   help="KO: partial multiple in high-volatility regimes.")
    p.add_argument("--partial-atr-percentile", type=float, default=0.7,
                   help="KO: ATR percentile threshold for the high-volatility regime.")
    p.add_argument("--partial-atr-window", type=int, default=100,
                   help="KO: trailing window for the ATR percentile.")
    p.add_argument("--partial-min-net-usd", type=float, default=0.0,
                   help="KO: only take a partial profit if its net after the fee is at least this.")
    p.add_argument("--reward-scale", type=float, default=100.0)
    p.add_argument("--dd-penalty", type=float, default=0.10)
    p.add_argument("--trade-penalty", type=float, default=0.01)
    p.add_argument("--signal-bonus", type=float, default=0.02,
                   help="Exploration shaping: bonus when the position aligns with a "
                        "sufficiently confident filtered signal (0 disables).")
    p.add_argument("--signal-conf-min", type=float, default=0.55)
    p.add_argument("--bc-samples", type=int, default=0,
                   help="Optional behaviour-cloning warm start: number of rule-policy "
                        "transitions (0 disables, pure PPO).")
    p.add_argument("--bc-epochs", type=int, default=15)
    p.add_argument("--bc-conf-min", type=float, default=0.60)
    p.add_argument("--bc-lr", type=float, default=1e-3)
    p.add_argument("--bc-anchor", type=float, default=0.0,
                   help="Auxiliary BC cross-entropy weight during PPO updates "
                        "(keeps the rule policy from collapsing to flat; 0 disables).")
    p.add_argument("--bc-entry-frac", type=float, default=0.0,
                   help="Oversample entry actions in the BC dataset to this fraction "
                        "(0 disables; useful for rare high-conviction setups).")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", default="cpu")
    return p.parse_args()


def main():
    args = parse_args()
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))

    profiles = list(PROFILE_CHOICES) if args.profile == "all_3" else [args.profile]
    run_name = args.run_name or f"{args.profile}_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = os.path.join(RUNS_DIR, run_name)
    os.makedirs(run_dir, exist_ok=True)
    log_path = os.path.join(run_dir, "training_run.log")
    log_file = open(log_path, "w")

    def log(msg: str):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    log(f"run={run_name} env={args.env} profile={args.profile} profiles={profiles}")
    log(f"data_root={args.data_root}")

    timeframes = resolve_timeframes(args.timeframes, args.exclude_timeframes)
    oot_tickers = tuple(v.strip() for v in args.oot_tickers.split(",") if v.strip())
    log(f"timeframes={timeframes if timeframes is not None else 'all'} "
        f"oot_tickers={oot_tickers}")

    t0 = time.time()
    series = build_series(args.data_root, profiles=profiles, timeframes=timeframes)
    log(f"Loaded {len(series)} raw series with signals for {profiles} ({time.time()-t0:.1f}s)")

    pools = build_pools(series, train_frac=args.train_frac, val_frac=args.val_frac,
                        min_idx=args.min_idx, timeframes=timeframes,
                        oot_tickers=oot_tickers)
    if not pools.train:
        raise RuntimeError("No training series found.")
    log(f"pools: train={len(pools.train)} series, val={len(pools.val)}, "
        f"test={len(pools.test)}, oot={len(pools.oot)}")

    cert_leverages = tuple(float(v) for v in args.cert_leverages.split(",") if v.strip())
    size_fractions = tuple(float(v) for v in args.size_fractions.split(",") if v.strip())
    mr_ko_ratios = (tuple(float(v) for v in args.mr_ko_ratios.split(",") if v.strip())
                    if args.mr_ko_ratios else None)
    if args.env == "ko":
        EnvClass = KOTradingEnv
        env_kwargs = dict(
            position_size=args.position_size,
            trade_fee=args.trade_fee,
            initial_cash=args.initial_cash,
            cert_leverages=cert_leverages,
            size_fractions=size_fractions,
            ko_buffer=args.ko_buffer,
            reward_scale_usd=args.reward_scale_usd,
            dd_penalty=args.dd_penalty,
            ko_penalty=args.ko_penalty,
            ko_event_penalty=args.ko_event_penalty,
            exit_on_sma_cross=args.exit_on_sma_cross,
            mean_revert_target=args.mean_revert_target,
            max_hold_bars=args.max_hold_bars,
            target_bonus=args.target_bonus,
            avoid_ko_bonus=args.avoid_ko_bonus,
            high_lev_threshold=args.high_lev_threshold,
            high_lev_ko_penalty=args.high_lev_ko_penalty,
            fee_basis=args.fee_basis,
            min_edge_ratio=args.min_edge_ratio,
            min_ko_buffer_atr=args.min_ko_buffer_atr,
            mr_only=args.mr_only,
            min_mr_ko_ratio=args.min_mr_ko_ratio,
            mr_ko_ratios=mr_ko_ratios,
            mr_ratio_vol_scaling=args.mr_ratio_vol_scaling,
            mr_ratio_bonus=args.mr_ratio_bonus,
            partial_target=args.partial_target,
            partial_fraction=args.partial_fraction,
            partial_ko_multiple=args.partial_ko_multiple,
            partial_atr=args.partial_atr,
            partial_multiple_low=args.partial_multiple_low,
            partial_multiple_high=args.partial_multiple_high,
            partial_atr_percentile=args.partial_atr_percentile,
            partial_atr_window=args.partial_atr_window,
            partial_min_net_usd=args.partial_min_net_usd,
            signal_bonus=args.signal_bonus,
            signal_conf_min=args.signal_conf_min,
        )
        log(f"KO env: fee=${args.trade_fee:.2f}/order stake=${args.position_size:.0f} "
            f"cash=${args.initial_cash:.0f} certs={cert_leverages} "
            f"sizes={size_fractions} buffer={args.ko_buffer:.3f} "
            f"exits(sma={args.exit_on_sma_cross},mean={args.mean_revert_target},"
            f"max_hold={args.max_hold_bars})")
    else:
        EnvClass = TradingEnv
        env_kwargs = dict(
            cost_bps=args.cost_bps,
            slippage_bps=args.slippage_bps,
            reward_scale=args.reward_scale,
            dd_penalty=args.dd_penalty,
            trade_penalty=args.trade_penalty,
            signal_bonus=args.signal_bonus,
            signal_conf_min=args.signal_conf_min,
        )

    envs = [
        EnvClass(
            series_pool=pools.train,
            profiles=profiles,
            episode_len=args.episode_len,
            random_start=True,
            seed=args.seed + i,
            **env_kwargs,
        )
        for i in range(args.n_envs)
    ]
    obs_dim = envs[0].obs_dim
    n_actions = int(envs[0].action_space.n)

    cfg = PPOConfig(
        lr=args.lr, gamma=args.gamma, gae_lambda=args.gae_lambda, clip=args.clip,
        ent_coef=args.ent_coef, vf_coef=args.vf_coef, ppo_epochs=args.ppo_epochs,
        batch_size=args.batch_size,
    )
    agent = PPOAgent(obs_dim, n_actions=n_actions, cfg=cfg, device=args.device, seed=args.seed)
    log(f"obs_dim={obs_dim} n_actions={n_actions} n_envs={args.n_envs} "
        f"rollout={args.rollout} iterations={args.iterations}")

    if args.bc_samples > 0:
        log(f"BC warm start: collecting {args.bc_samples} rule-policy transitions "
            f"(conf>={args.bc_conf_min})")
        bc_obs, bc_act, bc_ret = collect_bc_dataset(envs, args.bc_samples, args.bc_conf_min)
        log(f"BC dataset: {len(bc_act)} transitions | rule mean episode return {bc_ret:+.4f}")
        if args.bc_entry_frac > 0.0:
            entry_mask = bc_act >= 2
            n_entry = int(entry_mask.sum())
            if n_entry > 0:
                n_hold = len(bc_act) - n_entry
                target = float(np.clip(args.bc_entry_frac, 0.01, 0.9))
                repeat = max(1, int((target / (1.0 - target)) * n_hold / n_entry))
                bc_obs = np.concatenate(
                    [bc_obs, np.repeat(bc_obs[entry_mask], repeat, axis=0)], axis=0)
                bc_act = np.concatenate(
                    [bc_act, np.repeat(bc_act[entry_mask], repeat)], axis=0)
                log(f"BC entry oversampling: {n_entry} entries x{repeat} -> "
                    f"{len(bc_act)} transitions")
        acc = behaviour_clone(agent, bc_obs, bc_act, args.bc_epochs, args.bc_lr, log=log)
        log(f"BC warm start finished (action accuracy {acc:.3f})")
        bc_obs_t = torch.as_tensor(bc_obs, dtype=torch.float32, device=agent.device)
        bc_act_t = torch.as_tensor(bc_act, dtype=torch.long, device=agent.device)
        log(f"BC anchor coefficient: {args.bc_anchor}")
    else:
        bc_obs_t, bc_act_t = None, None

    history: List[Dict[str, float]] = []
    total_steps = 0
    obs = np.stack([env.reset()[0] for env in envs]).astype(np.float32)
    for it in range(1, args.iterations + 1):
        data, ep, obs = collect_rollout(envs, agent, args.rollout, obs)
        stats = agent.update(
            data["obs"], data["actions"], data["logp"],
            data["rewards"], data["dones"], data["values"],
            bc_obs=bc_obs_t, bc_actions=bc_act_t, bc_coef=args.bc_anchor,
        )
        total_steps += args.rollout * args.n_envs
        row = {
            "iteration": it,
            "steps": total_steps,
            "mean_episode_return": float(np.mean(ep["returns"])) if ep["returns"] else 0.0,
            "mean_episode_trades": float(np.mean(ep["trades"])) if ep["trades"] else 0.0,
            "mean_episode_maxdd": float(np.mean(ep["max_dd"])) if ep["max_dd"] else 0.0,
            "mean_step_reward": ep["mean_step_reward"],
            "episodes": len(ep["returns"]),
            **stats,
        }
        history.append(row)
        log(
            f"iter {it:03d}/{args.iterations} | steps {total_steps:6d} | "
            f"ep_ret {row['mean_episode_return']:+.4f} | trades {row['mean_episode_trades']:.1f} | "
            f"rew {row['mean_step_reward']:+.4f} | "
            f"pi_loss {stats['policy_loss']:.4f} | v_loss {stats['value_loss']:.4f} | "
            f"bc {stats['bc_loss']:.4f} | ent {stats['entropy']:.3f} | kl {stats['approx_kl']:.4f}"
        )

    checkpoint = {
        "model_state_dict": agent.model.state_dict(),
        "obs_dim": obs_dim,
        "n_actions": n_actions,
        "env_type": args.env,
        "profiles": profiles,
        "profile_arg": args.profile,
        "timeframes": timeframes,
        "oot_tickers": list(oot_tickers),
        "config": vars(args),
        "history": history,
    }
    if args.env == "ko":
        checkpoint.update({
            "position_size": args.position_size,
            "trade_fee": args.trade_fee,
            "initial_cash": args.initial_cash,
            "cert_leverages": list(cert_leverages),
            "size_fractions": list(size_fractions),
            "target_leverage": args.target_leverage,
            "ko_buffer": args.ko_buffer,
            "ko_penalty": args.ko_penalty,
            "ko_event_penalty": args.ko_event_penalty,
            "reward_scale_usd": args.reward_scale_usd,
        })
    ckpt_path = os.path.join(run_dir, "checkpoint.pt")
    torch.save(checkpoint, ckpt_path)
    log(f"Saved checkpoint: {ckpt_path}")

    # learning curve CSV + PNG
    csv_path = os.path.join(run_dir, "learning_curve.csv")
    keys = list(history[0].keys()) if history else []
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(history)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        its = [h["iteration"] for h in history]
        rets = [h["mean_episode_return"] for h in history]
        fig, ax = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
        ax[0].plot(its, rets, alpha=0.4, label="episode return")
        if len(rets) >= 5:
            k = 5
            smooth = np.convolve(rets, np.ones(k) / k, mode="valid")
            ax[0].plot(its[k - 1:], smooth, lw=2, label=f"MA({k})")
        ax[0].axhline(0, color="black", lw=0.8)
        ax[0].set_ylabel("episode return")
        ax[0].legend()
        ax[0].grid(alpha=0.3)
        ax[1].plot(its, [h["mean_episode_trades"] for h in history], label="trades/episode")
        ax[1].plot(its, [h["mean_episode_maxdd"] for h in history], label="episode max DD")
        ax[1].set_xlabel("PPO iteration")
        ax[1].legend()
        ax[1].grid(alpha=0.3)
        fig.suptitle(f"PPO training - {run_name} ({args.profile})")
        fig.tight_layout()
        png_path = os.path.join(run_dir, "learning_curve.png")
        fig.savefig(png_path, dpi=130)
        plt.close(fig)
        log(f"Saved learning curve: {png_path}")
    except Exception as e:  # pragma: no cover
        log(f"Could not create learning curve plot: {e}")

    meta = {
        "run_name": run_name,
        "env_type": args.env,
        "profile_arg": args.profile,
        "profiles": profiles,
        "timeframes": timeframes,
        "oot_tickers": list(oot_tickers),
        "obs_dim": obs_dim,
        "n_actions": n_actions,
        "iterations": args.iterations,
        "total_steps": total_steps,
        "config": vars(args),
        "final": history[-1] if history else {},
        "elapsed_sec": time.time() - t0,
    }
    with open(os.path.join(run_dir, "train_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    log(f"Done in {time.time()-t0:.1f}s")
    log_file.close()
    print(f"\nRun artifacts: {run_dir}")


if __name__ == "__main__":
    main()
