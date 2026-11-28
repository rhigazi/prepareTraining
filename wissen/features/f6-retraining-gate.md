---
type: Feature
title: Re-Training mit Gate
description: Ein-Konfigurations-Re-Training mit Gate-Check und Promotion nur bei bestandenem Gate.
status: umgesetzt
priority: mittel
---

# Ziel

Kontrolliertes Re-Training mit automatischer Promotion-Entscheidung anhand definierter Gate-Kriterien.

# Umfang

- `retrain_production.py`: baut Profildaten aus Rohdaten neu, trainiert genau eine Konfiguration mit eingefrorenen Hyperparametern, vergleicht Kandidat vs. aktiv auf Val/OOT/SMA-Segmenten (Val/OOT-F1, Segment-Hit, Event-Präzision, Extra-Quote, Mindestsignale); Promotion nur bei Bestehen (sonst Candidate erhalten, Warnung).

# Aufgaben

- [A6: Re-Training mit Gate](/aufgaben/a6-retraining-gate.md)

# Stand

Umgesetzt (Gate-Logik implementiert).
