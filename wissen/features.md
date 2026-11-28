---
type: Feature Overview
title: Features-Überblick
description: Zeigt für jedes Feature, ob es umgesetzt ist oder noch offen, mit Verweis auf die zugehörigen Aufgaben.
tags: [features, steuerung]
---

# Statuswerte

`offen` · `in Umsetzung` · `umgesetzt` · `pausiert`

# Regeln

* Jeder Eintrag verlinkt auf seine Feature-Datei unter `/features/` und auf die zugehörigen Aufgaben unter `/aufgaben/`.
* Jeder Feature-Eintrag trägt eine Priorität (`hoch`/`mittel`/`niedrig`); die Planung leitet daraus Reihenfolge und Meilensteine ab.
* Zu jedem offenen Punkt müssen die Aufgaben so dokumentiert sein, dass ein `coder` sie eigenständig abarbeiten kann (siehe [Phasenmodell](/projekt/phasen.md)).
* Jede Umsetzung wird hier eingetragen und ins [Projekt-Log](/log.md) protokolliert.

# Offene Features

*Noch keine.*

# Umgesetzte Features

* [Datenpipeline (Feature-Engineering)](features/f1-datenpipeline.md) — umgesetzt · Priorität **hoch** · [A1](aufgaben/a1-datenpipeline.md)
* [Modelltraining (Turning Points)](features/f2-modelltraining.md) — umgesetzt · Priorität **hoch** · [A2](aufgaben/a2-modelltraining.md)
* [Hyperparameter-/Feature-Suche](features/f3-hyperparameter-suche.md) — umgesetzt · Priorität **mittel** · [A3](aufgaben/a3-hyperparameter-suche.md)
* [Annotation & Validierung vs. SMA-Segmenten](features/f4-annotation-validierung.md) — umgesetzt · Priorität **mittel** · [A4](aufgaben/a4-annotation-validierung.md)
* [Produktions-Bundles & Inferenz](features/f5-produktions-bundles.md) — umgesetzt · Priorität **hoch** · [A5](aufgaben/a5-produktions-bundles.md)
* [Re-Training mit Gate](features/f6-retraining-gate.md) — umgesetzt · Priorität **mittel** · [A6](aufgaben/a6-retraining-gate.md)
* [RL-Trading-Prototyp](features/f7-rl-trading.md) — umgesetzt · Priorität **niedrig** · [A7](aufgaben/a7-rl-trading.md)
* [Projektmanagement-/OKF-Tooling](features/f8-projektmanagement-tooling.md) — umgesetzt · Priorität **hoch** · [A8](aufgaben/a8-projektmanagement-tooling.md)
* [RL-Experimente & Regime-Filter](features/f9-rl-experimente.md) — umgesetzt · Priorität **mittel** · [A9](aufgaben/a9-rl-regime-filter.md)
