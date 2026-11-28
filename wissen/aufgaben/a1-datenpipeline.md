---
type: Task
title: "A1: Datenpipeline (Feature-Engineering)"
description: Rohdaten in Feature-/Label-CSVs überführen (Sortierung/Dedup, TA-Features, Swing-Labeling, optionale Filter).
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: hoch
assigned_to: mensch
feature: /features/f1-datenpipeline.md
---

# Ziel

Rohdaten in konsistente, tickerunabhängige Feature-/Label-CSVs überführen, die von Training und Suche konsumiert werden können.

# Akzeptanzkriterien

- Sortierung/Dedup, TA-Lib-Features (ATR/NATR, Kerzengeometrie, Indikatorabstände, RSI, ADX, Stoch, rel. Volumen), tickerunabhängige Normalisierung.
- Swing-High/Low-Labeling mit ATR-Mindestbewegung, `label_max_move_atr`.
- NaN/Inf-Bereinigung; Performance < 5 s für 10k Kerzen.
- Optionale Filter `--min_rel_volume`, `--max_gap_minutes`.
- Endzeilen (`valid_future == False`) entfernt; Outside-Bar-Konflikte aufgelöst; `CrossSMA(38,80)`-Fallback.

# Betroffene Dateien

- `prepareTraining.py`, `prepare_sma5_data.py`, `ml4t_features.py`, `fib_features.py`

# Ergebnisse

- 2026-11-24: Umgesetzt und verifiziert (AMZN 15-Min-CSV, 1915 Zeilen, 0 NaNs). Nachbesserungen (Endzeilen, Outside-Bar, CrossSMA-Fallback, optionale Filter) eingearbeitet.
