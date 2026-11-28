---
type: Feature
title: RL-Trading-Prototyp
description: Kausales MDP auf Basis der drei Profil-Signale; PPO-Agent lernt Trading-Policy; Evaluation gegen naive Baselines.
status: umgesetzt
priority: niedrig
---

# Ziel

Prototyp eines RL-basierten Trading-Agenten auf den Profil-Signalen.

# Umfang

- `rl_trader/env.py`: kausale Gymnasium-Umgebung (`TradingEnv`/`KOTradingEnv`), State aus Profil-Signalen + Rohdaten, Aktion `close_t`, Reward aus `close_t→close_{t+1}`, Splits/Timeframes.
- `rl_trader/train_rl.py`: PPO-Training (eigene Implementierung, Actor-Critic, Torch) mit Checkpoints/Logs/Lernkurven.
- `rl_trader/eval_rl.py`: Bewertung gegen Baselines (blind/high_conf/flat) auf Val/Test/OOT inkl. Kennzahlen/Charts.

# Aufgaben

- [A7: RL-Trading-Prototyp](/aufgaben/a7-rl-trading.md)

# Stand

Umgesetzt (Runs unter `rl_trader/runs/`).
