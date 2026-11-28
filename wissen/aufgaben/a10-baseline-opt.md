---
type: Task
title: "A10: baseline_opt Gewinner (base_05)"
description: Gewinner des Strangs baseline_opt aus der eval_3ways-Suche mit Metriken und SMA-Segment-Validierung.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: mittel
assigned_to: mensch
feature: /features/f10-hyperparameter-ergebnisse.md
---

# Ziel

Beste Konfiguration des Strangs baseline_opt (prepared_data, 8 Trials) festhalten.

# Ergebnisse

- Gewinner-Trial: `base_05`, Score 0.4947, Threshold 0.45, Datenvariante `prepared_data`.
- F1: Val 0.414, Test 0.411, OOT 0.437.
- Globale SMA-Segment-Validierung: Hits Bull 308 (83.5 %), Hits Bear 313 (86.7 %), Extra 6055, Modell-Signale 6688, Extra-Rate 0.905, Mean-ATR-Dist 0.641, ATR-Qualität 0.610.
- Ergebnisse: `runs/eval_3ways/baseline_opt/best/metrics.json`, `reports/sma_validation_summary.md`, `training_run.log`, Charts.