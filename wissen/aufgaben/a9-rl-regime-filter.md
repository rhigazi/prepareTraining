---
type: Task
title: "A9: RL-Regime-Filter-Analyse & Evaluation"
description: MSFT-KO-Analyse, Regime-Filter-Konstruktion und OOT-Evaluation (v2, 1Hour, ml4t).
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: mittel
assigned_to: mensch
feature: /features/f9-rl-experimente.md
---

# Ziel

RL-Trading-Prototyp evaluieren und durch Regime-Filter (Shorts in überdehnten Uptrends) OOT-Ergebnis verbessern.

# Akzeptanzkriterien

- MSFT-KO-Analyse: 19 Trades mit Entry-Features; KO vs. Gewinner (Netto, Hold, ATR-Pct, Conf, d38, d80, Spread/ATR, MR-Room/ATR).
- Filter-Regel definiert: Short blockieren wenn `(close−SMA80)/ATR > 5.0` und ml4t-Confidence ≥ 0.65; Exits/Größe/Policy unverändert.
- Vergleich v2 Baseline vs. Regime-Filter auf Test + OOT (pro Ticker).
- Bericht in `rl_trader/reports/v2_ml4t_1h_regime_filter.md`.

# Betroffene Dateien

- `rl_trader/eval_rl.py`, `rl_trader/env.py`, `rl_trader/reports/v2_ml4t_1h_regime_filter.md`

# Ergebnisse

- OOT gesamt: Return +6.80 % → **+8.70 %**, Netto 2.039 $ → **2.609 $**, MaxDD 6.02 % → 4.68 %, Trades 60 → 49, KOs 9 → 7, Win-Rate 63.3 % → 65.3 %.
- MSFT: −4.45 % → **+0.14 %**, KOs 5 → 3, Netto −445 $ → +14 $.
- AAPL: +13.05 % → +11.98 %; NVDA: +11.79 % → **+13.97 %**.
- Testsplit blieb negativ (−0.20 % → −0.44 %); Filter blockiert dort nur 1 Einstieg. Empfehlung: Filter als OOT-/MSFT-Schutz; für Testsplit separate breitere Regime-Analyse.