---
type: Feature
title: Modelltraining (Turning Points)
description: Training eines MLP zur Klassifikation von Extrem-Hoch/Neutral/Extrem-Tief plus HGB-Benchmark, Checkpoint- und Signal-Export.
status: umgesetzt
priority: hoch
---

# Ziel

Ein trainiertes, reproduzierbares Turning-Point-Modell mit Threshold/Cooldown und Signal-Export bereitstellen.

# Umfang

- `train_turning_points.py`: `TurningPointMLP` + `HistGradientBoostingClassifier`-Benchmark, Chrono-/OOT-Split, Klassengewichtung, Regularisierung, Label-Smoothing, Cooldown-NMS (`suppress_signal_clusters`), Metriken.
- `train_sma5_model.py`: Wrapper auf `prepared_sma5`-Daten.
- `TurningPoint_Training_Colab.ipynb`: NMS/Cluster-Filter, automatisches `BEST_THRESHOLD`-Tuning (0.40–0.80), Regularisierung, Signal-Export (`predictions_test.csv`/`predictions_oot.csv`), `best_threshold`/`cooldown_bars` im Checkpoint.

# Aufgaben

- [A2: Modelltraining](/aufgaben/a2-modelltraining.md)

# Stand

Umgesetzt (Colab-Optimierung und Run-Logging dokumentiert).
