---
type: Task
title: "A5: Produktions-Bundles & Inferenz"
description: Drei eingefrorene Profile (ml4t/baseline/sma_auto) mit Modell+Scaler+Config; Inferenz wählt automatisch die passende Feature-Pipeline.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: hoch
assigned_to: mensch
feature: /features/f5-produktions-bundles.md
---

# Ziel

Produktionsreife Inferenz über eingefrorene Bundles mit einheitlicher CLI.

# Akzeptanzkriterien

- Drei Profile eingefroren in `production_models/<strand>/active/` + `registry.json`.
- Inferenz wählt automatisch die passende Feature-Pipeline, skaliert, wendet Threshold+Cooldown an.
- Batch-Modus erzeugt markierte CSVs + PNGs für alle drei Profile.
- CLI dokumentiert in `production_models/README.md`.

# Betroffene Dateien

- `build_production_bundles.py`, `production_common.py`, `predict_production.py`, `run_batch_3models.py`, `production_models/*`

# Ergebnisse

- Umgesetzt (Bundles und `registry.json` vorhanden).
