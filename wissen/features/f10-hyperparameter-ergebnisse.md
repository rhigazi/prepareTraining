---
type: Feature
title: Hyperparameter-Suchergebnisse (eval_3ways)
description: Gewinner pro Strang (baseline_opt, sma_auto_opt, ml4t_opt) mit Metriken und SMA-Segment-Validierung.
status: umgesetzt
priority: mittel
---

# Ziel

Beste Konfiguration pro Strang aus der eval_3ways-Suche festhalten (Trial, Score, F1, Hit-Raten, Extra-Rate).

# Umfang

- Strang `baseline_opt`: Gewinner `base_05` (Score 0.495, Val F1 0.414, Test F1 0.411, OOT F1 0.437, Threshold 0.45, Hit-Rate Bull/Bear ~0.83/0.87).
- Strang `sma_auto_opt`: Gewinner `sma_05` (Score 0.415, Val F1 0.121, Test F1 0.122, OOT F1 0.115, Threshold 0.45, Hit-Rate ~0.80/0.79).
- Strang `ml4t_opt`: Gewinner `ml4t_04` (Score 0.412, Val F1 0.137, Test F1 0.113, OOT F1 0.117, Threshold 0.50, Hit-Rate ~0.74/0.73).

Jeder Strang hat 8 Trials (`base_01..08`, `sma_01..08`, `ml4t_01..08`); Gewinner nach Score. Ergebnisse in `runs/eval_3ways/<strand>/best/`.

# Aufgaben

- [A10: baseline_opt Gewinner](/aufgaben/a10-baseline-opt.md)
- [A11: sma_auto_opt Gewinner](/aufgaben/a11-sma-auto-opt.md)
- [A12: ml4t_opt Gewinner](/aufgaben/a12-ml4t-opt.md)

# Stand

Umgesetzt (Metriken in `metrics.json`, SMA-Validierung in `reports/sma_validation_summary.md`).