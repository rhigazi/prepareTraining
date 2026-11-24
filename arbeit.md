# Zusammenfassung der Arbeit – 24.11.2026

## 1. `prepareTraining.py` erstellt
- CLI-Tool gemäß PRD implementiert (`--inputcsv`, `--outputcsv`, `--window_left`, `--window_right`, `--min_move_atr`).
- Pipeline: Sortierung/Dedup, TA-Lib-Features (ATR/NATR, Kerzengeometrie, Indikatorabstände, RSI, ADX, Stoch, rel. Volumen), tickerunabhängige Normalisierung.
- Swing-High/Low-Labeling mit ATR-Mindestbewegung, `label_max_move_atr`.
- NaN/Inf-Bereinigung, Performance < 5 s für 10k Kerzen.

## 2. Nachbesserungen `prepareTraining.py`
- Unvollständige Endzeilen (`valid_future == False`) werden über `np.nan` + `dropna` entfernt.
- Outside-Bar-Konflikte (`high_mask & low_mask`) werden aufgelöst (größere Gegenbewegung in ATR; Gleichstand → 0).
- `CrossSMA(38,80)` wird bei fehlenden/ungültigen Werten aus SMA38/SMA80 berechnet.
- Optionale Filter: `--min_rel_volume`, `--max_gap_minutes` (Fenster über Zeitlücken ungültig).
- Tests mit `AMZN_15Min_tool_202611212329.csv` (1915 Zeilen, 0 NaNs).

## 3. `TurningPoint_Training_Colab.ipynb` optimiert
- NMS/Cluster-Filter `suppress_signal_clusters` (vor/nach Vergleich).
- Automatisches `BEST_THRESHOLD`-Tuning (0.40–0.80) auf Validation.
- Klassen-Gewichtung (`CLASS_WEIGHT_POWER=0.35`), Regularisierung (Dropout 0.35, WD 5e-4, LR 5e-4), Label Smoothing 0.05.
- Benchmark: `HistGradientBoostingClassifier`.
- Signal-Export: `predictions_test.csv` / `predictions_oot.csv` mit Probabilities und raw/filtered Labels.
- `best_threshold` und `cooldown_bars` in `turning_point_mlp.pt`.

## 4. Run-Logging
- `Tee`-Logger schreibt Konsole + `/content/turning_point_artifacts/training_run.log`.
- Lauf-Header (Zeitstempel, CSVs, Features, Hyperparameter) und Abschlussblock (Metriken MLP/HGB, Artefaktpfade).
- Gemeinsames Datei-Handle, sauberer Fallback für `BEST_THRESHOLD`.

## 5. GitHub
- Mehrere Commits/Pushes auf `main` (prepareTraining.py, output.csv, Notebook, arbeit.md).
- End-to-End-Notebook-Lauf ohne Fehler verifiziert.