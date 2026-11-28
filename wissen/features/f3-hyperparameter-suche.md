---
type: Feature
title: Hyperparameter-/Feature-Suche
description: Systematische Suchläufe über Feature-Varianten, Label-Toleranzen und Post-Processing mit Gewinner-Auswahl pro Strang.
status: umgesetzt
priority: mittel
---

# Ziel

Beste Konfigurationen pro Strang (baseline_opt, sma_auto_opt, ml4t_opt) finden und als Gewinner ablegen.

# Umfang

- `run_eval_3ways.py`: drei unabhängige Stränge, Trials unter `runs/eval_3ways/`, Winner nach `<strand>/best/`, Charts.
- `run_ml4t_extremes_experiments.py`: ML4T-Features + Label-Toleranz-Suche.
- `run_visual_opt_search.py`: Optimierung auf starke Segment-Hits bei wenigen Extra-Signalen.
- `run_fib_opt_search.py`: Fibonacci-Features/Filter-Optimierung.
- `auto_optimize_extremes.py`: automatisierte Suche nach Nähe zu SMA-Segment-Extremen.

# Aufgaben

- [A3: Hyperparameter-/Feature-Suche](/aufgaben/a3-hyperparameter-suche.md)

# Stand

Umgesetzt (Gewinner in `runs/eval_3ways`).
