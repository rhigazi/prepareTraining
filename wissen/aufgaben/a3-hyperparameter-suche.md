---
type: Task
title: "A3: Hyperparameter-/Feature-Suche"
description: Systematische Suchläufe über Feature-Varianten, Label-Toleranzen und Post-Processing mit Gewinner-Auswahl pro Strang.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: mittel
assigned_to: mensch
feature: /features/f3-hyperparameter-suche.md
---

# Ziel

Beste Konfigurationen pro Strang (baseline_opt, sma_auto_opt, ml4t_opt) finden und als Gewinner ablegen.

# Akzeptanzkriterien

- Drei unabhängige Stränge mit Trials unter `runs/...` und Winner nach `<strand>/best/` + Charts.
- ML4T-Features + Label-Toleranz-Suche.
- Optimierung auf starke Segment-Hits bei wenigen Extra-Signalen.
- Fibonacci-Features/Filter-Optimierung.
- Automatisierte Suche nach Nähe zu SMA-Segment-Extremen.

# Betroffene Dateien

- `run_eval_3ways.py`, `run_ml4t_extremes_experiments.py`, `run_visual_opt_search.py`, `run_fib_opt_search.py`, `auto_optimize_extremes.py`

# Ergebnisse

- Umgesetzt; Such-Infrastruktur vorhanden, Gewinner in `runs/eval_3ways`.
