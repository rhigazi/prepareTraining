---
type: Task
title: "A11: sma_auto_opt Gewinner (sma_05)"
description: Gewinner des Strangs sma_auto_opt aus der eval_3ways-Suche mit Metriken und SMA-Segment-Validierung.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: mittel
assigned_to: mensch
feature: /features/f10-hyperparameter-ergebnisse.md
---

# Ziel

Beste Konfiguration des Strangs sma_auto_opt (sma5_tol2, 8 Trials) festhalten.

# Ergebnisse

- Gewinner-Trial: `sma_05`, Score 0.4149, Threshold 0.45, Datenvariante `sma5_tol2`.
- F1: Val 0.121, Test 0.122, OOT 0.115.
- Globale SMA-Segment-Validierung: Hits Bull 296 (80.2 %), Hits Bear 285 (78.9 %), Extra 3253, Modell-Signale 3857, Extra-Rate 0.843, Mean-ATR-Dist 1.266, ATR-Qualität 0.441.
- Ergebnisse: `runs/eval_3ways/sma_auto_opt/best/metrics.json`, `reports/sma_validation_summary.md`, `training_run.log`, Charts.