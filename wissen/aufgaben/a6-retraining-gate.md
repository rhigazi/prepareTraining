---
type: Task
title: "A6: Re-Training mit Gate"
description: Ein-Konfigurations-Re-Training mit Gate-Check und Promotion nur bei bestandenem Gate.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: mittel
assigned_to: mensch
feature: /features/f6-retraining-gate.md
---

# Ziel

Kontrolliertes Re-Training mit automatischer Promotion-Entscheidung anhand definierter Gate-Kriterien.

# Akzeptanzkriterien

- Baut Profildaten aus Rohdaten neu.
- Trainiert genau eine Konfiguration mit eingefrorenen Hyperparametern.
- Vergleicht Kandidat vs. aktiv auf Val/OOT/SMA-Segmenten (Val/OOT-F1, Segment-Hit, Event-Präzision, Extra-Quote, Mindestsignale).
- Promotion nur bei Bestehen (sonst Candidate erhalten, Warnung).

# Betroffene Dateien

- `retrain_production.py`, `production_common.py`

# Ergebnisse

- Umgesetzt (Gate-Logik implementiert).
