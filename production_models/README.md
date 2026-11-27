# production_models – Bundles, Inferenz & Re-Training

Drei eingefrorene Bestmodelle aus `runs/eval_3ways/`, direkt einsetzbar über
`predict_production.py`, regelmäßig nachjustierbar über
`retrain_production.py` – ohne den 3×8-Suchlauf.

## Profile

| Registry-Key | Bundle | Lauf | Datenpipeline | Threshold | Cooldown | Status |
|---|---|---|---|---:|---:|---|
| `ml4t` | `ml4t_opt` | `ml4t_04` | `ml4t_tol2` (stationäre Features) | 0.50 | 8 | **default_active** |
| `baseline` | `baseline_opt` | `base_05` | `prepared_data` (Standard-`feat_*`, Swing-Labels) | 0.45 | 6 | Profil 2 |
| `sma_auto` | `sma_auto_opt` | `sma_05` | `sma5_tol2` (SMA-38/80-Segmente, korrigierte Labels) | 0.45 | 8 | Profil 3 |

`ml4t` ist in `registry.json` als `default_active` markiert (beste
Event-Präzision, niedrigste Extra-Quote). Jedes Bundle liegt unter
`production_models/<bundle>/active/`:

```text
active/
├── turning_point_mlp.pt      # Gewichte
├── feature_scaler.joblib     # exakt zugehöriger Scaler
└── model_config.json         # Pipeline, Labels, Features, Architektur,
                              # Hyperparameter, Post-Processing, Referenzmetriken
```

`model_config.json` enthält u. a. die geordnete `feature_list`, die
Label-Regeln inkl. Toleranzfenster, `class_weight_power`/Gewichte, Epochen,
Threshold/Cooldown, SHA-256-Hashes und die Referenzmetriken (Val/Test/OOT-F1,
Hit Bull/Bear, Extra-Quote, Event-Präzision, ATR-Q).

## Inferenz

```bash
# Standardmodell aus registry.json (ml4t_04)
python3 predict_production.py \
  --input new_data/AAPL_1Hour.csv \
  --output out/AAPL_1Hour_signals.csv

# Profil wechseln
python3 predict_production.py --input new_data/ --output out/ --model-profile baseline
python3 predict_production.py --input new_data/ --output out/ --model-profile sma_auto
python3 predict_production.py --input new_data/ --output out/ --model-profile ml4t

# Profile anzeigen
python3 predict_production.py --list-profiles

# Optional: Threshold/Cooldown temporär überschreiben
python3 predict_production.py --input x.csv --output x_signals.csv \
  --threshold 0.55 --cooldown-bars 10
```

Das Skript wählt automatisch die zum Profil passende Feature-Aufbereitung
(`annotate_extremes` / `prepare_sma5_data` / `ml4t_features`), skaliert mit dem
gespeicherten Scaler, führt die MLP-Inferenz aus und wendet Threshold + Cooldown
(NMS) an. Erwartet werden Roh-CSVs mit `t,o,h,l,c,v` (optional `vw`); Ticker und
Timeframe werden aus dem Dateinamen gelesen (`AAPL_1Hour_tool.csv`).

Ausgabespalten:

```text
source_file, meta_t, meta_ticker, meta_timeframe,
meta_open, meta_high, meta_low, meta_close,
prob_-1, prob_0, prob_1, raw_pred, filtered_pred,
valid_features, model_profile, threshold, cooldown_bars
```

`prob_-1/0/+1` = Softmax für Extrem-Hoch / Neutral / Extrem-Tief.
`raw_pred` = Threshold ohne Cooldown-Sperre (`cooldown_bars=1`),
`filtered_pred` = finales Signal mit gespeichertem Cooldown.
Warmup-Zeilen ohne gültige Features liefern `filtered_pred=0` und
`valid_features=false`.

Bei Verzeichnis-Input entstehen pro Datei `<stem>_signals.csv` plus
`signals_all.csv`. Bei `--output *.csv` wird nur die kombinierte Datei
geschrieben.

## Batch: Rohdaten → markierte CSVs + PNGs (ein Befehl)

```bash
python3 run_batch_3models.py --input-dir ./raw_data --output-dir ./batch_output
```

Der Lauf verarbeitet jede Roh-CSV intern mit der zum Profil passenden
Feature-Transformation, dem gespeicherten Scaler, dem MLP und Threshold/Cooldown.
Es sind **keine** manuellen Zwischen-CSVs nötig; die Feature-Aufbereitung
erfolgt im Speicher.

Ausgabe pro Modell:

```text
batch_output/
├── batch_run.log
├── batch_summary.csv / .json
├── ml4t_opt/
│   ├── <stem>_marked.csv          # alle Rohspalten + prob_-1/0/+1,
│   │                              # raw_pred, filtered_pred, extreme_point/label
│   └── charts/<stem>_chart_*.png  # 400-Bar-Kacheln
├── baseline_opt/  (gleiche Struktur)
└── sma_auto_opt/  (gleiche Struktur)
```

