---
type: Feature
title: RL-Experimente & Regime-Filter
description: MSFT-KO-Analyse, Regime-Filter-Konstruktion und OOT-Evaluation (v2, 1Hour, ml4t).
status: umgesetzt
priority: mittel
---

# Ziel

RL-Trading-Prototyp evaluieren und durch Regime-Filter (Shorts in überdehnten Uptrends) OOT-Ergebnis verbessern.

# Umfang

- MSFT-KO-Analyse (19 Trades, Entry-Features, KO vs. Gewinner).
- Regime-Filter: Short blockieren wenn `(close−SMA80)/ATR > 5.0` und ml4t-Confidence ≥ 0.65.
- Vergleich v2 Baseline vs. Regime-Filter (Test + OOT, pro Ticker).

# Aufgaben

- [A9: RL-Regime-Filter-Analyse & Evaluation](/aufgaben/a9-rl-regime-filter.md)

# Stand

Umgesetzt (Bericht in `rl_trader/reports/v2_ml4t_1h_regime_filter.md`). OOT gesamt +6.80 % → +8.70 %, Netto 2.039 $ → 2.609 $. Testsplit blieb negativ.