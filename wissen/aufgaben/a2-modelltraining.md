---
type: Task
title: "A2: Modelltraining (Turning Points)"
description: Training eines MLP zur Extrem-Klassifikation plus HGB-Benchmark, Checkpoint- und Signal-Export.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: hoch
assigned_to: mensch
feature: /features/f2-modelltraining.md
---

# Ziel

Ein trainiertes, reproduzierbares Turning-Point-Modell mit Threshold/Cooldown und Signal-Export bereitstellen.

# Akzeptanzkriterien

- `TurningPointMLP` + `HistGradientBoostingClassifier`-Benchmark.
- Chrono-/OOT-Split, Klassengewichtung, Regularisierung, Label-Smoothing, Cooldown-NMS (`suppress_signal_clusters`).
- Export von Checkpoint, Scaler, Threshold/Cooldown und Signal-CSVs (`predictions_test.csv`/`predictions_oot.csv`).
- `best_threshold` und `cooldown_bars` im Checkpoint (`turning_point_mlp.pt`).

# Betroffene Dateien

- `train_turning_points.py`, `train_sma5_model.py`, `TurningPoint_Training_Colab.ipynb`

# Ergebnisse

- 2026-11-24: Umgesetzt; Colab-Optimierung (NMS/Cluster-Filter, Threshold-Tuning, Regularisierung) und Run-Logging via Tee dokumentiert.
