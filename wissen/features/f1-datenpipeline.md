---
type: Feature
title: Datenpipeline (Feature-Engineering)
description: Wandelt rohe OHLCV-CSVs in trainingsfähige Feature-/Label-CSVs um (Sortierung/Dedup, TA-Features, Swing-Labeling, optionale Filter).
status: umgesetzt
priority: hoch
---

# Ziel

Rohdaten in konsistente, tickerunabhängige Feature-/Label-CSVs überführen, die von Training und Suche konsumiert werden können.

# Umfang

- `prepareTraining.py`: Sortierung/Dedup, TA-Lib-Features (ATR/NATR, Kerzengeometrie, Indikatorabstände, RSI, ADX, Stoch, rel. Volumen), tickerunabhängige Normalisierung, Swing-High/Low-Labeling mit ATR-Mindestbewegung, NaN/Inf-Bereinigung, optionale Filter (`--min_rel_volume`, `--max_gap_minutes`).
- `prepare_sma5_data.py`: SMA(38/80)-Segment-Labels + 5 TA-Indikatoren.
- `ml4t_features.py`: stationärer ML4T-Feature-Builder (RSI, Stoch, ADX, Bollinger, MFI, Returns/Volatilität, rel. Volumen).
- `fib_features.py`: Fibonacci-Feature-Builder (Fib-Position/Abstände zu Swing-High/Low, Swing-Range in ATR).

# Aufgaben

- [A1: Datenpipeline](/aufgaben/a1-datenpipeline.md)

# Stand

Umgesetzt und End-to-End verifiziert (AMZN 15-Min-CSV, 1915 Zeilen, 0 NaNs).
