---
type: Feature
title: Produktions-Bundles & Inferenz
description: Drei eingefrorene Profile (ml4t/baseline/sma_auto) mit Modell+Scaler+Config; Inferenz wählt automatisch die passende Feature-Pipeline.
status: umgesetzt
priority: hoch
---

# Ziel

Produktionsreife Inferenz über eingefrorene Bundles mit einheitlicher CLI.

# Umfang

- `build_production_bundles.py`: friert die drei Eval-Gewinner als Bundles in `production_models/<strand>/active/` ein, schreibt `registry.json` (nur mit `--force` überschreiben).
- `production_common.py`: Registry/Bundle-Laden, profil-spezifische Feature-Pipelines, Inferenz/Postprocessing (Threshold+Cooldown-NMS), Metriken (Val/OOT/SMA-Segmente), Profildaten-Aufbau.
- `predict_production.py`: Inferenz-Einstiegspunkt (Profilwahl, Threshold/Cooldown-Override, Datei/Ordner-Input).
- `run_batch_3models.py`: Ein Befehl → markierte CSVs + PNGs für alle drei Profile (Inferenz im Speicher).

# Aufgaben

- [A5: Produktions-Bundles & Inferenz](/aufgaben/a5-produktions-bundles.md)

# Stand

Umgesetzt (Bundles und `registry.json` vorhanden; CLI dokumentiert in `production_models/README.md`).
