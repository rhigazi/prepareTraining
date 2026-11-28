---
type: Task
title: "A4: Annotation & Validierung"
description: Modellvorhersagen auf Rohdaten anwenden und gegen SMA-Segment-Extreme validieren.
task_status: abgeschlossen
phase: 8 Abgeschlossen
priority: mittel
assigned_to: mensch
feature: /features/f4-annotation-validierung.md
---

# Ziel

Modellvorhersagen auf Rohdaten anwenden und gegen SMA(38/80)-Segment-Extreme validieren (Hit Bull/Bear, Extra-Quote, Event-Präzision).

# Akzeptanzkriterien

- Annotiert rohe OHLCV-CSVs mit Turning-Point-Vorhersagen (Threshold/Cooldown, NMS).
- Validiert Treffer gegen SMA(38/80)-Cross-Segmente.
- Erzeugt Charts/Reports (Hit Bull/Bear, Extra-Quote, Event-Präzision).
- Vergleich sma5-Modell mit opt_01.

# Betroffene Dateien

- `annotate_extremes.py`, `extremes_tool.py`, `compare_sma5_tool.py`

# Ergebnisse

- Umgesetzt.
