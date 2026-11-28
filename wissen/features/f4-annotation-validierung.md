---
type: Feature
title: Annotation & Validierung vs. SMA-Segmenten
description: Wendet trainierte Modelle auf Rohdaten an, filtert Signal-Cluster und validiert Treffer gegen SMA(38/80)-Segment-Extreme.
status: umgesetzt
priority: mittel
---

# Ziel

Modellvorhersagen auf Rohdaten anwenden und gegen SMA-Segment-Extreme validieren (Hit Bull/Bear, Extra-Quote, Event-Präzision).

# Umfang

- `annotate_extremes.py`: Annotiert rohe OHLCV-CSVs mit Turning-Point-Vorhersagen (Threshold/Cooldown, NMS).
- `extremes_tool.py`: Annotiert rohe CSVs, validiert gegen SMA(38/80)-Cross-Segmente, erzeugt Charts/Reports.
- `compare_sma5_tool.py`: Annotiert/validiert sma5-Modell und vergleicht mit opt_01.

# Aufgaben

- [A4: Annotation & Validierung](/aufgaben/a4-annotation-validierung.md)

# Stand

Umgesetzt.
