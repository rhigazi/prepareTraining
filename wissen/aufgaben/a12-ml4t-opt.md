---
type: Task
title: "A12: ml4t_opt Gewinner (ml4t_04)"
description: Gewinner des Strangs ml4t_opt aus der eval_3ways-Suche mit Metriken und SMA-Segment-Validierung.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: mittel
assigned_to: mensch
feature: /features/f10-hyperparameter-ergebnisse.md
---

# Ziel

Beste Konfiguration des Strangs ml4t_opt (ml4t_tol2, 8 Trials) festhalten.

# Ergebnisse

- Gewinner-Trial: `ml4t_04`, Score 0.4118, Threshold 0.50, Datenvariante `ml4t_tol2`.
- F1: Val 0.137, Test 0.113, OOT 0.117.
- Globale SMA-Segment-Validierung: Hits Bull 274 (74.3 %), Hits Bear 262 (72.6 %), Extra 2484, Modell-Signale 3038, Extra-Rate 0.818, Mean-ATR-Dist 1.333, ATR-Qualität 0.429.
- Ergebnisse: `runs/eval_3ways/ml4t_opt/best/metrics.json`, `reports/sma_validation_summary.md`, `training_run.log`, Charts.