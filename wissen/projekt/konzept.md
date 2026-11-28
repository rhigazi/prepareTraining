---
type: Concept
title: Projektkonzept
description: Ziel, Vision und Rahmenbedingungen des Projekts prepareTraining (Turning-Point-Vorhersage).
tags: [projekt, konzept]
status: aktuell
---

# Ziel

Entwicklung einer ML-Pipeline zur Vorhersage von Turning Points (Extrem-Hoch/Extrem-Tief/Neutral) in OHLCV-Marktdaten (15-Min-Kerzen), inklusive Feature-Engineering, Modelltraining, Hyperparameter-/Feature-Suche, Annotation/Validierung gegen SMA(38/80)-Segment-Extreme, Produktions-Bundles mit Inferenz und Re-Training mit Gate sowie einem RL-Trading-Prototypen.

# Nicht-Ziele

- Keine Live-Order-Ausführung (RL-Teil ist Prototyp).
- Keine Echtzeit-Inferenz-Infrastruktur (Batch/CLI).

# Rahmenbedingungen

- Projektmanager ist der Hauptagent (OpenCode); Umsetzung über Subagenten (planner, coder, reviewer, tester, documenter).
- Gesamtes Projektwissen im OKF-Bundle `wissen/`.
- Datenbasis: `AMZN_15Min_tool_202611212329.csv` (1915 Zeilen); Erweiterung auf weitere Ticker möglich.
- Artefakte: `production_models/`, `runs/`, Notebooks.

# Offene Fragen

* Keine dokumentierten offenen Fragen (historische Umsetzung).