Die Charts enthalten Close + High/Low-Band, SMA 38/80, Cross-Punkte,
Segment-Referenzextreme, Modellmarker (−1/+1) und eine Kennzahlen-Box
(RUN/FILE: Signale, Extras, Hit Bull/Bear, Val/OOT, Threshold/Cooldown, ATR-Q).

Optionen: `--models ml4t baseline sma_auto`, `--chart-bars 400`,
`--no-charts`, `--keep-work` (behält `_work/` mit Aggregaten; sonst wird der
temporäre Arbeitsordner entfernt), `--pattern "*.csv"`.

## Regelmäßiges Re-Training

```bash
# ein Profil
python3 retrain_production.py --profile ml4t

# alle drei Profile
python3 retrain_production.py --all

# nur trainieren/prüfen, nie promoten
python3 retrain_production.py --profile ml4t --dry-run

# Gate überstimmen
python3 retrain_production.py --profile baseline --promote
```

Ablauf pro Profil:

1. Hyperparameter werden aus `active/model_config.json` gelesen.
2. Die Profildaten werden aus `raw_data/` exakt nach der gespeicherten Pipeline
   neu aufgebaut (oder per `--data-dir` vorgegeben).
3. Es wird **genau eine** Konfiguration trainiert (kein Grid-Search), mit
   festem gespeichertem Threshold/Cooldown.
4. Der Kandidat landet unter
   `production_models/<bundle>/candidates/<timestamp>/` inkl.
   `training_run.log`, `metrics.json`, `model_config.json`, `retrain.log` und
   `charts/AAPL_1Hour_control_1600-1999.png` (+ `last400`).
5. Aktives Modell und Kandidat werden auf dem **aktuellen** chronologischen
   Val/OOT-Split sowie den AAPL-SMA-Segmenten verglichen.
6. Nur bei bestandenem Gate (oder `--promote`) wird `active/` ersetzt; der
   vorherige Stand wandert nach `archive/<timestamp>/`. Sonst bleibt `active/`
   unverändert und es gibt eine Warnung im Log.

### Gate-Kriterien (Defaults in `model_config.json`)

| Kriterium | Regel |
|---|---|
| Val-F1 | Kandidat ≥ aktiv − max(0.02, 10 % von aktiv) |
| OOT-F1 | Kandidat ≥ aktiv − max(0.02, 10 % von aktiv) |
| Segment-HitAvg (OOT) | Kandidat ≥ aktiv − 0.05 |
| Event-Präzision (OOT) | Kandidat ≥ aktiv − 0.03 |
| Extra-Quote (OOT) | Kandidat ≤ aktiv + 0.05 |
| Mindest-Signale (OOT) | ≥ 50 |

Die Kriterien und Ist/Soll-Werte stehen als `gate.checks` im Kandidaten-
`metrics.json` und im `retrain.log`.

### Wichtige Optionen

- `--raw-dir` – Quelle der neuen Rohdaten (Default `./raw_data`)
- `--data-dir` – bereits aufbereitete CSVs statt Neuaufbau (nicht mit `--all`)
- `--dry-run` – vollständiger Lauf inkl. Gate/Charts, aber keine Promotion
- `--promote` – Promotion trotz Gate-Fehler (wird geloggt)
- `--keep-data` – temporär aufgebautes Dataset behalten

## Registry & Versionierung

`registry.json` ist die zentrale Steuerdatei:

```json
{
  "default_active": "ml4t_opt",
  "profiles": {
    "ml4t":     { "run_id": "ml4t_04", "active_dir": "ml4t_opt/active", "default": true },
    "baseline": { "run_id": "base_05", "active_dir": "baseline_opt/active" },
    "sma_auto": { "run_id": "sma_05",  "active_dir": "sma_auto_opt/active" }
  },
  "aliases": { "ml4t_opt": "ml4t", "baseline_opt": "baseline", "sma_auto_opt": "sma_auto" }
}
```

Nach einer Promotion werden `run_id`, `version`, `last_promotion` und
`last_retrain` aktualisiert. `model_config.json` im aktiven Bundle enthält
zusätzlich `lifecycle` und `retrain` mit Gate-Entscheidung und Elternversion.

## Staging / Tests

Für Tests ohne Eingriff in die echten Bundles kann das Wurzelverzeichnis
überschrieben werden:

```bash
cp -a production_models /tmp/prodtest
PRODUCTION_MODELS_DIR=/tmp/prodtest python3 retrain_production.py --profile ml4t
```

## Betrieblicher Hinweis

Die Segment-Trefferquote wird mit ±5 Bars gegen SMA(38/80)-Extreme gemessen.
Wegen der hohen Signal-Dichte ist die Event-Präzision die strengere Kennzahl
(Referenz: Baseline 0.093, SMA 0.152, ML4T 0.177). Für die Anwendung daher
`filtered_pred` und `prob_-1/prob_1` gemeinsam nutzen und die Gate-Werte nach
Marktregime beobachten.
