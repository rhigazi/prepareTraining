---
type: Task
title: "A7: RL-Trading-Prototyp"
description: Kausales MDP auf Basis der drei Profil-Signale; PPO-Agent lernt Trading-Policy; Evaluation gegen naive Baselines.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: niedrig
assigned_to: mensch
feature: /features/f7-rl-trading.md
---

# Ziel

Prototyp eines RL-basierten Trading-Agenten auf den Profil-Signalen.

# Akzeptanzkriterien

- Kausale Gymnasium-Umgebung (`TradingEnv`/`KOTradingEnv`), State aus Profil-Signalen + Rohdaten, Aktion `close_t`, Reward aus `close_t→close_{t+1}`.
- PPO-Training (eigene Implementierung, Actor-Critic, Torch) mit Checkpoints/Logs/Lernkurven.
- Evaluation gegen Baselines (blind/high_conf/flat) auf Val/Test/OOT inkl. Kennzahlen/Charts.

# Betroffene Dateien

- `rl_trader/env.py`, `rl_trader/train_rl.py`, `rl_trader/eval_rl.py`

# Ergebnisse

- Umgesetzt (Runs unter `rl_trader/runs/`).
